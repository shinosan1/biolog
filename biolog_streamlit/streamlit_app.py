from datetime import date, datetime, timedelta

import seaborn as sns
import streamlit as st

from api_client import ApiClientError, api_get
from cache import clear_health_caches
from config import USER_IDS, USER_LABELS
from time_utils import JST
from ui_style import inject_number_input_styles
from views.create import render_create
from views.edit import render_edit
from views.graph import render_graph
from views.import_view import render_csv_import
from views.list_view import render_list
from views.summary import render_summary

st.set_page_config(page_title="BioLog", layout="wide")
inject_number_input_styles()
st.title("BioLog — 家族健康記録")


def render_health_status(response: dict) -> None:
    status = response.get("status")
    if status == "ok":
        st.success("OK")
    elif status == "degraded":
        st.warning("注意 — API は劣化状態です")
    else:
        st.error("異常 — API は利用できない状態です")


# ── サイドバー ──────────────────────────────────────────
with st.sidebar:
    st.header("フィルター")
    selected_users: list = st.multiselect(
        "ユーザー",
        options=USER_IDS,
        default=["self"],
        format_func=lambda x: USER_LABELS[x],
    )

    today = date.today()
    date_start = st.date_input("開始日", value=today - timedelta(days=30))
    date_end = st.date_input("終了日", value=datetime.now(JST).date())

    st.divider()
    if st.button("更新"):
        clear_health_caches()
        st.rerun()

    st.caption("※ データ一覧は約10秒ごとに自動更新されます。必要に応じて「更新」を押してください。")

    if st.button("ヘルスチェック"):
        try:
            r = api_get("/api/health/health")
        except ApiClientError as e:
            st.error(f"API エラー: {e.message}")
            r = None
        if r:
            render_health_status(r)


# ── サマリーカード ──────────────────────────────────────
render_summary()

st.divider()


# ── タブ ────────────────────────────────────────────────
tab_graph, tab_list, tab_create, tab_edit = st.tabs(
    ["グラフ", "一覧", "新規登録", "修正・削除"]
)


# ────────────────────────────────
# タブ 1: グラフ
# ────────────────────────────────
with tab_graph:
    render_graph(selected_users, date_start, date_end)


# ────────────────────────────────
# タブ 2: 一覧
# ────────────────────────────────
with tab_list:
    render_list(selected_users, date_start, date_end)
    render_csv_import()


# ────────────────────────────────
# タブ 3: 新規登録
# ────────────────────────────────
with tab_create:
    render_create()


# ────────────────────────────────
# タブ 4: 修正・削除
# ────────────────────────────────
with tab_edit:
    render_edit()
