import sqlite3
import time
from typing import Any, Dict, List, Optional

from db_manager import get_connection

HEALTH_RECORD_COLUMNS = """
id, request_id, date, user_id,
temperature, pulse, systolic_bp, diastolic_bp,
weight, body_fat, muscle_mass, bmr,
meal_detail, activity_log,
memo, created_at
"""


def _rows_to_dicts(cur) -> List[Dict[str, Any]]:
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _row_to_dict(cur) -> Optional[Dict[str, Any]]:
    cols = [c[0] for c in cur.description]
    row = cur.fetchone()
    return dict(zip(cols, row)) if row else None


def _execute_read(query: str, params=(), *, one: bool = False):
    delays = (0.1, 0.2)
    for attempt in range(len(delays) + 1):
        try:
            with get_connection(read=True) as conn:
                cur = conn.execute(query, params)
                return _row_to_dict(cur) if one else _rows_to_dicts(cur)
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower() or attempt == len(delays):
                raise
            time.sleep(delays[attempt])
    raise RuntimeError("unreachable")


def check_database() -> bool:
    row = _execute_read("SELECT 1 AS ok", one=True)
    return bool(row and row.get("ok") == 1)


def get_metadata_value(key: str) -> Optional[str]:
    row = _execute_read(
        "SELECT value FROM schema_metadata WHERE key = ?", (key,), one=True
    )
    return row["value"] if row is not None else None


def get_health_records(
    user_id: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    if not 1 <= limit <= 500:
        raise ValueError("limit must be between 1 and 500")
    if not 0 <= offset <= 10000:
        raise ValueError("offset must be between 0 and 10000")

    if user_id:
        query = f"""
        SELECT {HEALTH_RECORD_COLUMNS}
        FROM health_records
        WHERE user_id = ?
        ORDER BY date DESC, id DESC
        LIMIT ? OFFSET ?
        """
        params = (user_id, limit, offset)
    else:
        query = f"""
        SELECT {HEALTH_RECORD_COLUMNS}
        FROM health_records
        ORDER BY date DESC, id DESC
        LIMIT ? OFFSET ?
        """
        params = (limit, offset)

    return _execute_read(query, params)


def get_health_records_by_date_range(
    start_date: str,
    end_date: str,
    user_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    if user_id:
        query = f"""
        SELECT {HEALTH_RECORD_COLUMNS}
        FROM health_records
        WHERE date >= ? AND date <= ? AND user_id = ?
        ORDER BY date ASC, id ASC
        """
        params = (start_date, end_date, user_id)
    else:
        query = f"""
        SELECT {HEALTH_RECORD_COLUMNS}
        FROM health_records
        WHERE date >= ? AND date <= ?
        ORDER BY date ASC, id ASC
        """
        params = (start_date, end_date)

    return _execute_read(query, params)


def get_record_by_id(record_id: int) -> Optional[Dict[str, Any]]:
    query = f"""
    SELECT {HEALTH_RECORD_COLUMNS}
    FROM health_records
    WHERE id = ?
    """
    return _execute_read(query, (record_id,), one=True)


def get_record_by_user_date(user_id: str, date: str) -> Optional[Dict[str, Any]]:
    query = """
    SELECT *
    FROM health_records
    WHERE user_id = ? AND date = ?
    """
    return _execute_read(query, (user_id, date), one=True)


def get_latest_record(user_id: str) -> Optional[Dict[str, Any]]:
    query = f"""
    SELECT {HEALTH_RECORD_COLUMNS}
    FROM health_records
    WHERE user_id = ?
    ORDER BY date DESC, id DESC
    LIMIT 1
    """
    return _execute_read(query, (user_id,), one=True)
