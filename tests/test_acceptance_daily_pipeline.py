from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

import scheduler
from app import create_app
from daily_pipeline import run_daily_pipeline
from data_utils import load_video_data


def record(title: str, url: str, publish_time: str) -> dict[str, object]:
    return {
        "title": title,
        "video_url": url,
        "up_name": "课程UP",
        "play_count": 100,
        "like_count": 10,
        "coin_count": 1,
        "favorite_count": 2,
        "share_count": 3,
        "comment_count": 4,
        "publish_time": publish_time,
        "crawl_date": "2026-08-07",
    }


def pipeline_config(tmp_path: Path) -> dict:
    return {
        "VIDEO_DATA_PATH": tmp_path / "videos.csv",
        "CLEANED_DATA_PATH": tmp_path / "videos_cleaned.csv",
        "CLEANING_SUMMARY_PATH": tmp_path / "cleaning_summary.json",
        "DAILY_PIPELINE_STATUS_PATH": tmp_path / "daily_pipeline_status.json",
        "AUTO_CRAWL_KEYWORDS": "Spark,Python",
        "AUTO_CRAWL_LIMIT": 10,
        "APP_TIMEZONE": "Asia/Shanghai",
        "HDFS_CMD": "hdfs",
        "HDFS_WEB_URL": "",
        "HDFS_WEB_USER": "tan",
    }


def test_daily_pipeline_filters_publish_date_deduplicates_and_cleans(tmp_path: Path):
    duplicate = "https://www.bilibili.com/video/BVsame"

    def crawler(keyword: str, _limit: int) -> pd.DataFrame:
        if keyword == "Spark":
            return pd.DataFrame([record("目标视频", duplicate + "/?from=search", "2026-08-06"), record("旧视频", "https://www.bilibili.com/video/BVold", "2026-08-05")])
        return pd.DataFrame([record("重复视频", duplicate, "2026-08-06"), record("另一个目标", "https://www.bilibili.com/video/BVnew", "2026-08-06 08:00:00")])

    result = run_daily_pipeline(
        "2026-08-06",
        config=pipeline_config(tmp_path),
        crawler=crawler,
        uploader=lambda *_args: (True, "uploaded"),
    )

    raw = load_video_data(tmp_path / "videos.csv")
    assert result["collected_count"] == 4
    assert result["date_filtered_count"] == 3
    assert result["added_count"] == 2
    assert raw["title"].tolist() == ["目标视频", "另一个目标"]
    assert (tmp_path / "videos_cleaned.csv").exists()
    assert result["cleaning_result"]["cleaned_count"] == 2


def test_hdfs_failure_keeps_daily_pipeline_local_data(tmp_path: Path):
    config = pipeline_config(tmp_path)
    crawled = pd.DataFrame([record("本地保留", "https://www.bilibili.com/video/BVlocal", "2026-08-06")])

    result = run_daily_pipeline(
        "2026-08-06",
        config=config,
        crawler=lambda *_args: crawled,
        uploader=lambda *_args: (False, "HDFS offline"),
    )

    assert load_video_data(config["VIDEO_DATA_PATH"])["title"].tolist() == ["本地保留"]
    assert result["hdfs_upload_status"] == "failed"
    assert "HDFS offline" in result["error_summary"]
    persisted = json.loads(config["DAILY_PIPELINE_STATUS_PATH"].read_text(encoding="utf-8"))
    assert persisted["target_date"] == "2026-08-06"


def test_existing_video_url_is_not_appended_again(tmp_path: Path):
    config = pipeline_config(tmp_path)
    pd.DataFrame([record("已有", "https://www.bilibili.com/video/BVsame", "2026-08-06")]).to_csv(
        config["VIDEO_DATA_PATH"], index=False, encoding="utf-8-sig"
    )
    crawled = pd.DataFrame([record("重复", "https://www.bilibili.com/video/BVsame/?x=1", "2026-08-06")])

    result = run_daily_pipeline(
        "2026-08-06",
        config=config,
        crawler=lambda *_args: crawled,
        uploader=lambda *_args: (True, "ok"),
    )

    assert result["added_count"] == 0
    assert len(load_video_data(config["VIDEO_DATA_PATH"])) == 1


def test_testing_app_never_starts_real_scheduler(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(scheduler, "BackgroundScheduler", lambda **_kwargs: pytest.fail("scheduler started"))
    app = create_app({"TESTING": True, "DATABASE": tmp_path / "users.db", "AUTO_CRAWL_ENABLED": True})

    assert scheduler.start_scheduler(app) is None


def test_flask_cli_debug_parent_never_starts_scheduler(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("WERKZEUG_RUN_MAIN", raising=False)
    monkeypatch.setenv("FLASK_DEBUG", "1")
    monkeypatch.setattr(scheduler, "_scheduler", None)
    monkeypatch.setattr(
        scheduler,
        "BackgroundScheduler",
        lambda **_kwargs: pytest.fail("debug reloader parent started scheduler"),
    )

    app = create_app(
        {
            "TESTING": False,
            "DATABASE": tmp_path / "users.db",
            "VIDEO_DATA_PATH": tmp_path / "videos.csv",
            "AUTO_CRAWL_ENABLED": True,
        }
    )

    assert app is not None


def test_runtime_app_starts_daily_scheduler_by_default(tmp_path: Path, monkeypatch):
    starts = []

    class FakeScheduler:
        def __init__(self, **_kwargs):
            pass

        def add_job(self, *_args, **_kwargs):
            pass

        def start(self):
            starts.append("started")

    monkeypatch.delenv("AUTO_CRAWL_ENABLED", raising=False)
    monkeypatch.delenv("FLASK_DEBUG", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("WERKZEUG_RUN_MAIN", raising=False)
    monkeypatch.setattr(scheduler, "_scheduler", None)
    monkeypatch.setattr(scheduler, "BackgroundScheduler", FakeScheduler)

    create_app(
        {
            "TESTING": False,
            "DATABASE": tmp_path / "users.db",
            "VIDEO_DATA_PATH": tmp_path / "videos.csv",
        }
    )

    assert starts == ["started"]


def test_testing_app_defaults_all_runtime_data_to_test_database_directory(tmp_path: Path):
    app = create_app({"TESTING": True, "DATABASE": tmp_path / "users.db"})

    runtime_paths = (
        "VIDEO_DATA_PATH",
        "CLEANED_DATA_PATH",
        "CLEANING_SUMMARY_PATH",
        "DAILY_PIPELINE_STATUS_PATH",
        "KNOWLEDGE_BASE_PATH",
        "INTERACTION_BACKFILL_STATE_PATH",
    )
    assert all(Path(app.config[name]).parent == tmp_path for name in runtime_paths)


def test_multiple_app_creation_starts_only_one_scheduler(tmp_path: Path, monkeypatch):
    starts = []

    class FakeScheduler:
        def __init__(self, **_kwargs):
            pass

        def add_job(self, *_args, **_kwargs):
            pass

        def start(self):
            starts.append("started")

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(scheduler, "_scheduler", None)
    monkeypatch.setattr(scheduler, "BackgroundScheduler", FakeScheduler)
    common = {
        "TESTING": False,
        "DATABASE": tmp_path / "users.db",
        "VIDEO_DATA_PATH": tmp_path / "videos.csv",
        "AUTO_CRAWL_ENABLED": True,
    }

    create_app(common)
    create_app(common)

    assert starts == ["started"]


def test_regular_user_cannot_run_yesterday_pipeline(tmp_path: Path):
    app = create_app({"TESTING": True, "DATABASE": tmp_path / "users.db", "VIDEO_DATA_PATH": tmp_path / "videos.csv"})
    client = app.test_client()
    client.post("/login", data={"username": "user", "password": "user123"})

    response = client.post("/data/daily-pipeline/run")

    assert response.status_code == 403


def test_admin_manual_trigger_calls_same_daily_pipeline_function(tmp_path: Path):
    app = create_app({"TESTING": True, "DATABASE": tmp_path / "users.db", "VIDEO_DATA_PATH": tmp_path / "videos.csv"})
    client = app.test_client()
    client.post("/login", data={"username": "admin", "password": "admin123"})
    result = {
        "target_date": "2026-08-06",
        "added_count": 2,
        "error_summary": "",
    }

    with patch("app.run_daily_pipeline", return_value=result) as pipeline:
        response = client.post("/data/daily-pipeline/run")

    assert response.status_code == 302
    pipeline.assert_called_once()
