import sys
import types
from pathlib import Path

import matplotlib.dates as mdates
import pandas as pd


STREAMLIT_DIR = Path(__file__).resolve().parents[1] / "biolog_streamlit"
if str(STREAMLIT_DIR) not in sys.path:
    sys.path.insert(0, str(STREAMLIT_DIR))

# The chart behavior under test does not depend on the optional font helper.
sys.modules.setdefault("japanize_matplotlib", types.ModuleType("japanize_matplotlib"))


def _dates_from_ticks(axis):
    return [
        mdates.num2date(tick).date().isoformat()
        for tick in axis.get_xticks()
    ]


def test_blood_pressure_ticks_only_include_measurement_dates(monkeypatch):
    import charts

    figures = []
    monkeypatch.setattr(charts.st, "pyplot", lambda figure, **_: figures.append(figure))
    monkeypatch.setattr(charts.plt, "tight_layout", lambda: None)
    data = pd.DataFrame([
        {"date": "2026-09-01", "user_id": "self", "systolic_bp": 120, "diastolic_bp": 80},
        {"date": "2026-09-02", "user_id": "self", "systolic_bp": None, "diastolic_bp": None},
        {"date": "2026-09-03", "user_id": "self", "systolic_bp": 118, "diastolic_bp": 78},
    ])
    data["date"] = pd.to_datetime(data["date"])

    charts.plot_blood_pressure(data, ["self"])

    axis = figures[0].axes[0]
    assert _dates_from_ticks(axis) == ["2026-09-01", "2026-09-03"]
    assert not any(line.get_visible() for line in axis.get_xgridlines())


def test_blood_pressure_tick_labels_are_limited_for_many_measurements():
    import charts

    dates = pd.date_range("2026-01-01", periods=30, freq="D")
    ticks = charts._blood_pressure_tick_dates(dates)

    assert len(ticks) <= 8
    assert ticks[0] == dates[0]
    assert ticks[-1] == dates[-1]
