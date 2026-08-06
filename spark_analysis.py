from __future__ import annotations

import logging
from pathlib import Path

from hdfs_utils import HDFS_DATA_PATH, check_hdfs_available

LOGGER = logging.getLogger(__name__)
HDFS_SPARK_PATH = f"hdfs://{HDFS_DATA_PATH}"


class SparkUnavailableError(Exception):
    """PySpark 或 Java 环境无法启动时抛出。"""


def _spark_functions():
    from pyspark.sql import functions as functions

    return functions


def create_spark_session():
    """仅在访问 Spark 页面时创建 Local Mode 会话。"""
    try:
        from pyspark.sql import SparkSession
    except ImportError as error:
        raise SparkUnavailableError("PySpark 未安装") from error

    try:
        return (
            SparkSession.builder.appName("BilibiliVideoAnalysis")
            .master("local[*]")
            .getOrCreate()
        )
    except Exception as error:
        raise SparkUnavailableError("Spark Local Mode 启动失败") from error


def select_data_source(cleaned_path: Path, raw_path: Path, hdfs_cmd: str) -> tuple[str, str | None]:
    """按 HDFS、清洗CSV、原始CSV 的顺序选择可用数据。"""
    hdfs_available, _message = check_hdfs_available(hdfs_cmd)
    if hdfs_available:
        return "HDFS", HDFS_SPARK_PATH
    if cleaned_path.exists() and cleaned_path.stat().st_size > 0:
        return "本地清洗CSV", str(cleaned_path)
    if raw_path.exists() and raw_path.stat().st_size > 0:
        return "本地原始CSV", str(raw_path)
    return "无可用数据", None


def _prepare_spark_data(data):
    functions = _spark_functions()
    for column in ("title", "up_name", "publish_time", "play_count"):
        if column not in data.columns:
            data = data.withColumn(column, functions.lit(""))

    play_text = functions.trim(functions.coalesce(functions.col("play_count"), functions.lit("")))
    normalized_play = functions.regexp_replace(play_text, "[, ]", "")
    play_value = functions.when(
        normalized_play.endswith("万"),
        functions.regexp_replace(normalized_play, "万$", "").cast("double") * 10000,
    ).otherwise(normalized_play.cast("double"))
    return (
        data.withColumn("play_count", functions.coalesce(play_value, functions.lit(0)).cast("long"))
        .withColumn("publish_time", functions.trim(functions.coalesce(functions.col("publish_time"), functions.lit(""))))
        .withColumn("up_name", functions.trim(functions.coalesce(functions.col("up_name"), functions.lit(""))))
        .withColumn("title", functions.trim(functions.coalesce(functions.col("title"), functions.lit(""))))
    )


def load_spark_data(spark, cleaned_path: Path, raw_path: Path, hdfs_cmd: str):
    """读取优先数据源；HDFS 读取失败时回退本地 CSV。"""
    source, path = select_data_source(cleaned_path, raw_path, hdfs_cmd)
    if path is None:
        return None, source

    candidates = [(source, path)]
    if source == "HDFS":
        if cleaned_path.exists() and cleaned_path.stat().st_size > 0:
            candidates.append(("本地清洗CSV", str(cleaned_path)))
        if raw_path.exists() and raw_path.stat().st_size > 0:
            candidates.append(("本地原始CSV", str(raw_path)))

    for candidate_source, candidate_path in candidates:
        try:
            data = spark.read.option("header", True).option("encoding", "UTF-8").csv(candidate_path)
            return _prepare_spark_data(data), candidate_source
        except Exception as error:
            if candidate_source == "HDFS":
                LOGGER.warning("Spark 读取 HDFS 失败，回退本地 CSV：%s", error)
                continue
            raise SparkUnavailableError("Spark 无法读取本地视频数据") from error

    raise SparkUnavailableError("Spark 无法读取 HDFS 或本地视频数据")


def _rows_to_dicts(rows) -> list[dict]:
    return [row.asDict(recursive=True) for row in rows]


def limit_chart_rows(rows: list[dict]) -> list[dict]:
    return rows[:10]


def sort_publish_trend(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=lambda row: row["publish_month"])


def analyze_up_video_count(data) -> list[dict]:
    functions = _spark_functions()
    rows = (
        data.filter(functions.col("up_name") != "")
        .groupBy("up_name")
        .count()
        .withColumnRenamed("count", "video_count")
        .orderBy(functions.desc("video_count"))
        .limit(10)
        .collect()
    )
    return limit_chart_rows(_rows_to_dicts(rows))


def analyze_top_played_videos(data) -> list[dict]:
    functions = _spark_functions()
    rows = (
        data.filter(functions.col("title") != "")
        .select("title", "play_count")
        .orderBy(functions.desc("play_count"))
        .limit(10)
        .collect()
    )
    return limit_chart_rows(_rows_to_dicts(rows))


def analyze_up_average_play(data) -> list[dict]:
    functions = _spark_functions()
    rows = (
        data.filter(functions.col("up_name") != "")
        .groupBy("up_name")
        .agg(functions.avg("play_count").alias("avg_play_count"))
        .orderBy(functions.desc("avg_play_count"))
        .limit(10)
        .collect()
    )
    return limit_chart_rows(_rows_to_dicts(rows))


def analyze_publish_trend(data) -> list[dict]:
    functions = _spark_functions()
    rows = (
        data.withColumn("publish_month", functions.substring("publish_time", 1, 7))
        .filter(functions.col("publish_month").rlike("^[0-9]{4}-[0-9]{2}$"))
        .groupBy("publish_month")
        .count()
        .withColumnRenamed("count", "video_count")
        .orderBy("publish_month")
        .collect()
    )
    return sort_publish_trend(_rows_to_dicts(rows))


def empty_analysis(source: str = "无可用数据") -> dict:
    return {
        "source": source,
        "total_count": 0,
        "up_video_count": [],
        "top_played": [],
        "up_avg_play": [],
        "publish_trend": [],
    }


def run_spark_analysis(cleaned_path: Path, raw_path: Path, hdfs_cmd: str) -> dict:
    """完成四项 Spark Local Mode 分析，并转换为模板可直接使用的字典。"""
    source, path = select_data_source(cleaned_path, raw_path, hdfs_cmd)
    if path is None:
        return empty_analysis(source)

    spark = create_spark_session()
    try:
        data, source = load_spark_data(spark, cleaned_path, raw_path, hdfs_cmd)
        if data is None:
            return empty_analysis(source)
        return {
            "source": source,
            "total_count": data.count(),
            "up_video_count": analyze_up_video_count(data),
            "top_played": analyze_top_played_videos(data),
            "up_avg_play": analyze_up_average_play(data),
            "publish_trend": analyze_publish_trend(data),
        }
    finally:
        spark.stop()
