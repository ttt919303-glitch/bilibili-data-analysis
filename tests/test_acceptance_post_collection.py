from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pandas as pd

from app import create_app
from data_utils import load_video_data


def create_client(tmp_path: Path):
    app = create_app(
        {
            "TESTING": True,
            "DATABASE": tmp_path / "users.db",
            "VIDEO_DATA_PATH": tmp_path / "videos.csv",
            "CLEANED_DATA_PATH": tmp_path / "videos_cleaned.csv",
            "CLEANING_SUMMARY_PATH": tmp_path / "summary.json",
            "HDFS_WEB_URL": "",
        }
    )
    client = app.test_client()
    client.post("/login", data={"username": "admin", "password": "admin123"})
    return client, app


def crawled_data() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "title": "采集后自动处理",
                "video_url": "https://www.bilibili.com/video/BVauto",
                "up_name": "UP",
                "play_count": 100,
                "like_count": 10,
                "coin_count": 1,
                "favorite_count": 2,
                "share_count": 3,
                "comment_count": 4,
                "publish_time": "2026-08-06",
                "crawl_date": "2026-08-07",
            }
        ]
    )


def test_api_collection_automatically_cleans_and_attempts_hdfs_upload(tmp_path: Path):
    client, app = create_client(tmp_path)

    with patch("app.crawl_bilibili", return_value=crawled_data()), patch(
        "app.upload_cleaned_to_hdfs", return_value=(True, "ok")
    ) as upload:
        response = client.post("/data/crawl", data={"keyword": "Spark", "limit": "1"})

    assert response.status_code == 302
    assert Path(app.config["CLEANED_DATA_PATH"]).exists()
    upload.assert_called_once()


def test_hdfs_failure_after_collection_keeps_raw_and_cleaned_csv(tmp_path: Path):
    client, app = create_client(tmp_path)

    with patch("app.crawl_bilibili", return_value=crawled_data()), patch(
        "app.upload_cleaned_to_hdfs", return_value=(False, "offline")
    ):
        client.post("/data/crawl", data={"keyword": "Spark", "limit": "1"})

    assert load_video_data(Path(app.config["VIDEO_DATA_PATH"]))["title"].tolist() == ["采集后自动处理"]
    assert load_video_data(Path(app.config["CLEANED_DATA_PATH"]))["title"].tolist() == ["采集后自动处理"]


def test_browser_collection_automatically_runs_same_post_pipeline(tmp_path: Path):
    client, app = create_client(tmp_path)
    raw_path = Path(app.config["VIDEO_DATA_PATH"])
    video_url = "https://www.bilibili.com/video/BVauto"

    def browser_crawl(_keyword: str, _limit: int, *, data_path: Path):
        crawled_data().to_csv(data_path, index=False, encoding="utf-8-sig")
        return {
            "status": "success",
            "saved_count": 1,
            "parsed_count": 1,
            "skipped_count": 0,
            "page_count": 1,
        }

    detail_result = {"status": "success", "updated_count": 1, "remaining_count": 0}
    with patch("app.crawl_bilibili_browser", side_effect=browser_crawl), patch(
        "app.get_supported_video_urls", side_effect=[[], [video_url]]
    ), patch("app.run_target_batches", return_value=detail_result), patch(
        "app.upload_cleaned_to_hdfs", return_value=(True, "ok")
    ) as upload:
        response = client.post("/data/browser-crawl", data={"keyword": "Spark", "limit": "1"})

    assert response.status_code == 302
    assert Path(app.config["CLEANED_DATA_PATH"]).exists()
    upload.assert_called_once()


def test_browser_backfill_receives_isolated_data_and_state_paths(tmp_path: Path):
    client, app = create_client(tmp_path)
    result = {
        "status": "success",
        "planned_count": 50,
        "updated_count": 0,
        "processed_count": 0,
        "skipped_count": 0,
        "failed_count": 0,
        "remaining_count": 0,
    }

    with patch("app.backfill_bilibili_interactions", return_value=result) as backfill:
        response = client.post("/data/browser-backfill")

    assert response.status_code == 302
    assert backfill.call_args.kwargs == {
        "limit": 50,
        "data_path": Path(app.config["VIDEO_DATA_PATH"]),
        "state_path": Path(app.config["INTERACTION_BACKFILL_STATE_PATH"]),
    }
