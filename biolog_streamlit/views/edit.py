import pandas as pd
import streamlit as st

from api_client import ApiClientError, api_delete, api_get, api_put
from cache import clear_health_caches
from config import LEGACY_UTC_MAX_RECORD_ID, USER_IDS, USER_LABELS
from form_components import (
    accept_latest_measurements,
    render_measurement_inputs,
    sync_edit_measurement_state,
)
from form_fields import MEASUREMENT_FIELDS
from payloads import build_update_payload
from safe_table import render_safe_table
from time_utils import to_jst


def _api_get_with_error(path: str, params: dict = None, suppress_404: bool = False):
    try:
        return api_get(path, params=params, suppress_404=suppress_404)
    except ApiClientError as e:
        st.error(f"API エラー: {e.message}")
        return None


def _legacy_utc_max_record_id() -> int:
    metadata = _api_get_with_error("/api/health/metadata")
    if metadata is None:
        return LEGACY_UTC_MAX_RECORD_ID
    return int(metadata["legacy_utc_max_record_id"])


def render_edit():
    st.subheader("修正・削除")

    # ── ユーザー選択 ──
    edit_user = st.selectbox(
        "編集するユーザー",
        options=USER_IDS,
        format_func=lambda x: USER_LABELS[x],
        key="edit_user_select",
    )

    # ── 登録済み日付一覧を取得 ──
    edit_records_list = _api_get_with_error(
        "/api/health/records",
        params={"user_id": edit_user, "limit": 500},
    ) or []
    edit_dates = sorted({r["date"] for r in edit_records_list}, reverse=True)

    if not edit_dates:
        st.info(f"{USER_LABELS[edit_user]}の登録済みデータがありません")
    else:
        edit_date = st.selectbox(
            "編集する日付",
            options=edit_dates,
            key="edit_date_select",
        )

        # ── 選択した日付のレコードを取得 ──
        current_for_edit = _api_get_with_error(
            "/api/health/record/day",
            params={"user_id": edit_user, "date": edit_date},
            suppress_404=True,
        )

        if not current_for_edit:
            st.warning(f"{edit_date} のレコードが見つかりません")
        else:
            rec = current_for_edit
            edit_key_prefix = f"edit_{edit_user}_{edit_date}"
            conflicts = sync_edit_measurement_state(
                st.session_state,
                edit_key_prefix,
                rec,
            )
            if conflicts:
                labels = {
                    field.name: field.label
                    for field in MEASUREMENT_FIELDS
                }
                conflict_labels = "、".join(labels[name] for name in conflicts)
                st.warning(
                    f"外部更新と未保存の編集が競合しています: {conflict_labels}。"
                    "現在の入力を保持しています。"
                )
                if st.button(
                    "競合項目を最新値に置換",
                    key=f"{edit_key_prefix}__accept_latest",
                ):
                    accept_latest_measurements(
                        st.session_state,
                        edit_key_prefix,
                        rec,
                        conflicts,
                    )
                    st.rerun()

            with st.form(f"edit_form_{edit_user}_{edit_date}"):
                measurements = render_measurement_inputs(
                    "edit",
                    edit_key_prefix,
                    rec,
                )
                edit_memo = st.text_input("メモ", value=rec.get("memo") or "")
                edit_meal_detail = st.text_area(
                    "食事ログ",
                    value=rec.get("meal_detail") or ""
                )
                edit_activity_log = st.text_area(
                    "行動ログ",
                    value=rec.get("activity_log") or ""
                )
                update_btn = st.form_submit_button("更新")

            if update_btn:
                body = build_update_payload(
                    measurements=measurements,
                    memo=edit_memo,
                    meal_detail=edit_meal_detail,
                    activity_log=edit_activity_log,
                )

                try:
                    result = api_put(f"/api/health/record/{rec['id']}", body)
                except ApiClientError as e:
                    st.error(f"更新失敗: {e.message}" if e.status_code else f"API エラー: {e.message}")
                    result = None
                if result:
                    st.success(f"更新完了 — {edit_date} ({USER_LABELS[edit_user]})")
                    clear_health_caches()
                    st.rerun()

    st.divider()
    st.markdown("**削除**")

    if st.session_state.get("clear_del_id"):
        if "del_id" in st.session_state:
            st.session_state["del_id"] = None
        del st.session_state["clear_del_id"]

    delete_id = st.number_input("削除するレコード ID", min_value=1, step=1, value=None, key="del_id")

    if delete_id is not None:
        del_preview = _api_get_with_error(f"/api/health/record/{int(delete_id)}", suppress_404=True)
    else:
        del_preview = None

    if del_preview:
        st.markdown("**削除対象レコード:**")
        disp = {k: v for k, v in del_preview.items() if k != "request_id"}
        disp["ユーザー"] = USER_LABELS.get(disp.pop("user_id", ""), "")
        if "created_at" in disp and disp["created_at"]:
            disp["created_at"] = to_jst(
                disp["created_at"], record_id=disp.get("id"),
                legacy_utc_max_record_id=_legacy_utc_max_record_id(),
            )
        render_safe_table(pd.DataFrame([disp]))

        confirm_delete = st.checkbox(f"上記レコード（ID: {delete_id}）を削除することを確認します")
        if st.button("削除実行", disabled=not confirm_delete):
            try:
                result = api_delete(f"/api/health/record/{int(delete_id)}")
            except ApiClientError as e:
                st.error(f"削除失敗: {e.message}" if e.status_code else f"API エラー: {e.message}")
                result = None
            if result:
                st.success(f"削除完了 — ID: {result.get('id')}")
                st.session_state["clear_del_id"] = True
                clear_health_caches()
                st.rerun()
    else:
        if delete_id is not None:
            st.warning(f"ID {int(delete_id)} のレコードは存在しません")
