from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from langchain_core.documents import Document

from knowledge_base import KnowledgeBaseService, build_video_documents
from qa import answer_question


def video_data() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "title": "Spark 大数据入门教程",
                "video_url": "https://www.bilibili.com/video/BVspark",
                "up_name": "数据老师",
                "play_count": 5000,
                "like_count": 600,
                "coin_count": 100,
                "favorite_count": 300,
                "share_count": 20,
                "comment_count": 80,
                "publish_time": "2026-08-06",
            },
            {
                "title": "Python 爬虫基础",
                "video_url": "https://www.bilibili.com/video/BVpython",
                "up_name": "编程老师",
                "play_count": 3000,
                "like_count": 200,
                "coin_count": 30,
                "favorite_count": 90,
                "share_count": 10,
                "comment_count": 40,
                "publish_time": "2026-08-06",
            },
        ]
    )


def test_langchain_documents_contain_all_required_video_fields():
    documents = build_video_documents(video_data().iloc[:1])

    assert len(documents) == 1
    assert isinstance(documents[0], Document)
    for expected in ("标题：Spark 大数据入门教程", "UP主：数据老师", "视频链接：", "播放量：5000", "点赞：600", "投币：100", "收藏：300", "分享：20", "评论：80", "发布时间：2026-08-06"):
        assert expected in documents[0].page_content


def test_local_retriever_finds_expected_spark_video(tmp_path: Path):
    session = KnowledgeBaseService(tmp_path).prepare(video_data(), "2026-08-06", "HDFS（WebHDFS）")

    hits = session.retriever.invoke("推荐适合学习 Spark 和大数据入门的视频")

    assert hits[0].metadata["title"] == "Spark 大数据入门教程"
    assert (tmp_path / "2026-08-06" / "index.joblib").exists()
    assert (tmp_path / "2026-08-06" / "metadata.json").exists()


def test_semantic_answer_displays_retrieved_titles_and_source(tmp_path: Path):
    data = video_data()
    session = KnowledgeBaseService(tmp_path).prepare(data, "2026-08-06", "本地清洗CSV")

    answer = answer_question("推荐几条适合学习Spark的视频。", data, retriever=session.retriever)

    assert "Spark 大数据入门教程" in answer
    assert "检索命中" in answer


def test_exact_statistics_still_use_pandas_instead_of_retriever(tmp_path: Path):
    data = video_data()
    session = KnowledgeBaseService(tmp_path).prepare(data, "2026-08-06", "本地清洗CSV")

    answer = answer_question("当前有多少视频？", data, retriever=session.retriever)

    assert "2条视频" in answer


def test_different_dates_use_different_index_data(tmp_path: Path):
    service = KnowledgeBaseService(tmp_path)
    first = service.prepare(video_data().iloc[:1], "2026-08-06", "本地清洗CSV")
    other_data = video_data().iloc[[1]].assign(title="Flink 流处理实战", publish_time="2026-08-05")
    second = service.prepare(other_data, "2026-08-05", "本地清洗CSV")

    assert first.retriever.invoke("Spark")[0].metadata["title"] == "Spark 大数据入门教程"
    assert second.retriever.invoke("Flink")[0].metadata["title"] == "Flink 流处理实战"
    assert (tmp_path / "2026-08-06" / "index.joblib").exists()
    assert (tmp_path / "2026-08-05" / "index.joblib").exists()


def test_source_data_change_rebuilds_index_fingerprint(tmp_path: Path):
    service = KnowledgeBaseService(tmp_path)
    service.prepare(video_data().iloc[:1], "2026-08-06", "本地清洗CSV")
    metadata_path = tmp_path / "2026-08-06" / "metadata.json"
    first_fingerprint = json.loads(metadata_path.read_text(encoding="utf-8"))["fingerprint"]

    changed = video_data().iloc[:1].assign(like_count=999)
    service.prepare(changed, "2026-08-06", "本地清洗CSV")
    second_fingerprint = json.loads(metadata_path.read_text(encoding="utf-8"))["fingerprint"]

    assert first_fingerprint != second_fingerprint
