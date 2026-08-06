from __future__ import annotations

import re
from pathlib import Path

from data_utils import parse_number
from hdfs_utils import load_analysis_dataframe


FIELDS = {
    "播放": "play_count",
    "点赞": "like_count",
    "投币": "coin_count",
    "收藏": "favorite_count",
    "评论": "comment_count",
    "分享": "share_count",
}


def format_number(value):
    return f"{int(value):,}"


def load_qa_data(
    cleaned_path: Path,
    raw_path: Path,
    hdfs_cmd: str = "hdfs",
    hdfs_url: str = "",
    hdfs_user: str = "tan",
):
    data, source = load_analysis_dataframe(cleaned_path, raw_path, hdfs_cmd, hdfs_url, hdfs_user)
    for field in FIELDS.values():
        if field not in data:
            data[field] = 0
        data[field] = data[field].map(parse_number)
    return data, source


def answer_question(question: str, data, retriever=None):
    question = question.strip()
    if not question:
        return "请输入问题。"
    if data.empty:
        return "当前知识库暂无视频数据，请先完成数据采集和清洗。"

    up_name = next((name for name in data["up_name"].dropna().unique() if str(name) in question), None)
    if up_name and "多少" in question and "视频" in question:
        count = int((data["up_name"] == up_name).sum())
        return f"UP主“{up_name}”在当前数据集中共有{count}条视频。"

    if "多少视频" in question or "多少条" in question:
        return f"当前本地知识库共收录{len(data)}条视频数据。"
    if "多少UP" in question:
        return f"当前本地知识库共有{data['up_name'].nunique()}位UP主。"
    if "UP主" in question and ("最多" in question or "视频数量" in question):
        counts = data.groupby("up_name").size()
        name = counts.idxmax()
        return f"视频数量最多的UP主是“{name}”，共收录{counts[name]}条视频。"

    if "标题" in question and ("包含" in question or "关键词" in question):
        match = re.search(r"(?:包含|关键词(?:为|是)?)\s*[“\"']?([^”\"'\s？?]+)", question)
        if match:
            keyword = match.group(1).replace("的视频有哪些", "").replace("的视频", "")
            rows = data[data["title"].astype(str).str.contains(keyword, case=False, na=False)]
            if rows.empty:
                return f"当前数据集中没有标题包含“{keyword}”的视频。"
            return "\n".join(
                f"{index + 1}.《{row.title}》- {row.up_name}"
                for index, row in enumerate(rows.head(20).itertuples())
            )

    field = next((value for key, value in FIELDS.items() if key in question), None)
    number = re.search(r"(?:前|top|最高的)\s*(\d+)", question, re.IGNORECASE)
    if field and number:
        count = min(int(number.group(1)), 20)
        rows = data.nlargest(count, field)
        return "\n".join(
            f"{index + 1}.《{row.title}》- {row.up_name} - {format_number(getattr(row, field))}"
            for index, row in enumerate(rows.itertuples())
        )
    if field and ("最高" in question or "最多" in question):
        row = data.loc[data[field].idxmax()]
        label = next(key for key, value in FIELDS.items() if value == field)
        return f"当前{label}量最高的视频是《{row['title']}》，UP主为{row['up_name']}，数值为{format_number(row[field])}。"

    if retriever is not None:
        hits = retriever.invoke(question)
        if not hits:
            return "该日期知识库未检索到相关视频。"
        lines = ["本地 LangChain Retriever 检索命中："]
        for index, document in enumerate(hits, start=1):
            title = document.metadata.get("title", "未知标题")
            up_name = document.metadata.get("up_name", "")
            video_url = document.metadata.get("video_url", "")
            lines.append(f"{index}.《{title}》 {up_name} {video_url}".strip())
        return "\n".join(lines)

    return "当前知识库主要支持B站视频数据查询，例如：哪个UP主视频最多？播放量最高的视频是哪个？"
