from __future__ import annotations

import sqlite3
import os
import threading
from datetime import datetime
from functools import wraps
from pathlib import Path

import pandas as pd
from flask import Flask, abort, flash, g, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from data_utils import (
    REQUIRED_COLUMNS,
    append_video_data,
    clean_video_data,
    get_cleaning_summary,
    load_cleaned_data,
    load_video_data,
    normalize_columns,
    parse_number,
)
from hdfs_utils import check_hdfs_available, check_hdfs_file, read_hdfs_preview, upload_cleaned_to_hdfs
from crawler import CrawlerError, crawl_bilibili
from browser_crawler import crawl_bilibili_browser
from browser_interaction_backfill import backfill_bilibili_interactions, get_supported_video_urls
from run_interaction_backfill import run_target_batches
from spark_analysis import SparkUnavailableError, run_spark_analysis
from mining import load_mining_data, run_association_rules, run_kmeans, train_hot_model, predict_hot_video, MODEL_FEATURES
from qa import answer_question, load_qa_data

PROJECT_DIR = Path(__file__).resolve().parent
BROWSER_CRAWL_LIMIT = 200
browser_crawl_lock = threading.Lock()


def get_db() -> sqlite3.Connection:
    """获取当前请求使用的 SQLite 连接。"""
    if "db" not in g:
        connection = sqlite3.connect(g.app.config["DATABASE"])
        connection.row_factory = sqlite3.Row
        g.db = connection
    return g.db


def initialize_users() -> None:
    """创建 users 表，并写入课程演示所需的两个固定账号。"""
    db = get_db()
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK (role IN ('admin', 'user'))
        )
        """
    )
    users = (
        ("admin", "admin123", "admin"),
        ("user", "user123", "user"),
    )
    for username, password, role in users:
        db.execute(
            "INSERT OR IGNORE INTO users (username, password_hash, role) VALUES (?, ?, ?)",
            (username, generate_password_hash(password), role),
        )
    db.commit()


def login_required(view):
    """未登录访问业务页面时统一回到登录页。"""

    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped_view


def admin_required(view):
    """限制数据管理页面仅允许管理员访问。"""

    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("login"))
        if g.user["role"] != "admin":
            abort(403)
        return view(*args, **kwargs)

    return wrapped_view


def create_app(test_config: dict | None = None) -> Flask:
    """创建课程项目的最小 Flask 应用。"""
    app = Flask(__name__)
    default_hdfs_web_url = os.getenv("HDFS_WEB_URL")
    if default_hdfs_web_url is None:
        default_hdfs_web_url = "" if test_config is not None else "http://192.168.8.140:50070"
    app.config.from_mapping(
        SECRET_KEY="course-project-secret-key",
        DATABASE=PROJECT_DIR / "instance" / "users.db",
        VIDEO_DATA_PATH=PROJECT_DIR / "data" / "videos.csv",
        CLEANED_DATA_PATH=PROJECT_DIR / "data" / "videos_cleaned.csv",
        CLEANING_SUMMARY_PATH=PROJECT_DIR / "data" / "cleaning_summary.json",
        HDFS_CMD=os.getenv("HDFS_CMD", "hdfs"),
        HDFS_WEB_URL=default_hdfs_web_url,
        HDFS_WEB_USER=os.getenv("HDFS_WEB_USER", "tan"),
        HDFS_DATA_PATH="/bilibili/videos_cleaned.csv",
        PORT=5052,
    )
    if test_config is not None:
        app.config.update(test_config)
        if "VIDEO_DATA_PATH" in test_config and "CLEANED_DATA_PATH" not in test_config:
            test_data_path = Path(app.config["VIDEO_DATA_PATH"])
            app.config["CLEANED_DATA_PATH"] = test_data_path.with_name("videos_cleaned.csv")
            app.config["CLEANING_SUMMARY_PATH"] = test_data_path.with_name("cleaning_summary.json")

    Path(app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)

    @app.before_request
    def load_logged_in_user() -> None:
        g.app = app
        user_id = session.get("user_id")
        g.user = None
        if user_id is not None:
            g.user = get_db().execute(
                "SELECT id, username, role FROM users WHERE id = ?", (user_id,)
            ).fetchone()

    @app.teardown_appcontext
    def close_db(_error: BaseException | None) -> None:
        db = g.pop("db", None)
        if db is not None:
            db.close()

    with app.app_context():
        g.app = app
        initialize_users()

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if g.user is not None:
            return redirect(url_for("home"))

        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            user = get_db().execute(
                "SELECT id, username, password_hash, role FROM users WHERE username = ?", (username,)
            ).fetchone()

            if user is not None and check_password_hash(user["password_hash"], password):
                session.clear()
                session["user_id"] = user["id"]
                return redirect(url_for("home"))

            flash("用户名或密码错误，请重新输入。", "danger")

        return render_template("login.html")

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.get("/")
    @login_required
    def home():
        raw_path = Path(app.config["VIDEO_DATA_PATH"])
        cleaned_path = Path(app.config["CLEANED_DATA_PATH"])
        video_data = load_cleaned_data(cleaned_path) if cleaned_path.exists() else load_video_data(raw_path)
        play_count = video_data["play_count"].map(parse_number).sum() if "play_count" in video_data else 0
        like_count = video_data["like_count"].map(parse_number).sum() if "like_count" in video_data else 0
        up_count = video_data["up_name"].nunique() if "up_name" in video_data else 0
        statistics = {
            "video_total": len(video_data),
            "up_total": int(up_count),
            "play_total": int(play_count),
            "like_total": int(like_count),
        }
        return render_template("home.html", statistics=statistics)

    @app.route("/qa", methods=["GET", "POST"])
    @login_required
    def qa_page():
        data, source = load_qa_data(Path(app.config["CLEANED_DATA_PATH"]), Path(app.config["VIDEO_DATA_PATH"]))
        answer = answer_question(request.form.get("question", ""), data) if request.method == "POST" else None
        return render_template("qa.html", data_count=len(data), source=source, answer=answer)

    @app.route("/mining", methods=["GET", "POST"])
    @login_required
    def mining_page():
        data, source = load_mining_data(Path(app.config["CLEANED_DATA_PATH"]), Path(app.config["VIDEO_DATA_PATH"]))
        context = {"data_count": len(data), "source": source, "clusters": [], "points": [], "metrics": None, "rules": [], "prediction": None}
        if len(data) < 10:
            context["message"] = "当前数据量过少，请继续采集或导入更多数据后分析。"
            return render_template("mining.html", **context)
        if request.method == "POST":
            action = request.form.get("action")
            if action == "cluster":
                context["clusters"], context["points"] = run_kmeans(data)
            elif action == "rules":
                context["rules"] = run_association_rules(data)
            elif action == "predict":
                try:
                    values = {key: max(float(request.form.get(key, "")), 0) for key in MODEL_FEATURES}
                except ValueError:
                    flash("预测输入必须为大于等于0的数字。", "danger")
                else:
                    model, context["metrics"] = train_hot_model(data)
                    context["prediction"] = predict_hot_video(model, values)
        if context["metrics"] is None:
            try:
                _model, context["metrics"] = train_hot_model(data)
            except ValueError:
                context["message"] = "当前数据类别不足，暂时无法训练爆款预测模型。"
        return render_template("mining.html", **context)

    def get_spark_analysis() -> dict:
        return run_spark_analysis(
            Path(app.config["CLEANED_DATA_PATH"]),
            Path(app.config["VIDEO_DATA_PATH"]),
            app.config["HDFS_CMD"],
        )

    @app.get("/spark")
    @login_required
    def spark_page():
        try:
            analysis = get_spark_analysis()
            spark_error = None
        except SparkUnavailableError as error:
            app.logger.warning("Spark 分析不可用：%s", error)
            analysis = {
                "source": "未启动",
                "total_count": 0,
                "up_video_count": [],
                "top_played": [],
                "up_avg_play": [],
                "publish_trend": [],
            }
            spark_error = "Spark当前无法启动，请检查Java和PySpark环境。"
        return render_template("spark.html", analysis=analysis, spark_error=spark_error)

    @app.get("/api/spark/analysis")
    @login_required
    def spark_analysis_api():
        try:
            return jsonify(get_spark_analysis())
        except SparkUnavailableError as error:
            app.logger.warning("Spark 分析接口不可用：%s", error)
            return jsonify({"error": "Spark当前无法启动，请检查Java和PySpark环境。"})

    @app.route("/data", methods=["GET", "POST"])
    @admin_required
    def data_management():
        raw_path = Path(app.config["VIDEO_DATA_PATH"])
        cleaned_path = Path(app.config["CLEANED_DATA_PATH"])
        summary_path = Path(app.config["CLEANING_SUMMARY_PATH"])
        if request.method == "POST":
            uploaded_file = request.files.get("file")
            if uploaded_file is None or uploaded_file.filename == "":
                flash("请选择需要导入的 CSV 文件。", "danger")
                return redirect(url_for("data_management"))

            safe_name = secure_filename(uploaded_file.filename)
            if not safe_name or Path(uploaded_file.filename).suffix.lower() != ".csv":
                flash("只支持上传 .csv 文件。", "danger")
                return redirect(url_for("data_management"))

            try:
                uploaded_data = pd.read_csv(uploaded_file, dtype=object, encoding="utf-8-sig")
            except (UnicodeDecodeError, pd.errors.EmptyDataError, pd.errors.ParserError):
                flash("CSV 文件无法读取，请确认文件为 UTF-8 编码的有效 CSV。", "danger")
                return redirect(url_for("data_management"))

            normalized_data = normalize_columns(uploaded_data)
            missing_columns = [column for column in REQUIRED_COLUMNS if column not in normalized_data]
            if missing_columns:
                flash(f"CSV缺少必要字段：{', '.join(missing_columns)}", "danger")
                return redirect(url_for("data_management"))

            imported_count = len(normalized_data)
            total_count = append_video_data(normalized_data, raw_path)
            flash(f"本次成功导入 {imported_count} 条视频数据，当前数据集共有 {total_count} 条数据。", "success")
            return redirect(url_for("data_management"))

        video_data = load_cleaned_data(cleaned_path) if cleaned_path.exists() else load_video_data(raw_path)
        raw_total_count = len(load_video_data(raw_path))
        hdfs_available, hdfs_message = check_hdfs_available(
            app.config["HDFS_CMD"],
            app.config["HDFS_WEB_URL"],
            app.config["HDFS_WEB_USER"],
        )
        hdfs_file_exists = False
        if hdfs_available:
            hdfs_file_exists, _file_message = check_hdfs_file(
                app.config["HDFS_CMD"],
                app.config["HDFS_WEB_URL"],
                app.config["HDFS_WEB_USER"],
            )
        recent_videos = video_data.tail(100).iloc[::-1].to_dict(orient="records")
        return render_template(
            "data.html",
            total_count=len(video_data),
            recent_videos=recent_videos,
            data_source="清洗数据" if cleaned_path.exists() else "原始数据",
            cleaning_summary=get_cleaning_summary(raw_path, cleaned_path, summary_path),
            hdfs_available=hdfs_available,
            hdfs_message=hdfs_message,
            hdfs_file_exists=hdfs_file_exists,
            hdfs_preview=session.pop("hdfs_preview", None),
            crawl_result=session.pop("crawl_result", None),
            browser_crawl_result=session.pop("browser_crawl_result", None),
            browser_backfill_result=session.pop("browser_backfill_result", None),
            raw_total_count=raw_total_count,
            crawl_progress=min(raw_total_count / 10_000 * 100, 100),
        )

    @app.post("/data/browser-crawl")
    @admin_required
    def browser_crawl_data():
        keyword = request.form.get("keyword", "").strip()
        limit_text = request.form.get("limit", "").strip()
        if not keyword:
            flash("请输入采集关键词。", "danger")
            return redirect(url_for("data_management"))

        try:
            limit = int(limit_text)
        except ValueError:
            flash("浏览器采集数量必须为1~200之间的整数。", "danger")
            return redirect(url_for("data_management"))

        if not 1 <= limit <= BROWSER_CRAWL_LIMIT:
            flash("浏览器采集数量必须为1~200之间的整数。", "danger")
            return redirect(url_for("data_management"))

        if not browser_crawl_lock.acquire(blocking=False):
            flash("浏览器采集任务正在运行，请等待当前任务完成。", "danger")
            return redirect(url_for("data_management"))

        result = None
        interaction_result = None
        raw_path = Path(app.config["VIDEO_DATA_PATH"])
        try:
            existing_urls = set(get_supported_video_urls(raw_path))
            result = crawl_bilibili_browser(keyword, limit)
            if int(result["saved_count"]) > 0:
                current_urls = get_supported_video_urls(raw_path)
                new_urls = [url for url in current_urls if url not in existing_urls]
                if not new_urls:
                    raise RuntimeError("browser crawl reported saved rows without new supported video URLs")
                interaction_result = run_target_batches(
                    new_urls,
                    report=lambda batch: app.logger.info(
                        "浏览器详情互动采集批次：batch=%s status=%s updated=%s remaining=%s",
                        batch.get("batch"),
                        batch.get("status"),
                        batch.get("updated_count"),
                        batch.get("remaining_count"),
                    )
                )
        except Exception as error:
            app.logger.exception("浏览器采集无法启动：%s", error)
            if result is None:
                flash("浏览器采集无法启动，请确认Microsoft Edge未被项目其他采集任务占用。", "danger")
            else:
                flash("搜索页数据已经保存，但详情互动数据采集失败，请查看应用日志。", "danger")
            return redirect(url_for("data_management"))
        finally:
            browser_crawl_lock.release()

        saved_count = int(result["saved_count"])
        status = str(result["status"])
        interaction_status = str(interaction_result["status"]) if interaction_result else "not_started"
        interaction_updated_count = int(interaction_result["updated_count"]) if interaction_result else 0
        interaction_remaining_count = int(interaction_result["remaining_count"]) if interaction_result else 0
        summary_status = interaction_status if interaction_status in {"partial", "verification_required"} else status
        session["browser_crawl_result"] = {
            "keyword": keyword,
            "planned_count": limit,
            "saved_count": saved_count,
            "parsed_count": int(result["parsed_count"]),
            "skipped_count": int(result["skipped_count"]),
            "page_count": int(result["page_count"]),
            "total_count": len(load_video_data(raw_path)),
            "interaction_updated_count": interaction_updated_count,
            "interaction_remaining_count": interaction_remaining_count,
            "interaction_status": interaction_status,
            "status": {
                "success": "正常完成",
                "partial": "部分完成",
                "no_results": "没有搜索结果",
                "verification_required": "需要人工验证",
                "page_structure_error": "页面结构异常",
                "page_timeout": "页面加载超时",
            }.get(summary_status, summary_status),
        }

        if interaction_status == "verification_required":
            flash(
                f"搜索页已新增 {saved_count} 条；详情互动数据采集需要人工验证，已完成 {interaction_updated_count} 条。",
                "danger",
            )
        elif interaction_status == "partial":
            flash(
                f"搜索页已新增 {saved_count} 条；详情互动采集完成 {interaction_updated_count} 条，仍有 {interaction_remaining_count} 条未完成。",
                "warning",
            )
        elif status == "success":
            flash(
                f"浏览器采集完成：成功新增 {saved_count} 条视频数据，并同步采集 {interaction_updated_count} 条详情互动数据。",
                "success",
            )
        elif status == "verification_required":
            flash("B站页面需要人工验证，本次已成功采集的数据已经保存，请完成验证后再继续。", "danger")
        elif status == "page_structure_error":
            flash("暂时无法识别B站搜索页面结构，请稍后检查页面。", "danger")
        elif status == "no_results":
            flash(f"B站搜索成功，但未找到与“{keyword}”相关的视频。", "danger")
        elif status == "partial":
            flash(f"计划采集{limit}条，本次成功新增{saved_count}条。", "warning")
        else:
            flash("浏览器页面加载超时，本次已成功采集的数据已经保存，请稍后再试。", "danger")
        return redirect(url_for("data_management"))

    @app.post("/data/browser-backfill")
    @admin_required
    def browser_backfill_data():
        if not browser_crawl_lock.acquire(blocking=False):
            flash("浏览器采集任务正在运行，请等待当前任务完成。", "danger")
            return redirect(url_for("data_management"))

        try:
            result = backfill_bilibili_interactions(limit=50)
        except Exception as error:
            app.logger.exception("浏览器互动数据回填失败：%s", error)
            flash("互动数据回填无法启动，请确认Microsoft Edge未被项目其他采集任务占用。", "danger")
            return redirect(url_for("data_management"))
        finally:
            browser_crawl_lock.release()

        status = str(result["status"])
        updated_count = int(result["updated_count"])
        raw_total_count = len(load_video_data(Path(app.config["VIDEO_DATA_PATH"])))
        session["browser_backfill_result"] = {
            "planned_count": int(result["planned_count"]),
            "updated_count": updated_count,
            "processed_count": int(result["processed_count"]),
            "skipped_count": int(result["skipped_count"]),
            "failed_count": int(result.get("failed_count", 0)),
            "remaining_count": int(result.get("remaining_count", 0)),
            "total_count": raw_total_count,
            "status": {
                "success": "正常完成",
                "partial": "部分完成",
                "verification_required": "需要人工验证",
                "page_structure_error": "页面结构异常",
                "page_timeout": "页面加载超时",
            }.get(status, status),
        }

        if status == "success":
            flash(f"互动数据回填完成：成功回填 {updated_count} 条视频数据。", "success")
        elif status == "partial":
            flash(
                f"互动数据本批部分完成：成功回填{updated_count}条，跳过{int(result['skipped_count'])}条；失败链接已记录，后续批次会有限重试。",
                "warning",
            )
        elif status == "verification_required":
            flash("B站页面需要人工验证，已成功回填的数据已经保存，请完成验证后再继续。", "danger")
        elif status == "page_structure_error":
            flash("暂时无法识别B站视频详情页互动数据结构，请稍后检查页面。", "danger")
        else:
            flash("B站视频详情页加载超时，已成功回填的数据已经保存，请稍后再试。", "danger")
        return redirect(url_for("data_management"))

    @app.post("/data/crawl")
    @admin_required
    def crawl_data():
        keyword = request.form.get("keyword", "").strip()
        limit_text = request.form.get("limit", "").strip()
        try:
            limit = int(limit_text)
        except ValueError:
            flash("采集数量必须为1~1000之间的整数。", "danger")
            return redirect(url_for("data_management"))

        if not 1 <= limit <= 1000:
            flash("采集数量必须为1~1000之间的整数。", "danger")
            return redirect(url_for("data_management"))

        try:
            crawled_data = crawl_bilibili(keyword, limit)
        except CrawlerError as error:
            app.logger.warning("B站采集失败：%s", error)
            flash(str(error), "danger")
            return redirect(url_for("data_management"))

        if crawled_data.empty:
            flash(f"B站搜索成功，但未找到与“{keyword}”相关的视频。", "danger")
            return redirect(url_for("data_management"))

        raw_path = Path(app.config["VIDEO_DATA_PATH"])
        total_count = append_video_data(normalize_columns(crawled_data), raw_path)
        crawl_status = crawled_data.attrs.get("crawl_status", "completed")
        crawl_message = crawled_data.attrs.get("crawl_message", "")
        session["crawl_result"] = {
            "keyword": keyword,
            "planned_count": limit,
            "success_count": len(crawled_data),
            "total_count": total_count,
            "page_count": crawled_data.attrs.get("page_count", 1),
            "status": {
                "completed": "正常完成",
                "insufficient": "搜索结果不足",
                "partial": "网络请求中断",
                "limited": "B站暂时限制后续搜索请求",
            }.get(crawl_status, "正常完成"),
            "message": crawl_message,
            "crawl_time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        flash(f"采集完成：成功采集 {len(crawled_data)} 条视频数据。", "success")
        return redirect(url_for("data_management"))

    @app.post("/data/clean")
    @admin_required
    def clean_data():
        raw_path = Path(app.config["VIDEO_DATA_PATH"])
        cleaned_path = Path(app.config["CLEANED_DATA_PATH"])
        summary_path = Path(app.config["CLEANING_SUMMARY_PATH"])
        if load_video_data(raw_path).empty:
            flash("暂无可清洗的视频数据，请先使用 B 站采集。", "danger")
            return redirect(url_for("data_management"))

        summary = clean_video_data(raw_path, cleaned_path, summary_path)
        flash(
            f"数据清洗完成：原始 {summary['raw_count']} 条，清洗后 {summary['cleaned_count']} 条，删除重复 {summary['duplicate_count']} 条。",
            "success",
        )
        return redirect(url_for("data_management"))

    @app.post("/data/hdfs/upload")
    @admin_required
    def upload_hdfs_data():
        success, message = upload_cleaned_to_hdfs(
            Path(app.config["CLEANED_DATA_PATH"]),
            app.config["HDFS_CMD"],
            app.config["HDFS_WEB_URL"],
            app.config["HDFS_WEB_USER"],
        )
        flash(message, "success" if success else "danger")
        return redirect(url_for("data_management"))

    @app.post("/data/hdfs/verify")
    @admin_required
    def verify_hdfs_data():
        available, _message = check_hdfs_available(
            app.config["HDFS_CMD"],
            app.config["HDFS_WEB_URL"],
            app.config["HDFS_WEB_USER"],
        )
        if not available:
            flash("HDFS服务当前不可用，请检查Hadoop是否启动。", "danger")
            return redirect(url_for("data_management"))

        exists, _message = check_hdfs_file(
            app.config["HDFS_CMD"],
            app.config["HDFS_WEB_URL"],
            app.config["HDFS_WEB_USER"],
        )
        if not exists:
            flash("HDFS中暂未找到 videos_cleaned.csv", "danger")
            return redirect(url_for("data_management"))

        success, preview = read_hdfs_preview(
            app.config["HDFS_CMD"],
            hdfs_url=app.config["HDFS_WEB_URL"],
            hdfs_user=app.config["HDFS_WEB_USER"],
        )
        if not success:
            flash(f"HDFS读取失败：{preview}", "danger")
            return redirect(url_for("data_management"))

        session["hdfs_preview"] = preview
        flash("HDFS文件存在，读取成功。", "success")
        return redirect(url_for("data_management"))

    @app.errorhandler(403)
    def forbidden(_error):
        return render_template("403.html"), 403

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(port=app.config["PORT"])
