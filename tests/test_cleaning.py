from __future__ import annotations

from pathlib import Path

import pandas as pd

try:
    from app import create_app
except ImportError:
    create_app = None

try:
    from data_utils import clean_video_data, load_cleaned_data
except ImportError:
    clean_video_data = None
    load_cleaned_data = None


def write_raw_csv(path: Path, rows: list[dict]) -> None:
    pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8-sig")


def create_client(tmp_path: Path):
    assert callable(create_app), "create_app 尚未实现"
    raw_path = tmp_path / "videos.csv"
    cleaned_path = tmp_path / "videos_cleaned.csv"
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret-key",
            "DATABASE": tmp_path / "users.db",
            "VIDEO_DATA_PATH": raw_path,
            "CLEANED_DATA_PATH": cleaned_path,
            "CLEANING_SUMMARY_PATH": tmp_path / "cleaning_summary.json",
        }
    )
    return app.test_client(), raw_path, cleaned_path


def login_as_admin(client) -> None:
    client.post("/login", data={"username": "admin", "password": "admin123"})


def test_cleaning_fills_missing_values_and_normalizes_negative_numbers(tmp_path):
    assert callable(clean_video_data), "clean_video_data 尚未实现"
    raw_path = tmp_path / "videos.csv"
    cleaned_path = tmp_path / "videos_cleaned.csv"
    write_raw_csv(
        raw_path,
        [
            {
                "title": "  ",
                "up_name": "",
                "play_count": "5万",
                "like_count": "-",
                "coin_count": -2,
                "favorite_count": "",
                "share_count": None,
                "comment_count": "10",
                "publish_time": "2026/07/20",
                "crawl_date": "",
            }
        ],
    )

    summary = clean_video_data(raw_path, cleaned_path)
    cleaned = load_cleaned_data(cleaned_path)

    assert summary["raw_count"] == 1
    assert cleaned.iloc[0]["title"] == "未知标题"
    assert cleaned.iloc[0]["up_name"] == "未知UP主"
    assert cleaned.iloc[0]["play_count"] == "50000"
    assert cleaned.iloc[0]["like_count"] == "0"
    assert cleaned.iloc[0]["coin_count"] == "0"
    assert cleaned.iloc[0]["publish_time"] == "2026-07-20"


def test_cleaning_removes_duplicates_by_url_or_title_and_up_name(tmp_path):
    assert callable(clean_video_data), "clean_video_data 尚未实现"
    raw_path = tmp_path / "videos.csv"
    cleaned_path = tmp_path / "videos_cleaned.csv"
    write_raw_csv(
        raw_path,
        [
            {"title": "视频甲", "up_name": "甲", "video_url": "https://example.com/a", "play_count": 1, "like_count": 1},
            {"title": "视频甲最新版", "up_name": "甲", "video_url": "https://example.com/a", "play_count": 2, "like_count": 2},
            {"title": "视频乙", "up_name": "乙", "video_url": "", "play_count": 3, "like_count": 3},
            {"title": "视频乙", "up_name": "乙", "video_url": "", "play_count": 4, "like_count": 4},
        ],
    )

    summary = clean_video_data(raw_path, cleaned_path)
    cleaned = load_cleaned_data(cleaned_path)

    assert summary["cleaned_count"] == 2
    assert summary["duplicate_count"] == 2
    assert set(cleaned["title"]) == {"视频甲最新版", "视频乙"}


def test_admin_cleaning_generates_cleaned_csv_and_keeps_raw_file(tmp_path):
    client, raw_path, cleaned_path = create_client(tmp_path)
    write_raw_csv(raw_path, [{"title": "视频甲", "up_name": "甲", "play_count": 100, "like_count": 10}])
    original_raw = raw_path.read_text(encoding="utf-8-sig")
    login_as_admin(client)

    response = client.post("/data/clean", follow_redirects=True)

    page = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "数据清洗完成：原始 1 条，清洗后 1 条，删除重复 0 条。" in page
    assert cleaned_path.exists()
    assert raw_path.read_text(encoding="utf-8-sig") == original_raw
    assert "当前数据来源：清洗数据" in page


def test_home_prefers_cleaned_data_when_it_exists(tmp_path):
    client, raw_path, cleaned_path = create_client(tmp_path)
    write_raw_csv(raw_path, [{"title": "原始视频", "up_name": "原始UP", "play_count": 999, "like_count": 999}])
    write_raw_csv(cleaned_path, [{"title": "清洗视频", "up_name": "清洗UP", "play_count": 12000, "like_count": 300}])
    login_as_admin(client)

    response = client.get("/")

    page = response.get_data(as_text=True)
    assert 'id="play-total">12,000' in page
    assert 'id="like-total">300' in page


def test_data_page_shows_cleaned_data_as_current_source(tmp_path):
    client, raw_path, cleaned_path = create_client(tmp_path)
    write_raw_csv(raw_path, [{"title": "原始视频", "up_name": "原始UP", "play_count": 999, "like_count": 999}])
    write_raw_csv(cleaned_path, [{"title": "清洗视频", "up_name": "清洗UP", "play_count": 100, "like_count": 10}])
    login_as_admin(client)

    response = client.get("/data")

    page = response.get_data(as_text=True)
    assert "当前数据来源：清洗数据" in page
    assert "清洗视频" in page
    assert "原始视频" not in page


def test_cleaning_without_raw_data_shows_friendly_message(tmp_path):
    client, _, cleaned_path = create_client(tmp_path)
    login_as_admin(client)

    response = client.post("/data/clean", follow_redirects=True)

    assert response.status_code == 200
    assert "暂无可清洗的视频数据，请先使用 B 站采集。" in response.get_data(as_text=True)
    assert not cleaned_path.exists()
