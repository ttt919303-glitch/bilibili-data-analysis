from typing import Dict, List

import pandas as pd
from langchain_community.retrievers import TFIDFRetriever
from langchain_core.documents import Document


class KnowledgeBaseError(ValueError):
    pass


def build_documents(records: List[Dict]) -> List[Document]:
    if not records:
        raise KnowledgeBaseError("该日期暂无数据")

    return [
        Document(
            page_content=(
                f"标题：{record['title']}\n"
                f"UP 主：{record['up_name']}\n"
                f"播放：{record['view_count']}\n"
                f"点赞：{record['like_count']}\n"
                f"投币：{record['coin_count']}\n"
                f"收藏：{record['favorite_count']}\n"
                f"分享：{record['share_count']}"
            ),
            metadata={
                "bvid": record["bvid"],
                "title": record["title"],
                "up_name": record["up_name"],
            },
        )
        for record in records
    ]


def build_retriever(records: List[Dict]) -> TFIDFRetriever:
    documents = build_documents(records)
    retriever = TFIDFRetriever.from_documents(documents)
    retriever.k = min(3, len(documents))
    return retriever


def answer_question(records: List[Dict], question: str) -> str:
    if not records:
        raise KnowledgeBaseError("该日期暂无数据")

    data = pd.DataFrame(records)
    if "UP主" in question and "视频" in question and "最多" in question:
        return _answer_most_videos_by_up(data)
    if "播放" in question and _contains_maximum_word(question):
        return _answer_maximum(data, "view_count", "播放量")

    has_likes = "点赞" in question
    has_coins = "投币" in question
    if has_likes and has_coins and _contains_maximum_word(question):
        return "\n".join(
            [
                _answer_maximum(data, "like_count", "点赞数"),
                _answer_maximum(data, "coin_count", "投币数"),
            ]
        )
    if has_likes and _contains_maximum_word(question):
        return _answer_maximum(data, "like_count", "点赞数")
    if has_coins and _contains_maximum_word(question):
        return _answer_maximum(data, "coin_count", "投币数")

    documents = build_retriever(records).invoke(question)
    return "\n\n".join(document.page_content for document in documents)


def _contains_maximum_word(question: str) -> bool:
    return any(word in question for word in ("最高", "最大", "最多"))


def _answer_most_videos_by_up(data: pd.DataFrame) -> str:
    counts = data.groupby("up_name").size()
    up_name = counts.idxmax()
    return f"视频数量最多的 UP 主是：{up_name}，共 {counts.loc[up_name]} 个视频。"


def _answer_maximum(data: pd.DataFrame, field: str, label: str) -> str:
    record = data.loc[data[field].idxmax()]
    return f"{label}最高的视频是：{record['title']}，{label}为 {record[field]}。"
