from __future__ import annotations

import subprocess
from io import StringIO
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

import pandas as pd

from data_utils import load_video_data

HDFS_DATA_PATH = "/bilibili/videos_cleaned.csv"
DEFAULT_WEBHDFS_USER = "tan"
WEBHDFS_TIMEOUT_SECONDS = 15


class DataSourceUnavailableError(RuntimeError):
    """Raised when neither HDFS nor an allowed local CSV source can be read."""


def _run_hdfs(command: list[str]) -> tuple[bool, str, str]:
    """安全执行 hdfs dfs 命令，不使用 shell 拼接。"""
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return False, "", "未找到 hdfs 命令，请检查 Hadoop 环境配置。"
    except OSError as error:
        return False, "", str(error)

    if result.returncode != 0:
        return False, result.stdout, result.stderr.strip() or "HDFS命令执行失败。"
    return True, result.stdout, ""


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def _webhdfs_url(
    web_url: str,
    path: str,
    operation: str,
    user: str,
    **parameters: str,
) -> str:
    base_url = web_url.rstrip("/") + "/webhdfs/v1"
    encoded_path = quote(path.lstrip("/"), safe="/")
    path_url = f"{base_url}/{encoded_path}" if encoded_path else f"{base_url}/"
    query = {"op": operation, "user.name": user, **parameters}
    return f"{path_url}?{urlencode(query)}"


def _response_text(response) -> str:
    return response.read().decode("utf-8", errors="replace")


def _request_url(
    url: str,
    method: str,
    data: bytes | None = None,
    opener=None,
) -> tuple[bool, str, str | None, str]:
    request = Request(url, data=data, method=method)
    try:
        if opener is None:
            response = urlopen(request, timeout=WEBHDFS_TIMEOUT_SECONDS)
        else:
            response = opener.open(request, timeout=WEBHDFS_TIMEOUT_SECONDS)
        with response:
            location = response.headers.get("Location")
            return True, _response_text(response), location, ""
    except HTTPError as error:
        location = error.headers.get("Location") if error.headers else None
        body = error.read().decode("utf-8", errors="replace")
        if location and error.code in {301, 302, 303, 307, 308}:
            return True, body, location, ""
        detail = body.strip() or error.reason or "HTTP请求失败"
        return False, body, None, f"WebHDFS HTTP {error.code}: {detail}"
    except (URLError, OSError) as error:
        return False, "", None, f"WebHDFS连接失败：{error}"


def _rewrite_datanode_location(location: str, web_url: str) -> str:
    location_parts = urlsplit(location)
    web_parts = urlsplit(web_url)
    datanode_host = web_parts.hostname
    if not datanode_host:
        return location
    datanode_port = location_parts.port or 50075
    netloc = f"{datanode_host}:{datanode_port}"
    return urlunsplit(
        (
            location_parts.scheme or web_parts.scheme,
            netloc,
            location_parts.path,
            location_parts.query,
            location_parts.fragment,
        )
    )


def _webhdfs_request(
    web_url: str,
    path: str,
    operation: str,
    user: str,
    method: str,
    data: bytes | None = None,
    opener=None,
    **parameters: str,
) -> tuple[bool, str, str | None, str]:
    return _request_url(
        _webhdfs_url(web_url, path, operation, user, **parameters),
        method,
        data=data,
        opener=opener,
    )


def check_hdfs_available(
    hdfs_cmd: str,
    hdfs_url: str | None = None,
    hdfs_user: str = DEFAULT_WEBHDFS_USER,
) -> tuple[bool, str]:
    """检查配置的 HDFS 命令或 WebHDFS 根目录是否可用。"""
    if hdfs_url:
        success, _body, _location, error = _webhdfs_request(
            hdfs_url, "/", "LISTSTATUS", hdfs_user, "GET"
        )
        if success:
            return True, "HDFS服务可用（WebHDFS）。"
        return False, error

    success, _stdout, error = _run_hdfs([hdfs_cmd, "dfs", "-ls", "/"])
    if success:
        return True, "HDFS服务可用。"
    return False, error


def _upload_with_webhdfs(
    cleaned_path: Path,
    hdfs_url: str,
    hdfs_user: str,
) -> tuple[bool, str]:
    opener = build_opener(_NoRedirectHandler())
    created, _body, _location, error = _webhdfs_request(
        hdfs_url, "/bilibili", "MKDIRS", hdfs_user, "PUT"
    )
    if not created:
        return False, f"创建 HDFS 目录失败：{error}"

    opened, _body, location, error = _webhdfs_request(
        hdfs_url,
        HDFS_DATA_PATH,
        "CREATE",
        hdfs_user,
        "PUT",
        data=None,
        opener=opener,
        overwrite="true",
    )
    if not opened or not location:
        return False, f"上传 HDFS 失败：{error or 'WebHDFS 未返回 DataNode 地址。'}"

    uploaded, _body, _location, error = _request_url(
        _rewrite_datanode_location(location, hdfs_url),
        "PUT",
        data=cleaned_path.read_bytes(),
        opener=opener,
    )
    if not uploaded:
        return False, f"上传 HDFS 失败：{error}"
    return True, f"清洗数据已成功上传到 HDFS：{HDFS_DATA_PATH}"


def upload_cleaned_to_hdfs(
    cleaned_path: Path,
    hdfs_cmd: str,
    hdfs_url: str | None = None,
    hdfs_user: str = DEFAULT_WEBHDFS_USER,
) -> tuple[bool, str]:
    """将清洗 CSV 上传至固定 HDFS 目标路径。"""
    if not cleaned_path.exists() or cleaned_path.stat().st_size == 0:
        return False, "暂无清洗后的数据，请先执行数据清洗。"

    available, _message = check_hdfs_available(hdfs_cmd, hdfs_url, hdfs_user)
    if not available:
        return False, "HDFS服务当前不可用，请检查Hadoop是否启动。"

    if hdfs_url:
        return _upload_with_webhdfs(cleaned_path, hdfs_url, hdfs_user)

    created, _stdout, error = _run_hdfs([hdfs_cmd, "dfs", "-mkdir", "-p", "/bilibili"])
    if not created:
        return False, f"创建 HDFS 目录失败：{error}"

    uploaded, _stdout, error = _run_hdfs(
        [hdfs_cmd, "dfs", "-put", "-f", str(cleaned_path), HDFS_DATA_PATH]
    )
    if not uploaded:
        return False, f"上传 HDFS 失败：{error}"
    return True, f"清洗数据已成功上传到 HDFS：{HDFS_DATA_PATH}"


def check_hdfs_file(
    hdfs_cmd: str,
    hdfs_url: str | None = None,
    hdfs_user: str = DEFAULT_WEBHDFS_USER,
) -> tuple[bool, str]:
    """检查固定 HDFS 清洗数据文件是否存在。"""
    if hdfs_url:
        exists, _body, _location, error = _webhdfs_request(
            hdfs_url, HDFS_DATA_PATH, "GETFILESTATUS", hdfs_user, "GET"
        )
        if exists:
            return True, "HDFS文件已上传。"
        return False, "HDFS中暂未找到 videos_cleaned.csv" if "HTTP 404" in error else error

    exists, _stdout, error = _run_hdfs([hdfs_cmd, "dfs", "-test", "-e", HDFS_DATA_PATH])
    if exists:
        return True, "HDFS文件已上传。"
    if "未找到 hdfs 命令" in error:
        return False, error
    return False, "HDFS中暂未找到 videos_cleaned.csv"


def read_hdfs_preview(
    hdfs_cmd: str,
    line_count: int = 5,
    hdfs_url: str | None = None,
    hdfs_user: str = DEFAULT_WEBHDFS_USER,
) -> tuple[bool, str]:
    """读取 HDFS 清洗数据前几行，用于页面验证。"""
    if hdfs_url:
        opener = build_opener(_NoRedirectHandler())
        opened, output, location, error = _webhdfs_request(
            hdfs_url,
            HDFS_DATA_PATH,
            "OPEN",
            hdfs_user,
            "GET",
            opener=opener,
        )
        if not opened or not location:
            return False, error or "WebHDFS 未返回 DataNode 地址。"
        read, output, _location, error = _request_url(
            _rewrite_datanode_location(location, hdfs_url), "GET", opener=opener
        )
        if not read:
            return False, error
        return True, "\n".join(output.splitlines()[:line_count])

    success, output, error = _run_hdfs([hdfs_cmd, "dfs", "-cat", HDFS_DATA_PATH])
    if not success:
        return False, error
    return True, "\n".join(output.splitlines()[:line_count])


def _read_webhdfs_text(hdfs_url: str, hdfs_user: str) -> str:
    opener = build_opener(_NoRedirectHandler())
    opened, output, location, error = _webhdfs_request(
        hdfs_url,
        HDFS_DATA_PATH,
        "OPEN",
        hdfs_user,
        "GET",
        opener=opener,
    )
    if not opened:
        raise DataSourceUnavailableError(error)
    if location:
        read, output, _location, error = _request_url(
            _rewrite_datanode_location(location, hdfs_url), "GET", opener=opener
        )
        if not read:
            raise DataSourceUnavailableError(error)
    return output


def _parse_csv_text(content: str) -> pd.DataFrame:
    try:
        return pd.read_csv(StringIO(content), dtype=object, keep_default_na=False)
    except (pd.errors.EmptyDataError, pd.errors.ParserError, UnicodeDecodeError) as error:
        raise DataSourceUnavailableError(f"HDFS CSV读取失败：{error}") from error


def load_analysis_dataframe(
    cleaned_path: Path,
    raw_path: Path,
    hdfs_cmd: str,
    hdfs_url: str | None,
    hdfs_user: str,
    allow_local_fallback: bool = True,
) -> tuple[pd.DataFrame, str]:
    """Load analysis data in HDFS, cleaned CSV, then raw CSV priority order."""
    hdfs_error = ""
    try:
        if hdfs_url:
            return _parse_csv_text(_read_webhdfs_text(hdfs_url, hdfs_user)), "HDFS（WebHDFS）"
        success, output, error = _run_hdfs([hdfs_cmd, "dfs", "-cat", HDFS_DATA_PATH])
        if success:
            return _parse_csv_text(output), "HDFS（命令行）"
        hdfs_error = error
    except (DataSourceUnavailableError, OSError) as error:
        hdfs_error = str(error)

    if not allow_local_fallback:
        raise DataSourceUnavailableError(hdfs_error or "HDFS数据不可用。")

    if cleaned_path.exists() and cleaned_path.stat().st_size > 0:
        return load_video_data(cleaned_path), "本地清洗CSV（HDFS不可用，已回退）"
    if raw_path.exists() and raw_path.stat().st_size > 0:
        return load_video_data(raw_path), "本地原始CSV（HDFS及清洗数据不可用，已回退）"
    return load_video_data(raw_path), "无可用数据"
