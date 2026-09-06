"""CSV snapshot import validation shared by the preview and write endpoints."""

import csv
from decimal import Decimal, InvalidOperation
from io import StringIO

from pydantic import ValidationError

from schemas import CsvImportRecord


MAX_CSV_BYTES = 5 * 1024 * 1024
MAX_CSV_ROWS = 5000

FIELD_NAMES = {
    "ユーザー": "user_id",
    "対象日": "date",
    "体重(kg)": "weight",
    "収縮期血圧": "systolic_bp",
    "拡張期血圧": "diastolic_bp",
    "体温(℃)": "temperature",
    "脈拍(bpm)": "pulse",
    "基礎代謝(kcal)": "bmr",
    "体脂肪率(%)": "body_fat",
    "筋肉量(kg)": "muscle_mass",
    "メモ": "memo",
    "食事ログ": "meal_detail",
    "行動ログ": "activity_log",
}
REQUIRED_HEADERS = set(FIELD_NAMES)
IGNORED_HEADERS = {"id", "記録日時", "created_at", "request_id"}
INTEGER_FIELDS = {"pulse", "systolic_bp", "diastolic_bp", "bmr"}
TEXT_FIELDS = {"memo", "meal_detail", "activity_log"}
USER_LABELS = {"自分": "self", "父": "father", "母": "mother"}


def _error(row: int, field: str, reason: str) -> dict:
    return {"row": row, "field": field, "reason": reason}


def _is_blank_row(values: dict) -> bool:
    return not any(value != "" for value in values.values())


def _remove_formula_prefix(value: str, enabled: bool) -> str:
    if enabled and len(value) > 1 and value[0] == "'" and value[1] in "=+-@":
        return value[1:]
    return value


def _number(value: str, field: str):
    if value == "":
        return None
    if value.strip() != value or "_" in value or len(value) > 64:
        raise ValueError("数値形式が不正です")
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise ValueError("数値として読み込めません")
    if not number.is_finite():
        raise ValueError("有限の数値を指定してください")
    if number.copy_abs().adjusted() > 6:
        raise ValueError("数値の範囲が不正です")
    if field in INTEGER_FIELDS:
        if number != number.to_integral_value():
            raise ValueError("整数を指定してください")
        return int(number)
    result = float(number)
    if result == 0 and number != 0:
        raise ValueError("小さすぎる数値は保存できません")
    if result == float("inf") or result == float("-inf"):
        raise ValueError("有限の数値を指定してください")
    return result


def _validate_record(row_number: int, values: dict, restore_formula_prefix: bool):
    payload = {}
    errors = []
    for header, field in FIELD_NAMES.items():
        value = values.get(header, "")
        if field in TEXT_FIELDS:
            payload[field] = _remove_formula_prefix(value, restore_formula_prefix)
        elif field == "user_id":
            payload[field] = USER_LABELS.get(value, value)
        elif field == "date":
            payload[field] = value
        else:
            try:
                payload[field] = _number(value, field)
            except ValueError as exc:
                errors.append(_error(row_number, header, str(exc)))
                payload[field] = None

    # Reuse the established update validation rules. CsvImportRecord deliberately
    # permits an all-empty daily snapshot because it is not a normal POST.
    try:
        validated = CsvImportRecord.model_validate(payload)
    except ValidationError as exc:
        for issue in exc.errors():
            field = issue["loc"][-1] if issue["loc"] else "row"
            header = next((h for h, f in FIELD_NAMES.items() if f == field), str(field))
            errors.append(_error(row_number, header, issue["msg"]))
    if errors:
        return None, errors
    return validated.model_dump(), []


def parse_csv_snapshot(csv_text: str, restore_formula_prefix: bool = False) -> dict:
    """Parse an exported BioLog CSV without retaining raw values in errors."""
    if not isinstance(csv_text, str):
        return {"total": 0, "rows": [], "errors": [_error(0, "CSV", "CSV本文が不正です")], "formula_prefix_count": 0}
    try:
        csv_size = len(csv_text.encode("utf-8"))
    except UnicodeEncodeError:
        return {"total": 0, "rows": [], "errors": [_error(0, "CSV", "UTF-8として扱えない文字があります")], "formula_prefix_count": 0}
    if csv_size > MAX_CSV_BYTES:
        return {"total": 0, "rows": [], "errors": [_error(0, "CSV", "CSVは5 MiB以下にしてください")], "formula_prefix_count": 0}
    try:
        reader = csv.reader(StringIO(csv_text, newline=""), strict=True)
        headers = next((row for row in reader if any(value != "" for value in row)), None)
    except (csv.Error, StopIteration):
        return {"total": 0, "rows": [], "errors": [_error(0, "CSV", "CSV形式が不正です")], "formula_prefix_count": 0}
    if not headers:
        return {"total": 0, "rows": [], "errors": [_error(1, "ヘッダー", "ヘッダー行がありません")], "formula_prefix_count": 0}
    if len(headers) != len(set(headers)):
        return {"total": 0, "rows": [], "errors": [_error(1, "ヘッダー", "重複したヘッダーがあります")], "formula_prefix_count": 0}
    missing = REQUIRED_HEADERS - set(headers)
    unknown = set(headers) - REQUIRED_HEADERS - IGNORED_HEADERS
    errors = []
    for header in sorted(missing):
        errors.append(_error(1, header, "必要な列がありません"))
    for header in sorted(unknown):
        errors.append(_error(1, header, "未対応の列です"))
    if errors:
        return {"total": 0, "rows": [], "errors": errors, "formula_prefix_count": 0}

    rows, seen = [], {}
    formula_prefix_count = 0
    total = 0
    try:
        while True:
            row_start = reader.line_num + 1
            try:
                raw = next(reader)
            except StopIteration:
                break
            if not any(value != "" for value in raw):
                continue
            total += 1
            if total > MAX_CSV_ROWS:
                errors.append(_error(row_start, "CSV", "データ行は5,000行以下にしてください"))
                break
            if len(raw) != len(headers):
                errors.append(_error(row_start, "CSV", "列数がヘッダーと一致しません"))
                continue
            values = dict(zip(headers, raw))
            formula_prefix_count += sum(
                1 for header in FIELD_NAMES
                if header in values and len(values[header]) > 1
                and values[header][0] == "'" and values[header][1] in "=+-@"
            )
            payload, row_errors = _validate_record(row_start, values, restore_formula_prefix)
            errors.extend(row_errors)
            if payload is None:
                continue
            key = (payload["user_id"], payload["date"])
            if key in seen:
                errors.append(_error(row_start, "対象日", f"ユーザー・対象日の重複（行{seen[key]}）"))
                continue
            seen[key] = row_start
            rows.append({"row": row_start, "payload": payload})
    except csv.Error:
        errors.append(_error(row_start, "CSV", "CSV形式が不正です"))
    return {"total": total, "rows": rows, "errors": errors,
            "formula_prefix_count": formula_prefix_count}
