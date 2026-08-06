from __future__ import annotations

import json
import logging
import os
import threading
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import pandas as pd

from crawler import crawl_bilibili
from data_utils import append_video_data, clean_video_data, load_video_data, normalize_columns
from date_utils import filter_by_publish_date, resolve_business_date
from hdfs_utils import upload_cleaned_to_hdfs


LOGGER = logging.getLogger(__name__)
DATA_PIPELINE_LOCK = threading.Lock()
PROJECT_DIR = Path(__file__).resolve().parent


def _setting(config: Mapping | None, name: str, default):
    if config is not None and name in config:
        return config[name]
    return os.getenv(name, default)


def _keywords(value) -> list[str]:
    items = value if isinstance(value, (list, tuple)) else str(value).split(",")
    return [str(item).strip() for item in items if str(item).strip()]


def normalize_dedup_url(value: object) -> str:
    candidate = str(value or "").strip()
    if not candidate:
        return ""
    if candidate.startswith("//"):
        candidate = f"https:{candidate}"
    parsed = urlsplit(candidate)
    scheme = "https" if parsed.netloc.lower().endswith("bilibili.com") else parsed.scheme.lower()
    return urlunsplit((scheme, parsed.netloc.lower(), parsed.path.rstrip("/"), "", ""))


def _deduplicate_new_rows(candidates: pd.DataFrame, existing: pd.DataFrame) -> pd.DataFrame:
    existing_keys = set()
    for _, row in existing.iterrows():
        url = normalize_dedup_url(row.get("video_url", ""))
        existing_keys.add(url or f"{row.get('title', '')}\0{row.get('up_name', '')}")

    rows = []
    seen = set(existing_keys)
    for _, row in candidates.iterrows():
        url = normalize_dedup_url(row.get("video_url", ""))
        key = url or f"{row.get('title', '')}\0{row.get('up_name', '')}"
        if key in seen:
            continue
        seen.add(key)
        normalized = row.copy()
        if url:
            normalized["video_url"] = url
        rows.append(normalized)
    return pd.DataFrame(rows, columns=candidates.columns)


def _write_status(path: Path, status: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(f"{path.suffix}.tmp")
    temporary_path.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary_path.replace(path)


def load_daily_pipeline_status(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def run_daily_pipeline(
    target_date: str | None = None,
    *,
    config: Mapping | None = None,
    crawler: Callable[[str, int], pd.DataFrame] = crawl_bilibili,
    uploader: Callable = upload_cleaned_to_hdfs,
    lock=DATA_PIPELINE_LOCK,
) -> dict:
    timezone_name = str(_setting(config, "APP_TIMEZONE", "Asia/Shanghai"))
    selected_date = resolve_business_date(target_date, timezone_name)
    keywords = _keywords(_setting(config, "AUTO_CRAWL_KEYWORDS", "大数据,人工智能,Python"))
    limit = int(_setting(config, "AUTO_CRAWL_LIMIT", 100))
    raw_path = Path(_setting(config, "VIDEO_DATA_PATH", PROJECT_DIR / "data" / "videos.csv"))
    cleaned_path = Path(_setting(config, "CLEANED_DATA_PATH", PROJECT_DIR / "data" / "videos_cleaned.csv"))
    summary_path = Path(_setting(config, "CLEANING_SUMMARY_PATH", PROJECT_DIR / "data" / "cleaning_summary.json"))
    status_path = Path(_setting(config, "DAILY_PIPELINE_STATUS_PATH", PROJECT_DIR / "data" / "daily_pipeline_status.json"))
    errors = []
    collected_frames = []

    for keyword in keywords:
        try:
            collected_frames.append(normalize_columns(crawler(keyword, limit)))
        except Exception as error:
            LOGGER.exception("每日采集关键词失败：keyword=%s", keyword)
            errors.append(f"{keyword}：{error}")

    collected_count = sum(len(frame) for frame in collected_frames)
    collected = pd.concat(collected_frames, ignore_index=True) if collected_frames else pd.DataFrame()
    filtered = filter_by_publish_date(collected, selected_date)
    date_filtered_count = len(filtered)

    with lock:
        existing = normalize_columns(load_video_data(raw_path))
        new_rows = _deduplicate_new_rows(filtered, existing) if not filtered.empty else filtered
        added_count = len(new_rows)
        if added_count:
            append_video_data(new_rows, raw_path)
        cleaning_result = clean_video_data(raw_path, cleaned_path, summary_path)

        hdfs_status = "skipped"
        if cleaned_path.exists() and cleaned_path.stat().st_size > 0:
            try:
                uploaded, message = uploader(
                    cleaned_path,
                    str(_setting(config, "HDFS_CMD", "hdfs")),
                    str(_setting(config, "HDFS_WEB_URL", "")),
                    str(_setting(config, "HDFS_WEB_USER", "tan")),
                )
                hdfs_status = "success" if uploaded else "failed"
                if not uploaded:
                    errors.append(message)
                    LOGGER.warning("每日任务 HDFS 上传失败：%s", message)
            except Exception as error:
                hdfs_status = "failed"
                errors.append(str(error))
                LOGGER.exception("每日任务 HDFS 上传异常")

        status = {
            "executed_at": datetime.now(ZoneInfo(timezone_name)).isoformat(timespec="seconds"),
            "target_date": selected_date,
            "keywords": keywords,
            "collected_count": collected_count,
            "date_filtered_count": date_filtered_count,
            "added_count": added_count,
            "cleaning_result": cleaning_result,
            "hdfs_upload_status": hdfs_status,
            "error_summary": "；".join(errors),
        }
        _write_status(status_path, status)
    return status
