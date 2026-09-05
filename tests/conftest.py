import importlib
import os
import sqlite3
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "biolog_api"
STREAMLIT_DIR = ROOT / "biolog_streamlit"
REAL_DB = (ROOT / "data" / "biolog.db").resolve()


def _add_import_paths():
    for path in (str(STREAMLIT_DIR), str(API_DIR)):
        if path not in sys.path:
            sys.path.insert(0, path)


@pytest.fixture(autouse=True)
def import_paths():
    _add_import_paths()


@pytest.fixture
def temp_db_modules(tmp_path, monkeypatch):
    db_path = (tmp_path / "biolog_test.db").resolve()
    assert db_path != REAL_DB
    assert ROOT not in db_path.parents

    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    assert Path(os.environ["DATABASE_PATH"]).resolve() != REAL_DB

    conn = sqlite3.connect(db_path)
    try:
        migration = importlib.import_module("migrations.versions.migrate_001_init")
        migration.run(conn)
        migration = importlib.import_module(
            "migrations.versions.migrate_002_request_history_and_metadata"
        )
        migration.run(conn)
        conn.commit()
    finally:
        conn.close()

    for name in ("db_manager", "write_repository", "biocore"):
        sys.modules.pop(name, None)

    db_manager = importlib.import_module("db_manager")
    assert Path(db_manager.DATABASE_PATH).resolve() == db_path
    assert Path(db_manager.DATABASE_PATH).resolve() != REAL_DB

    write_repository = importlib.import_module("write_repository")
    biocore = importlib.import_module("biocore")
    return write_repository, biocore, db_path
