import json
import logging
import threading

import pytest

from services import hdfs_service


class FakeHdfsClient:
    def __init__(self, files=None):
        self.files = dict(files or {})

    def status(self, path, strict=False):
        return {"type": "FILE"} if path in self.files else None

    def read(self, path, encoding="utf-8"):
        class Reader:
            def __enter__(inner):
                return inner

            def __exit__(inner, *args):
                return False

            def __iter__(inner):
                return iter(self.files[path].splitlines(True))

            def read(inner):
                return self.files[path]

        return Reader()

    def write(self, path, data, encoding="utf-8", overwrite=False):
        self.files[path] = data

    def rename(self, source, destination):
        self.files[destination] = self.files.pop(source)

    def delete(self, path, recursive=False):
        return self.files.pop(path, None) is not None


def row(bvid, title):
    return {
        "bvid": bvid, "title": title, "video_url": "u", "up_name": "UP",
        "publish_time": "2024-01-01 00:00:00", "view_count": 1,
        "like_count": 2, "coin_count": 3, "favorite_count": 4,
        "share_count": 5, "collect_date": "2026-08-08",
    }


def test_save_merges_same_date_and_keeps_latest_bvid(monkeypatch):
    path = hdfs_service.video_path("2026-08-08")
    client = FakeHdfsClient({path: json.dumps(row("BV1", "old"), ensure_ascii=False) + "\n"})
    monkeypatch.setattr(hdfs_service, "_client", lambda: client)

    count = hdfs_service.save_to_hdfs([row("BV1", "new"), row("BV2", "B")], "2026-08-08")

    saved = [json.loads(line) for line in client.files[path].splitlines()]
    assert count == 2
    assert [item["bvid"] for item in saved] == ["BV1", "BV2"]
    assert saved[0]["title"] == "new"
    assert all(item["collect_date"] == "2026-08-08" for item in saved)


def test_raw_path_is_separate_from_formal_path():
    date = "2026-08-08"

    assert hdfs_service.raw_video_path(date).endswith("/videos_raw.jsonl")
    assert hdfs_service.raw_video_path(date) != hdfs_service.video_path(date)


def test_bilibili_proxy_does_not_change_hdfs_client_configuration(app, monkeypatch):
    captured = {}

    class Client:
        def __init__(self, url, user):
            captured.update(url=url, user=user)

    monkeypatch.setenv("BILIBILI_PROXY", "http://127.0.0.1:7890")
    monkeypatch.setattr(hdfs_service, "InsecureClient", Client)
    app.config.update(HDFS_WEB_URL="http://127.0.0.1:9870", HDFS_USER="hadoop")

    with app.app_context():
        hdfs_service._client()

    assert captured == {"url": "http://127.0.0.1:9870", "user": "hadoop"}


def test_raw_save_merges_by_bvid_and_does_not_change_formal_file(monkeypatch):
    date = "2026-08-08"
    raw_path = hdfs_service.raw_video_path(date)
    formal_path = hdfs_service.video_path(date)
    formal_content = json.dumps(row("BVCLEAN", "cleaned"), ensure_ascii=False) + "\n"
    client = FakeHdfsClient(
        {
            formal_path: formal_content,
            raw_path: json.dumps(row("BV1", "old"), ensure_ascii=False) + "\n",
        }
    )
    monkeypatch.setattr(hdfs_service, "_client", lambda: client)

    count = hdfs_service.save_raw_to_hdfs(
        [row("BV1", "new"), row("BV2", "second")], date
    )

    saved = [json.loads(line) for line in client.files[raw_path].splitlines()]
    assert count == 1
    assert [(item["bvid"], item["title"]) for item in saved] == [
        ("BV1", "new"),
        ("BV2", "second"),
    ]
    assert client.files[formal_path] == formal_content
    assert hdfs_service.read_raw_from_hdfs(date) == saved


def test_read_raw_preserves_unicode_line_separators_inside_json_strings(monkeypatch):
    date = "2026-08-08"
    path = hdfs_service.raw_video_path(date)
    unicode_title = "第一行\u2028第二行\u2029第三行"
    content = (
        json.dumps(row("BV1", unicode_title), ensure_ascii=False)
        + "\n"
        + json.dumps(row("BV2", "ordinary"), ensure_ascii=False)
        + "\n"
    )
    monkeypatch.setattr(hdfs_service, "_client", lambda: FakeHdfsClient({path: content}))

    records = hdfs_service.read_raw_from_hdfs(date)

    assert [record["bvid"] for record in records] == ["BV1", "BV2"]
    assert records[0]["title"] == unicode_title


def test_raw_save_reports_zero_when_another_task_already_added_the_same_bvid(
    monkeypatch,
):
    date = "2026-08-08"
    raw_path = hdfs_service.raw_video_path(date)
    client = FakeHdfsClient(
        {raw_path: json.dumps(row("BV1", "other task"), ensure_ascii=False) + "\n"}
    )
    monkeypatch.setattr(hdfs_service, "_client", lambda: client)

    added_count = hdfs_service.save_raw_to_hdfs([row("BV1", "this task")], date)

    assert added_count == 0
    saved = [json.loads(line) for line in client.files[raw_path].splitlines()]
    assert saved == [row("BV1", "this task")]


def test_each_date_uses_process_local_threading_lock():
    first = hdfs_service._lock_for_date("2026-08-08")
    second = hdfs_service._lock_for_date("2026-08-08")
    other = hdfs_service._lock_for_date("2026-08-09")

    assert isinstance(first, type(threading.Lock()))
    assert first is second
    assert first is not other


def test_read_returns_empty_list_when_date_file_is_missing(monkeypatch):
    monkeypatch.setattr(hdfs_service, "_client", lambda: FakeHdfsClient())

    assert hdfs_service.read_from_hdfs("2026-08-08") == []


def test_save_rejects_empty_records():
    with pytest.raises(ValueError, match="empty"):
        hdfs_service.save_to_hdfs([], "2026-08-08")


def test_read_wraps_invalid_json_with_date_and_hdfs_path(monkeypatch):
    path = hdfs_service.video_path("2026-08-08")
    monkeypatch.setattr(hdfs_service, "_client", lambda: FakeHdfsClient({path: "not-json\n"}))

    with pytest.raises(hdfs_service.HdfsServiceError) as exc_info:
        hdfs_service.read_from_hdfs("2026-08-08")

    assert "2026-08-08" in str(exc_info.value)
    assert path in str(exc_info.value)


def test_save_restores_existing_file_when_temp_exchange_fails(monkeypatch):
    path = hdfs_service.video_path("2026-08-08")
    original = json.dumps(row("BV1", "old"), ensure_ascii=False) + "\n"

    class FailingRenameHdfsClient(FakeHdfsClient):
        def rename(self, source, destination):
            if source.startswith(path + ".tmp-"):
                raise OSError("temporary rename failed")
            super().rename(source, destination)

    client = FailingRenameHdfsClient({path: original})
    monkeypatch.setattr(hdfs_service, "_client", lambda: client)

    with pytest.raises(hdfs_service.HdfsServiceError) as exc_info:
        hdfs_service.save_to_hdfs([row("BV1", "new")], "2026-08-08")

    assert "2026-08-08" in str(exc_info.value)
    assert path in str(exc_info.value)
    assert client.files[path] == original
    assert not any(candidate.startswith(path + ".bak") for candidate in client.files)


def test_post_commit_backup_cleanup_failure_keeps_successful_save(
    monkeypatch, caplog
):
    path = hdfs_service.video_path("2026-08-08")
    original = json.dumps(row("BV1", "old"), ensure_ascii=False) + "\n"

    class CleanupFailingHdfsClient(FakeHdfsClient):
        def delete(self, backup_path, recursive=False):
            if backup_path.startswith(path + ".bak"):
                raise OSError("backup cleanup unavailable")
            return super().delete(backup_path, recursive=recursive)

    client = CleanupFailingHdfsClient({path: original})
    monkeypatch.setattr(hdfs_service, "_client", lambda: client)

    with caplog.at_level(logging.ERROR, logger=hdfs_service.LOGGER.name):
        count = hdfs_service.save_to_hdfs(
            [row("BV1", "new"), row("BV2", "B")], "2026-08-08"
        )

    saved = [json.loads(line) for line in client.files[path].splitlines()]
    assert count == 2
    assert [item["bvid"] for item in saved] == ["BV1", "BV2"]
    assert saved[0]["title"] == "new"
    assert "backup cleanup failed after commit" in caplog.text


def test_stale_backup_name_does_not_block_later_save(monkeypatch):
    path = hdfs_service.video_path("2026-08-08")
    stale_backup_path = path + ".bak"
    original = json.dumps(row("BV1", "old"), ensure_ascii=False) + "\n"

    class CollisionCheckingHdfsClient(FakeHdfsClient):
        def rename(self, source, destination):
            if destination in self.files:
                raise FileExistsError(destination)
            super().rename(source, destination)

    client = CollisionCheckingHdfsClient(
        {path: original, stale_backup_path: "stale backup"}
    )
    monkeypatch.setattr(hdfs_service, "_client", lambda: client)

    count = hdfs_service.save_to_hdfs([row("BV1", "new")], "2026-08-08")

    assert count == 1
    assert json.loads(client.files[path])["title"] == "new"
    assert client.files[stale_backup_path] == "stale backup"


def test_same_date_read_waits_for_save_exchange(monkeypatch):
    date = "2026-08-08"
    path = hdfs_service.video_path(date)
    original = json.dumps(row("BV1", "old"), ensure_ascii=False) + "\n"

    class PausingRenameHdfsClient(FakeHdfsClient):
        def __init__(self, files):
            super().__init__(files)
            self.backup_renamed = threading.Event()
            self.resume_exchange = threading.Event()

        def rename(self, source, destination):
            super().rename(source, destination)
            if source == path and destination.startswith(path + ".bak-"):
                self.backup_renamed.set()
                assert self.resume_exchange.wait(timeout=1)

    client = PausingRenameHdfsClient({path: original})
    monkeypatch.setattr(hdfs_service, "_client", lambda: client)
    writer_errors = []
    reader_errors = []
    read_result = []
    reader_started = threading.Event()
    reader_finished = threading.Event()

    def save():
        try:
            hdfs_service.save_to_hdfs([row("BV1", "new")], date)
        except Exception as exc:
            writer_errors.append(exc)

    def read():
        reader_started.set()
        try:
            read_result.extend(hdfs_service.read_from_hdfs(date))
        except Exception as exc:
            reader_errors.append(exc)
        finally:
            reader_finished.set()

    writer = threading.Thread(target=save)
    reader = threading.Thread(target=read)
    writer.start()
    assert client.backup_renamed.wait(timeout=1)
    reader.start()
    assert reader_started.wait(timeout=1)

    try:
        assert not reader_finished.wait(timeout=0.1)
    finally:
        client.resume_exchange.set()
        writer.join(timeout=1)
        reader.join(timeout=1)

    assert not writer.is_alive()
    assert not reader.is_alive()
    assert writer_errors == []
    assert reader_errors == []
    assert read_result == [row("BV1", "new")]
