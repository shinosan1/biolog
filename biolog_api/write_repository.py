import json
import sqlite3
import uuid

from time_utils import now_jst

from db_manager import get_connection
from log_utils import mask_pii


MEAL_DETAIL_MAX_LENGTH = 10000
ACTIVITY_LOG_MAX_LENGTH = 20000


def _merge_log_entries(existing, incoming):
    if not isinstance(incoming, str) or not incoming.strip():
        return existing
    if not isinstance(existing, str) or not existing.strip():
        return incoming

    existing_entries = {
        line.strip()
        for line in existing.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        if line.strip()
    }
    additions = []
    for line in incoming.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if line.strip() and line.strip() not in existing_entries:
            additions.append(line)
            existing_entries.add(line.strip())

    if not additions:
        return existing
    return existing.rstrip("\r\n") + "\n" + "\n".join(additions)


def insert_record(payload: dict) -> dict:
    with get_connection(write=True) as conn:
        try:
            history = conn.execute(
                "SELECT record_id FROM request_history WHERE request_id = ?",
                (payload["request_id"],),
            ).fetchone()
            if history is not None:
                return {"idempotent": True, "id": history["record_id"]}

            existing = conn.execute(
                """
                SELECT meal_detail, activity_log
                FROM health_records
                WHERE user_id = ? AND date = ?
                """,
                (payload["user_id"], payload["date"]),
            ).fetchone()
            meal_detail = payload.get("meal_detail")
            activity_log = payload.get("activity_log")
            if existing is not None:
                meal_detail = _merge_log_entries(
                    existing["meal_detail"], meal_detail
                )
                activity_log = _merge_log_entries(
                    existing["activity_log"], activity_log
                )

            _validate_log_lengths(meal_detail, activity_log)

            cur = conn.execute(
                """
                INSERT INTO health_records
                    (request_id, date, user_id, temperature, pulse,
                     systolic_bp, diastolic_bp, weight, body_fat,
                     muscle_mass, bmr, meal_detail, activity_log, memo)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(user_id, date) DO UPDATE SET
                    request_id   = excluded.request_id,
                    temperature  = COALESCE(excluded.temperature, health_records.temperature),
                    pulse        = COALESCE(excluded.pulse, health_records.pulse),
                    systolic_bp  = COALESCE(excluded.systolic_bp, health_records.systolic_bp),
                    diastolic_bp = COALESCE(excluded.diastolic_bp, health_records.diastolic_bp),
                    weight       = COALESCE(excluded.weight, health_records.weight),
                    body_fat     = COALESCE(excluded.body_fat, health_records.body_fat),
                    muscle_mass  = COALESCE(excluded.muscle_mass, health_records.muscle_mass),
                    bmr          = COALESCE(excluded.bmr, health_records.bmr),
                    meal_detail  = COALESCE(NULLIF(excluded.meal_detail, ''), health_records.meal_detail),
                    activity_log = COALESCE(NULLIF(excluded.activity_log, ''), health_records.activity_log),
                    memo         = COALESCE(NULLIF(excluded.memo, ''), health_records.memo)
                """,
                (
                    payload["request_id"],
                    payload["date"],
                    payload["user_id"],
                    payload.get("temperature"),
                    payload.get("pulse"),
                    payload.get("systolic_bp"),
                    payload.get("diastolic_bp"),
                    payload.get("weight"),
                    payload.get("body_fat"),
                    payload.get("muscle_mass"),
                    payload.get("bmr"),
                    meal_detail,
                    activity_log,
                    payload.get("memo") or "",
                ),
            )
            # ON CONFLICT が DO UPDATE 側に入ると、その接続では INSERT が発生せず
            # cursor.lastrowid が 0 のままになる。接続は書き込みごとに作り直すため、
            # UPSERT 後は必ず実レコードの id を引き直す。
            row = conn.execute(
                """
                SELECT id FROM health_records
                WHERE user_id = ? AND date = ?
                """,
                (payload["user_id"], payload["date"]),
            ).fetchone()
            record_id = row["id"] if row is not None else cur.lastrowid
            try:
                conn.execute(
                    "INSERT INTO request_history (request_id, record_id) VALUES (?, ?)",
                    (payload["request_id"], record_id),
                )
            except sqlite3.IntegrityError:
                history = conn.execute(
                    "SELECT record_id FROM request_history WHERE request_id = ?",
                    (payload["request_id"],),
                ).fetchone()
                if history is not None:
                    return {"idempotent": True, "id": history["record_id"]}
                raise
            return {"id": record_id}
        except sqlite3.IntegrityError as e:
            if "request_id" in str(e).lower():
                # DB責任: UNIQUE(request_id) 衝突 → SELECT で既存 id を返す（冪等）
                row = conn.execute(
                    "SELECT record_id FROM request_history WHERE request_id = ?",
                    (payload["request_id"],),
                ).fetchone()
                return {"idempotent": True, "id": row[0] if row else None}
            raise  # CHECK 制約違反など他の IntegrityError はバブルアップ


def update_record(payload: dict) -> dict:
    with get_connection(write=True) as conn:
        record_id = payload["id"]
        _ALLOWED = {
            "temperature": float,
            "pulse": int,
            "systolic_bp": int,
            "diastolic_bp": int,
            "weight": float,
            "body_fat": float,
            "muscle_mass": float,
            "bmr": int,
            "memo": str,
            "activity_log": str,
            "meal_detail": str,
        }
        fields = {}
        for k, v in payload.items():
            if k == "id":
                continue
            if k in _ALLOWED:
                if v is None:
                    continue
                try:
                    fields[k] = _ALLOWED[k](v)
                except Exception:
                    raise ValueError(f"Invalid type for {k}: {v}")
        if not fields:
            raise ValueError("No fields to update")
        existing = conn.execute(
            "SELECT meal_detail, activity_log FROM health_records WHERE id = ?",
            (record_id,),
        ).fetchone()
        if existing is None:
            raise ValueError(f"Record {record_id} not found")
        for field, maximum in (
            ("meal_detail", MEAL_DETAIL_MAX_LENGTH),
            ("activity_log", ACTIVITY_LOG_MAX_LENGTH),
        ):
            if field in fields and fields[field] != existing[field] and len(fields[field]) > maximum:
                raise ValueError(f"{field} must be at most {maximum} characters")
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [record_id]
        print(mask_pii(json.dumps({
            "event": "UPDATE_SQL_EXECUTED",
            "record_id": record_id,
            "fields": list(fields.keys()),
        }, ensure_ascii=False)), flush=True)
        cur = conn.execute(
            f"UPDATE health_records SET {set_clause} WHERE id = ?", values
        )
        if cur.rowcount == 0:
            raise ValueError(f"Record {record_id} not found")
        return {"id": record_id, "updated": cur.rowcount}


def delete_record(payload: dict) -> dict:
    with get_connection(write=True) as conn:
        record_id = payload["id"]
        conn.execute("DELETE FROM request_history WHERE record_id = ?", (record_id,))
        cur = conn.execute(
            "DELETE FROM health_records WHERE id = ?", (record_id,)
        )
        if cur.rowcount == 0:
            raise ValueError(f"Record {record_id} not found")
        return {"id": record_id, "deleted": cur.rowcount}


def import_snapshots(rows: list[dict]) -> dict:
    """Atomically apply complete daily snapshots from a validated CSV."""
    fields = (
        "temperature", "pulse", "systolic_bp", "diastolic_bp", "weight",
        "body_fat", "muscle_mass", "bmr", "meal_detail", "activity_log", "memo",
    )
    with get_connection(write=True) as conn:
        created = updated = skipped = 0
        for item in rows:
            payload = item["payload"]
            existing = conn.execute(
                "SELECT * FROM health_records WHERE user_id = ? AND date = ?",
                (payload["user_id"], payload["date"]),
            ).fetchone()
            if existing is None:
                request_id = str(uuid.uuid4())
                cur = conn.execute(
                    """
                    INSERT INTO health_records
                        (request_id, date, user_id, temperature, pulse, systolic_bp,
                         diastolic_bp, weight, body_fat, muscle_mass, bmr,
                         meal_detail, activity_log, memo, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        request_id, payload["date"], payload["user_id"],
                        *(payload[field] for field in fields), now_jst().isoformat(),
                    ),
                )
                conn.execute(
                    "INSERT INTO request_history (request_id, record_id) VALUES (?, ?)",
                    (request_id, cur.lastrowid),
                )
                created += 1
                continue

            if all(existing[field] == payload[field] for field in fields):
                skipped += 1
                continue
            set_clause = ", ".join(f"{field} = ?" for field in fields)
            conn.execute(
                f"UPDATE health_records SET {set_clause} WHERE id = ?",
                (*(payload[field] for field in fields), existing["id"]),
            )
            updated += 1
    return {"created": created, "updated": updated, "skipped": skipped, "errors": 0}


def _validate_log_lengths(meal_detail, activity_log):
    for value, maximum, field in (
        (meal_detail, MEAL_DETAIL_MAX_LENGTH, "meal_detail"),
        (activity_log, ACTIVITY_LOG_MAX_LENGTH, "activity_log"),
    ):
        if isinstance(value, str) and len(value) > maximum:
            raise ValueError(f"{field} must be at most {maximum} characters")
