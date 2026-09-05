def _payload(**overrides):
    base = {
        "request_id": "rid-1",
        "date": "2026-06-25",
        "user_id": "self",
        "temperature": 36.5,
        "pulse": 72,
        "systolic_bp": 120,
        "diastolic_bp": 80,
        "weight": 61.2,
        "body_fat": 20.1,
        "muscle_mass": 42.3,
        "bmr": 1400,
        "meal_detail": "meal",
        "activity_log": "act",
        "memo": "memo",
    }
    base.update(overrides)
    return base


EXPECTED_RECORD_KEYS = [
    "id",
    "request_id",
    "date",
    "user_id",
    "temperature",
    "pulse",
    "systolic_bp",
    "diastolic_bp",
    "weight",
    "body_fat",
    "muscle_mass",
    "bmr",
    "meal_detail",
    "activity_log",
    "memo",
    "created_at",
]


def test_insert_upsert_idempotent_and_reads(temp_db_modules):
    write_repository, biocore, _db_path = temp_db_modules

    assert write_repository.insert_record(_payload()) == {"id": 1}

    row = biocore.get_record_by_id(1)
    assert list(row.keys()) == EXPECTED_RECORD_KEYS
    assert row["request_id"] == "rid-1"
    assert row["weight"] == 61.2

    result = write_repository.insert_record(_payload(request_id="rid-2", weight=62.0))
    assert set(result) == {"id"}

    by_day = biocore.get_record_by_user_date("self", "2026-06-25")
    assert by_day["request_id"] == "rid-2"
    assert by_day["weight"] == 62.0

    assert write_repository.insert_record(
        _payload(request_id="rid-2", date="2026-06-26")
    ) == {"idempotent": True, "id": 1}

    assert list(biocore.get_latest_record("self").keys()) == EXPECTED_RECORD_KEYS
    assert list(biocore.get_health_records(user_id="self", limit=20, offset=0)[0].keys()) == EXPECTED_RECORD_KEYS
    assert list(biocore.get_health_records_by_date_range("2026-06-01", "2026-06-30")[0].keys()) == EXPECTED_RECORD_KEYS


def test_insert_upsert_preserves_existing_values_for_missing_none_and_empty(
    temp_db_modules,
):
    write_repository, biocore, _db_path = temp_db_modules
    original = _payload()
    write_repository.insert_record(original)

    result = write_repository.insert_record({
        "request_id": "rid-2",
        "date": "2026-06-25",
        "user_id": "self",
        "temperature": 36.1,
        "pulse": None,
        "meal_detail": None,
        "activity_log": "",
        "memo": None,
    })
    assert set(result) == {"id"}

    row = biocore.get_record_by_user_date("self", "2026-06-25")
    assert row["request_id"] == "rid-2"
    assert row["temperature"] == 36.1

    for field in (
        "pulse",
        "systolic_bp",
        "diastolic_bp",
        "weight",
        "body_fat",
        "muscle_mass",
        "bmr",
        "meal_detail",
        "activity_log",
        "memo",
    ):
        assert row[field] == original[field]


def test_activity_only_upsert_preserves_measurements_and_omitted_text(temp_db_modules):
    write_repository, biocore, _db_path = temp_db_modules
    original = _payload()
    write_repository.insert_record(original)

    result = write_repository.insert_record({
        "request_id": "rid-activity",
        "date": "2026-06-25",
        "user_id": "self",
        "activity_log": "AI生態資源動画編集",
    })
    assert set(result) == {"id"}

    row = biocore.get_record_by_user_date("self", "2026-06-25")
    assert row["activity_log"] == original["activity_log"] + "\nAI生態資源動画編集"
    assert row["weight"] == original["weight"]
    assert row["meal_detail"] == original["meal_detail"]
    assert row["memo"] == original["memo"]


def test_insert_upsert_appends_unique_activity_and_meal_entries(temp_db_modules):
    write_repository, biocore, _db_path = temp_db_modules
    write_repository.insert_record(_payload())

    write_repository.insert_record(_payload(
        request_id="rid-2",
        activity_log="act\nnew act",
        meal_detail="meal\nnew meal",
        memo="latest memo",
    ))
    row = biocore.get_record_by_user_date("self", "2026-06-25")
    assert row["activity_log"] == "act\nnew act"
    assert row["meal_detail"] == "meal\nnew meal"
    assert row["memo"] == "latest memo"

    write_repository.insert_record(_payload(
        request_id="rid-3",
        activity_log="new act",
        meal_detail="new meal",
        memo="latest memo",
    ))
    row = biocore.get_record_by_user_date("self", "2026-06-25")
    assert row["activity_log"] == "act\nnew act"
    assert row["meal_detail"] == "meal\nnew meal"


def test_insert_upsert_keeps_partial_matches_as_distinct_entries(temp_db_modules):
    write_repository, biocore, _db_path = temp_db_modules
    write_repository.insert_record(_payload(activity_log="動画編集"))
    write_repository.insert_record(_payload(
        request_id="rid-2",
        activity_log="AI生態資源動画編集",
    ))

    row = biocore.get_record_by_user_date("self", "2026-06-25")
    assert row["activity_log"] == "動画編集\nAI生態資源動画編集"


def test_update_keeps_existing_values_for_none_and_reports_empty_or_missing(
    temp_db_modules, monkeypatch, capsys,
):
    write_repository, biocore, _db_path = temp_db_modules
    write_repository.insert_record(_payload())
    masked_entries = []
    monkeypatch.setattr(
        write_repository,
        "mask_pii",
        lambda text: masked_entries.append(text) or "MASKED_UPDATE_LOG",
    )

    assert write_repository.update_record({
        "id": 1,
        "weight": 63.4,
        "temperature": None,
        "memo": "",
        "meal_detail": "",
        "activity_log": "",
    }) == {"id": 1, "updated": 1}
    assert masked_entries
    assert capsys.readouterr().out.strip() == "MASKED_UPDATE_LOG"

    row = biocore.get_record_by_id(1)
    assert row["weight"] == 63.4
    assert row["temperature"] == 36.5
    assert row["memo"] == ""
    assert row["meal_detail"] == ""
    assert row["activity_log"] == ""

    try:
        write_repository.update_record({"id": 1, "unknown": "x", "temperature": None})
    except ValueError as e:
        assert str(e) == "No fields to update"
    else:
        raise AssertionError("empty update did not fail")

    try:
        write_repository.update_record({"id": 999, "memo": "x"})
    except ValueError as e:
        assert str(e) == "Record 999 not found"
    else:
        raise AssertionError("missing update did not fail")


def test_delete_existing_and_missing_record(temp_db_modules):
    write_repository, biocore, _db_path = temp_db_modules
    write_repository.insert_record(_payload())

    assert write_repository.delete_record({"id": 1}) == {"id": 1, "deleted": 1}
    assert biocore.get_record_by_id(1) is None

    try:
        write_repository.delete_record({"id": 1})
    except ValueError as e:
        assert str(e) == "Record 1 not found"
    else:
        raise AssertionError("missing delete did not fail")


def test_update_allows_unchanged_legacy_oversized_log(temp_db_modules):
    write_repository, biocore, db_path = temp_db_modules
    write_repository.insert_record(_payload())
    oversized = "a" * 20001
    conn = __import__("sqlite3").connect(db_path)
    try:
        conn.execute("UPDATE health_records SET activity_log = ? WHERE id = 1", (oversized,))
        conn.commit()
    finally:
        conn.close()

    assert write_repository.update_record({"id": 1, "weight": 62.0, "activity_log": oversized}) == {"id": 1, "updated": 1}
    assert biocore.get_record_by_id(1)["activity_log"] == oversized
    try:
        write_repository.insert_record(_payload(request_id="too-long", activity_log="b" * 20001))
    except ValueError as exc:
        assert "activity_log" in str(exc)
    else:
        raise AssertionError("oversized appended log did not fail")
