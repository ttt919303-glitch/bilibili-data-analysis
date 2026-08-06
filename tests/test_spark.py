from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

try:
    from app import create_app
except ImportError:
    create_app = None

try:
    import spark_analysis
except ImportError:
    spark_analysis = None


EMPTY_ANALYSIS = {
    "source": "本地清洗CSV",
    "total_count": 0,
    "up_video_count": [],
    "top_played": [],
    "up_avg_play": [],
    "publish_trend": [],
}


def create_client(tmp_path: Path):
    assert callable(create_app), "create_app 尚未实现"
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret-key",
            "DATABASE": tmp_path / "users.db",
            "VIDEO_DATA_PATH": tmp_path / "videos.csv",
            "CLEANED_DATA_PATH": tmp_path / "videos_cleaned.csv",
            "HDFS_CMD": "hdfs",
        }
    )
    return app.test_client()


def login(client, username: str, password: str) -> None:
    client.post("/login", data={"username": username, "password": password})


def test_regular_user_can_open_spark_page(tmp_path):
    client = create_client(tmp_path)
    login(client, "user", "user123")

    with patch("app.run_spark_analysis", return_value=EMPTY_ANALYSIS):
        response = client.get("/spark")

    assert response.status_code == 200
    assert "Spark 数据分析" in response.get_data(as_text=True)


def test_admin_can_open_spark_page(tmp_path):
    client = create_client(tmp_path)
    login(client, "admin", "admin123")

    with patch("app.run_spark_analysis", return_value=EMPTY_ANALYSIS):
        response = client.get("/spark")

    assert response.status_code == 200


def test_empty_data_spark_page_does_not_return_500(tmp_path):
    client = create_client(tmp_path)
    login(client, "user", "user123")

    with patch("app.run_spark_analysis", return_value=EMPTY_ANALYSIS):
        response = client.get("/spark")

    assert response.status_code == 200
    assert "暂无可分析数据，请先完成数据采集和清洗。" in response.get_data(as_text=True)


def test_unavailable_spark_page_does_not_return_500(tmp_path):
    assert spark_analysis is not None, "spark_analysis 尚未实现"
    client = create_client(tmp_path)
    login(client, "user", "user123")

    with patch("app.run_spark_analysis", side_effect=spark_analysis.SparkUnavailableError("环境不可用")):
        response = client.get("/spark")

    assert response.status_code == 200
    assert "Spark当前无法启动，请检查Java和PySpark环境。" in response.get_data(as_text=True)


def test_hdfs_unavailable_falls_back_to_cleaned_csv(tmp_path):
    assert spark_analysis is not None, "spark_analysis 尚未实现"
    cleaned_path = tmp_path / "videos_cleaned.csv"
    raw_path = tmp_path / "videos.csv"
    cleaned_path.write_text("title,up_name\n测试,UP主\n", encoding="utf-8")

    with patch("spark_analysis.check_hdfs_available", return_value=(False, "未启动")):
        source, path = spark_analysis.select_data_source(cleaned_path, raw_path, "hdfs")

    assert source == "本地清洗CSV"
    assert path == str(cleaned_path)


def test_cleaned_csv_is_preferred_over_raw_csv(tmp_path):
    assert spark_analysis is not None, "spark_analysis 尚未实现"
    cleaned_path = tmp_path / "videos_cleaned.csv"
    raw_path = tmp_path / "videos.csv"
    cleaned_path.write_text("title\n清洗数据\n", encoding="utf-8")
    raw_path.write_text("title\n原始数据\n", encoding="utf-8")

    with patch("spark_analysis.check_hdfs_available", return_value=(False, "未启动")):
        source, path = spark_analysis.select_data_source(cleaned_path, raw_path, "hdfs")

    assert source == "本地清洗CSV"
    assert path == str(cleaned_path)


def test_spark_api_returns_four_analysis_results(tmp_path):
    client = create_client(tmp_path)
    login(client, "user", "user123")
    analysis = {
        **EMPTY_ANALYSIS,
        "total_count": 2,
        "up_video_count": [{"up_name": "UP主甲", "video_count": 2}],
        "top_played": [{"title": "视频甲", "play_count": 12000}],
        "up_avg_play": [{"up_name": "UP主甲", "avg_play_count": 6000}],
        "publish_trend": [{"publish_month": "2026-07", "video_count": 2}],
    }

    with patch("app.run_spark_analysis", return_value=analysis):
        response = client.get("/api/spark/analysis")

    assert response.status_code == 200
    payload = response.get_json()
    assert set(("up_video_count", "top_played", "up_avg_play", "publish_trend")).issubset(payload)


def test_top_results_are_limited_to_ten_rows():
    assert spark_analysis is not None, "spark_analysis 尚未实现"
    assert spark_analysis.limit_chart_rows([{"title": str(index)} for index in range(12)]) == [
        {"title": str(index)} for index in range(10)
    ]


def test_publish_trend_rows_are_sorted_by_year_month():
    assert spark_analysis is not None, "spark_analysis 尚未实现"
    rows = [
        {"publish_month": "2026-01", "video_count": 2},
        {"publish_month": "2025-12", "video_count": 1},
    ]

    assert spark_analysis.sort_publish_trend(rows) == [
        {"publish_month": "2025-12", "video_count": 1},
        {"publish_month": "2026-01", "video_count": 2},
    ]
