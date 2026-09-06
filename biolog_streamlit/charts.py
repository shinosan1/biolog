import japanize_matplotlib  # import するだけで日本語フォント有効化
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
from math import ceil
import pandas as pd
import streamlit as st

from config import USER_COLORS, USER_LABELS

plt.style.use("dark_background")


def _jp_date(x, _):
    try:
        dt = mdates.num2date(x)
        return f"{dt.year}年{dt.month}月{dt.day}日"
    except Exception:
        return ""


def plot_metric(df: pd.DataFrame, col: str, title: str, yunit: str, selected_users: list):
    plt.clf()
    fig, ax = plt.subplots(figsize=(10, 3.5))
    has_data = False
    for uid in selected_users:
        udf = (
            df[df["user_id"] == uid]
            .dropna(subset=[col])
            .sort_values("date")
        )
        if not udf.empty:
            ax.plot(
                udf["date"], udf[col],
                marker="o", label=USER_LABELS[uid],
                color=USER_COLORS[uid], linewidth=2, markersize=5,
            )
            has_data = True
    if has_data:
        ax.set_title(title, fontsize=13)
        ax.set_xlabel("日付", fontsize=10)
        ax.set_ylabel(yunit, fontsize=10)
        if col in ("weight", "temperature", "body_fat", "muscle_mass"):
            ax.yaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{x:.1f}"))
        all_dates = sorted(df["date"].unique())
        ax.set_xticks(all_dates)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
        fig.autofmt_xdate(rotation=30)
        fig.canvas.draw()
        ax.legend(loc="upper left", fontsize=9)
        ax.grid(True, alpha=0.3)
        plt.tight_layout()
        st.pyplot(fig, clear_figure=True)
    else:
        st.info(f"{title}のデータがありません")
    plt.close(fig)


def plot_blood_pressure(df: pd.DataFrame, selected_users: list):
    plt.clf()
    fig_bp, ax_bp = plt.subplots(figsize=(10, 4))
    has_bp = False
    measurement_dates = set()
    for uid in selected_users:
        udf = (
            df[df["user_id"] == uid]
            .dropna(subset=["systolic_bp", "diastolic_bp"])
            .sort_values("date")
        )
        if not udf.empty:
            measurement_dates.update(udf["date"])
            ax_bp.plot(
                udf["date"], udf["systolic_bp"],
                marker="o", label=f"{USER_LABELS[uid]} 収縮期",
                color=USER_COLORS[uid], linestyle="-", linewidth=2, markersize=5,
            )
            ax_bp.plot(
                udf["date"], udf["diastolic_bp"],
                marker="s", label=f"{USER_LABELS[uid]} 拡張期",
                color=USER_COLORS[uid], linestyle="--", linewidth=2, markersize=5,
            )
            has_bp = True
    if has_bp:
        ax_bp.axhline(y=120, color="gray",      linestyle="--", alpha=0.7, linewidth=1, label="目標: 収縮期 120")
        ax_bp.axhline(y=80,  color="lightgray", linestyle="--", alpha=0.7, linewidth=1, label="目標: 拡張期 80")
        ax_bp.set_title("血圧 (mmHg)", fontsize=13)
        ax_bp.set_xlabel("日付", fontsize=10)
        ax_bp.set_ylabel("mmHg", fontsize=10)
        ax_bp.set_xticks(_blood_pressure_tick_dates(measurement_dates))
        ax_bp.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
        fig_bp.autofmt_xdate(rotation=30)
        ax_bp.legend(loc="upper left", fontsize=9, ncol=2)
        ax_bp.grid(axis="y", alpha=0.3)
        plt.tight_layout()
        st.pyplot(fig_bp, clear_figure=True)
    else:
        st.info("血圧データがありません")
    plt.close(fig_bp)


def _blood_pressure_tick_dates(measurement_dates, max_ticks: int = 8):
    """Return measured dates only, limiting labels without hiding either end."""
    dates = sorted(measurement_dates)
    if len(dates) <= max_ticks:
        return dates

    step = ceil((len(dates) - 1) / (max_ticks - 1))
    ticks = dates[::step]
    if ticks[-1] != dates[-1]:
        ticks.append(dates[-1])
    return ticks
