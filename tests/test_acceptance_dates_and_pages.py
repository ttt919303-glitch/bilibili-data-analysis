from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from app import create_app


EMPTY_SPARK = {
    "source": "本地清洗CSV",
    "total_count": 0,
    "up_video_count": [],
    "top_played": [],
    "up_avg_play": [],
    "publish_trend": [],
}


def create_client(tmp_path: Path):
    raw_path = tmp_path / "videos.csv"
    pd.DataFrame(
        [
            {"title": "目标日期视频", "up_name": "UP甲", "play_count": 100, "like_count": 10, "publish_time": "2026-08-06"},
            {"title": "其他日期视频", "up_name": "UP乙", "play_count": 900, "like_count": 90, "publish_time": "2026-08-05"},
        ]
    ).to_csv(raw_path, index=False, encoding="utf-8-sig")
    app = create_app(
        {
            "TESTING": True,
            "DATABASE": tmp_path / "users.db",
            "VIDEO_DATA_PATH": raw_path,
            "CLEANED_DATA_PATH": tmp_path / "cleaned.csv",
            "KNOWLEDGE_BASE_PATH": tmp_path / "knowledge_base",
            "HDFS_WEB_URL": "",
        }
    )
    client = app.test_client()
    client.post("/login", data={"username": "admin", "password": "admin123"})
    return client


def test_home_statistics_use_only_selected_publish_date(tmp_path: Path):
    client = create_client(tmp_path)

    response = client.get("/?date=2026-08-06")

    page = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'id="video-total">1' in page
    assert 'id="play-total">100' in page
    assert "当前选择日期：2026-08-06" in page


def test_default_page_uses_yesterday_when_yesterday_exists(tmp_path: Path):
    client = create_client(tmp_path)

    response = client.get("/")

    page = response.get_data(as_text=True)
    assert 'id="video-total">1' in page
    assert "当前选择日期：2026-08-06" in page


def test_default_page_does_not_show_rows_from_other_dates(tmp_path: Path):
    client = create_client(tmp_path)
    raw_path = tmp_path / "videos.csv"
    pd.DataFrame(
        [
            {
                "title": "非昨日视频",
                "up_name": "UP乙",
                "play_count": 900,
                "like_count": 90,
                "publish_time": "2026-08-05",
            }
        ]
    ).to_csv(raw_path, index=False, encoding="utf-8-sig")

    with patch("app.resolve_business_date", return_value="2026-08-06"):
        response = client.get("/")

    page = response.get_data(as_text=True)
    assert 'id="video-total">0' in page
    assert "该日期暂无数据" in page


def test_invalid_date_returns_friendly_400_instead_of_500(tmp_path: Path):
    client = create_client(tmp_path)

    response = client.get("/?date=not-a-date")

    assert response.status_code == 400
    assert "日期格式无效" in response.get_data(as_text=True)


def test_date_with_no_data_displays_required_empty_message(tmp_path: Path):
    client = create_client(tmp_path)

    response = client.get("/?date=2020-01-01")

    assert response.status_code == 200
    assert "该日期暂无数据" in response.get_data(as_text=True)


@pytest.mark.parametrize("path", ["/", "/data", "/mining", "/spark", "/qa", "/api/spark/analysis"])
def test_all_date_pages_accept_date_query_parameter(tmp_path: Path, path: str):
    client = create_client(tmp_path)

    with patch("app.run_spark_analysis", return_value=EMPTY_SPARK):
        response = client.get(f"{path}?date=2026-08-06")

    assert response.status_code == 200
    if path != "/api/spark/analysis":
        page = response.get_data(as_text=True)
        assert 'type="date"' in page
        assert 'value="2026-08-06"' in page


def test_qa_page_shows_date_source_and_document_count(tmp_path: Path):
    client = create_client(tmp_path)

    response = client.get("/qa?date=2026-08-06")

    page = response.get_data(as_text=True)
    assert "当前选择日期：2026-08-06" in page
    assert "知识库文档数量：1" in page
    assert "当前数据来源：" in page


def test_spark_route_forwards_selected_date_to_analysis(tmp_path: Path):
    client = create_client(tmp_path)

    with patch("app.run_spark_analysis", return_value=EMPTY_SPARK) as analysis:
        response = client.get("/spark?date=2026-08-06")

    assert response.status_code == 200
    assert analysis.call_args.args[3] == "2026-08-06"


def test_post_form_preserves_selected_date(tmp_path: Path):
    client = create_client(tmp_path)

    response = client.post(
        "/qa",
        data={"date": "2026-08-06", "question": "当前有多少视频？"},
    )

    page = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'value="2026-08-06"' in page
    assert "1条视频" in page
