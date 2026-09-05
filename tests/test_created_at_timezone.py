from datetime import datetime, timezone
import importlib
from pathlib import Path
import sys

import pandas as pd
import pytest


STREAMLIT_DIR = Path(__file__).resolve().parents[1] / "biolog_streamlit"


@pytest.fixture
def streamlit_modules():
    module_names = ("config", "time_utils", "views.list_view")
    previous = {name: sys.modules.pop(name, None) for name in module_names}
    sys.path.insert(0, str(STREAMLIT_DIR))
    try:
        time_utils = importlib.import_module("time_utils")
        list_view = importlib.import_module("views.list_view")
        yield time_utils, list_view
    finally:
        for name in module_names:
            sys.modules.pop(name, None)
        for name, module in previous.items():
            if module is not None:
                sys.modules[name] = module
        sys.path.remove(str(STREAMLIT_DIR))


def test_legacy_naive_utc_is_converted_through_boundary(streamlit_modules):
    to_jst = streamlit_modules[0].to_jst
    assert to_jst("2026-07-27 15:00:00", record_id=145) == "2026-07-28 00:00"
    assert to_jst("2026-07-27 15:00:00", record_id=146) == "2026-07-28 00:00"


def test_post_timezone_change_naive_jst_is_not_shifted(streamlit_modules):
    to_jst = streamlit_modules[0].to_jst
    assert to_jst("2026-07-28 06:42:27", record_id=147) == "2026-07-28 06:42"
    assert to_jst("2026-08-01 12:48:52", record_id=154) == "2026-08-01 12:48"


def test_aware_values_keep_their_declared_offset(streamlit_modules):
    to_jst = streamlit_modules[0].to_jst
    assert to_jst("2026-08-01T03:48:52Z", record_id=154) == "2026-08-01 12:48"
    assert to_jst("2026-08-01T12:48:52+09:00", record_id=145) == "2026-08-01 12:48"
    aware_utc = datetime(2026, 8, 1, 3, 48, tzinfo=timezone.utc)
    assert to_jst(aware_utc, record_id=154) == "2026-08-01 12:48"


def test_missing_record_id_treats_naive_value_as_current_jst_format(streamlit_modules):
    assert streamlit_modules[0].to_jst("2026-08-01 12:48:52") == "2026-08-01 12:48"


def test_fresh_database_metadata_does_not_shift_early_ids(streamlit_modules):
    assert streamlit_modules[0].to_jst(
        "2026-08-01 12:48:52", record_id=1, legacy_utc_max_record_id=0
    ) == "2026-08-01 12:48"


def test_csv_bytes_have_bom_and_keep_japanese_content(streamlit_modules):
    csv = streamlit_modules[1]._csv_bytes(pd.DataFrame([{"メモ": "朝食"}]))
    assert csv.startswith(b"\xef\xbb\xbf")
    assert "朝食" in csv.decode("utf-8-sig")


def test_list_display_applies_boundary_to_created_at(streamlit_modules):
    view = streamlit_modules[1]
    displayed = view._prepare_display(pd.DataFrame([
        {
            "id": 146,
            "date": "2026-07-27",
            "user_id": "self",
            "created_at": "2026-07-27 15:00:00",
        },
        {
            "id": 147,
            "date": "2026-07-28",
            "user_id": "self",
            "created_at": "2026-07-28 06:42:27",
        },
    ]))

    assert displayed["記録日時"].tolist() == [
        "2026-07-28 00:00",
        "2026-07-28 06:42",
    ]
