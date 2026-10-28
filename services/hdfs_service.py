import json
import logging
import threading
import uuid
from typing import Dict, List

from flask import current_app
from hdfs import InsecureClient


BASE_PATH = "/bigdata_course/bilibili"
LOGGER = logging.getLogger(__name__)
_date_locks = {}
_date_locks_guard = threading.Lock()


class HdfsServiceError(RuntimeError):
    pass


def _lock_for_date(date: str) -> threading.Lock:
    with _date_locks_guard:
        return _date_locks.setdefault(date, threading.Lock())


def video_path(date: str) -> str:
    return f"{BASE_PATH}/date={date}/videos.jsonl"


def raw_video_path(date: str) -> str:
    return f"{BASE_PATH}/date={date}/videos_raw.jsonl"


def _client() -> InsecureClient:
    return InsecureClient(
        current_app.config["HDFS_WEB_URL"],
        user=current_app.config["HDFS_USER"],
    )


def _hdfs_error(operation: str, date: str, path: str, exc: Exception) -> HdfsServiceError:
    message = f"HDFS {operation} failed: date={date}, path={path}, error={exc}"
    LOGGER.exception(message)
    return HdfsServiceError(message)


def _read_records(client: InsecureClient, date: str, path: str) -> List[Dict]:
    try:
        if client.status(path, strict=False) is None:
            return []
        with client.read(path, encoding="utf-8") as reader:
            content = reader.read()
        return [json.loads(line) for line in content.split("\n") if line.strip()]
    except Exception as exc:
        raise _hdfs_error("read", date, path, exc) from exc


def _read_from_path(date: str, path: str) -> List[Dict]:
    with _lock_for_date(date):
        try:
            client = _client()
        except Exception as exc:
            raise _hdfs_error("connect", date, path, exc) from exc
        return _read_records(client, date, path)


def read_from_hdfs(date: str) -> List[Dict]:
    return _read_from_path(date, video_path(date))


def read_raw_from_hdfs(date: str) -> List[Dict]:
    return _read_from_path(date, raw_video_path(date))


def _save_to_path(
    data: List[Dict], date: str, path: str, count_only_new_bvids: bool = False
) -> int:
    if not data:
        raise ValueError("Cannot save empty video data")

    exchange_id = uuid.uuid4().hex
    temporary_path = f"{path}.tmp-{exchange_id}"
    backup_path = f"{path}.bak-{exchange_id}"
    incoming = {record["bvid"]: {**record, "collect_date": date} for record in data}

    with _lock_for_date(date):
        try:
            client = _client()
        except Exception as exc:
            raise _hdfs_error("connect", date, path, exc) from exc

        existing = _read_records(client, date, path)
        merged = {record["bvid"]: record for record in existing}
        new_bvid_count = len(set(incoming) - set(merged))
        merged.update(incoming)
        content = "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in merged.values())

        try:
            client.write(temporary_path, content, encoding="utf-8", overwrite=True)
        except Exception as exc:
            raise _hdfs_error("temporary write", date, path, exc) from exc

        target_exists = bool(existing) or _target_exists(client, date, path)
        if target_exists:
            try:
                client.rename(path, backup_path)
            except Exception as exc:
                raise _hdfs_error("backup", date, path, exc) from exc

        try:
            client.rename(temporary_path, path)
        except Exception as exc:
            if target_exists:
                try:
                    client.rename(backup_path, path)
                except Exception as recovery_exc:
                    raise _hdfs_error("exchange recovery", date, path, recovery_exc) from recovery_exc
            raise _hdfs_error("exchange", date, path, exc) from exc

        if target_exists:
            try:
                client.delete(backup_path, recursive=False)
            except Exception:
                LOGGER.exception(
                    "HDFS backup cleanup failed after commit: date=%s, path=%s, backup_path=%s",
                    date,
                    path,
                    backup_path,
                )

    return new_bvid_count if count_only_new_bvids else len(incoming)


def save_to_hdfs(data: List[Dict], date: str) -> int:
    return _save_to_path(data, date, video_path(date))


def save_raw_to_hdfs(data: List[Dict], date: str) -> int:
    return _save_to_path(data, date, raw_video_path(date), count_only_new_bvids=True)


def _target_exists(client: InsecureClient, date: str, path: str) -> bool:
    try:
        return client.status(path, strict=False) is not None
    except Exception as exc:
        raise _hdfs_error("status", date, path, exc) from exc
