"""Backfill Bilibili interaction counts from normal video detail pages."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable
from pathlib import Path
from random import uniform
from time import sleep
from urllib.parse import urlsplit

from browser_crawler import launch_persistent_browser
from data_utils import load_video_data, parse_number, save_video_data


BACKFILL_LIMIT = 50
MAX_RETRY_ATTEMPTS = 3
VERIFICATION_FUSE_THRESHOLD = 2
PLAY_COUNT_SELECTOR = "div.view.item .view-text"
LIKE_COUNT_SELECTOR = "span.video-like-info.video-toolbar-item-text"
COIN_COUNT_SELECTOR = "span.video-coin-info.video-toolbar-item-text"
FAVORITE_COUNT_SELECTOR = "span.video-fav-info.video-toolbar-item-text"
SHARE_COUNT_SELECTOR = ".video-share-wrap .video-toolbar-item-text"
DETAIL_METRIC_SELECTORS = {
    "play_count": PLAY_COUNT_SELECTOR,
    "like_count": LIKE_COUNT_SELECTOR,
    "coin_count": COIN_COUNT_SELECTOR,
    "favorite_count": FAVORITE_COUNT_SELECTOR,
    "share_count": SHARE_COUNT_SELECTOR,
}
ZERO_METRIC_LABELS = {
    "like_count": "点赞",
    "coin_count": "投币",
    "favorite_count": "收藏",
    "share_count": "分享",
}
STRONG_VERIFICATION_TEXTS = ("安全验证", "访问异常", "请完成验证")
DETAIL_READY_SCRIPT = r"""selectors => selectors.every(selector => {
                    const element = document.querySelector(selector);
                    const value = (element?.innerText || '').replace(/[\s,]/g, '');
                    return /^\d+(?:\.\d+)?(?:万|亿)?$/.test(value)
                        || ['点赞', '投币', '收藏', '分享'].includes(value);
                })
                || (document.body?.innerText || '').includes('安全验证')
                || (document.body?.innerText || '').includes('访问异常')
                || (document.body?.innerText || '').includes('请完成验证')"""
logger = logging.getLogger(__name__)


class DetailPageStructureError(RuntimeError):
    """Raised when a Bilibili detail page lacks the expected metrics."""


class VerificationRequiredError(RuntimeError):
    """Raised when Bilibili asks the user to complete verification."""


class DetailPageTimeoutError(RuntimeError):
    """Raised when a Bilibili detail page does not finish loading."""


def get_video_data_path() -> Path:
    return Path(__file__).resolve().parent / "data" / "videos.csv"


def get_backfill_state_path() -> Path:
    return Path(__file__).resolve().parent / "data" / "interaction_backfill_state.json"


def normalize_backfill_url(value: str | None) -> str | None:
    if not value:
        return None

    candidate = value.strip()
    if candidate.startswith("//"):
        candidate = f"https:{candidate}"
    parsed = urlsplit(candidate)
    if parsed.scheme not in {"http", "https"} or parsed.netloc != "www.bilibili.com":
        return None

    path = parsed.path.rstrip("/")
    if not (
        re.fullmatch(r"/video/(?:BV[A-Za-z0-9]+|av\d+)", path)
        or re.fullmatch(r"/cheese/play/ss\d+", path)
    ):
        return None
    return f"https://www.bilibili.com{path}"


def _load_backfill_state(path: Path) -> tuple[set[str], dict[str, dict[str, object]]]:
    if not path.exists():
        return set(), {}

    state = json.loads(path.read_text(encoding="utf-8"))
    urls = state.get("completed_urls")
    if not isinstance(urls, list) or not all(isinstance(url, str) for url in urls):
        raise ValueError("interaction backfill state must contain a completed_urls string list")
    completed_urls = set()
    for value in urls:
        video_url = normalize_backfill_url(value)
        if video_url is None:
            raise ValueError(f"interaction backfill state contains an invalid URL: {value}")
        completed_urls.add(video_url)

    stored_failures = state.get("failed_urls", {})
    if not isinstance(stored_failures, dict):
        raise ValueError("interaction backfill state failed_urls must be an object")
    failed_urls = {}
    for value, failure in stored_failures.items():
        if not isinstance(value, str) or not isinstance(failure, dict):
            raise ValueError("interaction backfill failures must map URLs to objects")
        video_url = normalize_backfill_url(value)
        if video_url is None:
            raise ValueError(f"interaction backfill state contains an invalid URL: {value}")
        attempts = failure.get("attempts")
        reason = failure.get("reason")
        if isinstance(attempts, bool) or not isinstance(attempts, int) or attempts < 1:
            raise ValueError("interaction backfill failure attempts must be positive integers")
        if not isinstance(reason, str) or not reason:
            raise ValueError("interaction backfill failure reasons must be non-empty strings")
        existing = failed_urls.get(video_url)
        if existing is None or attempts > int(existing["attempts"]):
            failed_urls[video_url] = {"attempts": attempts, "reason": reason}
    if completed_urls & failed_urls.keys():
        raise ValueError("interaction backfill state cannot mark a URL completed and failed")
    return completed_urls, failed_urls


def _save_backfill_state(
    path: Path,
    completed_urls: set[str],
    failed_urls: dict[str, dict[str, object]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(f"{path.suffix}.tmp")
    temporary_path.write_text(
        json.dumps(
            {
                "completed_urls": sorted(completed_urls),
                "failed_urls": dict(sorted(failed_urls.items())),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    temporary_path.replace(path)


def _video_urls(data) -> list[str]:
    urls = []
    seen_urls = set()
    for value in data.get("video_url", []):
        video_url = normalize_backfill_url(str(value).strip())
        if video_url is None or video_url in seen_urls:
            continue
        seen_urls.add(video_url)
        urls.append(video_url)
    return urls


def get_supported_video_urls(path: Path | None = None) -> list[str]:
    data = load_video_data(path or get_video_data_path())
    if data.empty:
        return []
    return _video_urls(data)


def _load_backfill_data(path: Path):
    data = load_video_data(path)
    if data.empty:
        raise ValueError("videos.csv does not contain any rows")
    if "video_url" not in data:
        raise ValueError("videos.csv does not contain a video_url column")
    if not _video_urls(data):
        raise ValueError("videos.csv does not contain any supported Bilibili URLs")
    return data


def _save_backfill_data(data, path: Path) -> None:
    temporary_path = path.with_name(f"{path.name}.backfill.tmp")
    save_video_data(data, temporary_path)
    temporary_path.replace(path)


def _pending_video_urls(
    video_urls: list[str],
    completed_urls: set[str],
    failed_urls: dict[str, dict[str, object]] | None = None,
) -> list[str]:
    failures = failed_urls or {}
    fresh_urls = [url for url in video_urls if url not in completed_urls and url not in failures]
    retryable_urls = [
        url
        for url in video_urls
        if url not in completed_urls
        and url in failures
        and int(failures[url]["attempts"]) < MAX_RETRY_ATTEMPTS
    ]
    retryable_urls.sort(key=lambda url: int(failures[url]["attempts"]))
    return fresh_urls + retryable_urls


def _target_video_urls(data, target_urls: Iterable[str] | None) -> list[str]:
    available_urls = _video_urls(data)
    if target_urls is None:
        return available_urls

    requested_urls = []
    seen_urls = set()
    for value in target_urls:
        video_url = normalize_backfill_url(value)
        if video_url is None:
            raise ValueError(f"unsupported target URL: {value}")
        if video_url not in seen_urls:
            seen_urls.add(video_url)
            requested_urls.append(video_url)

    missing_urls = [url for url in requested_urls if url not in available_urls]
    if missing_urls:
        raise ValueError(f"target URL is not present in videos.csv: {missing_urls[0]}")
    return requested_urls


def _mark_unsupported_urls(
    video_urls: list[str],
    completed_urls: set[str],
    failed_urls: dict[str, dict[str, object]],
) -> bool:
    changed = False
    for video_url in video_urls:
        if video_url in completed_urls or not urlsplit(video_url).path.startswith("/cheese/play/"):
            continue
        failure = {"attempts": MAX_RETRY_ATTEMPTS, "reason": "unsupported_course_url"}
        if failed_urls.get(video_url) != failure:
            failed_urls[video_url] = failure
            changed = True
    return changed


def _progress(
    video_urls: list[str],
    completed_urls: set[str],
    failed_urls: dict[str, dict[str, object]],
) -> dict[str, int]:
    known_urls = set(video_urls)
    completed_count = len(known_urls & completed_urls)
    failed_count = sum(url in known_urls and url not in completed_urls for url in failed_urls)
    retryable_count = sum(
        url not in completed_urls
        and (url not in failed_urls or int(failed_urls[url]["attempts"]) < MAX_RETRY_ATTEMPTS)
        for url in video_urls
    )
    return {
        "total_count": len(video_urls),
        "completed_count": completed_count,
        "failed_count": failed_count,
        "remaining_count": len(video_urls) - completed_count,
        "retryable_count": retryable_count,
    }


def get_backfill_progress() -> dict[str, int]:
    data = _load_backfill_data(get_video_data_path())
    completed_urls, failed_urls = _load_backfill_state(get_backfill_state_path())
    return _progress(_video_urls(data), completed_urls, failed_urls)


def reset_exhausted_failures() -> int:
    state_path = get_backfill_state_path()
    completed_urls, failed_urls = _load_backfill_state(state_path)
    reset_urls = [
        video_url
        for video_url, failure in failed_urls.items()
        if int(failure["attempts"]) >= MAX_RETRY_ATTEMPTS
        and failure["reason"] != "unsupported_course_url"
    ]
    for video_url in reset_urls:
        del failed_urls[video_url]
    if reset_urls:
        _save_backfill_state(state_path, completed_urls, failed_urls)
    return len(reset_urls)


def _parse_detail_metric(value: str) -> int:
    text = value.strip().replace(",", "").replace(" ", "")
    if not re.fullmatch(r"\d+(?:\.\d+)?(?:万|亿)?", text):
        raise DetailPageStructureError(f"invalid detail metric value: {value}")
    if text.endswith("亿"):
        return int(float(text[:-1]) * 100_000_000)
    return parse_number(text)


def parse_detail_metrics(page) -> dict[str, int]:
    metrics = {}
    for field, selector in DETAIL_METRIC_SELECTORS.items():
        locator = page.locator(selector)
        if locator.count() == 0:
            raise DetailPageStructureError(f"missing detail metric selector: {selector}")
        value = locator.first.inner_text()
        metrics[field] = 0 if value.strip() == ZERO_METRIC_LABELS.get(field) else _parse_detail_metric(value)
    return metrics


def _page_timeout_error():
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

    return PlaywrightTimeoutError


def _page_error():
    from playwright.sync_api import Error as PlaywrightError

    return PlaywrightError


def _is_verification_page(page) -> bool:
    try:
        page_text = page.locator("body").inner_text()
        if any(text in page_text for text in STRONG_VERIFICATION_TEXTS):
            return True
        if "验证码" not in page_text:
            return False
        return not any(page.locator(selector).count() for selector in DETAIL_METRIC_SELECTORS.values())
    except _page_timeout_error() as error:
        raise DetailPageTimeoutError(str(error)) from error


def _load_detail_metrics(page, video_url: str) -> dict[str, int]:
    try:
        page.goto(video_url, wait_until="commit", timeout=30_000)
        page.wait_for_function(
            DETAIL_READY_SCRIPT,
            arg=list(DETAIL_METRIC_SELECTORS.values()),
            timeout=30_000,
        )
    except (_page_timeout_error(), _page_error()) as error:
        if _is_verification_page(page):
            raise VerificationRequiredError() from error
        raise DetailPageTimeoutError(str(error)) from error

    try:
        return parse_detail_metrics(page)
    except (_page_timeout_error(), _page_error()) as error:
        raise DetailPageTimeoutError(str(error)) from error
    except DetailPageStructureError as error:
        if _is_verification_page(page):
            raise VerificationRequiredError() from error
        raise


def _result(
    status: str,
    limit: int,
    updated_count: int,
    processed_count: int,
    skipped_count: int,
    progress: dict[str, int],
    message: str,
) -> dict[str, object]:
    return {
        "status": status,
        "planned_count": limit,
        "updated_count": updated_count,
        "processed_count": processed_count,
        "skipped_count": skipped_count,
        "failed_count": progress["failed_count"],
        "remaining_count": progress["remaining_count"],
        "retryable_count": progress["retryable_count"],
        "message": message,
    }


def _failure_reason(error: Exception) -> str:
    if isinstance(error, VerificationRequiredError):
        return "verification_required"
    if isinstance(error, DetailPageStructureError):
        return "page_structure_error"
    if isinstance(error, DetailPageTimeoutError):
        return "page_timeout"
    raise TypeError(f"unsupported backfill failure: {type(error).__name__}")


def backfill_bilibili_interactions(
    limit: int = BACKFILL_LIMIT,
    target_urls: Iterable[str] | None = None,
) -> dict[str, object]:
    if not 1 <= limit <= BACKFILL_LIMIT:
        raise ValueError(f"limit must be between 1 and {BACKFILL_LIMIT}")

    data_path = get_video_data_path()
    state_path = get_backfill_state_path()
    data = _load_backfill_data(data_path)
    completed_urls, failed_urls = _load_backfill_state(state_path)
    video_urls = _target_video_urls(data, target_urls)
    if _mark_unsupported_urls(video_urls, completed_urls, failed_urls):
        _save_backfill_state(state_path, completed_urls, failed_urls)
    pending_urls = _pending_video_urls(video_urls, completed_urls, failed_urls)[:limit]
    if not pending_urls:
        progress = _progress(video_urls, completed_urls, failed_urls)
        status = "success" if progress["remaining_count"] == 0 else "partial"
        message = "no_pending_video_urls" if status == "success" else "unresolved_video_urls"
        return _result(status, limit, 0, 0, 0, progress, message)

    session = launch_persistent_browser()
    updated_count = 0
    processed_count = 0
    skipped_count = 0
    consecutive_verifications = 0
    normalized_urls = data["video_url"].map(lambda value: normalize_backfill_url(str(value).strip()))
    try:
        page = session.context.pages[0] if session.context.pages else session.context.new_page()
        for index, video_url in enumerate(pending_urls):
            processed_count += 1
            try:
                metrics = _load_detail_metrics(page, video_url)
            except (VerificationRequiredError, DetailPageStructureError, DetailPageTimeoutError) as error:
                reason = _failure_reason(error)
                consecutive_verifications = (
                    consecutive_verifications + 1 if reason == "verification_required" else 0
                )
                attempts = int(failed_urls.get(video_url, {}).get("attempts", 0)) + 1
                failed_urls[video_url] = {"attempts": attempts, "reason": reason}
                _save_backfill_state(state_path, completed_urls, failed_urls)
                skipped_count += 1
                logger.warning(
                    "Skipped Bilibili interaction backfill URL after %s attempt(s): %s (%s)",
                    attempts,
                    video_url,
                    reason,
                )
                if consecutive_verifications >= VERIFICATION_FUSE_THRESHOLD:
                    progress = _progress(video_urls, completed_urls, failed_urls)
                    return _result(
                        "verification_required",
                        limit,
                        updated_count,
                        processed_count,
                        skipped_count,
                        progress,
                        "verification_fuse_open",
                    )
                if index < len(pending_urls) - 1:
                    sleep(uniform(3, 6))
                continue

            consecutive_verifications = 0
            for field, value in metrics.items():
                data.loc[normalized_urls == video_url, field] = value
            _save_backfill_data(data, data_path)
            completed_urls.add(video_url)
            failed_urls.pop(video_url, None)
            _save_backfill_state(state_path, completed_urls, failed_urls)
            updated_count += 1
            if index < len(pending_urls) - 1:
                sleep(uniform(3, 6))

        progress = _progress(video_urls, completed_urls, failed_urls)
        status = "partial" if skipped_count or progress["failed_count"] else "success"
        message = "backfill_partial" if status == "partial" else "backfill_complete"
        return _result(status, limit, updated_count, processed_count, skipped_count, progress, message)
    finally:
        session.close()
