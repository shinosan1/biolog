"""Regression tests: insert_record must return the real record id.

同一 user_id + date の UPSERT が DO UPDATE 側に入ると、書き込みごとに接続を作り直す
この構成では cursor.lastrowid が 0 になる。INSERT / UPSERT / request_id 重複の
すべてで実在する id を返すことを固定する。
"""

import importlib
import sys
from queue import Queue


def _payload(**overrides):
    base = {
        "request_id": "rid-1",
        "date": "2026-08-23",
        "user_id": "self",
        "weight": 64.2,
        "meal_detail": "",
        "activity_log": "",
        "memo": "",
    }
    base.update(overrides)
    return base


def _seed_other_records(write_repository, count):
    """Push the interesting record past id=1 so a stale 0/1 cannot pass."""
    for i in range(count):
        write_repository.insert_record(_payload(
            request_id=f"seed-{i}",
            date=f"2026-08-{i + 1:02d}",
            user_id="father",
        ))


def test_insert_returns_the_new_record_id(temp_db_modules):
    write_repository, biocore, _ = temp_db_modules
    _seed_other_records(write_repository, 9)

    result = write_repository.insert_record(_payload())

    assert result == {"id": 10}
    assert biocore.get_record_by_user_date("self", "2026-08-23")["id"] == 10


def test_same_user_and_date_upsert_returns_the_existing_record_id(temp_db_modules):
    write_repository, biocore, _ = temp_db_modules
    _seed_other_records(write_repository, 9)
    created = write_repository.insert_record(_payload())

    updated = write_repository.insert_record(
        _payload(request_id="rid-2", weight=63.1)
    )

    assert updated == {"id": created["id"]} == {"id": 10}
    row = biocore.get_record_by_user_date("self", "2026-08-23")
    assert row["id"] == 10
    assert row["request_id"] == "rid-2"
    assert row["weight"] == 63.1
    assert len(biocore.get_health_records(user_id="self", limit=20, offset=0)) == 1


def test_repeated_upserts_keep_returning_the_same_id(temp_db_modules):
    write_repository, _, _ = temp_db_modules
    _seed_other_records(write_repository, 9)
    write_repository.insert_record(_payload())

    ids = [
        write_repository.insert_record(
            _payload(request_id=f"rid-{n}", weight=60.0 + n)
        )["id"]
        for n in range(2, 6)
    ]

    assert ids == [10, 10, 10, 10]


def test_duplicate_request_id_returns_the_stored_record_id(temp_db_modules):
    write_repository, _, _ = temp_db_modules
    _seed_other_records(write_repository, 9)
    created = write_repository.insert_record(_payload(request_id="rid-dup"))

    replayed = write_repository.insert_record(
        _payload(request_id="rid-dup", date="2026-09-01")
    )

    assert replayed == {"idempotent": True, "id": created["id"]}
    assert replayed["id"] == 10


def test_old_request_replay_does_not_roll_back_a_later_upsert(temp_db_modules):
    write_repository, biocore, _ = temp_db_modules
    first = write_repository.insert_record(_payload(request_id="r1", weight=60.0))
    write_repository.insert_record(_payload(request_id="r2", weight=65.0))

    replayed = write_repository.insert_record(_payload(request_id="r1", weight=60.0))

    assert replayed == {"idempotent": True, "id": first["id"]}
    assert biocore.get_record_by_id(first["id"])["weight"] == 65.0


def test_worker_reports_the_upserted_id_to_the_api_layer(temp_db_modules, monkeypatch):
    write_repository, _, _ = temp_db_modules
    _seed_other_records(write_repository, 9)
    created = write_repository.insert_record(_payload())

    sys.modules.pop("worker", None)
    worker = importlib.import_module("worker")
    assert worker.insert_record is write_repository.insert_record

    result = worker._execute_once({
        "operation": "insert",
        "request_id": "rid-worker",
        "payload": _payload(request_id="rid-worker", weight=62.5),
        "result_queue": Queue(),
    })

    assert result == {"id": created["id"]} == {"id": 10}
