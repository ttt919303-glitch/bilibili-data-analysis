from functools import wraps
import threading
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import pymysql
from flask import Flask, current_app, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from analysis.mining import MiningDataError, run_apriori, run_hot_prediction, run_kmeans
from analysis.spark_analysis import run_spark_analysis
from collector.bilibili_collector import CollectorError, clean_video_data, collect
from config import Config
from knowledge.qa import answer_question, build_retriever
from scheduler.jobs import build_scheduler
from services.database_initializer import initialize_database
from services.hdfs_service import (
    HdfsServiceError,
    read_from_hdfs,
    read_raw_from_hdfs,
    save_raw_to_hdfs,
    save_to_hdfs,
)


TASK_UPDATE_COLUMNS = {"success_count", "status", "finished_at", "message"}
TASK_PROGRESS = {}
TASK_PROGRESS_LOCK = threading.Lock()
COLLECTION_DATE_LOCKS = {}
COLLECTION_DATE_LOCKS_GUARD = threading.Lock()
PAGE_SIZE = 20
SHANGHAI_TIMEZONE = timezone(timedelta(hours=8))
HDFS_CONNECTION_ERROR = "连接 HDFS 失败，请检查 Hadoop/HDFS 是否启动。"


def yesterday_string(now: Optional[datetime] = None) -> str:
    reference_time = now or datetime.now()
    return (reference_time.date() - timedelta(days=1)).isoformat()


def current_local_datetime() -> datetime:
    return datetime.now(SHANGHAI_TIMEZONE)


def run_scheduled_collection(app: Flask) -> None:
    with app.app_context():
        collect_date = yesterday_string(current_local_datetime())
        keyword = app.config["DEFAULT_KEYWORD"]
        target_count = app.config["DEFAULT_TARGET_COUNT"]
        task_id = create_task(keyword, target_count, collect_date)
        app.logger.info(
            "Scheduled collection task created: task_id=%s, keyword=%s, target_count=%s, collect_date=%s",
            task_id,
            keyword,
            target_count,
            collect_date,
        )
        run_collection_task(app, task_id, keyword, target_count, collect_date)


def selected_date(value: Optional[str]) -> str:
    if value is None or value == "":
        return yesterday_string()

    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("日期必须为 YYYY-MM-DD 格式") from exc
    if parsed.isoformat() != value:
        raise ValueError("日期必须为 YYYY-MM-DD 格式")
    return value


def get_db_connection() -> pymysql.Connection:
    return pymysql.connect(
        host=current_app.config["MYSQL_HOST"],
        port=current_app.config["MYSQL_PORT"],
        user=current_app.config["MYSQL_USER"],
        password=current_app.config["MYSQL_PASSWORD"],
        database=current_app.config["MYSQL_DATABASE"],
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
    )


def find_user(username: str) -> Optional[dict]:
    with get_db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
            return cursor.fetchone()


def create_task(keyword: str, target_count: int, collect_date: str) -> int:
    with get_db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO collection_tasks
                    (keyword, target_count, success_count, status, collect_date, message)
                VALUES (%s, %s, 0, 'waiting', %s, '')
                """,
                (keyword, target_count, collect_date),
            )
            return cursor.lastrowid


def update_task(task_id: int, **values) -> None:
    if not values:
        raise ValueError("Task update cannot be empty")

    invalid_columns = set(values) - TASK_UPDATE_COLUMNS
    if invalid_columns:
        raise ValueError(f"Unsupported task columns: {sorted(invalid_columns)}")

    assignments = ", ".join(f"{column} = %s" for column in values)
    parameters = (*values.values(), task_id)
    with get_db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"UPDATE collection_tasks SET {assignments} WHERE id = %s",
                parameters,
            )


def get_task(task_id: int) -> Optional[dict]:
    with get_db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM collection_tasks WHERE id = %s", (task_id,))
            return cursor.fetchone()


def latest_videos(collect_date: str, limit: int = 10) -> list:
    return list(reversed(read_raw_from_hdfs(collect_date)))[:limit]


def unique_bvids(records: list) -> set:
    return {record["bvid"] for record in records if record.get("bvid")}


def _set_task_progress(task_id: int, existing_count: int, added_count: int) -> None:
    with TASK_PROGRESS_LOCK:
        TASK_PROGRESS[task_id] = {
            "existing_count": existing_count,
            "added_count": added_count,
            "total_count": existing_count + added_count,
        }


def _get_task_progress(task_id: int) -> dict:
    with TASK_PROGRESS_LOCK:
        return TASK_PROGRESS.get(
            task_id,
            {"existing_count": None, "added_count": 0, "total_count": None},
        ).copy()


def _collection_lock_for_date(collect_date: str) -> threading.Lock:
    with COLLECTION_DATE_LOCKS_GUARD:
        return COLLECTION_DATE_LOCKS.setdefault(collect_date, threading.Lock())


def run_collection_task(
    app: Flask,
    task_id: int,
    keyword: str,
    target_count: int,
    collect_date: str,
) -> None:
    with app.app_context():
        with _collection_lock_for_date(collect_date):
            try:
                update_task(task_id, status="running", message="")
                existing_records = read_raw_from_hdfs(collect_date)
                existing_bvids = unique_bvids(existing_records)
                existing_count = len(existing_bvids)
                _set_task_progress(task_id, existing_count, 0)
                app.logger.info(
                    "Collection task started: task_id=%s, keyword=%s, target_count=%s, "
                    "collect_date=%s, existing_count=%s",
                    task_id,
                    keyword,
                    target_count,
                    collect_date,
                    existing_count,
                )
                raw_videos = collect(
                    keyword,
                    target_count,
                    collect_date,
                    exclude_bvids=existing_bvids,
                    task_id=task_id,
                )
                if not raw_videos:
                    app.logger.info(
                        "Collection task found no new videos: task_id=%s, keyword=%s, "
                        "existing_count=%s, new_bvid_count=0",
                        task_id,
                        keyword,
                        existing_count,
                    )
                    update_task(
                        task_id,
                        status="failed",
                        success_count=0,
                        finished_at=datetime.now(),
                        message="该关键词未发现新的唯一视频",
                    )
                    return

                added_count = save_raw_to_hdfs(raw_videos, collect_date)
                total_count = len(unique_bvids(read_raw_from_hdfs(collect_date)))
                _set_task_progress(task_id, existing_count, added_count)
                if added_count == 0:
                    update_task(
                        task_id,
                        status="failed",
                        success_count=0,
                        finished_at=datetime.now(),
                        message="该关键词未发现新的唯一视频",
                    )
                    return
                message = "采集完成"
                if added_count < target_count:
                    message = f"目标新增{target_count}条，实际新增{added_count}条"
                update_task(
                    task_id,
                    status="success",
                    success_count=added_count,
                    finished_at=datetime.now(),
                    message=message,
                )
                app.logger.info(
                    "Collection task raw data saved: task_id=%s, collect_date=%s, "
                    "existing_count=%s, added_count=%s, total_count=%s, raw_path=%s",
                    task_id,
                    collect_date,
                    existing_count,
                    added_count,
                    total_count,
                    f"/bigdata_course/bilibili/date={collect_date}/videos_raw.jsonl",
                )
            except CollectorError:
                app.logger.exception(
                    "Collection task failed: task_id=%s, keyword=%s, collect_date=%s",
                    task_id,
                    keyword,
                    collect_date,
                )
                update_task(
                    task_id,
                    status="failed",
                    success_count=0,
                    finished_at=datetime.now(),
                    message="B站数据采集失败，请检查网络连接或接口状态。",
                )
            except HdfsServiceError:
                app.logger.exception(
                    "Collection task failed: task_id=%s, keyword=%s, collect_date=%s",
                    task_id,
                    keyword,
                    collect_date,
                )
                update_task(
                    task_id,
                    status="failed",
                    success_count=0,
                    finished_at=datetime.now(),
                    message="数据保存到 HDFS 失败，请检查 Hadoop/HDFS 是否启动。",
                )
            except Exception as exc:
                app.logger.exception(
                    "Collection task failed: task_id=%s, keyword=%s, collect_date=%s",
                    task_id,
                    keyword,
                    collect_date,
                )
                update_task(
                    task_id,
                    status="failed",
                    success_count=0,
                    finished_at=datetime.now(),
                    message=str(exc)[:500],
                )


def _parse_collect_request(payload: object) -> tuple:
    if not isinstance(payload, dict):
        raise ValueError("请求体必须是 JSON 对象")

    keyword = payload.get("keyword")
    collect_date = payload.get("date")
    target_count = payload.get("target_count")
    if not isinstance(keyword, str) or not keyword.strip():
        raise ValueError("关键字不能为空")
    if not isinstance(collect_date, str) or not collect_date:
        raise ValueError("日期必须为 YYYY-MM-DD 格式")
    collect_date = selected_date(collect_date)
    if isinstance(target_count, bool) or not isinstance(target_count, int):
        raise ValueError("目标数量必须是整数")
    if not 1 <= target_count <= 50000:
        raise ValueError("目标数量必须在 1 到 50000 之间")
    return keyword.strip(), target_count, collect_date


def _date_string(value: object) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()[:10]
    return str(value)


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
            return {"message": "只有管理员可以执行此操作"}, 403
        return view(*args, **kwargs)

    return wrapped


def create_app(test_config: Optional[dict] = None) -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)
    initialize_database(app)

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
        try:
            collect_date = selected_date(request.args.get("date"))
        except ValueError as exc:
            return str(exc), 400

        try:
            videos = read_from_hdfs(collect_date)
        except HdfsServiceError:
            app.logger.exception("Dashboard HDFS read failed: date=%s", collect_date)
            metrics = {
                "video_count": "--",
                "total_views": "--",
                "total_likes": "--",
                "total_coins": "--",
            }
            top_videos = []
            error = HDFS_CONNECTION_ERROR
        else:
            metrics = {
                "video_count": len(videos),
                "total_views": sum(video["view_count"] for video in videos),
                "total_likes": sum(video["like_count"] for video in videos),
                "total_coins": sum(video["coin_count"] for video in videos),
            }
            top_videos = sorted(
                videos, key=lambda video: video["view_count"], reverse=True
            )[:5]
            error = None
        app.logger.info(
            "Dashboard loaded: date=%s, video_count=%s",
            collect_date,
            metrics["video_count"],
        )
        return render_template(
            "index.html",
            selected_date=collect_date,
            metrics=metrics,
            top_videos=top_videos,
            error=error,
        )

    @app.get("/data")
    @login_required
    def data_page():
        try:
            collect_date = selected_date(request.args.get("date"))
        except ValueError as exc:
            return str(exc), 400

        try:
            page = int(request.args.get("page", "1"))
        except ValueError:
            return "页码必须是整数", 400
        if page < 1:
            return "页码必须大于或等于 1", 400

        query = request.args.get("q", "")
        query_key = query.casefold()
        try:
            videos = read_from_hdfs(collect_date)
        except HdfsServiceError:
            app.logger.exception("Data page HDFS read failed: date=%s", collect_date)
            videos = []
            dataset_count = None
            error = HDFS_CONNECTION_ERROR
        else:
            dataset_count = len(videos)
            error = None
        filtered_videos = [
            video
            for video in videos
            if query_key in video["title"].casefold()
            or query_key in video["up_name"].casefold()
        ]
        start = (page - 1) * PAGE_SIZE
        total_pages = (len(filtered_videos) + PAGE_SIZE - 1) // PAGE_SIZE
        app.logger.info(
            "Data query loaded: date=%s, query=%s, page=%s, result_count=%s",
            collect_date,
            query,
            page,
            len(filtered_videos),
        )
        return render_template(
            "data.html",
            selected_date=collect_date,
            query=query,
            videos=filtered_videos[start : start + PAGE_SIZE],
            page=page,
            total_pages=total_pages,
            dataset_count=dataset_count,
            error=error,
        )

    @app.get("/mining")
    @login_required
    def mining_page():
        try:
            collect_date = selected_date(request.args.get("date"))
        except ValueError as exc:
            return str(exc), 400

        results = {}
        errors = {}
        try:
            videos = read_from_hdfs(collect_date)
        except HdfsServiceError:
            app.logger.exception("Mining page HDFS read failed: date=%s", collect_date)
            videos = []
            error = HDFS_CONNECTION_ERROR
            no_data = False
        else:
            error = None
            no_data = not videos
            if videos:
                algorithms = {
                    "kmeans": run_kmeans,
                    "hot_prediction": run_hot_prediction,
                    "apriori": run_apriori,
                }
                for name, algorithm in algorithms.items():
                    try:
                        results[name] = algorithm(videos)
                    except MiningDataError as exc:
                        errors[name] = str(exc)
                        app.logger.warning(
                            "Mining algorithm unavailable: algorithm=%s, date=%s, reason=%s",
                            name,
                            collect_date,
                            exc,
                        )

        app.logger.info(
            "Mining page loaded: date=%s, video_count=%s, errors=%s",
            collect_date,
            len(videos),
            sorted(errors),
        )
        return render_template(
            "mining.html",
            selected_date=collect_date,
            results=results,
            errors=errors,
            error=error,
            no_data=no_data,
            video_count=len(videos),
        )

    @app.route("/collect")
    @login_required
    @admin_required
    def collect_page():
        try:
            collect_date = selected_date(request.args.get("date"))
        except ValueError as exc:
            return str(exc), 400

        course_target = app.config["COURSE_DATASET_TARGET"]
        try:
            existing_count = len(unique_bvids(read_raw_from_hdfs(collect_date)))
        except HdfsServiceError:
            app.logger.exception(
                "Collection progress HDFS read failed: date=%s", collect_date
            )
            existing_count = None
            completion_percent = None
            progress_width = 0
        else:
            completion_percent = existing_count / course_target * 100
            progress_width = min(completion_percent, 100)

        return render_template(
            "collect.html",
            selected_date=collect_date,
            course_target=course_target,
            existing_count=existing_count,
            completion_percent=completion_percent,
            progress_width=progress_width,
        )

    @app.get("/visualization")
    @login_required
    def visualization_page():
        try:
            collect_date = selected_date(request.args.get("date"))
        except ValueError as exc:
            return str(exc), 400

        try:
            analysis = run_spark_analysis(collect_date)
        except Exception:
            app.logger.exception("Spark analysis failed: date=%s", collect_date)
            return render_template(
                "visualization.html",
                selected_date=collect_date,
                analysis=None,
                error="Spark 分析失败，请检查 Spark、Java 和 HDFS 环境",
            )

        return render_template(
            "visualization.html",
            selected_date=collect_date,
            analysis=analysis,
            error=None,
        )

    @app.route("/knowledge", methods=["GET", "POST"])
    @login_required
    def knowledge_page():
        try:
            date_value = (
                request.form.get("date")
                if request.method == "POST"
                else request.args.get("date")
            )
            collect_date = selected_date(date_value)
        except ValueError as exc:
            return str(exc), 400

        question = request.form.get("question", "")
        if request.method == "POST" and not question.strip():
            return "问题不能为空", 400

        try:
            videos = read_from_hdfs(collect_date)
            if request.method == "POST":
                answer = answer_question(videos, question.strip())
            else:
                build_retriever(videos)
                answer = None
        except Exception:
            app.logger.exception("Knowledge base construction failed: date=%s", collect_date)
            return render_template(
                "knowledge.html",
                selected_date=collect_date,
                question=question,
                answer=None,
                error="知识库构建失败",
            )

        app.logger.info(
            "Knowledge page loaded: date=%s, video_count=%s, has_question=%s",
            collect_date,
            len(videos),
            bool(question.strip()),
        )
        return render_template(
            "knowledge.html",
            selected_date=collect_date,
            question=question,
            answer=answer,
            error=None,
        )

    @app.post("/api/collect")
    @login_required
    @admin_required
    def start_collection():
        try:
            keyword, target_count, collect_date = _parse_collect_request(
                request.get_json(silent=True)
            )
        except ValueError as exc:
            return {"message": str(exc)}, 400

        task_id = create_task(keyword, target_count, collect_date)
        app.logger.info(
            "Collection task created: task_id=%s, keyword=%s, target_count=%s, collect_date=%s",
            task_id,
            keyword,
            target_count,
            collect_date,
        )
        threading.Thread(
            target=run_collection_task,
            args=(app, task_id, keyword, target_count, collect_date),
            daemon=True,
        ).start()
        return {"task_id": task_id}, 202

    @app.post("/api/clean")
    @login_required
    @admin_required
    def clean_data():
        payload = request.get_json(silent=True)
        if (
            not isinstance(payload, dict)
            or not isinstance(payload.get("date"), str)
            or not payload["date"]
        ):
            return {"message": "日期必须为 YYYY-MM-DD 格式"}, 400
        try:
            clean_date = selected_date(payload["date"])
        except ValueError as exc:
            return {"message": str(exc)}, 400

        try:
            raw_records = read_raw_from_hdfs(clean_date)
            if not raw_records:
                return {"message": "该日期暂无原始采集数据"}, 404

            cleaned_records = clean_video_data(raw_records)
            if not cleaned_records:
                return {"message": "清洗后没有可保存的数据"}, 422

            save_to_hdfs(cleaned_records, clean_date)
        except Exception:
            current_app.logger.exception("Manual cleaning failed: date=%s", clean_date)
            return {
                "message": "数据清洗失败，请查看服务日志并检查 HDFS 与数据格式"
            }, 500
        before_count = len(raw_records)
        after_count = len(cleaned_records)
        current_app.logger.info(
            "Manual cleaning completed: date=%s, before_count=%s, after_count=%s",
            clean_date,
            before_count,
            after_count,
        )
        return {
            "before_count": before_count,
            "after_count": after_count,
            "removed_count": before_count - after_count,
            "message": "数据清洗完成",
        }

    @app.get("/api/collect/status/<int:task_id>")
    @login_required
    def collection_status(task_id: int):
        task = get_task(task_id)
        if task is None:
            return {"message": "采集任务不存在"}, 404

        videos = []
        note = ""
        progress = _get_task_progress(task_id)
        if task["status"] in {"success", "failed"} and progress["total_count"] is not None:
            counts = progress
            raw_records = None
            if task["status"] == "success":
                try:
                    raw_records = read_raw_from_hdfs(_date_string(task["collect_date"]))
                except HdfsServiceError:
                    app.logger.exception(
                        "Collection status HDFS read failed: task_id=%s, collect_date=%s",
                        task_id,
                        task["collect_date"],
                    )
        elif task["status"] in {"success", "failed"}:
            added_count = task["success_count"]
            try:
                raw_records = read_raw_from_hdfs(_date_string(task["collect_date"]))
            except HdfsServiceError:
                app.logger.exception(
                    "Collection status HDFS read failed: task_id=%s, collect_date=%s",
                    task_id,
                    task["collect_date"],
                )
                counts = {
                    "existing_count": None,
                    "added_count": added_count,
                    "total_count": None,
                }
            else:
                total_count = len(unique_bvids(raw_records))
                counts = {
                    "existing_count": None,
                    "added_count": added_count,
                    "total_count": total_count,
                }
        else:
            counts = progress
        if task["status"] == "success" and raw_records is not None:
            videos = list(reversed(raw_records))[:10]
            note = "该日期最新原始采集数据（最多10条）"
        return {
            **task,
            **counts,
            "course_target": app.config["COURSE_DATASET_TARGET"],
            "latest_videos": videos,
            "latest_videos_note": note,
        }

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    if app.config["ENABLE_SCHEDULER"]:
        scheduler = build_scheduler(lambda: run_scheduled_collection(app))
        scheduler.start()
        app.extensions["course_scheduler"] = scheduler

    return app


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=5000, debug=False)
