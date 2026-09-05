import pandas as pd
import streamlit as st

from api_client import ApiClientError, api_get
from config import LEGACY_UTC_MAX_RECORD_ID, USER_LABELS
from formatters import _safe_str, is_truncated, truncate
from safe_table import render_safe_table
from time_utils import to_jst


def _filter_records(records: list, selected_users: list) -> pd.DataFrame:
    if not selected_users or not records:
        return pd.DataFrame()
    df = pd.DataFrame(records)
    return df[df["user_id"].isin(selected_users)].copy()


def _prepare_display(
    df: pd.DataFrame, *, legacy_utc_max_record_id=LEGACY_UTC_MAX_RECORD_ID
) -> pd.DataFrame:
    df = df.copy()
    df["ユーザー"] = df["user_id"].map(USER_LABELS)
    display_cols = [
        "id", "date", "ユーザー", "created_at",
        "temperature", "pulse", "systolic_bp", "diastolic_bp",
        "weight", "body_fat", "muscle_mass", "bmr",
        "meal_detail", "activity_log", "memo",
    ]
    existing = [c for c in display_cols if c in df.columns]
    disp = df[existing].copy()
    if "created_at" in disp.columns:
        disp["created_at"] = disp.apply(
            lambda row: to_jst(
                row["created_at"], record_id=row.get("id"),
                legacy_utc_max_record_id=legacy_utc_max_record_id,
            ),
            axis=1,
        )
    disp = disp.rename(columns={
        "created_at":   "記録日時",
        "date":         "対象日",
        "weight":       "体重(kg)",
        "systolic_bp":  "収縮期血圧",
        "diastolic_bp": "拡張期血圧",
        "temperature":  "体温(℃)",
        "pulse":        "脈拍(bpm)",
        "body_fat":     "体脂肪率(%)",
        "muscle_mass":  "筋肉量(kg)",
        "bmr":          "基礎代謝(kcal)",
        "memo":         "メモ",
        "meal_detail":  "食事ログ",
        "activity_log": "行動ログ",
    })
    priority = [
        "id", "ユーザー", "対象日", "記録日時", "体重(kg)",
        "収縮期血圧", "拡張期血圧", "体温(℃)", "脈拍(bpm)",
        "基礎代謝(kcal)", "体脂肪率(%)", "筋肉量(kg)",
        "メモ", "食事ログ", "行動ログ",
    ]
    ordered = [c for c in priority if c in disp.columns]
    rest = [c for c in disp.columns if c not in ordered]
    return disp[ordered + rest]


def _sanitize_csv_value(value):
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def _sanitize_csv_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    sanitized = df.copy()
    for column in sanitized.columns:
        sanitized[column] = sanitized[column].map(_sanitize_csv_value)
    return sanitized


def _csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8-sig")


def _legacy_utc_max_record_id() -> int:
    metadata = api_get("/api/health/metadata")
    return int(metadata["legacy_utc_max_record_id"])


@st.fragment(run_every="10s")
def render_list(selected_users: list, date_start, date_end):
    st.subheader("データ一覧")

    if not selected_users:
        st.info("ユーザーを選択してください")
        return

    try:
        records = api_get(
            "/api/health/records/range",
            params={"start": str(date_start), "end": str(date_end)},
        )
        legacy_utc_max_record_id = _legacy_utc_max_record_id()
    except ApiClientError as e:
        st.error(f"API エラー: {e.message}")
        return

    full_df = _filter_records(records, selected_users)
    if full_df.empty:
        st.info("データがありません")
        return

    full_df = full_df.sort_values(["date", "id"], ascending=[False, False])
    page = st.number_input("ページ", min_value=1, value=1, step=1)
    page_size = 20
    offset = (page - 1) * page_size
    page_df = full_df.iloc[offset:offset + page_size]
    if page_df.empty:
        st.info("このページにはデータがありません")
    else:
        disp = _prepare_display(
            page_df, legacy_utc_max_record_id=legacy_utc_max_record_id
        )

        # 表示用: 長文列を省略
        _LIMITS = {
            "メモ":    40,
            "食事ログ": 80,
            "行動ログ": 200,
        }
        disp_view = disp.copy()
        for col, limit in _LIMITS.items():
            if col in disp_view.columns:
                disp_view[col] = disp_view[col].apply(
                    lambda s, lim=limit: truncate(s, lim)
                )

        render_safe_table(disp_view)

        # ─── 詳細表示（_LIMITS を超えるセルのみ expander 展開）───
        long_cols = [c for c in _LIMITS if c in disp.columns]
        has_date = "対象日" in disp.columns
        has_user = "ユーザー" in disp.columns
        shown_any = False
        for idx, _row in disp.iterrows():
            expanders_for_row = []
            for col in long_cols:
                full = _safe_str(disp.at[idx, col])
                if is_truncated(full, _LIMITS[col]):
                    expanders_for_row.append((col, full))
            if not expanders_for_row:
                continue
            if not shown_any:
                st.divider()
                st.caption("全文表示（省略された長文のみ）")
                shown_any = True
            label_date = _safe_str(disp.at[idx, "対象日"]) if has_date else ""
            label_user = _safe_str(disp.at[idx, "ユーザー"]) if has_user else ""
            for col, full in expanders_for_row:
                with st.expander(f"{label_date} / {label_user} / {col}"):
                    st.write(full)

    # CSV用: 選択ユーザー・指定期間の完全データ（ページングなし）
    disp_csv = _sanitize_csv_dataframe(_prepare_display(
        full_df, legacy_utc_max_record_id=legacy_utc_max_record_id
    ))
    csv = _csv_bytes(disp_csv)
    st.download_button(
        label="CSV ダウンロード",
        data=csv,
        file_name=f"biolog_{date_start}_{date_end}.csv",
        mime="text/csv",
    )
