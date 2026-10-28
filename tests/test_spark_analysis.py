import os
import shutil

import pytest

pytest.importorskip("pyspark")
from pyspark.sql import SparkSession


@pytest.fixture(scope="module")
def spark():
    java_home = os.environ.get("JAVA_HOME")
    java_in_java_home = (
        os.path.isfile(os.path.join(java_home, "bin", "java.exe"))
        if java_home
        else False
    )
    if shutil.which("java") is None and not java_in_java_home:
        pytest.skip("Java is required for the local Spark integration test")
    session = SparkSession.builder.master("local[1]").appName("course-test").getOrCreate()
    yield session
    session.stop()


def test_four_spark_analyses_have_expected_order(spark):
    from analysis.spark_analysis import analyze_dataframe

    rows = [
        ("A", "v1", 100, 10, 2, 3, 4),
        ("A", "v2", 300, 30, 4, 5, 6),
        ("B", "v3", 200, 20, 9, 9, 9),
    ]
    columns = [
        "up_name",
        "title",
        "view_count",
        "like_count",
        "coin_count",
        "favorite_count",
        "share_count",
    ]

    result = analyze_dataframe(spark.createDataFrame(rows, columns))

    assert set(result) == {"up_video_count", "top_views", "top_likes", "top_interactions"}
    assert result["up_video_count"][0] == {"name": "A", "value": 2}
    assert result["top_views"][0]["name"] == "v2"
    assert result["top_likes"][0]["name"] == "v2"
    assert result["top_interactions"][0]["name"] == "v3"


def test_visualization_page_renders_four_charts_for_selected_date(client, monkeypatch):
    requested_dates = []
    analysis = {
        "up_video_count": [{"name": "A", "value": 2}],
        "top_views": [{"name": "v2", "value": 300}],
        "top_likes": [{"name": "v2", "value": 30}],
        "top_interactions": [{"name": "v3", "value": 47}],
    }

    monkeypatch.setattr(
        "app.run_spark_analysis",
        lambda selected_date: requested_dates.append(selected_date) or analysis,
        raising=False,
    )
    with client.session_transaction() as session:
        session.update(user_id=1, username="student", role="user")

    response = client.get("/visualization?date=2026-08-01")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert requested_dates == ["2026-08-01"]
    assert 'value="2026-08-01"' in html
    for container_id in (
        "chart-up-count",
        "chart-top-views",
        "chart-top-likes",
        "chart-interactions",
    ):
        assert f'id="{container_id}"' in html
