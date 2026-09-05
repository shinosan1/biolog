import importlib
import sys
from queue import Queue


class _ThreadState:
    def __init__(self, alive):
        self._alive = alive

    def is_alive(self):
        return self._alive


def _load_api(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "unused.db"))
    for name in ("api", "worker", "write_repository", "db_manager", "biocore"):
        sys.modules.pop(name, None)
    return importlib.import_module("api")


def test_healthcheck_reports_ok_without_database_path(tmp_path, monkeypatch):
    api = _load_api(tmp_path, monkeypatch)
    monkeypatch.setattr(api, "_worker_thread", _ThreadState(True))
    monkeypatch.setattr(api.biocore, "check_database", lambda: True)
    monkeypatch.setattr(api, "get_queue", lambda: Queue(maxsize=100))

    result = api.health_check()

    assert result["status"] == "ok"
    assert result["worker_alive"] is True
    assert result["database_ok"] is True
    assert "db" not in result
    assert str(tmp_path) not in str(result)


def test_healthcheck_reports_unhealthy_when_worker_stops(tmp_path, monkeypatch):
    api = _load_api(tmp_path, monkeypatch)
    monkeypatch.setattr(api, "_worker_thread", _ThreadState(False))
    monkeypatch.setattr(api.biocore, "check_database", lambda: True)

    assert api.health_check()["status"] == "unhealthy"


def test_database_check_is_read_only(temp_db_modules):
    _, biocore, db_path = temp_db_modules
    before = db_path.read_bytes()

    assert biocore.check_database() is True
    assert db_path.read_bytes() == before


def test_metadata_endpoint_returns_database_specific_legacy_boundary(tmp_path, monkeypatch):
    api = _load_api(tmp_path, monkeypatch)
    monkeypatch.setattr(api.biocore, "get_metadata_value", lambda key: "0")

    assert api.health_metadata() == {"legacy_utc_max_record_id": 0}
