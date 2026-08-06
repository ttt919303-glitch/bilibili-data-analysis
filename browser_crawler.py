"""Phase B Edge-based Bilibili search diagnostics."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from random import uniform
from time import sleep
from typing import Callable
from urllib.parse import urlencode, urlsplit

import pandas as pd

from data_utils import VIDEO_COLUMNS, append_video_data, load_video_data, parse_number


BILIBILI_SEARCH_URL = "https://search.bilibili.com/all"
BROWSER_CHANNEL = "msedge"
VIDEO_CARD_SELECTOR = "div.bili-video-card:has(a[href*='/video/'])"
VIDEO_LINK_SELECTOR = "a[href*='/video/']"
TITLE_SELECTOR = "h3.bili-video-card__info--tit"
AUTHOR_SELECTOR = "span.bili-video-card__info--author"
PLAY_SELECTOR = "div.bili-video-card__stats--left span.bili-video-card__stats--item"
PUBLISH_TIME_SELECTOR = "span.bili-video-card__info--date"
MAX_CRAWL_LIMIT = 200
MAX_PAGES = 20


class BrowserCrawlerError(RuntimeError):
    """Raised when the project-specific browser cannot start."""


@dataclass
class PersistentBrowser:
    playwright: object
    context: object

    def close(self) -> None:
        self.context.close()
        self.playwright.stop()


def get_browser_data_dir() -> Path:
    return Path(__file__).resolve().parent / "browser_data"


def _sync_playwright_factory():
    from playwright.sync_api import sync_playwright

    return sync_playwright


def launch_persistent_browser() -> PersistentBrowser:
    browser_data_dir = get_browser_data_dir()
    browser_data_dir.mkdir(parents=True, exist_ok=True)
    playwright = None
    try:
        playwright = _sync_playwright_factory()().start()
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(browser_data_dir),
            channel=BROWSER_CHANNEL,
            headless=False,
        )
    except Exception as error:
        if playwright is not None:
            playwright.stop()
        raise BrowserCrawlerError(f"Unable to start the Edge browser: {error}") from error
    return PersistentBrowser(playwright, context)


def build_search_url(keyword: str, page: int = 1) -> str:
    parameters = {"keyword": keyword}
    if page > 1:
        parameters["page"] = page
    return f"{BILIBILI_SEARCH_URL}?{urlencode(parameters)}"


def _has_text(page, text: str) -> bool:
    return page.get_by_text(text, exact=False).count() > 0


def detect_page_state(page) -> str:
    if any(_has_text(page, text) for text in ("安全验证", "访问异常", "验证码")):
        return "verification_required"
    if _has_text(page, "没有搜索结果"):
        return "no_results"
    if page.locator(VIDEO_CARD_SELECTOR).count() == 0:
        return "page_structure_error"
    return "success"


def normalize_video_url(href: str | None) -> str | None:
    if not href:
        return None

    video_url = f"https:{href}" if href.startswith("//") else href
    parsed = urlsplit(video_url)
    if parsed.scheme != "https" or parsed.netloc != "www.bilibili.com":
        return None
    if not re.fullmatch(r"/video/BV[A-Za-z0-9]+/?", parsed.path):
        return None
    return video_url


def _clean_publish_time(value: str) -> str:
    return value.strip().lstrip("·").strip()


def parse_video_card(card) -> dict[str, object] | None:
    title_locator = card.locator(TITLE_SELECTOR)
    if title_locator.count() == 0:
        return None
    title = (title_locator.get_attribute("title") or title_locator.inner_text()).strip()
    video_url = normalize_video_url(card.locator(VIDEO_LINK_SELECTOR).first.get_attribute("href"))
    if not title or not video_url:
        return None

    author_locator = card.locator(AUTHOR_SELECTOR)
    play_counts = card.locator(PLAY_SELECTOR).all_inner_texts()
    publish_time_locator = card.locator(PUBLISH_TIME_SELECTOR)
    return {
        "title": title,
        "video_url": video_url,
        "up_name": author_locator.inner_text().strip() if author_locator.count() else "",
        "play_count": parse_number(play_counts[0]) if play_counts else 0,
        "publish_time": _clean_publish_time(publish_time_locator.inner_text()) if publish_time_locator.count() else "",
    }


def parse_video_cards(page, limit: int = 5) -> list[dict[str, object]]:
    if not 1 <= limit <= MAX_CRAWL_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_CRAWL_LIMIT}")

    cards = page.locator(VIDEO_CARD_SELECTOR)
    videos = []
    seen_urls = set()
    for index in range(cards.count()):
        video = parse_video_card(cards.nth(index))
        if video is None or video["video_url"] in seen_urls:
            continue
        seen_urls.add(video["video_url"])
        videos.append(video)
        if len(videos) == limit:
            break
    return videos


def _unique_video_link_count(page) -> int:
    cards = page.locator(VIDEO_CARD_SELECTOR)
    video_urls = set()
    for index in range(cards.count()):
        href = cards.nth(index).locator(VIDEO_LINK_SELECTOR).first.get_attribute("href")
        video_url = normalize_video_url(href)
        if video_url:
            video_urls.add(video_url)
    return len(video_urls)


def diagnose_search(keyword: str = "Python", limit: int = 5) -> dict[str, object]:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

    if not 1 <= limit <= 5:
        raise ValueError("limit must be between 1 and 5")

    session = launch_persistent_browser()
    try:
        page = session.context.pages[0] if session.context.pages else session.context.new_page()
        page_url = build_search_url(keyword)
        try:
            page.goto(page_url, wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_function(
                """() => document.querySelectorAll(\"div.bili-video-card:has(a[href*='/video/'])\").length > 0
                    || document.body.innerText.includes('安全验证')
                    || document.body.innerText.includes('访问异常')
                    || document.body.innerText.includes('验证码')
                    || document.body.innerText.includes('没有搜索结果')""",
                timeout=30_000,
            )
        except PlaywrightTimeoutError:
            return {
                "status": "page_timeout",
                "keyword": keyword,
                "page_url": page.url,
                "page_title": page.title(),
                "card_count": 0,
                "video_link_count": 0,
                "videos": [],
            }

        status = detect_page_state(page)
        card_count = page.locator(VIDEO_CARD_SELECTOR).count()
        return {
            "status": status,
            "keyword": keyword,
            "page_url": page.url,
            "page_title": page.title(),
            "card_count": card_count,
            "video_link_count": _unique_video_link_count(page),
            "videos": parse_video_cards(page, limit) if status == "success" else [],
        }
    finally:
        session.close()


def get_video_data_path() -> Path:
    return Path(__file__).resolve().parent / "data" / "videos.csv"


def _page_timeout_error():
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

    return PlaywrightTimeoutError


def _load_search_page(page, keyword: str, page_number: int) -> None:
    page.goto(build_search_url(keyword, page_number), wait_until="domcontentloaded", timeout=30_000)
    page.wait_for_function(
        """() => document.querySelectorAll(\"div.bili-video-card:has(a[href*='/video/'])\").length > 0
            || document.body.innerText.includes('安全验证')
            || document.body.innerText.includes('访问异常')
            || document.body.innerText.includes('验证码')
            || document.body.innerText.includes('没有搜索结果')""",
        timeout=30_000,
    )


def _existing_video_urls(path: Path) -> set[str]:
    existing_data = load_video_data(path)
    if "video_url" not in existing_data:
        return set()
    return {str(value).strip() for value in existing_data["video_url"] if str(value).strip()}


def _csv_records(videos: list[dict[str, object]]) -> list[dict[str, object]]:
    crawl_date = date.today().isoformat()
    return [
        {
            "title": video["title"],
            "video_url": video["video_url"],
            "up_name": video["up_name"],
            "play_count": video["play_count"],
            "like_count": 0,
            "coin_count": 0,
            "favorite_count": 0,
            "share_count": 0,
            "comment_count": 0,
            "publish_time": video["publish_time"],
            "crawl_date": crawl_date,
        }
        for video in videos
    ]


def _crawl_result(
    status: str,
    keyword: str,
    limit: int,
    saved_count: int,
    parsed_count: int,
    skipped_count: int,
    page_count: int,
    message: str,
) -> dict[str, object]:
    return {
        "status": status,
        "keyword": keyword,
        "planned_count": limit,
        "collected_count": saved_count,
        "parsed_count": parsed_count,
        "skipped_count": skipped_count,
        "page_count": page_count,
        "saved_count": saved_count,
        "message": message,
    }


def _report_page_progress(
    progress: Callable[[dict[str, int]], None] | None,
    page_number: int,
    parsed_count: int,
    skipped_count: int,
    new_count: int,
    saved_count: int,
    planned_count: int,
) -> None:
    if progress is None:
        return
    progress(
        {
            "page": page_number,
            "parsed_count": parsed_count,
            "skipped_count": skipped_count,
            "new_count": new_count,
            "saved_count": saved_count,
            "planned_count": planned_count,
        }
    )


def crawl_bilibili_browser(
    keyword: str,
    limit: int,
    progress: Callable[[dict[str, int]], None] | None = None,
) -> dict[str, object]:
    if not 1 <= limit <= MAX_CRAWL_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_CRAWL_LIMIT}")

    data_path = get_video_data_path()
    existing_urls = _existing_video_urls(data_path)
    seen_page_urls = set()
    previous_page_url = ""
    previous_first_video_url = ""
    previous_page_urls: set[str] = set()
    saved_count = 0
    parsed_count = 0
    skipped_count = 0
    consecutive_pages_without_new_urls = 0

    session = launch_persistent_browser()
    try:
        page = session.context.pages[0] if session.context.pages else session.context.new_page()
        for page_number in range(1, MAX_PAGES + 1):
            try:
                _load_search_page(page, keyword, page_number)
            except _page_timeout_error():
                status = "page_timeout" if saved_count == 0 else "partial"
                return _crawl_result(
                    status,
                    keyword,
                    limit,
                    saved_count,
                    parsed_count,
                    skipped_count,
                    page_number - 1,
                    "page_timeout",
                )

            state = detect_page_state(page)
            if state != "success":
                if state == "verification_required":
                    return _crawl_result(
                        state,
                        keyword,
                        limit,
                        saved_count,
                        parsed_count,
                        skipped_count,
                        page_number - 1,
                        "verification_required",
                    )
                status = state if saved_count == 0 else "partial"
                return _crawl_result(
                    status,
                    keyword,
                    limit,
                    saved_count,
                    parsed_count,
                    skipped_count,
                    page_number - 1,
                    "no_more_results" if state == "no_results" else state,
                )

            page_videos = parse_video_cards(page, MAX_CRAWL_LIMIT)
            page_urls = {video["video_url"] for video in page_videos}
            first_video_url = page_videos[0]["video_url"] if page_videos else ""
            if page_number > 1 and page.url == previous_page_url and first_video_url == previous_first_video_url and page_urls == previous_page_urls:
                _report_page_progress(progress, page_number, len(page_videos), 0, 0, saved_count, limit)
                return _crawl_result(
                    "partial",
                    keyword,
                    limit,
                    saved_count,
                    parsed_count,
                    skipped_count,
                    page_number - 1,
                    "page_not_changed",
                )

            parsed_count += len(page_videos)
            new_page_urls = page_urls - seen_page_urls
            consecutive_pages_without_new_urls = consecutive_pages_without_new_urls + 1 if not new_page_urls else 0
            if consecutive_pages_without_new_urls == 2:
                _report_page_progress(progress, page_number, len(page_videos), 0, 0, saved_count, limit)
                return _crawl_result(
                    "partial",
                    keyword,
                    limit,
                    saved_count,
                    parsed_count,
                    skipped_count,
                    page_number,
                    "two_pages_without_new_video_urls",
                )
            seen_page_urls.update(page_urls)

            batch_urls = set()
            new_videos = []
            page_skipped_count = 0
            for video in page_videos:
                video_url = video["video_url"]
                if video_url in existing_urls or video_url in batch_urls:
                    page_skipped_count += 1
                    skipped_count += 1
                    continue
                if len(new_videos) == limit - saved_count:
                    break
                batch_urls.add(video_url)
                new_videos.append(video)

            if new_videos:
                records = _csv_records(new_videos)
                append_video_data(pd.DataFrame(records, columns=VIDEO_COLUMNS), data_path)
                existing_urls.update(batch_urls)
                saved_count += len(new_videos)

            _report_page_progress(
                progress,
                page_number,
                len(page_videos),
                page_skipped_count,
                len(new_videos),
                saved_count,
                limit,
            )

            if saved_count == limit:
                return _crawl_result(
                    "success",
                    keyword,
                    limit,
                    saved_count,
                    parsed_count,
                    skipped_count,
                    page_number,
                    "collection_complete",
                )

            previous_page_url = page.url
            previous_first_video_url = first_video_url
            previous_page_urls = page_urls
            if page_number < MAX_PAGES:
                sleep(uniform(3, 6))

        return _crawl_result(
            "partial",
            keyword,
            limit,
            saved_count,
            parsed_count,
            skipped_count,
            MAX_PAGES,
            "max_pages_reached",
        )
    finally:
        session.close()
