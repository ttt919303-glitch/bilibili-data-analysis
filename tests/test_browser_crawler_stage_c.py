from __future__ import annotations

from datetime import date
import sys
from urllib.parse import parse_qs, urlsplit

import pandas as pd
import pytest

import browser_crawler


class FakeTimeout(Exception):
    pass


class FakePage:
    def __init__(self, pages):
        self._pages = pages
        self.current = None
        self.url = ""
        self.goto_urls = []

    def goto(self, url, **kwargs):
        page_number = int(parse_qs(urlsplit(url).query).get("page", ["1"])[0])
        self.goto_urls.append(url)
        self.current = self._pages.get(page_number, {"state": "no_results", "videos": []})
        if self.current.get("timeout"):
            raise FakeTimeout("timeout")
        self.url = self.current.get("url", url)

    def wait_for_function(self, *args, **kwargs):
        return None

    def title(self):
        return "Bilibili search"


class FakeContext:
    def __init__(self, page):
        self.pages = []
        self._page = page

    def new_page(self):
        return self._page

    def close(self):
        return None


class FakeSession:
    def __init__(self, page):
        self.context = FakeContext(page)
        self.closed = False

    def close(self):
        self.closed = True


def video(index):
    return {
        "title": f"video {index}",
        "video_url": f"https://www.bilibili.com/video/BV1test{index:04d}/",
        "up_name": "creator",
        "play_count": index,
        "publish_time": "2024-08-22",
    }


def install_crawl_mocks(monkeypatch, pages, existing_urls=()):
    page = FakePage(pages)
    saved_batches = []
    monkeypatch.setattr(browser_crawler, "launch_persistent_browser", lambda: FakeSession(page))
    monkeypatch.setattr(browser_crawler, "_page_timeout_error", lambda: FakeTimeout)
    monkeypatch.setattr(browser_crawler, "detect_page_state", lambda current_page: current_page.current["state"])
    monkeypatch.setattr(browser_crawler, "parse_video_cards", lambda current_page, limit: current_page.current["videos"])
    monkeypatch.setattr(browser_crawler, "load_video_data", lambda path: pd.DataFrame({"video_url": list(existing_urls)}))
    monkeypatch.setattr(browser_crawler, "get_video_data_path", lambda: "videos.csv")
    monkeypatch.setattr(browser_crawler, "sleep", lambda seconds: None)
    monkeypatch.setattr(browser_crawler, "uniform", lambda start, end: 3.0)

    def append(new_data, path):
        saved_batches.append(new_data.to_dict(orient="records"))
        return len(existing_urls) + sum(len(batch) for batch in saved_batches)

    monkeypatch.setattr(browser_crawler, "append_video_data", append)
    return page, saved_batches


@pytest.mark.parametrize("limit", [0, 201])
def test_crawl_rejects_limits_outside_phase_c_range(limit):
    with pytest.raises(ValueError, match="between 1 and 200"):
        browser_crawler.crawl_bilibili_browser("Python", limit)


def test_crawl_stops_after_one_page_when_target_is_saved(monkeypatch):
    page, saved_batches = install_crawl_mocks(monkeypatch, {1: {"state": "success", "videos": [video(index) for index in range(20)]}})

    result = browser_crawler.crawl_bilibili_browser("Python", 20)

    assert result["status"] == "success"
    assert result["saved_count"] == 20
    assert result["page_count"] == 1
    assert len(page.goto_urls) == 1
    assert len(saved_batches) == 1
    assert saved_batches[0][0]["like_count"] == 0
    assert saved_batches[0][0]["crawl_date"] == date.today().isoformat()


def test_crawl_accumulates_and_saves_each_page(monkeypatch):
    first_page = [video(index) for index in range(15)]
    second_page = [video(index) for index in range(15, 35)]
    page, saved_batches = install_crawl_mocks(
        monkeypatch,
        {1: {"state": "success", "videos": first_page}, 2: {"state": "success", "videos": second_page}},
    )

    result = browser_crawler.crawl_bilibili_browser("Python", 20)

    assert result["status"] == "success"
    assert result["saved_count"] == 20
    assert result["page_count"] == 2
    assert len(saved_batches) == 2
    assert "page=2" in page.goto_urls[1]


def test_crawl_skips_existing_csv_urls_and_same_batch_duplicates(monkeypatch):
    duplicate = video(1)
    page, saved_batches = install_crawl_mocks(
        monkeypatch,
        {1: {"state": "success", "videos": [video(0), duplicate, duplicate, video(2)]}, 2: {"state": "success", "videos": [video(3), video(4)]}},
        existing_urls={video(0)["video_url"]},
    )

    result = browser_crawler.crawl_bilibili_browser("Python", 4)

    assert result["saved_count"] == 4
    assert result["skipped_count"] == 2
    assert [record["video_url"] for batch in saved_batches for record in batch] == [
        video(1)["video_url"],
        video(2)["video_url"],
        video(3)["video_url"],
        video(4)["video_url"],
    ]
    assert len(page.goto_urls) == 2


def test_crawl_keeps_first_page_when_second_page_requires_verification(monkeypatch):
    _, saved_batches = install_crawl_mocks(
        monkeypatch,
        {1: {"state": "success", "videos": [video(index) for index in range(20)]}, 2: {"state": "verification_required", "videos": []}},
    )

    result = browser_crawler.crawl_bilibili_browser("Python", 50)

    assert result["status"] == "verification_required"
    assert result["saved_count"] == 20
    assert len(saved_batches) == 1


def test_crawl_keeps_first_page_when_second_page_times_out(monkeypatch):
    _, saved_batches = install_crawl_mocks(
        monkeypatch,
        {1: {"state": "success", "videos": [video(index) for index in range(20)]}, 2: {"timeout": True}},
    )

    result = browser_crawler.crawl_bilibili_browser("Python", 50)

    assert result["status"] == "partial"
    assert result["saved_count"] == 20
    assert len(saved_batches) == 1


def test_crawl_stops_normally_when_next_page_has_no_results(monkeypatch):
    _, saved_batches = install_crawl_mocks(
        monkeypatch,
        {1: {"state": "success", "videos": [video(index) for index in range(20)]}, 2: {"state": "no_results", "videos": []}},
    )

    result = browser_crawler.crawl_bilibili_browser("Python", 50)

    assert result["status"] == "partial"
    assert result["saved_count"] == 20
    assert len(saved_batches) == 1


def test_crawl_stops_when_second_page_does_not_change(monkeypatch):
    first_page = [video(index) for index in range(20)]
    _, _ = install_crawl_mocks(
        monkeypatch,
        {
            1: {"state": "success", "videos": first_page, "url": "https://search.bilibili.com/all?keyword=Python"},
            2: {"state": "success", "videos": first_page, "url": "https://search.bilibili.com/all?keyword=Python"},
        },
    )

    result = browser_crawler.crawl_bilibili_browser("Python", 50)

    assert result["status"] == "partial"
    assert result["message"] == "page_not_changed"


def test_crawl_stops_after_two_pages_without_new_video_urls(monkeypatch):
    first_page = [video(index) for index in range(20)]
    _, _ = install_crawl_mocks(
        monkeypatch,
        {
            1: {"state": "success", "videos": first_page},
            2: {"state": "success", "videos": first_page},
            3: {"state": "success", "videos": first_page},
        },
    )

    result = browser_crawler.crawl_bilibili_browser("Python", 100)

    assert result["status"] == "partial"
    assert result["message"] == "two_pages_without_new_video_urls"


def test_crawl_stops_at_max_pages(monkeypatch):
    pages = {index: {"state": "success", "videos": [video(index)]} for index in range(1, 21)}
    existing_urls = {video(index)["video_url"] for index in range(1, 21)}
    page, _ = install_crawl_mocks(monkeypatch, pages, existing_urls=existing_urls)

    result = browser_crawler.crawl_bilibili_browser("Python", 50)

    assert result["status"] == "partial"
    assert result["message"] == "max_pages_reached"
    assert len(page.goto_urls) == 20


def test_debug_search_mode_does_not_call_formal_crawl(monkeypatch, capsys):
    import debug_browser_crawler

    monkeypatch.setattr(
        debug_browser_crawler,
        "diagnose_search",
        lambda keyword, limit: {
            "status": "success",
            "keyword": keyword,
            "page_url": "https://search.bilibili.com/all?keyword=Python",
            "page_title": "Bilibili search",
            "card_count": 35,
            "video_link_count": 35,
            "videos": [],
        },
    )
    monkeypatch.setattr(debug_browser_crawler, "crawl_bilibili_browser", lambda keyword, limit: pytest.fail("crawl called"))
    monkeypatch.setattr(sys, "argv", ["debug_browser_crawler.py", "--browser", "msedge", "--search", "Python", "--limit", "5"])

    debug_browser_crawler.main()

    assert "browser search diagnostic" in capsys.readouterr().out


def test_debug_crawl_mode_calls_formal_crawl(monkeypatch, capsys):
    import debug_browser_crawler

    called = []
    def crawl(keyword, limit, progress=None):
        called.append((keyword, limit))
        assert progress is not None
        progress({
            "page": 1,
            "parsed_count": 20,
            "skipped_count": 0,
            "new_count": 20,
            "saved_count": 20,
            "planned_count": 20,
        })
        return {
        "status": "success",
        "keyword": keyword,
        "planned_count": limit,
        "parsed_count": limit,
        "skipped_count": 0,
        "saved_count": limit,
        "page_count": 1,
        "message": "collection_complete",
        }

    monkeypatch.setattr(debug_browser_crawler, "crawl_bilibili_browser", crawl)
    monkeypatch.setattr(sys, "argv", ["debug_browser_crawler.py", "--browser", "msedge", "--crawl", "Python", "--limit", "20"])

    debug_browser_crawler.main()

    assert called == [("Python", 20)]
    output = capsys.readouterr().out
    assert "formal browser collection" in output
    assert "page=1 parsed=20 skipped=0 new=20 saved=20/20" in output
