import importlib
import sys
from pathlib import Path
import pytest


ROOT = Path(__file__).resolve().parents[1]
STREAMLIT_DIR = ROOT / "biolog_streamlit"


class _Upload:
    def __init__(self, text): self.data = text.encode("utf-8-sig")
    def getvalue(self): return self.data


class _Context:
    def __enter__(self): return self
    def __exit__(self, *_): return False


class _St:
    def __init__(self, upload, buttons=(), formula=True):
        self.session_state, self.upload = {}, upload
        self.buttons, self.formula, self.reruns = list(buttons), formula, 0
    def expander(self, *_args, **_kwargs): return _Context()
    def caption(self, *_args, **_kwargs): pass
    def file_uploader(self, *_args, **_kwargs): return self.upload
    def checkbox(self, *_args, **_kwargs): return self.formula
    def button(self, *_args, **_kwargs): return self.buttons.pop(0) if self.buttons else False
    def write(self, *_args, **_kwargs): pass
    def warning(self, *_args, **_kwargs): pass
    def error(self, *_args, **_kwargs): pass
    def success(self, *_args, **_kwargs): pass
    def rerun(self): self.reruns += 1


def _view():
    sys.path.insert(0, str(STREAMLIT_DIR))
    try: return importlib.import_module("views.import_view")
    finally: sys.path.remove(str(STREAMLIT_DIR))


def test_ui_previews_before_execute_and_invalid_preview_never_writes(monkeypatch):
    view, calls = _view(), []
    st = _St(_Upload("a"), buttons=[True])
    monkeypatch.setattr(view, "st", st)
    monkeypatch.setattr(view, "render_safe_table", lambda *_: None)
    monkeypatch.setattr(view, "api_post", lambda path, body: calls.append(path) or {"total": 1, "created": 0, "updated": 0, "errors": [{"row": 2, "field": "対象日", "reason": "bad"}]})
    view.render_csv_import()
    assert calls == ["/api/health/import/preview"]
    st.buttons = [False, True]
    view.render_csv_import()
    assert calls == ["/api/health/import/preview"]


def test_ui_executes_once_clears_cache_reruns_and_retains_result(monkeypatch):
    view, calls, cleared = _view(), [], []
    st = _St(_Upload("a"), buttons=[True])
    monkeypatch.setattr(view, "st", st)
    monkeypatch.setattr(view, "render_safe_table", lambda *_: None)
    monkeypatch.setattr(view, "clear_health_caches", lambda: cleared.append(True))
    monkeypatch.setattr(view, "api_post", lambda path, body: calls.append(path) or {"total": 1, "created": 1, "updated": 0, "skipped": 0, "errors": []})
    view.render_csv_import()
    st.buttons = [False, True]
    view.render_csv_import()
    assert calls == ["/api/health/import/preview", "/api/health/import"]
    assert cleared == [True] and st.reruns == 1
    assert st.session_state["csv_import_result"]["created"] == 1
    assert "csv_import_preview" not in st.session_state
    st.buttons = [False]
    view.render_csv_import()
    assert st.session_state["csv_import_result"]["created"] == 1
    assert len(calls) == 2


def test_ui_upload_change_invalidates_preview(monkeypatch):
    view, st = _view(), _St(_Upload("a"))
    st.session_state.update({"csv_import_preview_key": "old", "csv_import_preview": {"errors": []}})
    monkeypatch.setattr(view, "st", st)
    monkeypatch.setattr(view, "render_safe_table", lambda *_: None)
    view.render_csv_import()
    assert "csv_import_preview" not in st.session_state


def test_ui_option_change_invalidates_preview_without_writing(monkeypatch):
    view, st = _view(), _St(_Upload("a"))
    st.session_state.update({"csv_import_preview_key": view._preview_key(st.upload.getvalue(), False),
                             "csv_import_preview": {"errors": []}})
    monkeypatch.setattr(view, "st", st)
    monkeypatch.setattr(view, "api_post", lambda *_: pytest.fail("must re-preview first"))
    view.render_csv_import()
    assert "csv_import_preview" not in st.session_state


def test_ui_error_preserves_upload_and_does_not_clear_caches(monkeypatch):
    view, st = _view(), _St(_Upload("a"), buttons=[False, True])
    preview = {"total": 1, "errors": []}
    st.session_state.update({"csv_import_preview_key": view._preview_key(st.upload.getvalue(), True),
                             "csv_import_preview": preview})
    warnings = []
    monkeypatch.setattr(view, "st", st)
    monkeypatch.setattr(st, "warning", warnings.append)
    monkeypatch.setattr(view, "clear_health_caches", lambda: pytest.fail("write was not confirmed"))
    def fail(*_):
        raise view.ApiClientError("read timeout", None)
    monkeypatch.setattr(view, "api_post", fail)
    view.render_csv_import()
    assert st.upload.getvalue() == b"\xef\xbb\xbfa"
    assert st.session_state["csv_import_preview"] == preview
    assert st.reruns == 0
    assert any("実行結果を確認できません" in message for message in warnings)
    st.buttons = [True]
    view.render_csv_import()
    assert "csv_import_preview" not in st.session_state


def test_upload_decodes_bom_japanese_and_rejects_wrong_encoding_or_size():
    view = _view()
    assert view._read_upload(_Upload("日本語"))[1] == "日本語"
    upload = _Upload("")
    upload.data = b"\xff"
    with pytest.raises(ValueError, match="UTF-8"):
        view._read_upload(upload)
    upload.data = b"x" * (5 * 1024 * 1024 + 1)
    with pytest.raises(ValueError, match="5 MiB"):
        view._read_upload(upload)
