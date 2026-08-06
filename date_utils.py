from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd


class InvalidBusinessDateError(ValueError):
    """Raised when a requested business date or timezone is invalid."""


def resolve_business_date(
    value: str | None,
    timezone_name: str = "Asia/Shanghai",
    *,
    now: datetime | None = None,
) -> str:
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as error:
        raise InvalidBusinessDateError(f"无效时区：{timezone_name}") from error

    if value is None or not value.strip():
        current = now.astimezone(timezone) if now is not None else datetime.now(timezone)
        return (current.date() - timedelta(days=1)).isoformat()

    candidate = value.strip()
    try:
        parsed = datetime.strptime(candidate, "%Y-%m-%d")
    except ValueError as error:
        raise InvalidBusinessDateError("日期格式无效，请使用 YYYY-MM-DD，例如 2026-08-06。") from error
    if parsed.strftime("%Y-%m-%d") != candidate:
        raise InvalidBusinessDateError("日期格式无效，请使用 YYYY-MM-DD，例如 2026-08-06。")
    return candidate


def filter_by_publish_date(data: pd.DataFrame, selected_date: str) -> pd.DataFrame:
    if data.empty or "publish_time" not in data.columns:
        return data.iloc[0:0].copy()
    publish_dates = pd.to_datetime(data["publish_time"], errors="coerce", format="mixed").dt.strftime("%Y-%m-%d")
    return data.loc[publish_dates == selected_date].reset_index(drop=True)
