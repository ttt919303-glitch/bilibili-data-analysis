from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pandas as pd
import pytest

import browser_interaction_backfill as backfill
from data_utils import VIDEO_COLUMNS, load_video_data


class FakeLocator:
    def __init__(self, text: str | None):
        self.text = text
        self.first = self

    def count(self) -> int:
        return 0 if self.text is None else 1

    def inner_text(self) -> str:
        assert self.text is not None
        return self.text


class FixturePage:
    def __init__(self, values: dict[str, str], body_text: str = ""):
        self.values = values
        self.body_text = body_text
        self.url = ""

    def locator(self, selector: str) -> FakeLocator:
        if selector == "body":
            return FakeLocator(self.body_text)
        return FakeLocator(self.values.get(selector))

    def goto(self, video_url: str, **_kwargs) -> None:
        self.url = video_url

    def wait_for_function(self, *_args, **_kwargs) -> None:
        pass


class FakePlaywrightTimeout(Exception):
    pass


class FakePlaywrightError(Exception):
    pass


class ConnectionClosedPage(FixturePage):
    def goto(self, video_url: str, **_kwargs) -> None:
        raise FakePlaywrightError(f"net::ERR_CONNECTION_CLOSED at {video_url}")


class CommitNavigationPage(FixturePage):
    def goto(self, video_url: str, **kwargs) -> None:
        if kwargs.get("wait_until") != "commit":
            raise FakePlaywrightTimeout("domcontentloaded did not finish")
        self.url = video_url


class TimeoutLocator(FakeLocator):
    def inner_text(self) -> str:
        raise FakePlaywrightTimeout("locator timed out")


class MetricTimeoutPage(FixturePage):
    def locator(self, selector: str) -> FakeLocator:
        if selector == backfill.COIN_COUNT_SELECTOR:
            return TimeoutLocator("3")
        return super().locator(selector)


class VerificationInspectionTimeoutPage(FixturePage):
    def wait_for_function(self, *_args, **_kwargs) -> None:
        raise FakePlaywrightTimeout("page wait timed out")

    def locator(self, selector: str) -> FakeLocator:
        if selector == "body":
            return TimeoutLocator("")
        return super().locator(selector)


def fixture_page() -> FixturePage:
    fixture = (Path(__file__).parent / "fixtures" / "bilibili_video_interactions.html").read_text(encoding="utf-8")
    return FixturePage(
        {
            backfill.PLAY_COUNT_SELECTOR: re.search(r'class="view-text">([^<]+)', fixture).group(1),
            backfill.LIKE_COUNT_SELECTOR: re.search(r'class="video-like-info[^>]*>([^<]+)', fixture).group(1),
            backfill.COIN_COUNT_SELECTOR: re.search(r'class="video-coin-info[^>]*>([^<]+)', fixture).group(1),
            backfill.FAVORITE_COUNT_SELECTOR: re.search(r'class="video-fav-info[^>]*>([^<]+)', fixture).group(1),
            ".video-share-wrap .video-toolbar-item-text": re.search(
                r'class="video-share-wrap[^>]*>\s*<span class="video-toolbar-item-text">([^<]+)', fixture
            ).group(1),
        }
    )


def records() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "title": "视频一",
                "video_url": "https://www.bilibili.com/video/BV1testA",
                "up_name": "UP一",
                "play_count": 0,
                "like_count": 0,
                "coin_count": 0,
                "favorite_count": 0,
                "share_count": 0,
                "comment_count": 0,
                "publish_time": "",
                "crawl_date": "2026-07-31",
            },
            {
                "title": "视频二",
                "video_url": "https://www.bilibili.com/video/BV1testB",
                "up_name": "UP二",
                "play_count": 0,
                "like_count": 0,
                "coin_count": 0,
                "favorite_count": 0,
                "share_count": 0,
                "comment_count": 0,
                "publish_time": "",
                "crawl_date": "2026-07-31",
            },
        ],
        columns=VIDEO_COLUMNS,
    )


def install_paths(monkeypatch, tmp_path: Path) -> tuple[Path, Path]:
    data_path = tmp_path / "videos.csv"
    state_path = tmp_path / "interaction_backfill_state.json"
    records().to_csv(data_path, index=False, encoding="utf-8-sig")
    monkeypatch.setattr(backfill, "get_video_data_path", lambda: data_path)
    monkeypatch.setattr(backfill, "get_backfill_state_path", lambda: state_path)
    monkeypatch.setattr(backfill, "sleep", lambda seconds: None)
    monkeypatch.setattr(backfill, "uniform", lambda start, end: 3.0)
    return data_path, state_path


def test_parse_detail_metrics_uses_real_detail_page_values():
    assert backfill.parse_detail_metrics(fixture_page()) == {
        "play_count": 18_397_000,
        "like_count": 483_000,
        "coin_count": 354_000,
        "favorite_count": 758_000,
        "share_count": 93_000,
    }


def test_parse_detail_metrics_requires_all_interaction_elements():
    page = FixturePage({backfill.PLAY_COUNT_SELECTOR: "100"})

    with pytest.raises(backfill.DetailPageStructureError):
        backfill.parse_detail_metrics(page)


def test_parse_detail_metrics_supports_hundred_million_unit():
    page = fixture_page()
    page.values[backfill.PLAY_COUNT_SELECTOR] = "1.2亿"

    assert backfill.parse_detail_metrics(page)["play_count"] == 120_000_000


def test_parse_detail_metrics_rejects_loading_placeholder():
    page = fixture_page()
    page.values[backfill.COIN_COUNT_SELECTOR] = "--"

    with pytest.raises(backfill.DetailPageStructureError, match="invalid detail metric value"):
        backfill.parse_detail_metrics(page)


def test_parse_detail_metrics_treats_real_share_label_as_zero():
    page = fixture_page()
    page.values[backfill.SHARE_COUNT_SELECTOR] = "分享"

    assert backfill.parse_detail_metrics(page)["share_count"] == 0


@pytest.mark.parametrize(
    ("field", "selector", "label"),
    [
        ("like_count", backfill.LIKE_COUNT_SELECTOR, "点赞"),
        ("coin_count", backfill.COIN_COUNT_SELECTOR, "投币"),
        ("favorite_count", backfill.FAVORITE_COUNT_SELECTOR, "收藏"),
    ],
)
def test_parse_detail_metrics_treats_real_zero_interaction_labels_as_zero(field, selector, label):
    page = fixture_page()
    page.values[selector] = label

    assert backfill.parse_detail_metrics(page)[field] == 0


def test_normal_detail_page_with_captcha_word_in_course_text_is_not_verification():
    page = fixture_page()
    page.body_text = "课程目录：selenium 验证码与元素等待"

    assert backfill._load_detail_metrics(page, "https://www.bilibili.com/video/BV1testA") == {
        "play_count": 18_397_000,
        "like_count": 483_000,
        "coin_count": 354_000,
        "favorite_count": 758_000,
        "share_count": 93_000,
    }


def test_detail_page_with_explicit_security_check_requires_verification():
    page = FixturePage({}, body_text="安全验证\n请完成验证后继续访问")

    with pytest.raises(backfill.VerificationRequiredError):
        backfill._load_detail_metrics(page, "https://www.bilibili.com/video/BV1testA")


def test_detail_ready_script_handles_missing_metric_element_without_javascript_error():
    node = shutil.which("node")
    if node is None:
        bundled_node = Path(r"C:\Users\TLT\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe")
        if bundled_node.exists():
            node = str(bundled_node)
    if node is None:
        pytest.skip("Node.js is unavailable for the browser readiness predicate test")

    script = (
        "const document = {"
        "querySelector: selector => selector === 'missing' ? null : {innerText: '1'},"
        "body: {innerText: ''}"
        "};"
        f"const ready = eval({json.dumps(backfill.DETAIL_READY_SCRIPT)});"
        "process.stdout.write(String(ready(['present', 'missing'])));"
    )
    result = subprocess.run([node, "-e", script], capture_output=True, text=True, check=False)

    assert result.returncode == 0
    assert result.stdout == "false"


def test_detail_ready_script_handles_missing_body_without_javascript_error():
    node = shutil.which("node")
    if node is None:
        bundled_node = Path(r"C:\Users\TLT\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe")
        if bundled_node.exists():
            node = str(bundled_node)
    if node is None:
        pytest.skip("Node.js is unavailable for the browser readiness predicate test")

    script = (
        "const document = {"
        "querySelector: selector => null,"
        "body: null"
        "};"
        f"const ready = eval({json.dumps(backfill.DETAIL_READY_SCRIPT)});"
        "process.stdout.write(String(ready(['missing'])));"
    )
    result = subprocess.run([node, "-e", script], capture_output=True, text=True, check=False)

    assert result.returncode == 0
    assert result.stdout == "false"


def test_detail_ready_script_accepts_real_zero_share_label():
    node = shutil.which("node")
    if node is None:
        bundled_node = Path(r"C:\Users\TLT\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe")
        if bundled_node.exists():
            node = str(bundled_node)
    if node is None:
        pytest.skip("Node.js is unavailable for the browser readiness predicate test")

    script = (
        "const document = {"
        "querySelector: selector => ({innerText: selector.includes('video-share-wrap') ? '分享' : '1'}),"
        "body: {innerText: ''}"
        "};"
        f"const ready = eval({json.dumps(backfill.DETAIL_READY_SCRIPT)});"
        f"process.stdout.write(String(ready({json.dumps(list(backfill.DETAIL_METRIC_SELECTORS.values()))})));"
    )
    result = subprocess.run([node, "-e", script], capture_output=True, text=True, check=False)

    assert result.returncode == 0
    assert result.stdout == "true"


def test_detail_ready_script_accepts_real_zero_coin_label():
    node = shutil.which("node")
    if node is None:
        bundled_node = Path(r"C:\Users\TLT\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe")
        if bundled_node.exists():
            node = str(bundled_node)
    if node is None:
        pytest.skip("Node.js is unavailable for the browser readiness predicate test")

    script = (
        "const document = {"
        "querySelector: selector => ({innerText: selector.includes('video-coin-info') ? '投币' : '1'}),"
        "body: {innerText: ''}"
        "};"
        f"const ready = eval({json.dumps(backfill.DETAIL_READY_SCRIPT)});"
        f"process.stdout.write(String(ready({json.dumps(list(backfill.DETAIL_METRIC_SELECTORS.values()))})));"
    )
    result = subprocess.run([node, "-e", script], capture_output=True, text=True, check=False)

    assert result.returncode == 0
    assert result.stdout == "true"


def test_metric_locator_timeout_becomes_skippable_page_timeout(monkeypatch):
    page = MetricTimeoutPage(fixture_page().values)
    monkeypatch.setattr(backfill, "_page_timeout_error", lambda: FakePlaywrightTimeout)

    with pytest.raises(backfill.DetailPageTimeoutError, match="locator timed out"):
        backfill._load_detail_metrics(page, "https://www.bilibili.com/video/BV1testA")


def test_connection_closed_navigation_becomes_skippable_page_timeout(monkeypatch):
    page = ConnectionClosedPage(fixture_page().values)
    monkeypatch.setattr(backfill, "_page_timeout_error", lambda: FakePlaywrightTimeout)
    monkeypatch.setattr(backfill, "_page_error", lambda: FakePlaywrightError)

    with pytest.raises(backfill.DetailPageTimeoutError, match="ERR_CONNECTION_CLOSED"):
        backfill._load_detail_metrics(page, "https://www.bilibili.com/video/BV1testA")


def test_detail_navigation_waits_for_commit_then_uses_metric_readiness(monkeypatch):
    page = CommitNavigationPage(fixture_page().values)
    monkeypatch.setattr(backfill, "_page_timeout_error", lambda: FakePlaywrightTimeout)

    metrics = backfill._load_detail_metrics(page, "https://www.bilibili.com/video/BV1testA")

    assert metrics["play_count"] == 18_397_000


def test_verification_inspection_timeout_becomes_page_timeout(monkeypatch):
    page = VerificationInspectionTimeoutPage({})
    monkeypatch.setattr(backfill, "_page_timeout_error", lambda: FakePlaywrightTimeout)

    with pytest.raises(backfill.DetailPageTimeoutError):
        backfill._load_detail_metrics(page, "https://www.bilibili.com/video/BV1testA")


def test_backfill_updates_every_raw_row_for_a_completed_url(monkeypatch, tmp_path):
    data_path, state_path = install_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(backfill, "_load_detail_metrics", lambda page, video_url: {
        "play_count": 100,
        "like_count": 20,
        "coin_count": 3,
        "favorite_count": 4,
        "share_count": 5,
    })
    monkeypatch.setattr(backfill, "launch_persistent_browser", lambda: FakeSession())

    result = backfill.backfill_bilibili_interactions(limit=1)

    data = load_video_data(data_path)
    assert result["status"] == "success"
    assert result["updated_count"] == 1
    assert data.loc[0, "coin_count"] == "3"
    assert json.loads(state_path.read_text(encoding="utf-8"))["completed_urls"] == ["https://www.bilibili.com/video/BV1testA"]


def test_backfill_resumes_from_checkpoint(monkeypatch, tmp_path):
    data_path, state_path = install_paths(monkeypatch, tmp_path)
    state_path.write_text(json.dumps({"completed_urls": ["https://www.bilibili.com/video/BV1testA"]}), encoding="utf-8")
    visited = []
    monkeypatch.setattr(backfill, "_load_detail_metrics", lambda page, video_url: visited.append(video_url) or {
        "play_count": 100,
        "like_count": 20,
        "coin_count": 3,
        "favorite_count": 4,
        "share_count": 5,
    })
    monkeypatch.setattr(backfill, "launch_persistent_browser", lambda: FakeSession())

    result = backfill.backfill_bilibili_interactions(limit=50)

    assert result["updated_count"] == 1
    assert visited == ["https://www.bilibili.com/video/BV1testB"]
    assert load_video_data(data_path).loc[1, "share_count"] == "5"


def test_targeted_backfill_does_not_visit_unrelated_pending_urls(monkeypatch, tmp_path):
    data_path, _state_path = install_paths(monkeypatch, tmp_path)
    visited = []
    monkeypatch.setattr(
        backfill,
        "_load_detail_metrics",
        lambda page, video_url: visited.append(video_url)
        or {
            "play_count": 100,
            "like_count": 20,
            "coin_count": 3,
            "favorite_count": 4,
            "share_count": 5,
        },
    )
    monkeypatch.setattr(backfill, "launch_persistent_browser", lambda: FakeSession())

    result = backfill.backfill_bilibili_interactions(
        limit=50,
        target_urls=["https://www.bilibili.com/video/BV1testB"],
    )

    assert result["status"] == "success"
    assert result["updated_count"] == 1
    assert visited == ["https://www.bilibili.com/video/BV1testB"]
    data = load_video_data(data_path)
    assert data.loc[0, "coin_count"] == "0"
    assert data.loc[1, "coin_count"] == "3"


def test_supported_video_urls_are_empty_before_first_collection(tmp_path):
    assert backfill.get_supported_video_urls(tmp_path / "missing.csv") == []


def test_backfill_includes_legacy_av_and_cheese_detail_urls():
    data = pd.DataFrame(
        {
            "video_url": [
                "http://www.bilibili.com/video/av1655409998",
                "https://www.bilibili.com/video/av1655409998/",
                "https://www.bilibili.com/cheese/play/ss29903?query_from=0&search_query=大数据技术",
            ]
        }
    )

    assert backfill._video_urls(data) == [
        "https://www.bilibili.com/video/av1655409998",
        "https://www.bilibili.com/cheese/play/ss29903",
    ]


def test_backfill_state_migrates_equivalent_urls_to_canonical_form(tmp_path):
    state_path = tmp_path / "interaction_backfill_state.json"
    state_path.write_text(
        json.dumps(
            {
                "completed_urls": ["https://www.bilibili.com/video/BV1testA/"],
                "failed_urls": {
                    "http://www.bilibili.com/video/av1655409998/": {
                        "attempts": 1,
                        "reason": "page_timeout",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    completed_urls, failed_urls = backfill._load_backfill_state(state_path)

    assert completed_urls == {"https://www.bilibili.com/video/BV1testA"}
    assert failed_urls == {
        "https://www.bilibili.com/video/av1655409998": {
            "attempts": 1,
            "reason": "page_timeout",
        }
    }


def test_backfill_marks_course_url_unsupported_without_opening_edge(monkeypatch, tmp_path):
    data_path, state_path = install_paths(monkeypatch, tmp_path)
    data = records().iloc[:1].copy()
    data.loc[0, "video_url"] = "https://www.bilibili.com/cheese/play/ss29903?query_from=0"
    data.to_csv(data_path, index=False, encoding="utf-8-sig")
    monkeypatch.setattr(
        backfill,
        "launch_persistent_browser",
        lambda: pytest.fail("a course season URL is not a normal video detail page"),
    )

    result = backfill.backfill_bilibili_interactions(limit=50)

    assert result["status"] == "partial"
    assert result["failed_count"] == 1
    assert result["retryable_count"] == 0
    assert json.loads(state_path.read_text(encoding="utf-8"))["failed_urls"] == {
        "https://www.bilibili.com/cheese/play/ss29903": {
            "attempts": 3,
            "reason": "unsupported_course_url",
        }
    }


def test_backfill_updates_every_duplicate_legacy_av_row(monkeypatch, tmp_path):
    data_path, state_path = install_paths(monkeypatch, tmp_path)
    data = records()
    data["video_url"] = "http://www.bilibili.com/video/av1655409998"
    data.to_csv(data_path, index=False, encoding="utf-8-sig")
    monkeypatch.setattr(
        backfill,
        "_load_detail_metrics",
        lambda page, video_url: {
            "play_count": 100,
            "like_count": 20,
            "coin_count": 3,
            "favorite_count": 4,
            "share_count": 5,
        },
    )
    monkeypatch.setattr(backfill, "launch_persistent_browser", lambda: FakeSession())

    result = backfill.backfill_bilibili_interactions(limit=1)

    data = load_video_data(data_path)
    assert result["updated_count"] == 1
    assert data["coin_count"].tolist() == ["3", "3"]
    assert json.loads(state_path.read_text(encoding="utf-8"))["completed_urls"] == [
        "https://www.bilibili.com/video/av1655409998"
    ]


def test_backfill_csv_replace_is_atomic_when_write_fails(monkeypatch, tmp_path):
    data_path = tmp_path / "videos.csv"
    original = b"original-csv"
    data_path.write_bytes(original)

    def fail_after_partial_write(data, path):
        path.write_bytes(b"partial")
        raise OSError("disk write failed")

    monkeypatch.setattr(backfill, "save_video_data", fail_after_partial_write)

    with pytest.raises(OSError, match="disk write failed"):
        backfill._save_backfill_data(records(), data_path)

    assert data_path.read_bytes() == original


def test_backfill_fails_fast_for_empty_source_csv(monkeypatch, tmp_path):
    data_path = tmp_path / "videos.csv"
    state_path = tmp_path / "interaction_backfill_state.json"
    pd.DataFrame(columns=VIDEO_COLUMNS).to_csv(data_path, index=False, encoding="utf-8-sig")
    monkeypatch.setattr(backfill, "get_video_data_path", lambda: data_path)
    monkeypatch.setattr(backfill, "get_backfill_state_path", lambda: state_path)
    monkeypatch.setattr(
        backfill,
        "launch_persistent_browser",
        lambda: pytest.fail("invalid source data must fail before Edge starts"),
    )

    with pytest.raises(ValueError, match="videos.csv does not contain any rows"):
        backfill.backfill_bilibili_interactions(limit=50)


def test_backfill_skips_failed_url_and_keeps_processing(monkeypatch, tmp_path):
    data_path, state_path = install_paths(monkeypatch, tmp_path)
    outcomes = iter(
        [
            backfill.VerificationRequiredError(),
            {"play_count": 100, "like_count": 20, "coin_count": 3, "favorite_count": 4, "share_count": 5},
        ]
    )

    def load_detail_metrics(page, video_url):
        outcome = next(outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(backfill, "_load_detail_metrics", load_detail_metrics)
    monkeypatch.setattr(backfill, "launch_persistent_browser", lambda: FakeSession())

    result = backfill.backfill_bilibili_interactions(limit=2)

    assert result["status"] == "partial"
    assert result["updated_count"] == 1
    assert result["skipped_count"] == 1
    assert load_video_data(data_path).loc[1, "like_count"] == "20"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["completed_urls"] == ["https://www.bilibili.com/video/BV1testB"]
    assert state["failed_urls"] == {
        "https://www.bilibili.com/video/BV1testA": {
            "attempts": 1,
            "reason": "verification_required",
        }
    }


def test_backfill_stops_after_two_consecutive_verification_pages(monkeypatch, tmp_path):
    data_path, _state_path = install_paths(monkeypatch, tmp_path)
    data = records()
    third = data.iloc[[0]].copy()
    third.loc[:, "video_url"] = "https://www.bilibili.com/video/BV1testC"
    pd.concat([data, third], ignore_index=True).to_csv(data_path, index=False, encoding="utf-8-sig")
    visited = []

    def require_verification(page, video_url):
        visited.append(video_url)
        raise backfill.VerificationRequiredError()

    monkeypatch.setattr(backfill, "_load_detail_metrics", require_verification)
    monkeypatch.setattr(backfill, "launch_persistent_browser", lambda: FakeSession())

    result = backfill.backfill_bilibili_interactions(limit=3)

    assert result["status"] == "verification_required"
    assert result["processed_count"] == 2
    assert result["skipped_count"] == 2
    assert visited == [
        "https://www.bilibili.com/video/BV1testA",
        "https://www.bilibili.com/video/BV1testB",
    ]


def test_backfill_defers_failed_url_until_fresh_urls_are_done(monkeypatch, tmp_path):
    _data_path, state_path = install_paths(monkeypatch, tmp_path)
    state_path.write_text(
        json.dumps(
            {
                "completed_urls": [],
                "failed_urls": {
                    "https://www.bilibili.com/video/BV1testA": {
                        "attempts": 1,
                        "reason": "page_timeout",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    visited = []
    monkeypatch.setattr(
        backfill,
        "_load_detail_metrics",
        lambda page, video_url: visited.append(video_url)
        or {"play_count": 100, "like_count": 20, "coin_count": 3, "favorite_count": 4, "share_count": 5},
    )
    monkeypatch.setattr(backfill, "launch_persistent_browser", lambda: FakeSession())

    backfill.backfill_bilibili_interactions(limit=1)

    assert visited == ["https://www.bilibili.com/video/BV1testB"]


def test_backfill_stops_retrying_after_three_failed_attempts(monkeypatch, tmp_path):
    _data_path, state_path = install_paths(monkeypatch, tmp_path)
    state_path.write_text(
        json.dumps(
            {
                "completed_urls": ["https://www.bilibili.com/video/BV1testB"],
                "failed_urls": {
                    "https://www.bilibili.com/video/BV1testA": {
                        "attempts": 3,
                        "reason": "page_structure_error",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        backfill,
        "launch_persistent_browser",
        lambda: pytest.fail("an exhausted URL must not launch Edge"),
    )

    result = backfill.backfill_bilibili_interactions(limit=50)

    assert result["status"] == "partial"
    assert result["processed_count"] == 0
    assert result["failed_count"] == 1
    assert result["retryable_count"] == 0


def test_reset_exhausted_failures_starts_new_cycle_but_keeps_unsupported_courses(monkeypatch, tmp_path):
    _data_path, state_path = install_paths(monkeypatch, tmp_path)
    state_path.write_text(
        json.dumps(
            {
                "completed_urls": [],
                "failed_urls": {
                    "https://www.bilibili.com/video/BV1testA": {
                        "attempts": 3,
                        "reason": "page_timeout",
                    },
                    "https://www.bilibili.com/video/BV1testB": {
                        "attempts": 2,
                        "reason": "page_structure_error",
                    },
                    "https://www.bilibili.com/cheese/play/ss29903": {
                        "attempts": 3,
                        "reason": "unsupported_course_url",
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    reset_count = backfill.reset_exhausted_failures()

    failures = json.loads(state_path.read_text(encoding="utf-8"))["failed_urls"]
    assert reset_count == 1
    assert "https://www.bilibili.com/video/BV1testA" not in failures
    assert failures["https://www.bilibili.com/video/BV1testB"]["attempts"] == 2
    assert failures["https://www.bilibili.com/cheese/play/ss29903"]["reason"] == "unsupported_course_url"


def test_backfill_records_genuine_zero_metrics_as_completed(monkeypatch, tmp_path):
    _data_path, state_path = install_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(backfill, "_load_detail_metrics", lambda page, video_url: {
        "play_count": 0,
        "like_count": 0,
        "coin_count": 0,
        "favorite_count": 0,
        "share_count": 0,
    })
    monkeypatch.setattr(backfill, "launch_persistent_browser", lambda: FakeSession())

    backfill.backfill_bilibili_interactions(limit=1)

    assert json.loads(state_path.read_text(encoding="utf-8"))["completed_urls"] == ["https://www.bilibili.com/video/BV1testA"]


@pytest.mark.parametrize("limit", (0, 51))
def test_backfill_rejects_limits_outside_fifty(limit):
    with pytest.raises(ValueError, match="limit must be between 1 and 50"):
        backfill.backfill_bilibili_interactions(limit=limit)


class FakePage:
    pass


class FakeContext:
    pages = [FakePage()]


class FakeSession:
    context = FakeContext()

    def close(self) -> None:
        pass
