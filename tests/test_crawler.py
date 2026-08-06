from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pandas as pd

try:
    from app import create_app
except ImportError:
    create_app = None

try:
    from crawler import CrawlerError, crawl_bilibili
except ImportError:
    CrawlerError = None
    crawl_bilibili = None

try:
    from data_utils import clean_video_data, load_video_data
except ImportError:
    clean_video_data = None
    load_video_data = None


def create_client(tmp_path: Path):
    assert callable(create_app), "create_app 尚未实现"
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
    return app.test_client(), tmp_path / "videos.csv", tmp_path / "videos_cleaned.csv"


def login(client, username: str, password: str) -> None:
    client.post("/login", data={"username": username, "password": password})


def crawled_videos() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "title": "大数据技术入门",
                "video_url": "https://www.bilibili.com/video/BV1test",
                "up_name": "课程UP主",
                "play_count": "1.2万",
                "like_count": 50,
                "coin_count": 0,
                "favorite_count": 0,
                "share_count": 0,
                "comment_count": 0,
                "publish_time": "2026-07-30",
                "crawl_date": "2026-07-30",
            }
        ]
    )


def test_regular_user_cannot_start_crawl(tmp_path):
    client, _raw_path, _cleaned_path = create_client(tmp_path)
    login(client, "user", "user123")

    response = client.post("/data/crawl", data={"keyword": "大数据技术", "limit": "10"})

    assert response.status_code == 403


def test_admin_can_see_crawl_card(tmp_path):
    client, _raw_path, _cleaned_path = create_client(tmp_path)
    login(client, "admin", "admin123")

    response = client.get("/data")

    assert response.status_code == 200
    assert "B站数据采集" in response.get_data(as_text=True)


def test_successful_crawl_appends_raw_video_data(tmp_path):
    client, raw_path, _cleaned_path = create_client(tmp_path)
    login(client, "admin", "admin123")

    with patch("app.crawl_bilibili", return_value=crawled_videos()):
        response = client.post(
            "/data/crawl",
            data={"keyword": "大数据技术", "limit": "10"},
            follow_redirects=True,
        )

    saved_data = load_video_data(raw_path)
    page = response.get_data(as_text=True)
    assert len(saved_data) == 1
    assert saved_data.loc[0, "title"] == "大数据技术入门"
    assert "成功采集：1条" in page
    assert "当前累计：1条" in page


def test_crawl_network_failure_shows_friendly_message(tmp_path):
    client, _raw_path, _cleaned_path = create_client(tmp_path)
    login(client, "admin", "admin123")
    assert CrawlerError is not None, "CrawlerError 尚未实现"

    with patch("app.crawl_bilibili", side_effect=CrawlerError("无法连接B站搜索服务，请检查网络后重试。")):
        response = client.post(
            "/data/crawl",
            data={"keyword": "大数据技术", "limit": "10"},
            follow_redirects=True,
        )

    assert response.status_code == 200
    assert "无法连接B站搜索服务，请检查网络后重试。" in response.get_data(as_text=True)


def test_invalid_crawl_limit_shows_friendly_message(tmp_path):
    client, _raw_path, _cleaned_path = create_client(tmp_path)
    login(client, "admin", "admin123")

    response = client.post(
        "/data/crawl",
        data={"keyword": "大数据技术", "limit": "0"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert "采集数量必须为1~1000之间的整数。" in response.get_data(as_text=True)


def test_crawled_data_can_be_cleaned_by_existing_flow(tmp_path):
    assert callable(clean_video_data), "clean_video_data 尚未实现"
    raw_path = tmp_path / "videos.csv"
    cleaned_path = tmp_path / "videos_cleaned.csv"
    crawled_videos().to_csv(raw_path, index=False, encoding="utf-8-sig")

    summary = clean_video_data(raw_path, cleaned_path)
    cleaned_data = load_video_data(cleaned_path)

    assert summary["cleaned_count"] == 1
    assert cleaned_data.loc[0, "play_count"] == "12000"


def test_crawler_rejects_empty_keyword():
    assert callable(crawl_bilibili), "crawl_bilibili 尚未实现"
    assert CrawlerError is not None, "CrawlerError 尚未实现"

    try:
        crawl_bilibili("", 10)
    except CrawlerError as error:
        assert str(error) == "请输入采集关键词。"
    else:
        raise AssertionError("空关键词应被拒绝")
