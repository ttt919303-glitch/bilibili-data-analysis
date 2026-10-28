from datetime import datetime

import pytest

from services.hdfs_service import HdfsServiceError


HDFS_ERROR_MESSAGE = "连接 HDFS 失败，请检查 Hadoop/HDFS 是否启动。"


def login(client):
    with client.session_transaction() as session:
        session.update(user_id=1, username="student", role="user")


def test_yesterday_uses_local_calendar_date():
    from app import yesterday_string

    assert yesterday_string(datetime(2026, 8, 9, 0, 5)) == "2026-08-08"


def test_data_page_passes_explicit_snapshot_date(client, monkeypatch):
    login(client)
    requested = []
    monkeypatch.setattr("app.read_from_hdfs", lambda date: requested.append(date) or [])

    response = client.get("/data?date=2026-08-01")

    assert response.status_code == 200
    assert requested == ["2026-08-01"]
    assert "该日期暂无数据" in response.get_data(as_text=True)


def test_data_page_filters_title_and_up_name(client, monkeypatch):
    login(client)
    monkeypatch.setattr(
        "app.read_from_hdfs",
        lambda date: [
            {"title": "Spark 教程", "up_name": "甲", "bvid": "BV1"},
            {"title": "Hadoop", "up_name": "Spark老师", "bvid": "BV2"},
            {"title": "Python", "up_name": "乙", "bvid": "BV3"},
        ],
    )

    text = client.get("/data?date=2026-08-08&q=Spark").get_data(as_text=True)

    assert "BV1" in text and "BV2" in text
    assert "BV3" not in text


def test_authenticated_pages_use_classroom_shell(client, monkeypatch):
    login(client)
    monkeypatch.setattr("app.read_from_hdfs", lambda date: [])

    page = client.get("/data?date=2026-08-14").get_data(as_text=True)

    assert 'class="sidebar"' in page
    assert "基于大数据技术的B站视频数据分析与AI知识库" in page
    assert 'class="menu-link active"' in page


def test_login_page_does_not_render_business_sidebar(client):
    page = client.get("/login").get_data(as_text=True)

    assert 'class="sidebar"' not in page


def test_data_page_renders_responsive_wide_table_and_dataset_count(
    client, monkeypatch
):
    login(client)
    rows = [
        {
            "bvid": "BV1",
            "title": "很长的课程视频标题一",
            "video_url": "https://www.bilibili.com/video/BV1",
            "up_name": "甲",
            "publish_time": "2026-08-14 08:00:00",
            "view_count": 100,
            "like_count": 20,
            "coin_count": 10,
            "favorite_count": 8,
            "share_count": 3,
        },
        {
            "bvid": "BV2",
            "title": "课程视频标题二",
            "video_url": "https://www.bilibili.com/video/BV2",
            "up_name": "乙",
            "publish_time": "2026-08-14 09:00:00",
            "view_count": 200,
            "like_count": 30,
            "coin_count": 15,
            "favorite_count": 12,
            "share_count": 5,
        },
    ]
    monkeypatch.setattr("app.read_from_hdfs", lambda date: rows)

    page = client.get("/data?date=2026-08-14").get_data(as_text=True)

    assert 'class="table-responsive' in page
    assert 'title="很长的课程视频标题一"' in page
    assert "当前正式数据：2 条" in page


@pytest.mark.parametrize("path", ["/", "/data", "/mining"])
def test_core_page_renders_hdfs_connection_error(client, monkeypatch, caplog, path):
    login(client)
    technical_error = "HDFS read failed: WinError 10061 connection refused"

    def fail_read(date):
        raise HdfsServiceError(technical_error)

    monkeypatch.setattr("app.read_from_hdfs", fail_read)

    with caplog.at_level("ERROR"):
        response = client.get(path, query_string={"date": "2026-08-08"})

    page = response.get_data(as_text=True)
    assert response.status_code == 200
    assert HDFS_ERROR_MESSAGE in page
    assert "该日期暂无数据" not in page
    assert technical_error in caplog.text


def test_dashboard_does_not_present_placeholder_metrics_as_real_data(
    client, monkeypatch
):
    login(client)
    monkeypatch.setattr(
        "app.read_from_hdfs",
        lambda date: (_ for _ in ()).throw(HdfsServiceError("connection refused")),
    )

    page = client.get("/?date=2026-08-08").get_data(as_text=True)

    assert "视频数：--" in page
    assert "总播放：--" in page
    assert "总点赞：--" in page
    assert "总投币：--" in page


def test_data_page_keeps_an_empty_table_when_hdfs_read_fails(client, monkeypatch):
    login(client)
    monkeypatch.setattr(
        "app.read_from_hdfs",
        lambda date: (_ for _ in ()).throw(HdfsServiceError("connection refused")),
    )

    page = client.get("/data?date=2026-08-08").get_data(as_text=True)

    assert "<table>" in page
    assert "<tbody>" in page
    assert page.count("<tr>") == 1


@pytest.mark.parametrize("path", ["/", "/data", "/mining"])
def test_core_page_distinguishes_missing_date_file_from_hdfs_failure(
    client, monkeypatch, path
):
    login(client)
    monkeypatch.setattr("app.read_from_hdfs", lambda date: [])

    page = client.get(path, query_string={"date": "2026-08-08"}).get_data(
        as_text=True
    )

    assert "该日期暂无数据" in page
    assert HDFS_ERROR_MESSAGE not in page


def test_mining_does_not_run_algorithms_when_hdfs_read_fails(client, monkeypatch):
    login(client)
    monkeypatch.setattr(
        "app.read_from_hdfs",
        lambda date: (_ for _ in ()).throw(HdfsServiceError("connection refused")),
    )
    for algorithm in ("run_kmeans", "run_hot_prediction", "run_apriori"):
        monkeypatch.setattr(
            f"app.{algorithm}",
            lambda videos, name=algorithm: pytest.fail(
                f"{name} must not run after an HDFS read failure"
            ),
        )

    response = client.get("/mining?date=2026-08-08")

    assert response.status_code == 200
    assert HDFS_ERROR_MESSAGE in response.get_data(as_text=True)
