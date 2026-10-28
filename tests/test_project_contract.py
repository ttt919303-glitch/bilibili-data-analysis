import re
from pathlib import Path

from collector.bilibili_collector import VIDEO_FIELDS


EXPECTED_FIELDS = [
    "bvid", "title", "video_url", "up_name", "publish_time", "view_count",
    "like_count", "coin_count", "favorite_count", "share_count", "collect_date",
]
FORBIDDEN_PRODUCTION_PATTERNS = [
    re.compile(r"['\"]comment(?:_count)?['\"]", re.IGNORECASE),
    re.compile(
        r"\b(?:get|fetch|list|collect|download)[_-]?(?:video[_-]?)?comments?\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:read_csv|to_csv)\s*\(", re.IGNORECASE),
    re.compile(
        r"\b(?:csv(?:[_\s/-]*(?:upload|download))|(?:upload|download)(?:[_\s/-]*csv))\b",
        re.IGNORECASE,
    ),
    re.compile(r"<input\b[^>]*\btype\s*=\s*['\"]file['\"][^>]*>", re.IGNORECASE),
]


def test_video_field_contract_is_exact():
    assert VIDEO_FIELDS == EXPECTED_FIELDS


def test_production_files_contain_no_forbidden_comment_or_csv_flow():
    roots = [
        Path("app.py"),
        Path("collector"),
        Path("services"),
        Path("analysis"),
        Path("knowledge"),
        Path("scheduler"),
        Path("templates"),
        Path("static"),
    ]
    files = []
    for root in roots:
        files.extend([root] if root.is_file() else list(root.rglob("*")))
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in files
        if path.is_file() and path.suffix in {".py", ".html", ".js"}
    )
    assert not [
        pattern.pattern
        for pattern in FORBIDDEN_PRODUCTION_PATTERNS
        if pattern.search(source)
    ]


def test_required_routes_exist(app):
    routes = {str(rule) for rule in app.url_map.iter_rules()}
    assert {
        "/",
        "/login",
        "/logout",
        "/collect",
        "/data",
        "/mining",
        "/visualization",
        "/knowledge",
        "/api/collect",
        "/api/clean",
        "/api/collect/status/<int:task_id>",
    } <= routes


def test_default_config_contains_only_safe_classroom_credentials():
    source = Path("config.py").read_text(encoding="utf-8")
    assert re.search(
        r'SECRET_KEY\s*=\s*os\.environ\["SECRET_KEY"\]',
        source,
    )
    assert re.search(
        r'MYSQL_PASSWORD\s*=\s*os\.getenv\("MYSQL_PASSWORD",\s*""\)', source
    )
    assert not re.search(r"COOKIE|TOKEN|SESSDATA|bili_jct", source, re.IGNORECASE)
