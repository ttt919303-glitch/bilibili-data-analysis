# 基于多技术栈的数据分析与 AI 知识库构建 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个单进程 Flask 本科课程项目，让管理员从网页触发真实 B 站公开数据采集，并完成 pandas 清洗、HDFS 存储、日期查询、机器学习挖掘、Spark/ECharts 分析、LangChain 本地问答和每日定时采集。

**Architecture:** 使用 Flask + Jinja2 单体应用，B 站采集集中在一个采集器文件，HDFS 作为视频数据主存储，MySQL 只保存用户与采集任务。所有下游模块按同一 `collect_date` 从 HDFS 读取 11 个固定字段，任务线程、按日期的 `threading.Lock` 和 APScheduler 均运行在同一个 Python 进程中。

**Tech Stack:** Python 3.8+、Flask、PyMySQL、requests、pandas、hdfs、scikit-learn、mlxtend、PySpark 3.x、ECharts、LangChain Community、APScheduler、pytest。

## Global Constraints

- 项目是普通本科课程作业，优先能运行、能演示、容易解释，不使用微服务、前后端分离或企业级目录。
- 单个 Flask Python 进程运行；只使用进程内 `threading.Lock`，不得增加 Redis 分布式锁、数据库锁或其他分布式组件。
- 不使用 Docker、Kubernetes、Kafka、RabbitMQ、Celery、Elasticsearch、React 或 Vue。
- 不采集评论内容或评论数量；不得请求评论接口或读取 `stat.reply`。
- 视频数据字段只能是 `bvid`、`title`、`video_url`、`up_name`、`publish_time`、`view_count`、`like_count`、`coin_count`、`favorite_count`、`share_count`、`collect_date`。
- KMeans 特征只能是 `like_count`、`coin_count`、`favorite_count`、`share_count`。
- 爆款标签是 `view_count >= 当日 view_count 的 80% 分位数`；预测输入只能是四项互动指标，不能包含 `view_count`。
- Apriori 只能使用 `high_like`、`high_coin`、`high_favorite`、`high_share`。
- HDFS 是课程数据主存储，核心流程不提供 CSV 上传或下载中转。
- `collect_date` 是快照/采集归属日期，不要求等于 `publish_time`；凌晨任务把数据归档到昨天分区。
- 任务状态只能是 `waiting`、`running`、`success`、`failed`；至少 1 条成功写入 HDFS 即为 `success`，不足目标数量写入 `message`，0 条或整体失败为 `failed`。
- 采集完成后页面展示该日期最新部分视频，不增加任务结果表，不宣称是本次任务全部结果。
- 真实接口或外部服务失败时保留可追踪日志并明确报错，禁止随机数据、静默兜底或假成功。

---

## Planned File Map

```text
.
├── app.py                         # Flask 工厂、路由、MySQL 小型辅助函数、采集任务线程
├── config.py                      # 单机默认配置及环境变量覆盖
├── requirements.txt               # Python 3.8 可用的依赖版本
├── README.md                       # 本科课程演示说明
├── collector/
│   └── bilibili_collector.py      # 搜索、详情、累计采集和 pandas 清洗
├── services/
│   └── hdfs_service.py            # WebHDFS JSONL 读写、合并去重和日期锁
├── analysis/
│   ├── mining.py                  # KMeans、爆款预测、Apriori
│   └── spark_analysis.py          # 一次读取产生四组 Spark TOP10
├── knowledge/
│   └── qa.py                      # LangChain TF-IDF Retriever 和结构化问答
├── scheduler/
│   └── jobs.py                    # 00:10 定时注册，不包含第二套采集逻辑
├── templates/
│   ├── base.html
│   ├── login.html
│   ├── index.html
│   ├── collect.html
│   ├── data.html
│   ├── mining.html
│   ├── visualization.html
│   └── knowledge.html
├── static/
│   ├── css/style.css
│   └── js/main.js
├── sql/init.sql
└── tests/
    ├── conftest.py
    ├── test_auth.py
    ├── test_collector.py
    ├── test_hdfs_service.py
    ├── test_collection_flow.py
    ├── test_pages.py
    ├── test_mining.py
    ├── test_spark_analysis.py
    ├── test_knowledge.py
    ├── test_scheduler.py
    └── test_project_contract.py
```

`app.py` 保留少量 MySQL CRUD，是为了避免为两张表增加 DAO/Repository 层；采集、HDFS、分析、知识库和调度仍各自只有一个清晰入口文件。

---

### Task 1: 项目基础、MySQL、登录与权限

**Files:**
- Create: `.gitignore`
- Create: `requirements.txt`
- Create: `config.py`
- Create: `app.py`
- Create: `sql/init.sql`
- Create: `templates/base.html`
- Create: `templates/login.html`
- Create: `templates/index.html`
- Create: `static/css/style.css`
- Create: `tests/conftest.py`
- Create: `tests/test_auth.py`

**Interfaces:**
- Produces: `create_app(test_config: Optional[dict] = None) -> Flask`
- Produces: `get_db_connection() -> pymysql.Connection`
- Produces: `find_user(username: str) -> Optional[dict]`
- Produces: `login_required(view)` and `admin_required(view)` decorators
- Produces: MySQL tables `users` and `collection_tasks`

- [ ] **Step 1: 写登录和权限失败测试**

```python
# tests/test_auth.py
from werkzeug.security import generate_password_hash


def test_admin_login_writes_role(client, monkeypatch):
    monkeypatch.setattr(
        "app.find_user",
        lambda username: {
            "id": 1,
            "username": "admin",
            "password": generate_password_hash("admin-test-passphrase"),
            "role": "admin",
        },
    )
    response = client.post(
        "/login", data={"username": "admin", "password": "admin-test-passphrase"}
    )
    assert response.status_code == 302
    with client.session_transaction() as session:
        assert session["username"] == "admin"
        assert session["role"] == "admin"


def test_invalid_password_is_rejected(client, monkeypatch):
    monkeypatch.setattr(
        "app.find_user",
        lambda username: {
            "id": 2,
            "username": "student",
            "password": generate_password_hash("user-test-passphrase"),
            "role": "user",
        },
    )
    response = client.post(
        "/login", data={"username": "student", "password": "wrong"}
    )
    assert response.status_code == 200
    assert "用户名或密码错误" in response.get_data(as_text=True)


def test_login_required_redirects_anonymous_user(client):
    response = client.get("/")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]
```

```python
# tests/conftest.py
import pytest

from app import create_app


@pytest.fixture()
def app():
    return create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "ENABLE_SCHEDULER": False,
        }
    )


@pytest.fixture()
def client(app):
    return app.test_client()
```

- [ ] **Step 2: 运行测试并确认因应用尚不存在而失败**

Run: `python -m pytest tests/test_auth.py -q`

Expected: FAIL，错误包含 `ModuleNotFoundError: No module named 'app'`。

- [ ] **Step 3: 写最小 Flask、配置、SQL 和模板实现**

```python
# config.py
import os


class Config:
    SECRET_KEY = os.environ["SECRET_KEY"]
    MYSQL_HOST = os.getenv("MYSQL_HOST", "127.0.0.1")
    MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
    MYSQL_USER = os.getenv("MYSQL_USER", "root")
    MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
    MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "bigdata_course")
    HDFS_WEB_URL = os.getenv("HDFS_WEB_URL", "http://127.0.0.1:9870")
    HDFS_NAMENODE_URI = os.getenv("HDFS_NAMENODE_URI", "hdfs://127.0.0.1:9000")
    HDFS_USER = os.getenv("HDFS_USER", "hadoop")
    SPARK_MASTER = os.getenv("SPARK_MASTER", "local[*]")
    DEFAULT_KEYWORD = os.getenv("DEFAULT_KEYWORD", "大数据技术")
    DEFAULT_TARGET_COUNT = int(os.getenv("DEFAULT_TARGET_COUNT", "20"))
    ENABLE_SCHEDULER = os.getenv("ENABLE_SCHEDULER", "1") == "1"
```

```python
# app.py 的第一阶段入口
from functools import wraps

import pymysql
from flask import Flask, current_app, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from config import Config


def get_db_connection():
    return pymysql.connect(
        host=current_app.config["MYSQL_HOST"],
        port=current_app.config["MYSQL_PORT"],
        user=current_app.config["MYSQL_USER"],
        password=current_app.config["MYSQL_PASSWORD"],
        database=current_app.config["MYSQL_DATABASE"],
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
    )


def find_user(username):
    with get_db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
            return cursor.fetchone()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if session.get("role") != "admin":
            return {"message": "只有管理员可以采集数据"}, 403
        return view(*args, **kwargs)
    return wrapped


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            user = find_user(request.form["username"].strip())
            if user and check_password_hash(user["password"], request.form["password"]):
                session.clear()
                session.update(
                    user_id=user["id"], username=user["username"], role=user["role"]
                )
                return redirect(url_for("index"))
            flash("用户名或密码错误", "danger")
        return render_template("login.html")

    @app.route("/")
    @login_required
    def index():
        return render_template("index.html")

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    return app


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=5000, debug=False)
```

`sql/init.sql` 只创建所需表，不包含默认用户或口令。应用启动时从 `ADMIN_USERNAME`、`ADMIN_PASSWORD`、`USER_USERNAME` 和 `USER_PASSWORD` 环境变量读取两组初始凭据，并使用 Werkzeug 生成密码哈希：

```sql
CREATE DATABASE IF NOT EXISTS bigdata_course DEFAULT CHARACTER SET utf8mb4;
USE bigdata_course;

CREATE TABLE IF NOT EXISTS users (
    id INT PRIMARY KEY AUTO_INCREMENT,
    username VARCHAR(50) NOT NULL UNIQUE,
    password VARCHAR(255) NOT NULL,
    role ENUM('admin', 'user') NOT NULL
);

CREATE TABLE IF NOT EXISTS collection_tasks (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    keyword VARCHAR(100) NOT NULL,
    target_count INT NOT NULL,
    success_count INT NOT NULL DEFAULT 0,
    status ENUM('waiting', 'running', 'success', 'failed') NOT NULL,
    collect_date DATE NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at DATETIME NULL,
    message VARCHAR(500) NOT NULL DEFAULT ''
);

```

第一阶段的 `index.html` 只需继承 `base.html` 并显示项目名称与“登录成功”，确保登录跳转后页面可渲染；Task 5 再把它扩展为真实昨日统计首页。`base.html` 此阶段只引用已经存在的首页和退出路由，后续任务增加导航入口时同步扩展。

`.gitignore` 使用以下内容，避免提交本地环境和设计阶段产生的 PDF 临时渲染文件：

```gitignore
__pycache__/
*.py[cod]
.venv/
.pytest_cache/
.env
tmp/
```

`requirements.txt` 固定为以下 Python 3.8 可安装版本：

```text
Flask==3.0.3
PyMySQL==1.1.1
cryptography==42.0.8
requests==2.32.3
numpy==1.24.4
pandas==2.0.3
hdfs==2.7.3
scipy==1.10.1
scikit-learn==1.3.2
mlxtend==0.23.1
pyspark==3.5.1
langchain==0.2.17
langchain-community==0.2.19
APScheduler==3.10.4
pytest==8.3.5
```

- [ ] **Step 4: 运行登录测试、导入检查和路由检查**

Run: `python -m pip install -r requirements.txt`

Expected: 所有依赖安装成功；如果网络或索引不可用，保留原始安装错误并在获准联网后重试，不替换为缺少课程组件的最小依赖。

Run: `python -m pytest tests/test_auth.py -q`

Expected: 3 passed。

Run: `python -m compileall app.py config.py`

Expected: 两个文件均成功编译。

Run: `python -c "from app import create_app; print(sorted(str(r) for r in create_app({'ENABLE_SCHEDULER': False}).url_map.iter_rules()))"`

Expected: 输出包含 `/`、`/login`、`/logout` 和 `/static/<path:filename>`。

- [ ] **Step 5: 提交基础阶段**

```bash
git add .gitignore requirements.txt config.py app.py sql templates/base.html templates/login.html templates/index.html static/css/style.css tests/conftest.py tests/test_auth.py
git commit -m "feat: add course app authentication foundation"
```

---

### Task 2: B 站真实公开数据采集与 pandas 清洗

**Files:**
- Create: `collector/__init__.py`
- Create: `collector/bilibili_collector.py`
- Create: `tests/test_collector.py`

**Interfaces:**
- Produces: `search_videos(keyword: str, page: int) -> List[str]`
- Produces: `get_video_detail(bvid: str) -> Dict`
- Produces: `collect(keyword: str, target_count: int, collect_date: str) -> List[Dict]`
- Produces: `clean_video_data(data: List[Dict]) -> List[Dict]`
- Uses only B 站公开搜索 `https://api.bilibili.com/x/web-interface/search/type` 和详情 `https://api.bilibili.com/x/web-interface/view`

- [ ] **Step 1: 写固定字段、接口映射、累计采集与清洗测试**

```python
# tests/test_collector.py
from collector import bilibili_collector as collector


EXPECTED_FIELDS = {
    "bvid", "title", "video_url", "up_name", "publish_time",
    "view_count", "like_count", "coin_count", "favorite_count",
    "share_count", "collect_date",
}


def test_get_video_detail_maps_public_view_fields(monkeypatch):
    payload = {
        "code": 0,
        "data": {
            "bvid": "BV1TEST",
            "title": "Spark 入门",
            "pubdate": 1723075200,
            "owner": {"name": "课程UP"},
            "stat": {
                "view": 1200, "like": 80, "coin": 20,
                "favorite": 30, "share": 10, "reply": 999,
            },
        },
    }
    monkeypatch.setattr(collector, "_request_json", lambda url, params: payload)
    result = collector.get_video_detail("BV1TEST")
    assert set(result) == EXPECTED_FIELDS - {"collect_date"}
    assert result["view_count"] == 1200
    assert result["like_count"] == 80
    assert "comment_count" not in result
    assert "comments" not in result


def test_collect_adds_snapshot_date_without_filtering_publish_time(monkeypatch):
    monkeypatch.setattr(collector, "search_videos", lambda keyword, page: ["BV1TEST"])
    monkeypatch.setattr(
        collector,
        "get_video_detail",
        lambda bvid: {
            "bvid": bvid, "title": "旧视频", "video_url": "https://www.bilibili.com/video/BV1TEST",
            "up_name": "课程UP", "publish_time": "2024-01-01 08:00:00",
            "view_count": 1, "like_count": 2, "coin_count": 3,
            "favorite_count": 4, "share_count": 5,
        },
    )
    result = collector.collect("大数据技术", 1, "2026-08-08")
    assert result[0]["collect_date"] == "2026-08-08"
    assert result[0]["publish_time"] == "2024-01-01 08:00:00"


def test_clean_video_data_converts_units_and_deduplicates_bvid():
    rows = [
        {"bvid": "BV1", "title": "A", "video_url": "u", "up_name": "UP",
         "publish_time": "2026-08-01", "view_count": "1.1万", "like_count": "2万",
         "coin_count": None, "favorite_count": 3, "share_count": "4",
         "collect_date": "2026/08/08"},
        {"bvid": "BV1", "title": "A2", "video_url": "u2", "up_name": "UP",
         "publish_time": "2026-08-02", "view_count": 12000, "like_count": 5,
         "coin_count": 6, "favorite_count": 7, "share_count": 8,
         "collect_date": "2026-08-08"},
    ]
    result = collector.clean_video_data(rows)
    assert len(result) == 1
    assert result[0]["title"] == "A2"
    assert result[0]["view_count"] == 12000
    assert result[0]["collect_date"] == "2026-08-08"
    assert set(result[0]) == EXPECTED_FIELDS
```

- [ ] **Step 2: 运行测试并确认缺少采集器而失败**

Run: `python -m pytest tests/test_collector.py -q`

Expected: FAIL，错误包含 `No module named 'collector'`。

- [ ] **Step 3: 实现集中式采集器**

实现必须包含以下常量与映射，不得实现 `get_video_comments`：

```python
SEARCH_URL = "https://api.bilibili.com/x/web-interface/search/type"
DETAIL_URL = "https://api.bilibili.com/x/web-interface/view"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
    "Referer": "https://www.bilibili.com/",
}
VIDEO_FIELDS = [
    "bvid", "title", "video_url", "up_name", "publish_time", "view_count",
    "like_count", "coin_count", "favorite_count", "share_count", "collect_date",
]
```

`_request_json(url, params)` 使用模块级 `requests.Session`、`timeout=10`、最多三次请求；只重试 `requests.RequestException` 和 HTTP 5xx，HTTP 412/429、业务 `code != 0`、非 JSON 立即抛出带 URL、状态码和响应摘要的 `CollectorError`。每次重试前等待 1、2 秒，成功详情请求之间默认等待 0.5 秒。

`search_videos` 参数固定为 `search_type=video`、`keyword`、`page`，从 `data.result` 提取非空 BV 号并保持顺序去重。`get_video_detail` 从 `data.stat` 读取 `view/like/coin/favorite/share`，不访问 `reply`，并把 Unix `pubdate` 转为本地 `YYYY-MM-DD HH:MM:SS`。

`collect` 逐页搜索，直到达到 `target_count`、搜索结果为空或连续页面没有新 BV 号；单个详情失败只记录 `bvid` 和异常并继续。第一页搜索失败直接抛出，后续页失败且已有成功数据时停止并返回已有真实记录。

`clean_video_data` 使用 pandas DataFrame，只对字符串数量解析 `万`、`亿`，整数直接保留；空统计填 0、限制为非负整数、日期统一、空 BV 删除、重复 BV 保留最后一条，最后只输出 `VIDEO_FIELDS`。

- [ ] **Step 4: 运行采集器测试与真实小批量探测**

Run: `python -m pytest tests/test_collector.py -q`

Expected: 全部通过。

Run: `python -c "from collector.bilibili_collector import collect; print(collect('大数据技术', 1, '2026-08-08'))"`

Expected when network/API is available: 输出 1 条含 11 个固定字段的真实记录，数值来自详情接口且不含任何评论字段。

Expected when blocked: 命令明确打印或抛出实际 URL、HTTP 状态/业务码和响应摘要；保留失败证据，不切换到样例或随机数据。

- [ ] **Step 5: 提交采集与清洗阶段**

```bash
git add collector tests/test_collector.py
git commit -m "feat: collect and clean public bilibili video data"
```

---

### Task 3: WebHDFS 自动存储、合并去重与进程内日期锁

**Files:**
- Create: `services/__init__.py`
- Create: `services/hdfs_service.py`
- Create: `tests/test_hdfs_service.py`

**Interfaces:**
- Produces: `video_path(date: str) -> str`
- Produces: `save_to_hdfs(data: List[Dict], date: str) -> int`
- Produces: `read_from_hdfs(date: str) -> List[Dict]`
- HDFS path: `/bigdata_course/bilibili/date=YYYY-MM-DD/videos.jsonl`

- [ ] **Step 1: 写路径、合并去重、归属日期和锁测试**

```python
# tests/test_hdfs_service.py
import json
import threading

from services import hdfs_service


class FakeHdfsClient:
    def __init__(self, files=None):
        self.files = dict(files or {})

    def status(self, path, strict=False):
        return {"type": "FILE"} if path in self.files else None

    def read(self, path, encoding="utf-8"):
        class Reader:
            def __enter__(inner):
                return iter(self.files[path].splitlines(True))
            def __exit__(inner, *args):
                return False
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


def test_each_date_uses_process_local_threading_lock():
    first = hdfs_service._lock_for_date("2026-08-08")
    second = hdfs_service._lock_for_date("2026-08-08")
    other = hdfs_service._lock_for_date("2026-08-09")
    assert isinstance(first, type(threading.Lock()))
    assert first is second
    assert first is not other
```

- [ ] **Step 2: 运行测试并确认服务尚不存在**

Run: `python -m pytest tests/test_hdfs_service.py -q`

Expected: FAIL，错误包含 `No module named 'services'`。

- [ ] **Step 3: 实现 WebHDFS JSON Lines 服务**

```python
# services/hdfs_service.py 的公开边界
import json
import threading
import uuid

from flask import current_app
from hdfs import InsecureClient

BASE_PATH = "/bigdata_course/bilibili"
_date_locks = {}
_date_locks_guard = threading.Lock()


def _lock_for_date(date):
    with _date_locks_guard:
        return _date_locks.setdefault(date, threading.Lock())


def video_path(date):
    return f"{BASE_PATH}/date={date}/videos.jsonl"


def _client():
    return InsecureClient(
        current_app.config["HDFS_WEB_URL"],
        user=current_app.config["HDFS_USER"],
    )
```

`read_from_hdfs` 在文件不存在时返回空列表，在连接/解码错误时抛出带日期和路径的 `HdfsServiceError`。`save_to_hdfs` 拒绝空列表，把每条记录的 `collect_date` 设为函数日期，读取旧记录后按 BV 号合并，写入 `videos.jsonl.tmp-<uuid>`；如果目标已存在则先改名为 `.bak`，临时文件改名成功后删除备份，交换失败时恢复备份并抛错。返回值是本次传入并成功归档的去重记录数，不是同日总量。

所有“读取旧数据、合并、写临时文件、交换文件”操作必须位于 `_lock_for_date(date)` 的同一个 `with` 块中。只使用上述进程内锁。

- [ ] **Step 4: 运行 HDFS 单元测试**

Run: `python -m pytest tests/test_hdfs_service.py -q`

Expected: 全部通过，测试不需要真实 Hadoop。

- [ ] **Step 5: 提交 HDFS 阶段**

```bash
git add services tests/test_hdfs_service.py
git commit -m "feat: persist daily video snapshots to hdfs"
```

---

### Task 4: 管理员采集 API、后台线程、状态轮询与页面回显

**Files:**
- Modify: `app.py`
- Create: `templates/collect.html`
- Create: `static/js/main.js`
- Create: `tests/test_collection_flow.py`

**Interfaces:**
- Produces: `POST /api/collect -> {task_id}`
- Produces: `GET /api/collect/status/<task_id> -> task fields + latest_videos`
- Produces: `run_collection_task(app, task_id, keyword, target_count, collect_date) -> None`
- Consumes: `collect()`, `clean_video_data()`, `save_to_hdfs()`, `read_from_hdfs()`

- [ ] **Step 1: 写权限、真实调用链和状态语义测试**

```python
# tests/test_collection_flow.py
def login_as(client, role):
    with client.session_transaction() as session:
        session.update(user_id=1, username=role, role=role)


def test_normal_user_cannot_call_collect_api(client):
    login_as(client, "user")
    response = client.post(
        "/api/collect",
        json={"keyword": "大数据技术", "date": "2026-08-08", "target_count": 20},
    )
    assert response.status_code == 403


def test_collection_runner_calls_collector_cleaner_and_hdfs(app, monkeypatch):
    raw = [{"bvid": "BV1"}]
    cleaned = [{"bvid": "BV1", "collect_date": "2026-08-08"}]
    calls = []
    monkeypatch.setattr("app.collect", lambda keyword, target, date: calls.append("collect") or raw)
    monkeypatch.setattr("app.clean_video_data", lambda rows: calls.append("clean") or cleaned)
    monkeypatch.setattr("app.save_to_hdfs", lambda rows, date: calls.append("hdfs") or 1)
    monkeypatch.setattr("app.update_task", lambda task_id, **values: calls.append(values["status"]))
    from app import run_collection_task
    run_collection_task(app, 7, "大数据技术", 20, "2026-08-08")
    assert calls[:3] == ["running", "collect", "clean"]
    assert "hdfs" in calls
    assert calls[-1] == "success"


def test_short_collection_is_success_with_actual_count_message(app, monkeypatch):
    monkeypatch.setattr("app.collect", lambda *args: [{"bvid": "BV1"}])
    monkeypatch.setattr("app.clean_video_data", lambda rows: rows)
    monkeypatch.setattr("app.save_to_hdfs", lambda rows, date: 1)
    updates = []
    monkeypatch.setattr("app.update_task", lambda task_id, **values: updates.append(values))
    from app import run_collection_task
    run_collection_task(app, 8, "大数据技术", 20, "2026-08-08")
    assert updates[-1]["status"] == "success"
    assert updates[-1]["success_count"] == 1
    assert "目标 20 条，实际采集 1 条" in updates[-1]["message"]


def test_zero_rows_is_failed(app, monkeypatch):
    monkeypatch.setattr("app.collect", lambda *args: [])
    monkeypatch.setattr("app.clean_video_data", lambda rows: rows)
    updates = []
    monkeypatch.setattr("app.update_task", lambda task_id, **values: updates.append(values))
    from app import run_collection_task
    run_collection_task(app, 9, "大数据技术", 20, "2026-08-08")
    assert updates[-1]["status"] == "failed"
    assert updates[-1]["success_count"] == 0
```

- [ ] **Step 2: 运行主链路测试并确认路由/函数缺失**

Run: `python -m pytest tests/test_collection_flow.py -q`

Expected: FAIL，至少包含 `/api/collect` 404 或 `run_collection_task` 导入失败。

- [ ] **Step 3: 实现任务 CRUD、线程和采集页面**

在 `app.py` 中增加四个简单参数化 SQL 函数：

```python
def create_task(keyword, target_count, collect_date): ...
def update_task(task_id, **values): ...
def get_task(task_id): ...
def latest_videos(date, limit=10):
    return list(reversed(read_from_hdfs(date)))[:limit]
```

`update_task` 只允许更新 `success_count/status/finished_at/message` 四个白名单列，不拼接外部输入列名。`run_collection_task` 的顺序固定为：`running -> collect -> clean -> 非空检查 -> save_to_hdfs -> success`。少于目标数量时 message 使用 `目标 N 条，实际采集 M 条`；0 条、采集整体异常或 HDFS 异常时 `failed`，日志使用 `logger.exception` 保留任务 ID、关键字和日期。

`POST /api/collect` 校验：非空关键字、合法 ISO 日期、`1 <= target_count <= 50000`。创建任务后启动 daemon `threading.Thread`，返回 HTTP 202 和 `task_id`。`GET /api/collect/status/<id>` 验证登录；成功任务附带该日期从 HDFS 读取的最多 10 条 `latest_videos`，这些记录明确标注为“该日期最新部分数据”。

`collect.html` 只包含关键字、日期、目标数量、开始按钮、任务信息和 7 列最新视频表格（标题、UP 主、播放、点赞、投币、收藏、分享）。`main.js` 每 2 秒轮询状态，状态为 `success/failed` 后停止；不得出现文件上传控件或 CSV 逻辑。

- [ ] **Step 4: 运行主链路测试、模板检查和 URL 检查**

Run: `python -m pytest tests/test_collection_flow.py -q`

Expected: 全部通过。

Run: `python -c "from app import create_app; print(sorted(str(r) for r in create_app({'ENABLE_SCHEDULER': False}).url_map.iter_rules()))"`

Expected: 新增 `/collect`、`/api/collect`、`/api/collect/status/<int:task_id>`。

Run: `rg -n "file|upload|csv|comment_count|comments" templates static collector app.py`

Expected: 无 CSV 上传和评论字段命中；允许 HTML 资源中的普通 `file` 单词时必须人工确认不是上传功能。

- [ ] **Step 5: 提交 Web 采集主链路**

```bash
git add app.py templates/collect.html static/js/main.js tests/test_collection_flow.py
git commit -m "feat: connect admin collection page to hdfs pipeline"
```

---

### Task 5: 统一日期、首页统计与数据查询

**Files:**
- Modify: `app.py`
- Modify: `templates/index.html`
- Create: `templates/data.html`
- Create: `tests/test_pages.py`

**Interfaces:**
- Produces: `yesterday_string(now: datetime | None = None) -> str`
- Produces: `selected_date(value: str | None) -> str`
- Produces: `GET /?date=YYYY-MM-DD`
- Produces: `GET /data?date=YYYY-MM-DD&q=关键字&page=1`

- [ ] **Step 1: 写默认昨天、显式日期、搜索和分页测试**

```python
# tests/test_pages.py
from datetime import datetime


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
```

- [ ] **Step 2: 运行页面测试并确认 `/data` 不存在**

Run: `python -m pytest tests/test_pages.py -q`

Expected: FAIL，包含 `/data` 404 或日期辅助函数缺失。

- [ ] **Step 3: 实现统一日期和两个页面**

`selected_date` 对空值返回昨天，对非 ISO 日期抛出 `ValueError` 并由页面返回 HTTP 400。首页一次读取所选日期 HDFS 记录，计算视频数、总播放、总点赞、总投币和按播放排序 TOP5。

数据页在内存中按标题或 UP 主做不区分大小写包含搜索，每页 20 条，页码小于 1 返回 400，页码超过总页数显示空表。标题链接使用原始 `video_url` 并加 `target="_blank" rel="noopener"`。两个页面顶部保持同一日期输入，所有链接继续携带当前日期。

导航栏只在 `session.role == 'admin'` 时显示数据采集入口；普通用户仍可看到首页、数据查询、数据挖掘、Spark 可视化、AI 知识库和退出登录。

- [ ] **Step 4: 运行页面与完整现有测试**

Run: `python -m pytest tests/test_pages.py tests/test_auth.py tests/test_collection_flow.py -q`

Expected: 全部通过。

- [ ] **Step 5: 提交日期和查询阶段**

```bash
git add app.py templates/base.html templates/index.html templates/data.html tests/test_pages.py
git commit -m "feat: add daily dashboard and video query"
```

---

### Task 6: KMeans、爆款预测与 Apriori

**Files:**
- Create: `analysis/__init__.py`
- Create: `analysis/mining.py`
- Modify: `app.py`
- Create: `templates/mining.html`
- Create: `tests/test_mining.py`

**Interfaces:**
- Produces: `run_kmeans(records: List[Dict]) -> List[Dict]`
- Produces: `run_hot_prediction(records: List[Dict]) -> Dict`
- Produces: `run_apriori(records: List[Dict], min_support=0.2, min_confidence=0.6) -> List[Dict]`
- Produces: `GET /mining?date=YYYY-MM-DD`

- [ ] **Step 1: 写特征合同、聚类、爆款标签和关联规则测试**

```python
# tests/test_mining.py
import pandas as pd
import pytest

from analysis import mining


def records(count=20):
    return [
        {
            "bvid": f"BV{i}", "title": f"视频{i}", "view_count": i * 100,
            "like_count": i + 1, "coin_count": (i % 5) + 1,
            "favorite_count": i + 2, "share_count": (i % 4) + 1,
        }
        for i in range(count)
    ]


def test_feature_contract_is_exact():
    assert mining.INTERACTION_FEATURES == [
        "like_count", "coin_count", "favorite_count", "share_count"
    ]
    assert "view_count" not in mining.INTERACTION_FEATURES


def test_kmeans_returns_three_named_groups():
    result = mining.run_kmeans(records())
    assert {item["cluster_name"] for item in result} == {"低互动", "中互动", "高互动"}
    assert sum(item["video_count"] for item in result) == 20


def test_kmeans_rejects_fewer_than_three_distinct_feature_vectors():
    duplicate_rows = records(3)
    for row in duplicate_rows:
        row.update(like_count=1, coin_count=1, favorite_count=1, share_count=1)
    with pytest.raises(mining.MiningDataError, match="数据差异不足，无法完成3类聚类"):
        mining.run_kmeans(duplicate_rows)


def test_hot_prediction_uses_view_only_for_label(monkeypatch):
    captured = {}
    original_split = mining.train_test_split
    def recording_split(X, y, **kwargs):
        captured["columns"] = list(X.columns)
        return original_split(X, y, **kwargs)
    monkeypatch.setattr(mining, "train_test_split", recording_split)
    result = mining.run_hot_prediction(records(40))
    assert captured["columns"] == mining.INTERACTION_FEATURES
    assert result["threshold"] == pd.Series([i * 100 for i in range(40)]).quantile(0.8)


def test_apriori_uses_only_four_high_interaction_items():
    result = mining.run_apriori(records(40), min_support=0.1, min_confidence=0.1)
    allowed = {"high_like", "high_coin", "high_favorite", "high_share"}
    for rule in result:
        assert set(rule["antecedents"]) | set(rule["consequents"]) <= allowed
```

- [ ] **Step 2: 运行挖掘测试并确认模块缺失**

Run: `python -m pytest tests/test_mining.py -q`

Expected: FAIL，错误包含 `No module named 'analysis'`。

- [ ] **Step 3: 实现三个本科难度算法和页面**

```python
# analysis/mining.py 的固定合同
INTERACTION_FEATURES = [
    "like_count", "coin_count", "favorite_count", "share_count"
]
HIGH_FEATURES = {
    "like_count": "high_like",
    "coin_count": "high_coin",
    "favorite_count": "high_favorite",
    "share_count": "high_share",
}
```

`run_kmeans` 至少需要 3 条记录，并且四项互动特征必须至少存在 3 个不同特征向量；不满足后者时抛出 `MiningDataError("数据差异不足，无法完成3类聚类")`，不得强行产生三个类别。满足条件后使用 `StandardScaler` 和 `KMeans(n_clusters=3, random_state=42, n_init=10)`；按四维簇中心之和从小到大命名低/中/高互动，结果包含 `cluster_name/video_count/avg_view_count/avg_like_count`。

`run_hot_prediction` 使用 pandas `quantile(0.8)` 生成标签；X 严格等于 `records[INTERACTION_FEATURES]`。使用 `train_test_split(test_size=0.25, random_state=42, stratify=y)` 和 `RandomForestClassifier(n_estimators=100, random_state=42)`，返回阈值、accuracy、precision、recall、classification_report 和逐视频预测。少于 10 条或标签只有一类时抛出可展示的 `MiningDataError`。

`run_apriori` 用各列中位数产生四个 `high_*` 布尔列，调用 `mlxtend.frequent_patterns.apriori` 与 `association_rules(metric="confidence", min_threshold=min_confidence)`，结果把 frozenset 转成排序字符串列表。没有规则时返回空列表。

`/mining` 只读取选定日期一次，分别运行三个算法；每个算法独立捕获 `MiningDataError` 并显示原因，不能因某个数据量不足让整个页面 500。

- [ ] **Step 4: 运行挖掘和日期贯穿测试**

Run: `python -m pytest tests/test_mining.py tests/test_pages.py -q`

Expected: 全部通过。

- [ ] **Step 5: 提交数据挖掘阶段**

```bash
git add analysis/mining.py analysis/__init__.py app.py templates/mining.html tests/test_mining.py
git commit -m "feat: add course-level video data mining"
```

---

### Task 7: Spark 四项分析与 ECharts 可视化

**Files:**
- Create: `analysis/spark_analysis.py`
- Modify: `app.py`
- Create: `templates/visualization.html`
- Modify: `static/css/style.css`
- Create: `tests/test_spark_analysis.py`

**Interfaces:**
- Produces: `analyze_dataframe(dataframe) -> Dict[str, List[Dict]]`
- Produces: `run_spark_analysis(date: str) -> Dict[str, List[Dict]]`
- Produces keys: `up_video_count`, `top_views`, `top_likes`, `top_interactions`
- Produces: `GET /visualization?date=YYYY-MM-DD`

- [ ] **Step 1: 写本地 Spark DataFrame 分析与模板容器测试**

```python
# tests/test_spark_analysis.py
import shutil

import pytest

pytest.importorskip("pyspark")
from pyspark.sql import SparkSession
from analysis.spark_analysis import analyze_dataframe


@pytest.fixture(scope="module")
def spark():
    if shutil.which("java") is None:
        pytest.skip("Java is required for the local Spark integration test")
    session = SparkSession.builder.master("local[1]").appName("course-test").getOrCreate()
    yield session
    session.stop()


def test_four_spark_analyses_have_expected_order(spark):
    rows = [
        ("A", "v1", 100, 10, 2, 3, 4),
        ("A", "v2", 300, 30, 4, 5, 6),
        ("B", "v3", 200, 20, 9, 9, 9),
    ]
    columns = ["up_name", "title", "view_count", "like_count", "coin_count", "favorite_count", "share_count"]
    result = analyze_dataframe(spark.createDataFrame(rows, columns))
    assert set(result) == {"up_video_count", "top_views", "top_likes", "top_interactions"}
    assert result["up_video_count"][0] == {"name": "A", "value": 2}
    assert result["top_views"][0]["name"] == "v2"
    assert result["top_likes"][0]["name"] == "v2"
    assert result["top_interactions"][0]["name"] == "v3"
```

另在同一测试文件增加 Flask 路由测试，patch `app.run_spark_analysis` 返回四个列表，并断言 HTML 包含 `chart-up-count`、`chart-top-views`、`chart-top-likes`、`chart-interactions` 四个容器及选择日期。

- [ ] **Step 2: 运行 Spark 测试并记录基线**

Run: `python -m pytest tests/test_spark_analysis.py -q`

Expected with PySpark/Java available: FAIL，原因是 `analysis.spark_analysis` 尚不存在。

Expected without PySpark/Java: 测试被明确 SKIP 或报出 Java gateway 根因；不得伪造通过。安装课程环境后必须重新运行。

- [ ] **Step 3: 实现一次 HDFS 读取和四组结果**

`run_spark_analysis(date)` 使用：

```python
path = f"{current_app.config['HDFS_NAMENODE_URI']}/bigdata_course/bilibili/date={date}/videos.jsonl"
spark = (
    SparkSession.builder
    .master(current_app.config["SPARK_MASTER"])
    .appName("BigDataCourseAnalysis")
    .getOrCreate()
)
dataframe = spark.read.json(path)
return analyze_dataframe(dataframe)
```

`analyze_dataframe` 使用 Spark SQL functions 完成：UP 主按 `count(*)` 降序 TOP10、视频按播放降序 TOP10、按点赞降序 TOP10、按四项互动和降序 TOP10。每组结果转为 `{name, value}`，标题显示截断只在模板中处理，数据层保留完整标题。

`/visualization` 传入 `analysis` JSON。模板通过 ECharts CDN 创建两列四卡片图，使用 `tojson` 注入数据，不拼接未转义 JavaScript 字符串。Spark 异常时记录堆栈并显示“Spark 分析失败，请检查 Spark、Java 和 HDFS 环境”。

- [ ] **Step 4: 运行 Spark 测试与模板路由测试**

Run: `python -m pytest tests/test_spark_analysis.py -q`

Expected with Java/Spark available: 全部通过。

Run: `python -m pytest tests/test_pages.py -q`

Expected: 全部通过，日期逻辑无回归。

- [ ] **Step 5: 提交 Spark/ECharts 阶段**

```bash
git add analysis/spark_analysis.py app.py templates/visualization.html static/css/style.css tests/test_spark_analysis.py
git commit -m "feat: visualize four spark analyses"
```

---

### Task 8: LangChain TF-IDF 本地知识库

**Files:**
- Create: `knowledge/__init__.py`
- Create: `knowledge/qa.py`
- Modify: `app.py`
- Create: `templates/knowledge.html`
- Create: `tests/test_knowledge.py`

**Interfaces:**
- Produces: `build_documents(records: List[Dict]) -> List[Document]`
- Produces: `build_retriever(records: List[Dict]) -> TFIDFRetriever`
- Produces: `answer_question(records: List[Dict], question: str) -> str`
- Produces: `GET/POST /knowledge?date=YYYY-MM-DD`

- [ ] **Step 1: 写 Document、三类精确回答与普通检索测试**

```python
# tests/test_knowledge.py
from knowledge.qa import answer_question, build_documents


RECORDS = [
    {"title": "Spark A", "up_name": "甲", "view_count": 100, "like_count": 20,
     "coin_count": 5, "favorite_count": 8, "share_count": 3, "bvid": "BV1"},
    {"title": "Hadoop B", "up_name": "甲", "view_count": 300, "like_count": 10,
     "coin_count": 30, "favorite_count": 6, "share_count": 2, "bvid": "BV2"},
    {"title": "Python C", "up_name": "乙", "view_count": 200, "like_count": 50,
     "coin_count": 4, "favorite_count": 7, "share_count": 1, "bvid": "BV3"},
]


def test_documents_contain_real_video_metrics():
    documents = build_documents(RECORDS)
    assert len(documents) == 3
    assert "Spark A" in documents[0].page_content
    assert documents[0].metadata["bvid"] == "BV1"


def test_answers_required_structured_questions():
    assert "甲" in answer_question(RECORDS, "哪个UP主视频最多？")
    assert "Hadoop B" in answer_question(RECORDS, "播放量最高的视频是哪个？")
    answer = answer_question(RECORDS, "哪些视频点赞投币最高？")
    assert "Python C" in answer
    assert "Hadoop B" in answer


def test_other_question_uses_local_retriever():
    answer = answer_question(RECORDS, "我想了解 Spark")
    assert "Spark A" in answer
```

- [ ] **Step 2: 运行知识库测试并确认模块缺失**

Run: `python -m pytest tests/test_knowledge.py -q`

Expected: FAIL，错误包含 `No module named 'knowledge'`。

- [ ] **Step 3: 实现本地 TF-IDF Retriever 和页面**

`build_documents` 为每条记录生成 LangChain `Document`，page content 包含标题、UP 主、播放、点赞、投币、收藏、分享，metadata 包含 `bvid/title/up_name`。不得包含任何评论字段。

`build_retriever` 使用 `langchain_community.retrievers.TFIDFRetriever.from_documents(documents)`，并设置 `k = min(3, len(documents))`。三类指定问题先通过关键词规则进入 pandas 精确统计：UP 主计数、播放最大、点赞最大与投币最大；其他问题调用 `retriever.invoke(question)`，把最相关文档内容合并成简短回答。空日期数据抛出 `KnowledgeBaseError("该日期暂无数据")`。

`/knowledge` GET 显示日期和问题表单，POST 仍从 URL/form 中的同一日期读取 HDFS；问题为空返回 HTTP 400。构建失败记录异常并在页面显示“知识库构建失败”，不能影响其他页面。

- [ ] **Step 4: 运行知识库和页面测试**

Run: `python -m pytest tests/test_knowledge.py tests/test_pages.py -q`

Expected: 全部通过。

- [ ] **Step 5: 提交 AI 知识库阶段**

```bash
git add knowledge app.py templates/knowledge.html tests/test_knowledge.py
git commit -m "feat: add local langchain video knowledge base"
```

---

### Task 9: 每日 00:10 自动采集昨天快照

**Files:**
- Create: `scheduler/__init__.py`
- Create: `scheduler/jobs.py`
- Modify: `app.py`
- Create: `tests/test_scheduler.py`

**Interfaces:**
- Produces: `build_scheduler(job_func: Callable[[], None]) -> BackgroundScheduler`
- Produces: `run_scheduled_collection(app) -> None`
- Reuses: `create_task()` and `run_collection_task()` from `app.py`

- [ ] **Step 1: 写调度时间、昨天归档和同一采集入口测试**

```python
# tests/test_scheduler.py
from datetime import datetime

from scheduler.jobs import build_scheduler


def test_scheduler_registers_single_daily_job_at_0010():
    scheduler = build_scheduler(lambda: None)
    jobs = scheduler.get_jobs()
    assert len(jobs) == 1
    assert jobs[0].id == "collect_yesterday"
    fields = jobs[0].trigger.fields
    assert str(fields[5]) == "0"
    assert str(fields[6]) == "10"


def test_scheduled_collection_archives_to_yesterday(app, monkeypatch):
    created = []
    executed = []
    monkeypatch.setattr("app.current_local_datetime", lambda: datetime(2026, 8, 9, 0, 10))
    monkeypatch.setattr("app.create_task", lambda keyword, target, date: created.append((keyword, target, date)) or 12)
    monkeypatch.setattr("app.run_collection_task", lambda app, task_id, keyword, target, date: executed.append((task_id, date)))
    from app import run_scheduled_collection
    run_scheduled_collection(app)
    assert created[0][2] == "2026-08-08"
    assert executed == [(12, "2026-08-08")]
```

- [ ] **Step 2: 运行调度测试并确认模块缺失**

Run: `python -m pytest tests/test_scheduler.py -q`

Expected: FAIL，错误包含 `No module named 'scheduler'`。

- [ ] **Step 3: 实现只负责注册的调度器**

```python
# scheduler/jobs.py
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger


def build_scheduler(job_func):
    scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
    scheduler.add_job(
        job_func,
        CronTrigger(hour=0, minute=10, timezone="Asia/Shanghai"),
        id="collect_yesterday",
        replace_existing=True,
        max_instances=1,
    )
    return scheduler
```

`app.run_scheduled_collection(app)` 在 app context 中计算昨天，使用 `DEFAULT_KEYWORD` 和 `DEFAULT_TARGET_COUNT` 创建任务，然后同步调用与手动线程相同的 `run_collection_task`；因此归档日期是昨天，视频原始 `publish_time` 不被改写。

`create_app` 仅在 `ENABLE_SCHEDULER=True` 时构建和启动一次调度器，保存到 `app.extensions["course_scheduler"]`。`app.py` 以 `debug=False` 启动，测试配置始终关闭 scheduler，避免 pytest 后台线程。

- [ ] **Step 4: 运行调度和采集主链路测试**

Run: `python -m pytest tests/test_scheduler.py tests/test_collection_flow.py -q`

Expected: 全部通过，且现有采集调用顺序无回归。

- [ ] **Step 5: 提交自动采集阶段**

```bash
git add scheduler app.py tests/test_scheduler.py
git commit -m "feat: schedule yesterday collection at midnight"
```

---

### Task 10: 合同测试、README、真实环境联调与最终清理

**Files:**
- Create: `tests/test_project_contract.py`
- Create: `README.md`
- Modify: only files proven necessary by failing tests or live evidence

**Interfaces:**
- Verifies: 11-field contract, route/template/JS alignment, no comment or CSV upload path, task semantics, default date, imports
- Documents: MySQL、Hadoop/HDFS、Spark、Flask、管理员/普通用户、采集、分析、知识库和常见错误

- [ ] **Step 1: 写项目合同测试**

```python
# tests/test_project_contract.py
from pathlib import Path

from collector.bilibili_collector import VIDEO_FIELDS


EXPECTED_FIELDS = [
    "bvid", "title", "video_url", "up_name", "publish_time", "view_count",
    "like_count", "coin_count", "favorite_count", "share_count", "collect_date",
]


def test_video_field_contract_is_exact():
    assert VIDEO_FIELDS == EXPECTED_FIELDS


def test_production_files_contain_no_comment_fields_or_upload_flow():
    roots = [Path("app.py"), Path("collector"), Path("services"), Path("analysis"),
             Path("knowledge"), Path("scheduler"), Path("templates"), Path("static")]
    files = []
    for root in roots:
        files.extend([root] if root.is_file() else list(root.rglob("*")))
    text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in files
        if path.is_file() and path.suffix in {".py", ".html", ".js"}
    ).lower()
    assert "comment_count" not in text
    assert "get_video_comments" not in text
    assert 'type="file"' not in text
    assert "upload csv" not in text


def test_required_routes_exist(app):
    routes = {str(rule) for rule in app.url_map.iter_rules()}
    assert {"/", "/login", "/logout", "/collect", "/data", "/mining",
            "/visualization", "/knowledge", "/api/collect",
            "/api/collect/status/<int:task_id>"} <= routes
```

- [ ] **Step 2: 运行全部自动测试并修复真实根因**

Run: `python -m pytest -q`

Expected on Python-only machine: 除明确依赖 Java/PySpark 的测试可 SKIP 外，其余全部通过；任何失败必须根据堆栈修复根因，不增加吞错兜底。

Run: `python -m compileall app.py config.py collector services analysis knowledge scheduler`

Expected: 所有 Python 文件成功编译。

Run: `git diff --check`

Expected: 无空白错误。

- [ ] **Step 3: 编写普通本科课程 README**

README 按以下固定顺序编写，不使用企业项目徽章或部署平台内容：

1. 项目介绍与课程模块对应关系。
2. Python 3.8+、Hadoop 3.x、Spark 3.x、MySQL 8.0 环境。
3. 精简项目目录。
4. `mysql -u root -p < sql/init.sql` 初始化方法和两组演示账号。
5. `start-dfs.cmd`/`start-dfs.sh` 与 `hdfs dfs -ls /bigdata_course/bilibili`。
6. WebHDFS 9870、NameNode RPC 9000 和日期目录说明。
7. Java、`spark-submit --version` 与 `local[*]` 说明。
8. `python -m venv .venv`、激活环境、`pip install -r requirements.txt`。
9. 环境变量和 `python app.py`。
10. 管理员采集 20 条的完整网页演示步骤，强调不上传 CSV。
11. 数据查询、KMeans、爆款预测、Apriori、四张 Spark 图演示。
12. AI 知识库三类问题演示。
13. HDFS/MySQL/Spark/B 站接口错误的检查方法。
14. 已知边界：公开接口限制时保存实际成功数量，0 条失败，绝不生成假数据。

- [ ] **Step 4: 在课程服务可用时执行真实端到端联调**

Run: `mysql -u root -p < sql/init.sql`

Expected: 两张表创建成功，`admin` 和 `student` 可查询。

Run: `python app.py`

Expected: Flask 在 `127.0.0.1:5000` 启动，无调度器重复注册日志。

浏览器验收顺序：管理员登录 -> `/collect` 输入“大数据技术”、昨天、20 -> 观察 `running` -> `success` 或带真实接口证据的 `failed` -> 成功时页面展示该日期最新部分视频 -> `hdfs dfs -cat /bigdata_course/bilibili/date=YYYY-MM-DD/videos.jsonl | head` 验证真实字段 -> `/data` -> `/mining` -> `/visualization` -> `/knowledge`。

Spark 验收 Run: `spark-submit --version`，然后访问 `/visualization?date=YYYY-MM-DD`。

Expected: 四个 ECharts 容器都有来自 Spark 的 TOP10 数据；若失败，页面与日志明确指出 Java、Spark 或 HDFS 根因。

知识库问题依次输入：`哪个UP主视频最多？`、`播放量最高的视频是哪个？`、`哪些视频点赞投币最高？`。

Expected: 回答中的标题、UP 主和统计值能在同日 HDFS JSON Lines 中复核。

- [ ] **Step 5: 清理过度工程化并完成最终验证提交**

检查并删除：与现有文件风格不一致的冗余注释、宽泛 `except Exception: pass`、假数据兜底、未使用抽象、`any` 风格绕过、任务结果表、评论字段、CSV 上传、分布式组件配置。保留必要的单个视频异常隔离、HDFS 文件恢复和用户可读错误边界。

Run: `python -m pytest -q`

Expected: 自动测试通过，Spark 测试仅在缺少 Java 时有明确 SKIP。

Run: `rg -n "comment_count|get_video_comments|type=.?file|upload.*csv|celery|rabbitmq|kafka|redis.*lock|partial" --glob '!docs/**' --glob '!tests/**' .`

Expected: 生产代码无命中；SQL 的合法状态集合中无 `partial`。

```bash
git add README.md tests/test_project_contract.py
git add app.py config.py collector services analysis knowledge scheduler templates static sql requirements.txt
git commit -m "docs: finish course project verification guide"
```

---

## Implementation Checkpoints

- Task 1 后：两类用户能登录，匿名访问被拦截，MySQL SQL 与代码字段一致。
- Task 4 后：优先验收采集按钮完整主链路；此时尚不进入挖掘和可视化扩展。
- Task 5 后：昨天默认值和显式日期已经贯穿首页、查询和采集结果。
- Task 6 后：用测试锁定四项互动特征，防止以后重新加入播放量或评论数量。
- Task 7 后：Spark 只读取所选 HDFS 日期并产生四张图所需结构。
- Task 8 后：三类问题可从真实记录精确回答，其他问题走本地 TF-IDF Retriever。
- Task 9 后：00:10 自动任务复用手动采集入口并归档到昨天。
- Task 10 后：自动测试、真实服务联调证据、README 和非过度工程化检查全部完成。
