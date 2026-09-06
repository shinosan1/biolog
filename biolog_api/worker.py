import json
import sqlite3
import time
from datetime import datetime, timezone
from queue import Queue

from log_utils import mask_pii
from queue_manager import get_queue
from write_repository import delete_record, import_snapshots, insert_record, update_record


def _log(op, request_id, queue_size, retry, status, extra=None):
    def safe(o):
        try:
            json.dumps(o)
            return o
        except Exception:
            return str(o)

    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "op": op,
        "request_id": request_id,
        "queue_size": queue_size,
        "retry": retry,
        "status": status,
    }

    if extra:
        entry["extra"] = safe(extra)

    print(mask_pii(json.dumps(entry, ensure_ascii=False)), flush=True)

def worker_loop():
    q: Queue = get_queue()
    while True:
        task = q.get()

        if task is None:
            _log("shutdown", "", q.qsize(), 0, "stopping")
            q.task_done()
            break

        request_id = task.get("request_id", "")
        result_queue = task["result_queue"]

        try:
            result = _execute_with_retry(task, q)
            result_queue.put({"request_id": request_id, "status": "success", **result})
        except sqlite3.OperationalError as e:
            _report_task_error(task, q, result_queue, e, "database")
        except ValueError as e:
            error_kind = "not_found" if "not found" in str(e).lower() else "validation"
            _report_task_error(task, q, result_queue, e, error_kind)
        except Exception as e:
            _report_task_error(task, q, result_queue, e, "internal")
        finally:
            q.task_done()


def _report_task_error(task, q, result_queue, error, error_kind):
    request_id = task.get("request_id", "")
    _log(
        task.get("operation", "?"),
        request_id,
        q.qsize(),
        0,
        "error",
        {"error_kind": error_kind, "exception_type": type(error).__name__},
    )
    public_messages = {
        "not_found": "Record not found",
        "validation": "Invalid write request",
        "database": "Database operation failed",
        "internal": "Worker operation failed",
    }
    result_queue.put({
        "request_id": request_id,
        "status": "error",
        "error_kind": error_kind,
        "error": public_messages[error_kind],
    })


def _execute_with_retry(task: dict, q: Queue) -> dict:
    max_retry = 5
    delay = 0.1
    op = task.get("operation", "?")
    request_id = task.get("request_id", "")

    for attempt in range(max_retry):
        try:
            result = _execute_once(task)
            _log(op, request_id, q.qsize(), attempt, "success", result)
            return result
        except Exception as e:
            if "database is locked" not in str(e):
                raise
            _log(op, request_id, q.qsize(), attempt, "retry", {"error": str(e)})
            if attempt == max_retry - 1:
                raise
            time.sleep(delay)
            delay *= 2

    raise RuntimeError("unreachable")


def _execute_once(task: dict) -> dict:
    op = task["operation"]
    payload = task["payload"]
    _log(
        "worker_received",
        task.get("request_id", ""),
        0,
        0,
        "info",
        {"fields": sorted(payload.keys())},
    )
    activity_log = payload.get("activity_log")

    if activity_log is None:
        _log(
            "activity_log_missing",
            task.get("request_id", ""),
            0,
            0,
            "warning",
            {"fields": sorted(payload.keys())},
        )
    if op == "insert":
        return insert_record(payload)

    if op == "update":
        return update_record(payload)

    if op == "delete":
        return delete_record(payload)

    if op == "import":
        return import_snapshots(payload["rows"])

    raise ValueError(f"Unknown operation: {op}")
