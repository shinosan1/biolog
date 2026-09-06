import importlib
import sys
import threading
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from queue import Queue

import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "biolog_api"
STREAMLIT_DIR = ROOT / "biolog_streamlit"


@pytest.fixture
def display_modules():
    names = ("config", "time_utils", "views.list_view")
    previous = {name: sys.modules.pop(name, None) for name in names}
    sys.path.insert(0, str(STREAMLIT_DIR))
    try:
        yield importlib.import_module("time_utils"), importlib.import_module("views.list_view")
    finally:
        for name in names:
            sys.modules.pop(name, None)
        for name, module in previous.items():
            if module is not None:
                sys.modules[name] = module
        sys.path.remove(str(STREAMLIT_DIR))


def _csv(**overrides):
    row = {
        "id": "1", "ユーザー": "自分", "対象日": "2026-09-01", "記録日時": "2026-09-01 08:00",
        "体重(kg)": "61.2", "収縮期血圧": "120", "拡張期血圧": "80", "体温(℃)": "36.5",
        "脈拍(bpm)": "72", "基礎代謝(kcal)": "1400", "体脂肪率(%)": "20.1", "筋肉量(kg)": "42.3",
        "メモ": "メモ", "食事ログ": "朝食", "行動ログ": "散歩",
    }
    row.update(overrides)
    return pd.DataFrame([row]).to_csv(index=False).encode("utf-8-sig").decode("utf-8-sig")


def _modules(temp_db_modules):
    for name in ("schemas", "csv_import"):
        sys.modules.pop(name, None)
    schemas = importlib.import_module("schemas")
    csv_import = importlib.import_module("csv_import")
    write_repository, biocore, db_path = temp_db_modules
    return csv_import, write_repository, biocore, db_path


def test_exported_csv_round_trips_with_bom_and_japanese(temp_db_modules, display_modules):
    csv_import, write_repository, biocore, _ = _modules(temp_db_modules)
    list_view = display_modules[1]
    write_repository.insert_record({
        "request_id": "source", "user_id": "self", "date": "2026-09-01",
        "weight": 61.2, "memo": '=日本語,"引用"',
        "meal_detail": "ごはん\nお茶", "activity_log": "散歩",
    })
    original = biocore.get_record_by_user_date("self", "2026-09-01")
    display = list_view._prepare_display(pd.DataFrame([original]), legacy_utc_max_record_id=0)
    exported = list_view._csv_bytes(list_view._sanitize_csv_dataframe(display))
    assert exported.startswith(b"\xef\xbb\xbf")
    parsed = csv_import.parse_csv_snapshot(exported.decode("utf-8-sig"), True)
    assert not parsed["errors"]
    write_repository.update_record({"id": original["id"], "weight": 70, "memo": "changed"})
    assert write_repository.import_snapshots(parsed["rows"])["updated"] == 1
    row = biocore.get_record_by_user_date("self", "2026-09-01")
    for field in csv_import.FIELD_NAMES.values():
        assert row[field] == original[field]


def test_snapshot_updates_blanks_replaces_logs_and_repeated_import_skips(temp_db_modules):
    csv_import, write_repository, biocore, _ = _modules(temp_db_modules)
    write_repository.insert_record({
        "request_id": "normal-r1", "date": "2026-09-01", "user_id": "self",
        "weight": 60.0, "pulse": 70, "meal_detail": "古い食事", "activity_log": "古い行動", "memo": "old",
    })
    parsed = csv_import.parse_csv_snapshot(_csv(**{
        "体重(kg)": "", "脈拍(bpm)": "", "食事ログ": "朝食", "行動ログ": "散歩", "メモ": "",
    }))
    assert not parsed["errors"]
    assert write_repository.import_snapshots(parsed["rows"]) == {"created": 0, "updated": 1, "skipped": 0, "errors": 0}
    row = biocore.get_record_by_user_date("self", "2026-09-01")
    assert row["weight"] is None and row["pulse"] is None
    assert row["meal_detail"] == "朝食" and row["activity_log"] == "散歩" and row["memo"] == ""
    assert write_repository.import_snapshots(parsed["rows"])["skipped"] == 1


def test_import_does_not_delete_other_days_or_break_request_history(temp_db_modules):
    csv_import, write_repository, biocore, _ = _modules(temp_db_modules)
    original = {"request_id": "r1", "date": "2026-09-02", "user_id": "self", "weight": 60.0}
    first = write_repository.insert_record(original)
    write_repository.insert_record({"request_id": "other", "date": "2026-09-03", "user_id": "self", "weight": 70.0})
    parsed = csv_import.parse_csv_snapshot(_csv(**{"対象日": "2026-09-02", "体重(kg)": "65"}))
    write_repository.import_snapshots(parsed["rows"])
    assert biocore.get_record_by_user_date("self", "2026-09-03")["weight"] == 70.0
    assert write_repository.insert_record(original) == {"idempotent": True, "id": first["id"]}
    assert biocore.get_record_by_user_date("self", "2026-09-02")["weight"] == 65

    forged = csv_import.parse_csv_snapshot(_csv(**{
        "id": "9999", "対象日": "2026-09-02", "created_at": "1900-01-01",
        "request_id": "other", "体重(kg)": "66",
    }))
    assert forged["errors"] == []
    before = biocore.get_record_by_user_date("self", "2026-09-02")
    write_repository.import_snapshots(forged["rows"])
    after = biocore.get_record_by_user_date("self", "2026-09-02")
    for field in ("id", "created_at", "request_id"):
        assert after[field] == before[field]
    assert after["weight"] == 66


def test_invalid_rows_report_line_field_and_prevent_writes(temp_db_modules):
    csv_import, write_repository, biocore, _ = _modules(temp_db_modules)
    broken = _csv(**{"対象日": "2026-02-30", "体重(kg)": "not-a-number", "食事ログ": "x" * 10001})
    parsed = csv_import.parse_csv_snapshot(broken)
    assert parsed["errors"]
    assert all({"row", "field", "reason"} <= set(error) for error in parsed["errors"])
    assert {error["field"] for error in parsed["errors"]} >= {"対象日", "体重(kg)", "食事ログ"}
    assert biocore.get_health_records(limit=20, offset=0) == []


def test_duplicate_keys_and_formula_prefix_are_handled_without_silent_change(temp_db_modules):
    csv_import, _write_repository, _biocore, _ = _modules(temp_db_modules)
    two = _csv(**{"メモ": "'=danger"}) + _csv(**{"id": "2"}).split("\n", 1)[1]
    duplicate = csv_import.parse_csv_snapshot(two, restore_formula_prefix=True)
    assert any(error["field"] == "対象日" for error in duplicate["errors"])
    single = csv_import.parse_csv_snapshot(_csv(**{"メモ": "'=danger"}), restore_formula_prefix=True)
    assert single["rows"][0]["payload"]["memo"] == "=danger"
    retained = csv_import.parse_csv_snapshot(_csv(**{"メモ": "'=danger"}), False)
    assert retained["rows"][0]["payload"]["memo"] == "'=danger"


@pytest.mark.parametrize("boundary", [0, 146])
def test_new_import_timestamp_is_aware_jst_for_legacy_boundary(temp_db_modules, display_modules, monkeypatch, boundary):
    csv_import, write_repository, biocore, db_path = _modules(temp_db_modules)
    now = datetime(2026, 9, 6, 0, 15, tzinfo=timezone(timedelta(hours=9)))
    monkeypatch.setattr(write_repository, "now_jst", lambda: now)
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE schema_metadata SET value=? WHERE key='legacy_utc_max_record_id'", (str(boundary),))
    parsed = csv_import.parse_csv_snapshot(_csv())
    write_repository.import_snapshots(parsed["rows"])
    row = biocore.get_record_by_user_date("self", "2026-09-01")
    assert row["id"] == 1
    assert display_modules[0].to_jst(row["created_at"], record_id=1, legacy_utc_max_record_id=boundary) == "2026-09-06 00:15"
    changed = csv_import.parse_csv_snapshot(_csv(**{"体重(kg)": "65"}))
    write_repository.import_snapshots(changed["rows"])
    assert biocore.get_record_by_user_date("self", "2026-09-01")["created_at"] == row["created_at"]


def test_import_transaction_rolls_back_every_row_on_write_failure(temp_db_modules):
    csv_import, write_repository, biocore, db_path = _modules(temp_db_modules)
    first = csv_import.parse_csv_snapshot(_csv(**{"対象日": "2026-09-04"}))["rows"][0]
    invalid = {"row": 3, "payload": {**first["payload"], "date": "2026-09-05", "memo": None}}
    with pytest.raises(sqlite3.IntegrityError):
        write_repository.import_snapshots([first, invalid])
    assert biocore.get_record_by_user_date("self", "2026-09-04") is None
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT count(*) FROM request_history").fetchone()[0] == 0


def test_all_empty_snapshot_clears_existing_logs_and_measurements(temp_db_modules):
    parser, repo, core, _ = _modules(temp_db_modules)
    repo.import_snapshots(parser.parse_csv_snapshot(_csv())["rows"])
    empty = {header: "" for header, field in parser.FIELD_NAMES.items() if field not in {"user_id", "date"}}
    parsed = parser.parse_csv_snapshot(_csv(**empty))
    assert parsed["errors"] == []
    assert repo.import_snapshots(parsed["rows"])["updated"] == 1
    row = core.get_record_by_user_date("self", "2026-09-01")
    for field in parser.FIELD_NAMES.values():
        if field not in {"user_id", "date"}:
            assert row[field] == ("" if field in parser.TEXT_FIELDS else None)


def test_import_reaches_the_real_isolated_worker_queue(temp_db_modules, monkeypatch):
    csv_import, _write_repository, biocore, _ = _modules(temp_db_modules)
    sys.modules.pop("worker", None)
    worker = importlib.import_module("worker")
    queue = Queue()
    monkeypatch.setattr(worker, "get_queue", lambda: queue)
    thread = threading.Thread(target=worker.worker_loop, daemon=True)
    thread.start()
    result_queue = Queue()
    rows = csv_import.parse_csv_snapshot(_csv())["rows"]
    queue.put({"operation": "import", "request_id": "", "payload": {"rows": rows}, "result_queue": result_queue})
    result = result_queue.get(timeout=2)
    queue.put(None)
    thread.join(timeout=2)
    assert result["status"] == "success"
    assert biocore.get_record_by_user_date("self", "2026-09-01")["weight"] == 61.2


def test_multiline_start_line_and_extreme_decimal_are_rejected(temp_db_modules):
    csv_import, _write_repository, _biocore, _ = _modules(temp_db_modules)
    text = _csv(**{"メモ": "1行目\n2行目", "体重(kg)": "1e999999999"})
    parsed = csv_import.parse_csv_snapshot(text)
    assert any(error["row"] == 2 and error["field"] == "体重(kg)" for error in parsed["errors"])


def test_http_import_validates_before_queue_then_uses_real_worker(temp_db_modules, monkeypatch):
    from fastapi.testclient import TestClient

    parser, repo, core, db_path = _modules(temp_db_modules)
    previous = {name: sys.modules.pop(name, None) for name in ("api", "worker")}
    worker = importlib.import_module("worker")
    api = importlib.import_module("api")
    queue = Queue()
    monkeypatch.setattr(worker, "get_queue", lambda: queue)
    monkeypatch.setattr(api, "get_queue", lambda: queue)
    # No lifespan entry: only our isolated Worker is started; no process signals.
    client = TestClient(api.app)
    thread = None
    try:
        good = _csv()
        bad = good + _csv(**{"対象日": "invalid"}).split("\n", 1)[1]
        preview = client.post("/api/health/import/preview", json={"csv_text": bad})
        assert preview.status_code == 200
        assert preview.json()["created"] == 1
        assert preview.json()["errors"][0]["row"] == 3
        response = client.post("/api/health/import", json={"csv_text": bad})
        assert response.status_code == 422
        assert queue.empty()
        assert core.get_health_records() == []
        with sqlite3.connect(db_path) as conn:
            assert conn.execute("SELECT count(*) FROM request_history").fetchone()[0] == 0
        thread = threading.Thread(target=worker.worker_loop, daemon=True)
        thread.start()
        result = client.post("/api/health/import", json={"csv_text": good})
        assert result.status_code == 200
        assert result.json()["created"] == 1
        assert core.get_record_by_user_date("self", "2026-09-01")["weight"] == 61.2
        again = client.post("/api/health/import", json={"csv_text": good})
        assert again.json()["skipped"] == 1
        invalid_envelope = client.post("/api/health/import", json={"csv_text": {"private": "health secret"}})
        assert invalid_envelope.status_code == 422
        assert "health secret" not in invalid_envelope.text
        assert invalid_envelope.json()["detail"]["errors"][0]["field"] == "csv_text"
    finally:
        client.close()
        if thread:
            queue.put(None)
            thread.join(timeout=3)
            assert not thread.is_alive()
        for name, module in previous.items():
            sys.modules.pop(name, None)
            if module is not None:
                sys.modules[name] = module


def test_csv_size_row_count_and_structural_boundaries(temp_db_modules):
    parser, _, _, _ = _modules(temp_db_modules)
    assert parser.parse_csv_snapshot("あ" * (parser.MAX_CSV_BYTES // 3 + 1))["errors"]
    header, data = _csv().split("\n", 1)
    oversized = header + "\n" + data * (parser.MAX_CSV_ROWS + 1)
    result = parser.parse_csv_snapshot(oversized)
    assert any("5,000" in e["reason"] for e in result["errors"])
    short_row = header + "\n自分,2026-09-01\n"
    assert parser.parse_csv_snapshot(short_row)["total"] == 1
    assert parser.parse_csv_snapshot(short_row)["errors"][0]["row"] == 2
    for text in (header + '\n"unterminated', _csv().replace("メモ,", "未対応,"), _csv().replace("メモ,", "対象日,")):
        assert parser.parse_csv_snapshot(text)["errors"]
    assert parser.parse_csv_snapshot(header + '\n"unterminated')["errors"][0]["row"] == 2
    assert parser.parse_csv_snapshot("\n\n" + _csv() + "\n")["total"] == 1


@pytest.mark.parametrize("header,value", [
    ("脈拍(bpm)", "72.5"), ("体温(℃)", "42.1"),
    ("収縮期血圧", "251"), ("拡張期血圧", "29"),
    ("基礎代謝(kcal)", "5000"), ("筋肉量(kg)", "0"),
    ("体脂肪率(%)", "nan"), ("体脂肪率(%)", "1e-99999"),
    ("行動ログ", "x" * 20001), ("メモ", "x" * 10001),
])
def test_csv_rejects_out_of_range_values(temp_db_modules, header, value):
    parser, _, _, _ = _modules(temp_db_modules)
    errors = parser.parse_csv_snapshot(_csv(**{header: value}))["errors"]
    assert any(error["field"] == header and error["row"] == 2 for error in errors)
