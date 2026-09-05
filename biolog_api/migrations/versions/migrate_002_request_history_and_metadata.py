MIGRATION_ID = "002"
DESCRIPTION = "add request id history and created_at format metadata"


_LEGACY_UTC_CUTOVER = "2026-07-27 23:59:59"


def _set_legacy_utc_metadata(conn):
    existing = conn.execute(
        "SELECT value FROM schema_metadata WHERE key = ?",
        ("legacy_utc_max_record_id",),
    ).fetchone()
    if existing is not None:
        return

    total = conn.execute("SELECT COUNT(*) FROM health_records").fetchone()[0]
    if total == 0:
        value = "0"
    else:
        rows = conn.execute(
            """
            SELECT created_at FROM health_records
            WHERE id <= ?
            ORDER BY id
            """,
            (146,),
        ).fetchall()
        if not rows or any(row[0] is None for row in rows):
            raise RuntimeError(
                "Cannot determine legacy UTC created_at format safely; "
                "set schema_metadata manually after reviewing the database"
            )
        values = [row[0] for row in rows]
        if max(values) <= _LEGACY_UTC_CUTOVER:
            value = "146"
        elif min(values) > _LEGACY_UTC_CUTOVER:
            value = "0"
        else:
            raise RuntimeError(
                "Mixed legacy UTC and JST created_at values require manual review"
            )
    conn.execute(
        "INSERT INTO schema_metadata (key, value) VALUES (?, ?)",
        ("legacy_utc_max_record_id", value),
    )


def run(conn):
    # The runner wraps this migration and its schema_migrations entry in one
    # transaction, so a duplicate request_id or ambiguous timestamp rolls back.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS request_history (
            request_id TEXT PRIMARY KEY,
            record_id INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )

    duplicate = conn.execute(
        """
        SELECT request_id FROM health_records
        WHERE request_id IS NOT NULL AND request_id <> ''
        GROUP BY request_id HAVING COUNT(*) > 1
        LIMIT 1
        """
    ).fetchone()
    if duplicate is not None:
        raise RuntimeError(
            "Duplicate non-empty request_id exists; resolve it before migration"
        )

    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uidx_hr_request_id "
        "ON health_records(request_id)"
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO request_history (request_id, record_id)
        SELECT request_id, id FROM health_records
        WHERE request_id IS NOT NULL AND request_id <> ''
        """
    )
    _set_legacy_utc_metadata(conn)
