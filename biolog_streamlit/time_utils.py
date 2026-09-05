from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from config import LEGACY_UTC_MAX_RECORD_ID

JST = ZoneInfo("Asia/Tokyo")


def to_jst(dt, *, record_id=None, legacy_utc_max_record_id=LEGACY_UTC_MAX_RECORD_ID) -> str:
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt.replace(" ", "T"))

    if dt.tzinfo is None:
        try:
            is_legacy_utc = int(record_id) <= legacy_utc_max_record_id
        except (TypeError, ValueError):
            is_legacy_utc = False
        dt = dt.replace(tzinfo=timezone.utc if is_legacy_utc else JST)

    return dt.astimezone(JST).strftime("%Y-%m-%d %H:%M")
