"""Regression tests for the create / edit / delete UI state transitions.

実際の `render_create()` / `render_edit()` を Streamlit の AppTest で動かし、
API 呼び出しだけを差し替える。Session State の残留や、画面表示と書き込み対象の
不一致が起きないことを固定する。
"""

import sys
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
STREAMLIT_DIR = PROJECT_ROOT / "biolog_streamlit"
if str(STREAMLIT_DIR) not in sys.path:
    sys.path.insert(0, str(STREAMLIT_DIR))

from form_components import create_measurement_state_keys


@pytest.fixture(autouse=True)
def streamlit_modules():
    """`time_utils` は biolog_api 側にも同名モジュールがあり、conftest の sys.path 順では
    API 側が先に解決される。ビューを動かす間だけ Streamlit 側を確実に読み込む。
    tests/test_created_at_timezone.py と同じ方式。
    """
    module_names = ("config", "time_utils", "views", "views.create", "views.edit")
    previous = {name: sys.modules.pop(name, None) for name in module_names}
    sys.path.insert(0, str(STREAMLIT_DIR))
    try:
        yield
    finally:
        for name in module_names:
            sys.modules.pop(name, None)
        for name, module in previous.items():
            if module is not None:
                sys.modules[name] = module
        sys.path.remove(str(STREAMLIT_DIR))


# sys.path の優先順位は streamlit_modules フィクスチャが管理する。
# ここで insert すると解除されずに残り、後続の API 側テストを壊す。
_HEADER = "import streamlit as st\n"

_CREATE_BODY = """
import views.create as create
from api_client import ApiClientError

if "posted" not in st.session_state:
    st.session_state["posted"] = []


def fake_post(path, body):
    if st.session_state.get("api_mode") == "error":
        raise ApiClientError("registration failed", 500)
    st.session_state["posted"].append({"path": path, "body": body})
    return {"message": "registered", "id": 10}


create.api_post = fake_post
create.clear_health_caches = lambda: None
create.render_create()
"""

_EDIT_BODY = """
import copy

import views.edit as edit
from api_client import ApiClientError


def _record(rid, user_id, date, memo):
    return {
        "id": rid, "request_id": f"r{rid}", "date": date, "user_id": user_id,
        "temperature": 36.5, "pulse": 70, "systolic_bp": 120, "diastolic_bp": 80,
        "weight": 64.2, "body_fat": 18.0, "muscle_mass": 42.0, "bmr": 1400,
        "meal_detail": f"meal-{memo}", "activity_log": f"act-{memo}", "memo": memo,
        "created_at": "2026-08-23 07:00:00",
    }


if "records" not in st.session_state:
    st.session_state["records"] = {
        11: _record(11, "self", "2026-08-23", "memo-A"),
        12: _record(12, "self", "2026-08-22", "memo-B"),
        13: _record(13, "father", "2026-07-10", "memo-F"),
    }
if "api_calls" not in st.session_state:
    st.session_state["api_calls"] = []

records = st.session_state["records"]
api_calls = st.session_state["api_calls"]


def fake_get(path, params=None, suppress_404=False):
    api_calls.append(("GET", path, params))
    if path == "/api/health/metadata":
        return {"legacy_utc_max_record_id": 0}
    if path == "/api/health/records":
        return [
            copy.deepcopy(r) for r in records.values()
            if r["user_id"] == params["user_id"]
        ]
    if path == "/api/health/record/day":
        for r in records.values():
            if r["user_id"] == params["user_id"] and r["date"] == params["date"]:
                return copy.deepcopy(r)
        if suppress_404:
            return None
        raise ApiClientError("Record not found", 404)
    if path.startswith("/api/health/record/"):
        rid = int(path.rsplit("/", 1)[1])
        if rid in records:
            return copy.deepcopy(records[rid])
        if suppress_404:
            return None
        raise ApiClientError("Record not found", 404)
    raise AssertionError(f"unexpected GET {path}")


def fake_put(path, body):
    rid = int(path.rsplit("/", 1)[1])
    api_calls.append(("PUT", path, dict(body)))
    records[rid].update({k: v for k, v in body.items() if v is not None})
    return {"message": "updated", "id": rid, "updated": 1}


def fake_delete(path):
    rid = int(path.rsplit("/", 1)[1])
    api_calls.append(("DELETE", path, None))
    records.pop(rid)
    return {"message": "deleted", "id": rid, "deleted": 1}


edit.api_get = fake_get
edit.api_put = fake_put
edit.api_delete = fake_delete
edit.clear_health_caches = lambda: None
edit.render_edit()
"""


def _app(body: str) -> AppTest:
    app = AppTest.from_string(_HEADER + body, default_timeout=30)
    app.run()
    return app


def _button(app: AppTest, label: str):
    for button in app.button:
        if button.label == label:
            return button
    raise AssertionError(
        f"button {label!r} not rendered: {[b.label for b in app.button]}"
    )


# ── 新規登録 ────────────────────────────────────────────────

def _create_snapshot(app: AppTest) -> dict:
    snapshot = {
        key: app.text_input(key=key).value
        for key in create_measurement_state_keys("create")
    }
    snapshot["user"] = app.selectbox(key="create_user_select").value
    snapshot["date"] = app.date_input(key="create_date_input").value
    snapshot["memo"] = app.text_input(key="create_memo").value
    snapshot["meal_detail"] = app.text_area(key="create_meal_detail").value
    snapshot["activity_log"] = app.text_area(key="create_activity_log").value
    return snapshot


def _fill_create_form(app: AppTest, weight: str = "64.2") -> None:
    app.selectbox(key="create_user_select").select("father")
    app.text_input(key="create_weight_text").set_value(weight)
    app.text_input(key="create_memo").set_value("memo-1")
    app.text_area(key="create_meal_detail").set_value("meal-1")
    app.text_area(key="create_activity_log").set_value("act-1")
    app.run()


def test_create_form_returns_to_its_initial_state_after_a_successful_post():
    app = _app(_CREATE_BODY)
    initial = _create_snapshot(app)

    _fill_create_form(app)
    assert _create_snapshot(app) != initial

    _button(app, "登録").click().run()

    posted = app.session_state["posted"]
    assert len(posted) == 1
    assert posted[0]["body"]["memo"] == "memo-1"
    assert posted[0]["body"]["weight"] == 64.2
    assert _create_snapshot(app) == initial
    assert "clear_create_form" not in app.session_state
    assert not app.exception


def test_create_form_keeps_the_input_when_the_payload_is_invalid():
    app = _app(_CREATE_BODY)

    _fill_create_form(app, weight="not-a-number")
    filled = _create_snapshot(app)

    _button(app, "登録").click().run()

    assert app.session_state["posted"] == []
    assert len(app.error) == 1
    assert _create_snapshot(app) == filled


def test_create_form_keeps_the_input_when_the_api_call_fails():
    app = _app(_CREATE_BODY)
    app.session_state["api_mode"] = "error"

    _fill_create_form(app)
    filled = _create_snapshot(app)

    _button(app, "登録").click().run()

    assert app.session_state["posted"] == []
    assert len(app.error) == 1
    assert _create_snapshot(app) == filled


# ── 修正・削除 ──────────────────────────────────────────────

def test_switching_users_moves_the_date_selection_into_the_new_user_options():
    app = _app(_EDIT_BODY)
    app.selectbox(key="edit_date_select").select("2026-08-22").run()
    assert app.selectbox(key="edit_date_select").value == "2026-08-22"

    app.selectbox(key="edit_user_select").select("father").run()

    date_select = app.selectbox(key="edit_date_select")
    assert date_select.options == ["2026-07-10"]
    assert date_select.value == "2026-07-10"
    assert app.session_state["edit_date_select"] == "2026-07-10"
    assert app.text_input[0].value == "memo-F"
    assert not app.warning
    assert not app.exception


def test_date_selection_stays_valid_after_deleting_the_selected_record():
    app = _app(_EDIT_BODY)
    app.selectbox(key="edit_date_select").select("2026-08-22").run()

    app.number_input(key="del_id").set_value(12).run()
    assert ("GET", "/api/health/record/12", None) in app.session_state["api_calls"]

    app.checkbox[0].check().run()
    _button(app, "削除実行").click().run()

    assert ("DELETE", "/api/health/record/12", None) in app.session_state["api_calls"]
    assert 12 not in app.session_state["records"]

    date_select = app.selectbox(key="edit_date_select")
    assert date_select.options == ["2026-08-23"]
    assert date_select.value == "2026-08-23"
    assert app.number_input(key="del_id").value is None
    assert not app.warning
    assert not app.exception


def test_update_targets_the_record_on_screen_after_switching_dates_back():
    app = _app(_EDIT_BODY)

    app.text_input[0].set_value("unsaved-A").run()
    app.selectbox(key="edit_date_select").select("2026-08-22").run()
    assert app.text_input[0].value == "memo-B"

    app.selectbox(key="edit_date_select").select("2026-08-23").run()
    assert app.text_input[0].value == "memo-A"

    app.text_input[0].set_value("memo-A-edited")
    app.number_input(key="edit_self_2026-08-23_weight").set_value(65.0)
    app.run()
    _button(app, "更新").click().run()

    puts = [call for call in app.session_state["api_calls"] if call[0] == "PUT"]
    assert len(puts) == 1
    _op, path, body = puts[0]
    assert path == "/api/health/record/11"
    assert body["memo"] == "memo-A-edited"
    assert body["weight"] == 65.0
    assert app.session_state["records"][12]["memo"] == "memo-B"
    assert not app.exception
