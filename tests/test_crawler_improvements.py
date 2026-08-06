from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import pandas as pd
import pytest

import crawler
from app import create_app
from data_utils import load_video_data


def search_item(index: int, *, video_url: str | None = None) -> dict:
    return {
        "title": f"<em class=\"keyword\">Python</em> 视频{index}",
        "arcurl": video_url or f"https://www.bilibili.com/video/BV{index}",
        "author": f"UP主{index}",
        "play": "1.2万",
        "like": 10,
        "favorites": 5,
        "review": 2,
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


def test_limit_500_automatically_fetches_multiple_pages():
    pages = [[search_item(page * 50 + index) for index in range(50)] for page in range(10)]

    with patch("crawler._fetch_search_page", side_effect=pages) as fetch_page, patch("crawler.time.sleep"):
        data = crawler.crawl_bilibili("Python", 500)

    assert len(data) == 500
    assert fetch_page.call_count == 10
    assert data.attrs["page_count"] == 10


def test_crawler_stops_after_reaching_limit():
    pages = [[search_item(index) for index in range(50)], [search_item(index + 50) for index in range(50)]]

    with patch("crawler._fetch_search_page", side_effect=pages) as fetch_page, patch("crawler.time.sleep"):
        data = crawler.crawl_bilibili("Python", 75)

    assert len(data) == 75
    assert fetch_page.call_count == 2


def test_crawler_stops_when_a_page_has_no_results():
    with patch("crawler._fetch_search_page", return_value=[]), patch("crawler.time.sleep"):
        data = crawler.crawl_bilibili("xjskqowueuwoq123987xyz", 100)

    assert data.empty
    assert data.attrs["crawl_status"] == "empty"
    assert data.attrs["page_count"] == 1


@pytest.mark.parametrize("limit", [1, 1000])
def test_crawler_accepts_valid_limit_bounds(limit):
    with patch("crawler._fetch_search_page", return_value=[]), patch("crawler.time.sleep"):
        data = crawler.crawl_bilibili("Python", limit)

    assert data.empty


@pytest.mark.parametrize("limit", [0, 1001])
def test_crawler_rejects_invalid_limit_bounds(limit):
    with pytest.raises(crawler.CrawlerError, match="采集数量必须为1~1000之间的整数。"):
        crawler.crawl_bilibili("Python", limit)


def test_network_failure_is_not_reported_as_empty_result():
    with patch("crawler._fetch_search_page", side_effect=crawler.CrawlerError("无法连接B站搜索服务，请检查网络后重试。")):
        with pytest.raises(crawler.CrawlerError, match="无法连接B站搜索服务，请检查网络后重试。"):
            crawler.crawl_bilibili("Python", 10)


def test_http_412_has_a_specific_friendly_error():
    error = HTTPError("https://example.com", 412, "blocked", {}, BytesIO())
    with patch("crawler.urlopen", side_effect=error):
        with pytest.raises(crawler.CrawlerError, match="B站当前限制了搜索请求，请稍后再试。"):
            crawler._fetch_search_page("Python", 1, 50)


def test_api_code_error_is_distinguished_from_empty_result():
    response = FakeResponse({"code": -999, "data": {"result": []}})
    with patch("crawler.urlopen", return_value=response):
        with pytest.raises(crawler.CrawlerError, match="B站搜索接口返回异常，请稍后重试。"):
            crawler._fetch_search_page("Python", 1, 50)


def test_invalid_json_is_distinguished_from_empty_result():
    response = FakeResponse(b"not-json")
    with patch("crawler.urlopen", return_value=response):
        with pytest.raises(crawler.CrawlerError, match="B站返回数据解析失败，请稍后重试。"):
            crawler._fetch_search_page("Python", 1, 50)


def test_missing_result_array_is_reported_as_structure_change():
    response = FakeResponse({"code": 0, "data": {}})
    with patch("crawler.urlopen", return_value=response):
        with pytest.raises(crawler.CrawlerError, match="B站搜索接口数据结构发生变化，暂时无法解析视频结果。"):
            crawler._fetch_search_page("Python", 1, 50)


def test_chinese_keyword_uses_url_encoding():
    response = FakeResponse({"code": 0, "data": {"result": []}})
    with patch("crawler.urlopen", return_value=response) as open_request:
        crawler._fetch_search_page("大数据技术", 1, 50)

    assert "%E5%A4%A7" in open_request.call_args.args[0].full_url


def test_crawler_uses_public_search_endpoint_with_video_results():
    assert crawler.SEARCH_URL == "https://api.bilibili.com/x/web-interface/search/type"


def test_duplicate_video_urls_are_removed_within_one_crawl():
    pages = [
        [search_item(1, video_url="https://www.bilibili.com/video/BVsame"), search_item(2)],
        [search_item(3, video_url="https://www.bilibili.com/video/BVsame"), search_item(4)],
        [],
    ]
    with patch("crawler._fetch_search_page", side_effect=pages), patch("crawler.time.sleep"):
        data = crawler.crawl_bilibili("Python", 10)

    assert len(data) == 3
    assert data["video_url"].nunique() == 3
    assert data.attrs["crawl_status"] == "insufficient"


def test_partial_data_is_returned_when_a_later_page_fails():
    pages = [[search_item(index) for index in range(50)], crawler.CrawlerError("无法连接B站搜索服务，请检查网络后重试。")]
    with patch("crawler._fetch_search_page", side_effect=pages), patch("crawler.time.sleep"):
        data = crawler.crawl_bilibili("Python", 100)

    assert len(data) == 50
    assert data.attrs["crawl_status"] == "partial"
    assert data.attrs["page_count"] == 1
    assert data.attrs["crawl_message"] == "无法连接B站搜索服务，请检查网络后重试。"


def test_data_page_saves_partial_crawl_and_shows_progress(tmp_path):
    client, raw_path = create_client(tmp_path)
    login(client)
    data = pd.DataFrame([search_item(1)])
    data = crawler._finalize_data([crawler._to_video_record(search_item(1))], "partial", 1, "无法连接B站搜索服务，请检查网络后重试。")

    with patch("app.crawl_bilibili", return_value=data):
        response = client.post("/data/crawl", data={"keyword": "Python", "limit": "100"}, follow_redirects=True)

    page = response.get_data(as_text=True)
    assert len(load_video_data(raw_path)) == 1
    assert "请求页数：1页" in page
    assert "状态：网络请求中断" in page
    assert "1 / 10000 条" in page


def test_data_page_only_calls_no_results_after_verified_empty_search(tmp_path):
    client, _raw_path = create_client(tmp_path)
    login(client)
    data = crawler._finalize_data([], "empty", 1, "")

    with patch("app.crawl_bilibili", return_value=data):
        response = client.post("/data/crawl", data={"keyword": "不存在的关键词", "limit": "10"}, follow_redirects=True)

    assert "B站搜索成功，但未找到与“不存在的关键词”相关的视频。" in response.get_data(as_text=True)


class FakeResponse:
    status = 200

    def __init__(self, payload: dict | bytes):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback):
        return False

    def read(self) -> bytes:
        if isinstance(self.payload, bytes):
            return self.payload
        return json.dumps(self.payload).encode("utf-8")
