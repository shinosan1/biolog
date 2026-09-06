"""CSV snapshot import UI. The file is kept in session memory only."""

import hashlib

import pandas as pd
import streamlit as st

from api_client import ApiClientError, api_post
from cache import clear_health_caches
from safe_table import render_safe_table


def _show_errors(errors) -> None:
    if not errors:
        return
    rows = [
        {"行": item.get("row", ""), "項目": item.get("field", ""),
         "理由": item.get("reason", "")}
        for item in errors if isinstance(item, dict)
    ]
    if rows:
        render_safe_table(pd.DataFrame(rows))


def _preview_key(data: bytes, restore_formula_prefix: bool) -> str:
    return hashlib.sha256(data + str(restore_formula_prefix).encode()).hexdigest()


def _read_upload(uploaded_file):
    data = uploaded_file.getvalue()
    if len(data) > 5 * 1024 * 1024:
        raise ValueError("CSVは5 MiB以下にしてください")
    try:
        return data, data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError("UTF-8またはUTF-8 BOM付きCSVを選択してください")


def _show_preview(preview: dict) -> None:
    st.write(
        f"CSVデータ行: {preview.get('total', 0)} / "
        f"新規予定: {preview.get('created', 0)} / "
        f"更新予定: {preview.get('updated', 0)} / "
        f"エラー指摘数: {len(preview.get('errors', []))}"
    )
    count = preview.get("formula_prefix_count", 0)
    if count:
        st.warning(
            f"数式対策の先頭アポストロフィ候補が {count} 件あります。"
            "元から同じ文字で始まる値とは区別できません。"
        )
    _show_errors(preview.get("errors", []))


def render_csv_import() -> None:
    with st.expander("CSV インポート"):
        st.caption("BioLogのCSV出力を、各ユーザー・対象日の完全な状態として追加・更新します。")
        st.caption("空欄の測定値はNULL、空欄のメモ・ログは空文字として復元します。id・記録日時・request_idは取り込みません。")
        st.caption("事前にCSVをバックアップしてください。最大5 MiB・5,000行で、サイドバーの期間・ユーザーフィルターとは独立して取り込みます。実行時に状態を再判定します。")
        uploaded = st.file_uploader("CSVファイル", type=["csv"], key="csv_import_file")
        restore_formula_prefix = st.checkbox(
            "CSV出力の数式対策で付いた先頭の ' を戻す",
            key="csv_import_restore_formula_prefix",
            value=True,
            help="BioLog出力の保護文字を戻します。元から同じアポストロフィがある値を保持する場合は解除してください。",
        )
        if uploaded is None:
            for key in ("csv_import_preview", "csv_import_preview_key", "csv_import_result"):
                st.session_state.pop(key, None)
            return
        try:
            data, csv_text = _read_upload(uploaded)
        except ValueError as exc:
            st.error(str(exc))
            return
        fingerprint = _preview_key(data, restore_formula_prefix)
        if st.session_state.get("csv_import_preview_key") != fingerprint:
            st.session_state.pop("csv_import_preview", None)
            st.session_state.pop("csv_import_result", None)
            st.session_state["csv_import_preview_key"] = fingerprint

        if st.button("内容を解析", key="csv_import_preview_button"):
            st.session_state.pop("csv_import_preview", None)
            st.session_state.pop("csv_import_result", None)
            try:
                st.session_state["csv_import_preview"] = api_post(
                    "/api/health/import/preview",
                    {"csv_text": csv_text, "restore_formula_prefix": restore_formula_prefix},
                )
            except ApiClientError as exc:
                detail = exc.message
                if isinstance(detail, dict):
                    st.error(detail.get("message", "CSV解析に失敗しました"))
                    _show_errors(detail.get("errors", []))
                else:
                    st.error(f"API エラー: {detail}")

        preview = st.session_state.get("csv_import_preview")
        previous_result = st.session_state.get("csv_import_result")
        if previous_result:
            st.success(
                f"完了: 新規 {previous_result.get('created', 0)}件、"
                f"更新 {previous_result.get('updated', 0)}件、"
                f"スキップ {previous_result.get('skipped', 0)}件、"
                f"エラー {previous_result.get('errors', 0)}件"
            )
        if not preview:
            return
        _show_preview(preview)
        if preview.get("errors"):
            st.error("エラーを修正してから、もう一度解析してください。")
            return
        if st.button("インポートを実行", key="csv_import_execute_button", type="primary"):
            try:
                result = api_post(
                    "/api/health/import",
                    {"csv_text": csv_text, "restore_formula_prefix": restore_formula_prefix},
                )
            except ApiClientError as exc:
                detail = exc.message
                if isinstance(detail, dict):
                    st.error(detail.get("message", "CSV取り込みに失敗しました"))
                    _show_errors(detail.get("errors", []))
                else:
                    st.error(f"API エラー: {detail}")
                if exc.status_code == 503 or exc.status_code is None:
                    st.warning("実行結果を確認できません。自動再試行は行わないため、更新してから内容を確認してください。")
                return
            clear_health_caches()
            st.session_state["csv_import_result"] = result
            st.session_state.pop("csv_import_preview", None)
            st.rerun()
