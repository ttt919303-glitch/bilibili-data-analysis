from typing import Dict, List

from flask import current_app
from pyspark.sql import SparkSession, functions as F


def _records(dataframe) -> List[Dict]:
    return [row.asDict() for row in dataframe.collect()]


def analyze_dataframe(dataframe) -> Dict[str, List[Dict]]:
    interaction_total = (
        F.col("like_count")
        + F.col("coin_count")
        + F.col("favorite_count")
        + F.col("share_count")
    )

    up_video_count = (
        dataframe.groupBy("up_name")
        .agg(F.count("*").alias("value"))
        .orderBy(F.desc("value"))
        .limit(10)
        .select(F.col("up_name").alias("name"), "value")
    )
    top_views = (
        dataframe.orderBy(F.desc("view_count"))
        .limit(10)
        .select(F.col("title").alias("name"), F.col("view_count").alias("value"))
    )
    top_likes = (
        dataframe.orderBy(F.desc("like_count"))
        .limit(10)
        .select(F.col("title").alias("name"), F.col("like_count").alias("value"))
    )
    top_interactions = (
        dataframe.withColumn("interaction_count", interaction_total)
        .orderBy(F.desc("interaction_count"))
        .limit(10)
        .select(F.col("title").alias("name"), F.col("interaction_count").alias("value"))
    )

    return {
        "up_video_count": _records(up_video_count),
        "top_views": _records(top_views),
        "top_likes": _records(top_likes),
        "top_interactions": _records(top_interactions),
    }


def run_spark_analysis(date: str) -> Dict[str, List[Dict]]:
    path = (
        f"{current_app.config['HDFS_NAMENODE_URI']}"
        f"/bigdata_course/bilibili/date={date}/videos.jsonl"
    )
    spark = (
        SparkSession.builder.master(current_app.config["SPARK_MASTER"])
        .appName("BigDataCourseAnalysis")
        .getOrCreate()
    )
    dataframe = spark.read.json(path)
    return analyze_dataframe(dataframe)
