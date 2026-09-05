import importlib
import sqlite3

import pytest


def _migration():
    return importlib.import_module(
        "migrations.versions.migrate_002_request_history_and_metadata"
    )


def _old_schema(conn):
    conn.execute(
        """
        CREATE TABLE health_records (
            id INTEGER PRIMARY KEY, request_id TEXT, date TEXT NOT NULL,
            user_id TEXT NOT NULL, created_at TEXT NOT NULL
        )
        """
    )


def test_migration_adds_history_unique_index_and_is_safe_to_repeat(tmp_path):
    conn = sqlite3.connect(tmp_path / "legacy.db")
    try:
        _old_schema(conn)
        conn.execute(
            "INSERT INTO health_records VALUES (1, 'old-request', '2026-07-27', 'self', '2026-07-27 15:00:00')"
        )
        _migration().run(conn)
        _migration().run(conn)
        assert conn.execute("SELECT record_id FROM request_history WHERE request_id = 'old-request'").fetchone() == (1,)
        assert conn.execute("SELECT value FROM schema_metadata WHERE key = 'legacy_utc_max_record_id'").fetchone() == ("146",)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO health_records (request_id, date, user_id, created_at) VALUES ('old-request', '2026-07-28', 'self', '2026-07-28 00:00:00')"
            )
    finally:
        conn.close()


def test_migration_rejects_duplicate_request_ids_without_partial_schema(tmp_path):
    conn = sqlite3.connect(tmp_path / "duplicate.db")
    try:
        _old_schema(conn)
        conn.execute("INSERT INTO health_records VALUES (1, 'same', '2026-08-01', 'self', '2026-08-01 00:00:00')")
        conn.execute("INSERT INTO health_records VALUES (2, 'same', '2026-08-02', 'self', '2026-08-02 00:00:00')")
        with pytest.raises(RuntimeError, match="Duplicate"):
            _migration().run(conn)
        conn.rollback()
        assert conn.execute("SELECT name FROM sqlite_master WHERE name = 'request_history'").fetchone() is None
    finally:
        conn.close()
