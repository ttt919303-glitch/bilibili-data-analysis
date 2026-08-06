from __future__ import annotations

import html
import json
import random
import re
import time
from datetime import date, datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

from data_utils import VIDEO_COLUMNS, parse_number

SEARCH_URL = "https://api.bilibili.com/x/web-interface/search/type"
MAX_CRAWL_LIMIT = 1000
BLOCKED_API_CODES = {-429, -412, -403, -352}


class CrawlerError(Exception):
    """B站公开搜索接口无法完成采集时抛出。"""

    def __init__(self, message: str, *, is_limited: bool = False) -> None:
        super().__init__(message)
        self.is_limited = is_limited


def _log(message: str) -> None:
    print(f"[B站采集] {message}")


def _clean_title(value: object) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", str(value or ""))).strip()


def _format_publish_time(value: object) -> str:
    try:
        return datetime.fromtimestamp(int(value)).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError):
        return ""


def _to_video_record(item: dict) -> dict[str, object]:
    video_url = str(item.get("arcurl", "")).strip()
    if video_url.startswith("//"):
        video_url = f"https:{video_url}"
    if not video_url and item.get("bvid"):
        video_url = f"https://www.bilibili.com/video/{item['bvid']}"

    return {
        "title": _clean_title(item.get("title")),
        "video_url": video_url,
        "up_name": str(item.get("author", "")).strip(),
        "play_count": parse_number(item.get("play", 0)),
        "like_count": parse_number(item.get("like", 0)),
        "coin_count": 0,
        "favorite_count": parse_number(item.get("favorites", 0)),
        "share_count": 0,
        "comment_count": parse_number(item.get("review", 0)),
        "publish_time": _format_publish_time(item.get("pubdate")),
        "crawl_date": date.today().isoformat(),
    }


def _fetch_search_page(keyword: str, page: int, page_size: int) -> list[dict]:
    query = urlencode(
        {
            "search_type": "video",
            "keyword": keyword,
            "page": page,
            "page_size": page_size,
        }
    )
    request = Request(
        f"{SEARCH_URL}?{query}",
        headers={"User-Agent": "Mozilla/5.0 (course-project-data-collector)"},
    )
    try:
        with urlopen(request, timeout=10) as response:
            _log(f"HTTP={response.status}")
            if response.status != 200:
                raise CrawlerError(f"B站搜索请求失败，HTTP状态码：{response.status}。")
            try:
                payload = json.loads(response.read().decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                _log("JSON解析失败")
                raise CrawlerError("B站返回数据解析失败，请稍后重试。") from error
    except HTTPError as error:
        _log(f"HTTP={error.code}")
        if error.code in {403, 412, 429}:
            raise CrawlerError("B站当前限制了搜索请求，请稍后再试。", is_limited=True) from error
        raise CrawlerError(f"B站搜索请求失败，HTTP状态码：{error.code}。") from error
    except (URLError, TimeoutError, OSError) as error:
        _log("网络请求失败")
        raise CrawlerError("无法连接B站搜索服务，请检查网络后重试。") from error

    api_code = payload.get("code") if isinstance(payload, dict) else None
    _log(f"api_code={api_code}")
    if api_code != 0:
        if api_code in BLOCKED_API_CODES:
            raise CrawlerError("B站当前限制了搜索请求，请稍后再试。", is_limited=True)
        raise CrawlerError("B站搜索接口返回异常，请稍后重试。")

    data = payload.get("data")
    if not isinstance(data, dict) or "result" not in data or not isinstance(data["result"], list):
        raise CrawlerError("B站搜索接口数据结构发生变化，暂时无法解析视频结果。")
    results = data["result"]
    _log(f"当前页解析={len(results)}条")
    return results


def _finalize_data(
    records: list[dict[str, object]],
    crawl_status: str,
    page_count: int,
    crawl_message: str,
) -> pd.DataFrame:
    data = pd.DataFrame(records, columns=VIDEO_COLUMNS)
    data.attrs.update(
        {
            "crawl_status": crawl_status,
            "page_count": page_count,
            "crawl_message": crawl_message,
        }
    )
    return data


def crawl_bilibili(keyword: str, limit: int) -> pd.DataFrame:
    """低频自动分页读取B站公开视频搜索结果，并返回标准视频字段。"""
    keyword = keyword.strip()
    if not keyword:
        raise CrawlerError("请输入采集关键词。")
    if not 1 <= limit <= MAX_CRAWL_LIMIT:
        raise CrawlerError("采集数量必须为1~1000之间的整数。")

    records: list[dict[str, object]] = []
    seen_keys: set[str] = set()
    page_size = min(limit, 50)
    page = 1
    while len(records) < limit:
        _log(f"keyword={keyword} page={page}")
        try:
            results = _fetch_search_page(keyword, page, page_size)
        except CrawlerError as error:
            if records:
                if error.is_limited:
                    return _finalize_data(
                        records,
                        "limited",
                        page - 1,
                        "B站暂时限制了后续搜索请求，请稍后继续采集。",
                    )
                return _finalize_data(records, "partial", page - 1, str(error))
            raise

        if not results:
            status = "empty" if not records else "insufficient"
            return _finalize_data(records, status, page, "")

        for item in results:
            record = _to_video_record(item)
            dedup_key = record["video_url"] or f"{record['title']}\0{record['up_name']}"
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)
            records.append(record)
            if len(records) >= limit:
                return _finalize_data(records[:limit], "completed", page, "")

        _log(f"当前累计={len(records)}条")
        page += 1
        time.sleep(random.uniform(2, 4))

    return _finalize_data(records[:limit], "completed", page, "")
