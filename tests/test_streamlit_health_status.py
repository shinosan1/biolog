import ast
from pathlib import Path


class _StreamlitSpy:
    def __init__(self):
        self.calls = []

    def success(self, text):
        self.calls.append(("success", text))

    def warning(self, text):
        self.calls.append(("warning", text))

    def error(self, text):
        self.calls.append(("error", text))


def _health_renderer():
    source = Path(__file__).resolve().parents[1] / "biolog_streamlit" / "streamlit_app.py"
    module = ast.parse(source.read_text(encoding="utf-8"))
    function = next(
        node for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name == "render_health_status"
    )
    namespace = {"st": _StreamlitSpy()}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec"), namespace)
    return namespace["render_health_status"], namespace["st"]


def test_degraded_and_unhealthy_health_responses_are_not_success():
    render, st = _health_renderer()
    render({"status": "degraded"})
    render({"status": "unhealthy"})

    assert [kind for kind, _text in st.calls] == ["warning", "error"]
