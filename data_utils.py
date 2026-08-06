from __future__ import annotations

import logging
import json
from datetime import date, datetime
from pathlib import Path

import pandas as pd

LOGGER = logging.getLogger(__name__)

VIDEO_COLUMNS = [
    "title",
    "video_url",
    "up_name",
    "play_count",
    "like_count",
    "coin_count",
    "favorite_count",
    "share_count",
    "comment_count",
    "publish_time",
    "crawl_date",
]
REQUIRED_COLUMNS = ["title", "up_name", "play_count", "like_count"]
NUMBER_COLUMNS = [
    "play_count",
    "like_count",
    "coin_count",
    "favorite_count",
    "share_count",
    "comment_count",
]
COLUMN_ALIASES = {
    "标题": "title",
    "视频标题": "title",
    "视频链接": "video_url",
    "URL": "video_url",
    "UP主": "up_name",
    "博主": "up_name",
    "播放量": "play_count",
    "点赞": "like_count",
    "点赞量": "like_count",
    "投币": "coin_count",
    "投币量": "coin_count",
    "收藏": "favorite_count",
    "收藏量": "favorite_count",
    "分享": "share_count",
    "转发": "share_count",
    "评论": "comment_count",
    "评论数": "comment_count",
    "发布时间": "publish_time",
    "采集日期": "crawl_date",
}


def parse_number(value: object) -> int:
    """将常见播放量、互动量文本转换为整数。"""
    if value is None or pd.isna(value):
        return 0

    text = str(value).strip().replace(",", "").replace(" ", "")
    if text in {"", "-", "--"}:
        return 0

    multiplier = 10_000 if text.endswith("万") else 1
    if multiplier == 10_000:
        text = text[:-1]

    try:
        return int(float(text) * multiplier)
    except ValueError:
        return 0


def normalize_columns(data: pd.DataFrame) -> pd.DataFrame:
    """映射常见中文列名，并补齐非核心字段默认值。"""
    normalized = data.rename(
        columns={column: COLUMN_ALIASES.get(str(column).strip(), str(column).strip()) for column in data.columns}
    ).copy()
    normalized = normalized.loc[:, ~normalized.columns.duplicated()]

    for column in NUMBER_COLUMNS:
        if column not in normalized:
            if column in REQUIRED_COLUMNS:
                continue
            normalized[column] = 0
        normalized[column] = normalized[column].map(parse_number)

    for column in ("video_url", "publish_time"):
        if column not in normalized:
            normalized[column] = ""
        normalized[column] = normalized[column].fillna("")

    if "crawl_date" not in normalized:
        normalized["crawl_date"] = date.today().isoformat()
    else:
        normalized["crawl_date"] = normalized["crawl_date"].fillna("").replace("", date.today().isoformat())

    return normalized


def load_video_data(path: Path) -> pd.DataFrame:
    """读取本地视频 CSV；文件不存在或损坏时返回空数据以保证页面可用。"""
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame(columns=VIDEO_COLUMNS)

    try:
        return pd.read_csv(path, dtype=object, encoding="utf-8-sig", keep_default_na=False)
    except (OSError, UnicodeDecodeError, pd.errors.EmptyDataError, pd.errors.ParserError) as error:
        LOGGER.warning("读取视频数据失败：%s", error)
        return pd.DataFrame(columns=VIDEO_COLUMNS)


def save_video_data(data: pd.DataFrame, path: Path) -> None:
    """将标准字段顺序的视频数据写入固定 CSV 文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    data.reindex(columns=VIDEO_COLUMNS).to_csv(path, index=False, encoding="utf-8-sig")


def append_video_data(new_data: pd.DataFrame, path: Path) -> int:
    """向现有 videos.csv 追加数据，并返回当前累计数量。"""
    existing_data = normalize_columns(load_video_data(path))
    combined_data = pd.concat([existing_data, new_data], ignore_index=True)
    save_video_data(combined_data, path)
    return len(combined_data)


def _is_blank(value: object) -> bool:
    return value is None or pd.isna(value) or str(value).strip() == ""


def _format_date(values: pd.Series, fallback: str) -> pd.Series:
    parsed_dates = pd.to_datetime(values, errors="coerce", format="mixed")
    return parsed_dates.dt.strftime("%Y-%m-%d").fillna(fallback)


def clean_video_data(
    raw_path: Path,
    cleaned_path: Path,
    summary_path: Path | None = None,
) -> dict[str, int | str]:
    """使用基础规则清洗原始视频数据，并写入独立的清洗 CSV。"""
    raw_data = load_video_data(raw_path)
    raw_count = len(raw_data)
    if raw_count == 0:
        return {"raw_count": 0, "cleaned_count": 0, "duplicate_count": 0, "missing_count": 0}

    blank_rows = raw_data.apply(lambda row: all(_is_blank(value) for value in row), axis=1)
    cleaned_data = raw_data.loc[~blank_rows].copy()
    missing_count = 0

    for column, default_value in (("title", "未知标题"), ("up_name", "未知UP主")):
        if column not in cleaned_data:
            missing_count += len(cleaned_data)
            cleaned_data[column] = default_value
        else:
            empty_values = cleaned_data[column].map(_is_blank)
            missing_count += int(empty_values.sum())
            cleaned_data[column] = cleaned_data[column].map(
                lambda value: default_value if _is_blank(value) else str(value).strip()
            )

    for column in NUMBER_COLUMNS:
        if column not in cleaned_data:
            missing_count += len(cleaned_data)
            cleaned_data[column] = 0
        else:
            missing_count += int(cleaned_data[column].map(_is_blank).sum())
        cleaned_data[column] = cleaned_data[column].map(lambda value: max(parse_number(value), 0))

    for column in ("video_url", "publish_time", "crawl_date"):
        if column not in cleaned_data:
            cleaned_data[column] = ""
        cleaned_data[column] = cleaned_data[column].map(lambda value: "" if _is_blank(value) else str(value).strip())

    cleaned_data["publish_time"] = _format_date(cleaned_data["publish_time"], "")
    cleaned_data["crawl_date"] = _format_date(cleaned_data["crawl_date"], date.today().isoformat())

    has_video_url = cleaned_data["video_url"] != ""
    url_rows = cleaned_data.loc[has_video_url].drop_duplicates(subset=["video_url"], keep="last")
    no_url_rows = cleaned_data.loc[~has_video_url].copy()
    no_url_rows["_dedup_key"] = no_url_rows["title"] + "\u0000" + no_url_rows["up_name"]
    no_url_rows = no_url_rows.drop_duplicates(subset=["_dedup_key"], keep="last").drop(columns="_dedup_key")
    cleaned_data = pd.concat([url_rows, no_url_rows]).sort_index()

    duplicate_count = len(raw_data.loc[~blank_rows]) - len(cleaned_data)
    save_video_data(cleaned_data, cleaned_path)
    summary: dict[str, int | str] = {
        "raw_count": raw_count,
        "cleaned_count": len(cleaned_data),
        "duplicate_count": duplicate_count,
        "missing_count": missing_count,
        "last_cleaned_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }

    if summary_path is not None:
        summary_path.write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")

    return summary


def load_cleaned_data(path: Path) -> pd.DataFrame:
    """读取已经生成的清洗数据。"""
    return load_video_data(path)


def get_cleaning_summary(raw_path: Path, cleaned_path: Path, summary_path: Path) -> dict[str, int | str]:
    """读取最近一次清洗摘要；尚未清洗时返回当前可展示的默认值。"""
    default_summary: dict[str, int | str] = {
        "raw_count": len(load_video_data(raw_path)),
        "cleaned_count": len(load_cleaned_data(cleaned_path)),
        "duplicate_count": 0,
        "missing_count": 0,
        "last_cleaned_at": "尚未清洗",
    }
    if not summary_path.exists():
        return default_summary

    try:
        return {**default_summary, **json.loads(summary_path.read_text(encoding="utf-8"))}
    except (OSError, json.JSONDecodeError) as error:
        LOGGER.warning("读取清洗摘要失败：%s", error)
        return default_summary
