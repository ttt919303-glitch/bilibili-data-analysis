from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from urllib.error import HTTPError

try:
    from app import create_app
except ImportError:
    create_app = None

try:
    from hdfs_utils import check_hdfs_available, check_hdfs_file, upload_cleaned_to_hdfs
except ImportError:
    check_hdfs_available = None
    check_hdfs_file = None
    upload_cleaned_to_hdfs = None


def completed_process(returncode: int = 0, stdout: str = "", stderr: str = ""):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


class WebHdfsResponse:
    def __init__(self, body: str = "", status: int = 200, headers: dict[str, str] | None = None):
        self.status = status
        self._body = body.encode("utf-8")
        self.headers = headers or {}

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


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
            "HDFS_CMD": "hdfs",
            "HDFS_WEB_URL": "",
        }
    )
    return app.test_client()


def login(client, username: str, password: str) -> None:
    client.post("/login", data={"username": username, "password": password})


def test_upload_does_not_run_hdfs_when_cleaned_file_is_missing(tmp_path):
    assert callable(upload_cleaned_to_hdfs), "upload_cleaned_to_hdfs 尚未实现"

    with patch("hdfs_utils.subprocess.run") as run:
        success, message = upload_cleaned_to_hdfs(tmp_path / "videos_cleaned.csv", "hdfs")

    assert not success
    assert message == "暂无清洗后的数据，请先执行数据清洗。"
    run.assert_not_called()


def test_missing_hdfs_command_returns_friendly_error():
    assert callable(check_hdfs_available), "check_hdfs_available 尚未实现"

    with patch("hdfs_utils.subprocess.run", side_effect=FileNotFoundError):
        available, message = check_hdfs_available("hdfs")

    assert not available
    assert "未找到 hdfs 命令" in message


def test_webhdfs_check_reads_root_listing_when_configured():
    assert callable(check_hdfs_available), "check_hdfs_available 尚未实现"

    with patch(
        "hdfs_utils.urlopen",
        return_value=WebHdfsResponse('{"FileStatuses":{"FileStatus":[]}}'),
    ) as open_url:
        available, message = check_hdfs_available(
            "hdfs", "http://192.168.8.140:50070", "tan"
        )

    assert available
    assert message == "HDFS服务可用（WebHDFS）。"
    request = open_url.call_args.args[0]
    assert request.full_url == (
        "http://192.168.8.140:50070/webhdfs/v1/?op=LISTSTATUS&user.name=tan"
    )
    assert request.method == "GET"


def test_webhdfs_create_rewrites_unresolvable_datanode_host(tmp_path):
    assert callable(upload_cleaned_to_hdfs), "upload_cleaned_to_hdfs 尚未实现"
    cleaned_path = tmp_path / "videos_cleaned.csv"
    cleaned_path.write_text("title,up_name,play_count,like_count\n视频甲,UP主甲,1,1\n", encoding="utf-8")

    redirect = HTTPError(
        "http://192.168.8.140:50070/webhdfs/v1/bilibili/videos_cleaned.csv",
        307,
        "temporary redirect",
        {"Location": "http://tan:50075/webhdfs/v1/bilibili/videos_cleaned.csv?op=CREATE"},
        None,
    )

    class FakeOpener:
        def __init__(self):
            self.requests = []

        def open(self, request, timeout):
            self.requests.append(request)
            if len(self.requests) == 1:
                raise redirect
            return WebHdfsResponse(status=201)

    fake_opener = FakeOpener()
    with patch(
        "hdfs_utils.urlopen",
        return_value=WebHdfsResponse('{"FileStatuses":{"FileStatus":[]}}'),
    ), patch("hdfs_utils.build_opener", return_value=fake_opener):
        success, message = upload_cleaned_to_hdfs(
            cleaned_path, "hdfs", "http://192.168.8.140:50070", "tan"
        )

    assert success
    assert message == "清洗数据已成功上传到 HDFS：/bilibili/videos_cleaned.csv"
    assert len(fake_opener.requests) == 2
    assert fake_opener.requests[1].full_url.startswith("http://192.168.8.140:50075/")


def test_upload_runs_mkdir_and_put_after_hdfs_is_available(tmp_path):
    assert callable(upload_cleaned_to_hdfs), "upload_cleaned_to_hdfs 尚未实现"
    cleaned_path = tmp_path / "videos_cleaned.csv"
    cleaned_path.write_text("title,up_name,play_count,like_count\n视频甲,UP主甲,1,1\n", encoding="utf-8")

    with patch(
        "hdfs_utils.subprocess.run",
        side_effect=[completed_process(), completed_process(), completed_process()],
    ) as run:
        success, message = upload_cleaned_to_hdfs(cleaned_path, "hdfs")

    assert success
    assert message == "清洗数据已成功上传到 HDFS：/bilibili/videos_cleaned.csv"
    assert run.call_count == 3
    assert run.call_args_list[1].args[0] == ["hdfs", "dfs", "-mkdir", "-p", "/bilibili"]
    assert run.call_args_list[2].args[0][-2:] == [str(cleaned_path), "/bilibili/videos_cleaned.csv"]


def test_hdfs_file_check_recognizes_existing_file():
    assert callable(check_hdfs_file), "check_hdfs_file 尚未实现"

    with patch("hdfs_utils.subprocess.run", return_value=completed_process()) as run:
        exists, message = check_hdfs_file("hdfs")

    assert exists
    assert message == "HDFS文件已上传。"
    assert run.call_args.args[0] == ["hdfs", "dfs", "-test", "-e", "/bilibili/videos_cleaned.csv"]


def test_hdfs_unavailable_does_not_break_data_page(tmp_path):
    client = create_client(tmp_path)
    login(client, "admin", "admin123")

    with patch("app.check_hdfs_available", return_value=(False, "未找到 hdfs 命令")):
        response = client.get("/data")

    assert response.status_code == 200
    assert "HDFS状态：未启动" in response.get_data(as_text=True)


def test_regular_user_cannot_upload_to_hdfs(tmp_path):
    client = create_client(tmp_path)
    login(client, "user", "user123")

    response = client.post("/data/hdfs/upload")

    assert response.status_code == 403


def test_admin_upload_route_passes_webhdfs_configuration(tmp_path):
    cleaned_path = tmp_path / "videos_cleaned.csv"
    cleaned_path.write_text("title,up_name,play_count,like_count\n视频甲,UP主甲,1,1\n", encoding="utf-8")
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret-key",
            "DATABASE": tmp_path / "users.db",
            "VIDEO_DATA_PATH": tmp_path / "videos.csv",
            "CLEANED_DATA_PATH": cleaned_path,
            "CLEANING_SUMMARY_PATH": tmp_path / "cleaning_summary.json",
            "HDFS_CMD": "hdfs",
            "HDFS_WEB_URL": "http://192.168.8.140:50070",
            "HDFS_WEB_USER": "tan",
        }
    )
    client = app.test_client()
    login(client, "admin", "admin123")

    with patch("app.upload_cleaned_to_hdfs", return_value=(True, "ok")) as upload:
        response = client.post("/data/hdfs/upload")

    assert response.status_code == 302
    assert upload.call_args.args == (
        cleaned_path,
        "hdfs",
        "http://192.168.8.140:50070",
        "tan",
    )


def test_admin_can_see_hdfs_controls(tmp_path):
    client = create_client(tmp_path)
    login(client, "admin", "admin123")

    with patch("app.check_hdfs_available", return_value=(False, "未找到 hdfs 命令")):
        response = client.get("/data")

    assert response.status_code == 200
    assert "HDFS 数据存储" in response.get_data(as_text=True)
    assert "上传清洗数据到 HDFS" in response.get_data(as_text=True)
