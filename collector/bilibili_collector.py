import logging
import os
import time
from datetime import datetime
from typing import Collection, Dict, List, NamedTuple, Optional

import pandas as pd
import requests

from config import Config


SEARCH_URL = "https://api.bilibili.com/x/web-interface/wbi/search/type"
DETAIL_URL = "https://api.bilibili.com/x/web-interface/view"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
    "Referer": "https://www.bilibili.com/",
}
VIDEO_FIELDS = [
    "bvid", "title", "video_url", "up_name", "publish_time", "view_count",
    "like_count", "coin_count", "favorite_count", "share_count", "collect_date",
]
STAT_FIELDS = ["view_count", "like_count", "coin_count", "favorite_count", "share_count"]
REQUEST_TIMEOUT_SECONDS = 10
MAX_REQUEST_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 1.0
DETAIL_REQUEST_DELAY_SECONDS = 0.5

LOGGER = logging.getLogger(__name__)


def _create_session(proxy: Optional[str] = None) -> requests.Session:
    session = requests.Session()
    session.headers.update(HEADERS)
    configured_proxy = proxy if proxy is not None else os.getenv("BILIBILI_PROXY")
    if configured_proxy:
        session.proxies.update({"http": configured_proxy, "https": configured_proxy})
    return session


SESSION = _create_session(Config.BILIBILI_PROXY)


class CollectorError(RuntimeError):
    pass


class SearchPage(NamedTuple):
    bvids: List[str]
    total_pages: int


def _response_summary(response: requests.Response) -> str:
    return response.text[:300]


def _request_error_message(
    url: str,
    status_code: Optional[int],
    business_code: Optional[int],
    response_summary: str,
) -> str:
    return (
        f"Bilibili request failed: url={url}, http_status={status_code}, "
        f"business_code={business_code}, response={response_summary}"
    )


def _log_and_create_error(
    url: str,
    status_code: Optional[int],
    business_code: Optional[int],
    response_summary: str,
) -> CollectorError:
    message = _request_error_message(url, status_code, business_code, response_summary)
    LOGGER.error(message)
    return CollectorError(message)


def _request_json(url: str, params: Dict) -> Dict:
    for attempt in range(MAX_REQUEST_ATTEMPTS):
        try:
            response = SESSION.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
        except requests.RequestException as exc:
            error = _log_and_create_error(url, None, None, str(exc))
            if attempt == MAX_REQUEST_ATTEMPTS - 1:
                raise error from exc
            time.sleep(RETRY_DELAY_SECONDS)
            continue

        status_code = response.status_code
        response_summary = _response_summary(response)
        if status_code >= 500:
            error = _log_and_create_error(url, status_code, None, response_summary)
            if attempt == MAX_REQUEST_ATTEMPTS - 1:
                raise error
            time.sleep(RETRY_DELAY_SECONDS)
            continue
        if status_code >= 400:
            raise _log_and_create_error(url, status_code, None, response_summary)

        try:
            payload = response.json()
        except ValueError as exc:
            raise _log_and_create_error(url, status_code, None, response_summary) from exc

        if not isinstance(payload, dict):
            raise _log_and_create_error(url, status_code, None, response_summary)

        business_code = payload.get("code")
        if business_code != 0:
            raise _log_and_create_error(url, status_code, business_code, response_summary)
        return payload

    raise RuntimeError("request retry loop terminated unexpectedly")


def search_videos(keyword: str, page: int) -> SearchPage:
    payload = _request_json(
        SEARCH_URL,
        {"search_type": "video", "keyword": keyword, "page": page},
    )
    data = payload.get("data", {})
    result = data.get("result", [])
    total_pages = data.get("numPages")
    if result == [] and total_pages == 0:
        total_pages = page
    if not isinstance(total_pages, int) or total_pages < page:
        raise CollectorError(
            f"Invalid WBI pagination: page={page}, numPages={total_pages}"
        )
    bvids = []
    seen_bvids = set()
    for item in result:
        bvid = item.get("bvid")
        if isinstance(bvid, str):
            bvid = bvid.strip()
        if bvid and bvid not in seen_bvids:
            seen_bvids.add(bvid)
            bvids.append(bvid)
    return SearchPage(bvids, total_pages)


def get_video_detail(bvid: str) -> Dict:
    payload = _request_json(DETAIL_URL, {"bvid": bvid})
    data = payload["data"]
    stat = data["stat"]
    return {
        "bvid": data["bvid"],
        "title": data["title"],
        "video_url": f"https://www.bilibili.com/video/{data['bvid']}",
        "up_name": data["owner"]["name"],
        "publish_time": datetime.fromtimestamp(data["pubdate"]).strftime("%Y-%m-%d %H:%M:%S"),
        "view_count": stat["view"],
        "like_count": stat["like"],
        "coin_count": stat["coin"],
        "favorite_count": stat["favorite"],
        "share_count": stat["share"],
    }


def collect(
    keyword: str,
    target_count: int,
    collect_date: str,
    exclude_bvids: Optional[Collection[str]] = None,
    task_id: Optional[int] = None,
) -> List[Dict]:
    collected = []
    historical_bvids = set(exclude_bvids or ())
    task_seen_bvids = set()
    page = 1

    while len(collected) < target_count:
        try:
            search_page = search_videos(keyword, page)
        except CollectorError:
            if page == 1 or not collected:
                raise
            LOGGER.exception("Stopping collection after search failure on page %s", page)
            break

        if not search_page.bvids:
            break

        existing_skipped = 0
        task_duplicate_skipped = 0
        detail_success = 0
        detail_failed = 0
        for bvid in search_page.bvids:
            if len(collected) >= target_count:
                break
            if bvid in historical_bvids:
                existing_skipped += 1
                continue
            if bvid in task_seen_bvids:
                task_duplicate_skipped += 1
                continue
            task_seen_bvids.add(bvid)
            try:
                video = get_video_detail(bvid)
            except Exception as exc:
                LOGGER.exception("Skipping Bilibili video detail: bvid=%s, error=%s", bvid, exc)
                detail_failed += 1
                continue
            video["collect_date"] = collect_date
            collected.append(video)
            detail_success += 1
            if len(collected) < target_count:
                time.sleep(DETAIL_REQUEST_DELAY_SECONDS)

        LOGGER.info(
            "Collection page scanned: task_id=%s keyword=%s page=%s search_count=%s "
            "existing_skipped=%s task_duplicate_skipped=%s detail_success=%s "
            "detail_failed=%s added_total=%s target_count=%s",
            task_id,
            keyword,
            page,
            len(search_page.bvids),
            existing_skipped,
            task_duplicate_skipped,
            detail_success,
            detail_failed,
            len(collected),
            target_count,
        )
        if page >= search_page.total_pages:
            break
        page += 1

    if not collected:
        LOGGER.info(
            "Collection exhausted without new videos: task_id=%s keyword=%s "
            "pages_scanned=%s new_bvid_count=0 target_count=%s",
            task_id,
            keyword,
            page,
            target_count,
        )
    return collected


def _parse_stat_value(value: object) -> object:
    if not isinstance(value, str):
        return value

    normalized = value.strip().replace(",", "")
    multiplier = 1
    if normalized.endswith("万"):
        normalized = normalized[:-1]
        multiplier = 10_000
    elif normalized.endswith("亿"):
        normalized = normalized[:-1]
        multiplier = 100_000_000

    try:
        return int(float(normalized) * multiplier)
    except ValueError:
        return 0


def _normalize_date(series: pd.Series, include_time: bool) -> pd.Series:
    date_format = "%Y-%m-%d %H:%M:%S" if include_time else "%Y-%m-%d"

    def format_date(value: object) -> str:
        if pd.isna(value):
            return ""
        parsed = pd.to_datetime(value, errors="coerce")
        if pd.isna(parsed):
            return ""
        return parsed.strftime(date_format)

    return series.map(format_date)


def clean_video_data(data: List[Dict]) -> List[Dict]:
    frame = pd.DataFrame(data).reindex(columns=VIDEO_FIELDS)
    if frame.empty:
        return []

    frame["bvid"] = frame["bvid"].fillna("").astype(str).str.strip()
    frame = frame.loc[frame["bvid"] != ""].copy()
    if frame.empty:
        return []

    for field in STAT_FIELDS:
        frame[field] = pd.to_numeric(frame[field].map(_parse_stat_value), errors="coerce")
        frame[field] = frame[field].fillna(0).clip(lower=0).astype("int64")

    frame["publish_time"] = _normalize_date(frame["publish_time"], include_time=True)
    frame["collect_date"] = _normalize_date(frame["collect_date"], include_time=False)
    for field in ("title", "video_url", "up_name"):
        frame[field] = frame[field].fillna("").astype(str)

    frame = frame.drop_duplicates(subset="bvid", keep="last")
    return frame[VIDEO_FIELDS].to_dict(orient="records")
