from __future__ import annotations

from io import BytesIO
from pathlib import Path

try:
    from app import create_app
except ImportError:
    create_app = None

try:
    from data_utils import parse_number
except ImportError:
    parse_number = None


def create_client(tmp_path: Path):
    assert callable(create_app), "create_app 尚未实现"
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret-key",
            "DATABASE": tmp_path / "users.db",
            "VIDEO_DATA_PATH": tmp_path / "videos.csv",
        }
    )
    return app.test_client(), tmp_path / "videos.csv"


def login(client, username: str, password: str) -> None:
    client.post("/login", data={"username": username, "password": password})


def test_parse_number_converts_ten_thousands_to_integers():
    assert callable(parse_number), "parse_number 尚未实现"
    assert parse_number("1.2万") == 12000
    assert parse_number("5万") == 50000
    assert parse_number("-") == 0


def test_regular_user_cannot_open_data_management(tmp_path):
    client, _ = create_client(tmp_path)
    login(client, "user", "user123")

    response = client.get("/data")

    assert response.status_code == 403
    assert "无权访问" in response.get_data(as_text=True)


def test_admin_can_open_data_management(tmp_path):
    client, _ = create_client(tmp_path)
    login(client, "admin", "admin123")

    response = client.get("/data")

    assert response.status_code == 200
    assert "数据管理" in response.get_data(as_text=True)


def test_admin_can_import_csv_and_view_recent_videos(tmp_path):
    client, data_path = create_client(tmp_path)
    login(client, "admin", "admin123")
    csv_content = "标题,UP主,播放量,点赞\n视频甲,UP主甲,1.2万,300\n视频乙,UP主乙,5000,120\n"

    response = client.post(
        "/data",
        data={"file": (BytesIO(csv_content.encode("utf-8")), "videos.csv")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )

    page = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "本次成功导入 2 条视频数据，当前数据集共有 2 条数据。" in page
    assert "视频甲" in page
    assert ">nan<" not in page
    assert data_path.exists()


def test_import_missing_required_field_shows_friendly_message(tmp_path):
    client, _ = create_client(tmp_path)
    login(client, "admin", "admin123")
    csv_content = "title,up_name,play_count\n缺少点赞字段,UP主甲,100\n"

    response = client.post(
        "/data",
        data={"file": (BytesIO(csv_content.encode("utf-8")), "missing.csv")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )

    assert "CSV缺少必要字段：like_count" in response.get_data(as_text=True)


def test_home_reads_real_statistics_from_videos_csv(tmp_path):
    client, data_path = create_client(tmp_path)
    data_path.write_text(
        "title,video_url,up_name,play_count,like_count,coin_count,favorite_count,share_count,comment_count,publish_time,crawl_date\n"
        "视频甲,,UP主甲,12000,300,0,0,0,0,,2026-07-30\n"
        "视频乙,,UP主甲,5000,120,0,0,0,0,,2026-07-30\n",
        encoding="utf-8",
    )
    login(client, "user", "user123")

    response = client.get("/")

    page = response.get_data(as_text=True)
    assert 'id="video-total">2' in page
    assert 'id="up-total">1' in page
    assert 'id="play-total">17,000' in page
    assert 'id="like-total">420' in page


def test_data_table_shows_collection_date_separately_from_publish_time(tmp_path):
    client, data_path = create_client(tmp_path)
    data_path.write_text(
        "title,video_url,up_name,play_count,like_count,coin_count,favorite_count,share_count,comment_count,publish_time,crawl_date\n"
        "视频甲,https://www.bilibili.com/video/BV1testA,UP甲,100,20,3,4,5,6,2024-01-02,2026-08-04\n",
        encoding="utf-8",
    )
    login(client, "admin", "admin123")

    response = client.get("/data")

    page = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "采集日期" in page
    assert "2026-08-04" in page
    assert "2024-01-02" in page
