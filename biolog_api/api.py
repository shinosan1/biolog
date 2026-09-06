import json
import os
import signal
import threading
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from queue import Empty, Queue as SyncQueue
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from pydantic import ValidationError

import biocore
import preprocess as pp
from csv_import import parse_csv_snapshot
from db_manager import get_connection
from log_utils import mask_pii
from queue_manager import get_queue
from schemas import CsvImportRequest, HealthRecordCreate, HealthRecordUpdate
from worker import worker_loop
DATABASE_PATH = os.getenv("DATABASE_PATH", "")

_worker_thread: Optional[threading.Thread] = None


def _start_worker() -> threading.Thread:
    t = threading.Thread(target=worker_loop, daemon=True, name="biolog-worker")
    t.start()
    return t


def _stop_worker(t: threading.Thread):
    get_queue().put(None)
    t.join(timeout=10)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _worker_thread

    _worker_thread = _start_worker()

    def _handle_sigterm(signum, frame):
        if _worker_thread:
            _stop_worker(_worker_thread)

    signal.signal(signal.SIGTERM, _handle_sigterm)

    yield

    if _worker_thread:
        _stop_worker(_worker_thread)


app = FastAPI(title="BioLog API", lifespan=lifespan)

def _enqueue_and_wait(operation: str, payload: dict) -> dict:
    result_q: SyncQueue = SyncQueue()
    task = {
        "operation": operation,
        "request_id": payload.get("request_id", ""),
        "payload": payload,
        "result_queue": result_q,
    }
    q = get_queue()
    if q.full():
        raise HTTPException(status_code=503, detail="Write queue is full, try again later")
    q.put(task)
    try:
        result = result_q.get(timeout=30)
    except Empty:
        raise HTTPException(
            status_code=503,
            detail="Write worker did not respond in time",
        )
    if result["status"] == "error":
        detail = result.get("error", "Worker error")
        error_kind = result.get("error_kind")
        if error_kind == "not_found":
            raise HTTPException(status_code=404, detail=detail)
        if error_kind == "validation":
            raise HTTPException(status_code=422, detail=detail)
        raise HTTPException(status_code=500, detail=detail)
    return result


@app.get("/api/health/health")
def health_check():
    q = get_queue()
    worker_alive = bool(_worker_thread and _worker_thread.is_alive())
    try:
        database_ok = biocore.check_database()
    except Exception:
        database_ok = False

    if not worker_alive or not database_ok:
        status = "unhealthy"
    elif q.full():
        status = "degraded"
    else:
        status = "ok"

    return {
        "status": status,
        "worker_alive": worker_alive,
        "database_ok": database_ok,
        "queue": {"size": q.qsize(), "max_size": q.maxsize},
    }


@app.get("/api/health/metadata")
def health_metadata():
    value = biocore.get_metadata_value("legacy_utc_max_record_id")
    if value is None:
        raise HTTPException(status_code=503, detail="Database metadata is unavailable")
    try:
        return {"legacy_utc_max_record_id": int(value)}
    except ValueError:
        raise HTTPException(status_code=500, detail="Database metadata is invalid")


@app.post("/api/health/record", status_code=201)
async def create_record(request: Request):
    try:
        raw = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail="Request body must be valid JSON")
    if not isinstance(raw, dict):
        raise HTTPException(status_code=422, detail="Request body must be a JSON object")
    rid = raw.get("request_id", "?")

    # ---- logging wrapper ----
    def log(obj):
        print(mask_pii(json.dumps(obj, ensure_ascii=False)), flush=True)
    # ------------------------

    log({"event": "REQ_START", "request_id": rid})
    log({"event": "API_IN", "fields": list(raw.keys())})

    try:
        preprocessed = pp.preprocess_record(raw)
    except ValueError as e:
        log({
            "event": "PREPROCESS",
            "status": "error",
            "endpoint": "/api/health/record",
            "error_type": type(e).__name__,
            "fields": sorted(raw.keys()),
        })
        raise HTTPException(status_code=422, detail=str(e))

    generated = [k for k in ("request_id", "date") if not raw.get(k)]

    if generated:
        log({"event": "API_ENRICH", "generated": generated})

    log({"event": "PREPROCESS", "request_id": preprocessed.get("request_id")})

    known = set(HealthRecordCreate.model_fields.keys())
    unknown = set(preprocessed.keys()) - known

    if unknown:
        log({"event": "UNKNOWN_KEYS", "keys": sorted(unknown)})

    try:
        record = HealthRecordCreate(**preprocessed)
    except Exception as e:
        log({
            "event": "VALIDATION",
            "status": "error",
            "endpoint": "/api/health/record",
            "error_type": type(e).__name__,
            "fields": sorted(preprocessed.keys()),
        })
        raise HTTPException(status_code=422, detail=str(e))

    log({"event": "VALIDATION", "status": "ok"})

    payload = record.model_dump()

    log({
        "event": "API_PAYLOAD_KEYS",
        "keys": list(payload.keys())
    })

    log({
        "event": "API_PAYLOAD_BEFORE_QUEUE",
        "fields": list(payload.keys())
    })

    log({
        "event": "DB_WRITE",
        "request_id": payload["request_id"]
    })

    result = _enqueue_and_wait("insert", payload)

    log({
        "event": "REQ_END",
        "request_id": payload["request_id"],
        "status": "ok"
    })

    return {"message": "登録完了", **result}

@app.put("/api/health/record/{record_id}")
def update_record(record_id: int, record: HealthRecordUpdate):
    payload = {"id": record_id, **record.model_dump(exclude_unset=True)}
    print(json.dumps({
        "event": "UPDATE_REQUEST",
        "record_id": record_id,
        "fields": [k for k in payload if k != "id"],
    }, ensure_ascii=False), flush=True)
    result = _enqueue_and_wait("update", payload)
    return {"message": "更新完了", **result}


def _csv_import_preview(request: CsvImportRequest) -> dict:
    parsed = parse_csv_snapshot(
        request.csv_text, request.restore_formula_prefix
    )
    keys = [(item["payload"]["user_id"], item["payload"]["date"])
            for item in parsed["rows"]]
    existing = biocore.get_records_by_user_dates(keys) if keys else set()
    updated = sum(key in existing for key in keys)
    return {
        "total": parsed["total"], "created": len(keys) - updated,
        "updated": updated, "skipped": 0, "errors": parsed["errors"],
        "formula_prefix_count": parsed["formula_prefix_count"],
    }


async def _read_csv_import_request(request: Request) -> CsvImportRequest:
    try:
        raw = await request.json()
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(status_code=422, detail={
            "message": "CSVインポート要求が不正です",
            "errors": [{"row": 0, "field": "CSV", "reason": "JSON形式が不正です"}],
        })
    try:
        return CsvImportRequest.model_validate(raw)
    except ValidationError as exc:
        # Do not return Pydantic's input echo: it could contain health data.
        errors = [{"row": 0, "field": ".".join(map(str, issue["loc"])) or "CSV",
                   "reason": issue["msg"]}
                  for issue in exc.errors(include_input=False)]
        raise HTTPException(status_code=422, detail={
            "message": "CSVインポート要求が不正です", "errors": errors,
        })


@app.post("/api/health/import/preview")
def preview_csv_import(payload: CsvImportRequest = Depends(_read_csv_import_request)):
    return _csv_import_preview(payload)


@app.post("/api/health/import")
def import_csv(payload: CsvImportRequest = Depends(_read_csv_import_request)):
    parsed = parse_csv_snapshot(
        payload.csv_text, payload.restore_formula_prefix
    )
    if parsed["errors"]:
        raise HTTPException(status_code=422, detail={
            "message": "CSVにエラーがあるため取り込みませんでした",
            "errors": parsed["errors"],
        })
    result = _enqueue_and_wait("import", {"rows": parsed["rows"]})
    return {"message": "CSV取り込み完了", **result}


@app.get("/api/health/record/day")
def get_record_by_day(user_id: str, date: str):
    record = biocore.get_record_by_user_date(user_id, date)
    if record is None:
        raise HTTPException(status_code=404, detail="Record not found")
    return record


@app.get("/api/health/record/{record_id}")
def get_record(record_id: int):
    record = biocore.get_record_by_id(record_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Record {record_id} not found")
    return record


@app.delete("/api/health/record/{record_id}")
def delete_record(record_id: int):
    payload = {"id": record_id}
    result = _enqueue_and_wait("delete", payload)
    return {"message": "削除完了", **result}


@app.get("/api/health/records")
def list_records(
    user_id: Optional[str] = None,
    limit: int = Query(default=20, ge=1, le=500),
    offset: int = Query(default=0, ge=0, le=10000),
):
    try:
        return biocore.get_health_records(user_id=user_id, limit=limit, offset=offset)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/health/records/range")
def records_by_range(
    start: str,
    end: str,
    user_id: Optional[str] = None,
):
    try:
        start_date = date.fromisoformat(start)
        end_date = date.fromisoformat(end)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=422,
            detail="start and end must be real dates in YYYY-MM-DD format",
        )
    if start_date.isoformat() != start or end_date.isoformat() != end:
        raise HTTPException(
            status_code=422,
            detail="start and end must use YYYY-MM-DD format",
        )
    if start_date > end_date:
        raise HTTPException(status_code=422, detail="start must not be after end")
    try:
        return biocore.get_health_records_by_date_range(
            start_date=start, end_date=end, user_id=user_id
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/health/records/latest/{user_id}")
def latest_record(user_id: str):
    record = biocore.get_latest_record(user_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"No records for user_id={user_id}")
    return record
