from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

import crawler
from app import create_app
from data_utils import load_video_data


def search_item(index: int) -> dict:
    return {
        "title": f"Python 视频{index}",
        "arcurl": f"https://www.bilibili.com/video/BV{index}",
        "author": f"UP主{index}",
        "play": 1000,
        "pubdate": 1_720_000_000,
    }


def create_client(tmp_path: Path):
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret-key",
            "DATABASE": tmp_path / "users.db",
            "VIDEO_DATA_PATH": tmp_path / "videos.csv",
            "CLEANED_DATA_PATH": tmp_path / "videos_cleaned.csv",
            "CLEANING_SUMMARY_PATH": tmp_path / "cleaning_summary.json",
        }
    )
    return app.test_client(), tmp_path / "videos.csv"


def login(client) -> None:
    client.post("/login", data={"username": "admin", "password": "admin123"})


def test_blocked_api_code_has_restriction_message():
    response = FakeResponse({"code": -352, "data": {"result": []}})
    with patch("crawler.urlopen", return_value=response):
        with pytest.raises(crawler.CrawlerError, match="B站当前限制了搜索请求，请稍后再试。"):
            crawler._fetch_search_page("Python", 1, 50)


def test_rate_limit_after_data_returns_partial_data_without_retry():
    pages = [
        [search_item(index) for index in range(50)],
        crawler.CrawlerError("B站当前限制了搜索请求，请稍后再试。", is_limited=True),
    ]
    with patch("crawler._fetch_search_page", side_effect=pages) as fetch_page, patch("crawler.time.sleep"):
        data = crawler.crawl_bilibili("Python", 300)

    assert len(data) == 50
    assert data.attrs["crawl_status"] == "limited"
    assert data.attrs["crawl_message"] == "B站暂时限制了后续搜索请求，请稍后继续采集。"
    assert fetch_page.call_count == 2


def test_rate_limit_on_first_page_does_not_return_data():
    with patch(
        "crawler._fetch_search_page",
        side_effect=crawler.CrawlerError("B站当前限制了搜索请求，请稍后再试。", is_limited=True),
    ):
        with pytest.raises(crawler.CrawlerError, match="B站当前限制了搜索请求，请稍后再试。"):
            crawler.crawl_bilibili("Python", 300)


def test_requests_use_a_random_two_to_four_second_delay():
    pages = [[search_item(index) for index in range(50)], []]
    with patch("crawler._fetch_search_page", side_effect=pages), patch("crawler.random.uniform", return_value=3) as delay, patch("crawler.time.sleep") as sleep:
        crawler.crawl_bilibili("Python", 100)

    delay.assert_called_once_with(2, 4)
    sleep.assert_called_once_with(3)


def test_data_page_saves_limited_partial_results(tmp_path):
    client, raw_path = create_client(tmp_path)
    login(client)
    data = crawler._finalize_data(
        [crawler._to_video_record(search_item(1))],
        "limited",
        1,
        "B站暂时限制了后续搜索请求，请稍后继续采集。",
    )

    with patch("app.crawl_bilibili", return_value=data):
        response = client.post("/data/crawl", data={"keyword": "Python", "limit": "300"}, follow_redirects=True)

    page = response.get_data(as_text=True)
    assert len(load_video_data(raw_path)) == 1
    assert "计划采集：300条；成功采集：1条" in page
    assert "B站暂时限制了后续搜索请求，请稍后继续采集。" in page


class FakeResponse:
    status = 200

    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback):
        return False

    def read(self) -> bytes:
        import json

        return json.dumps(self.payload).encode("utf-8")
