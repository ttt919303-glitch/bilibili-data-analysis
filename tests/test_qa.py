from __future__ import annotations

import pandas as pd

from qa import answer_question


def sample_data():
    return pd.DataFrame(
        [
            {
                "title": "大数据入门",
                "up_name": "UP主甲",
                "play_count": 1000,
                "like_count": 100,
                "coin_count": 10,
                "favorite_count": 30,
                "comment_count": 5,
                "share_count": 2,
            },
            {
                "title": "Python数据分析",
                "up_name": "UP主乙",
                "play_count": 5000,
                "like_count": 500,
                "coin_count": 80,
                "favorite_count": 60,
                "comment_count": 30,
                "share_count": 8,
            },
            {
                "title": "大数据实战",
                "up_name": "UP主甲",
                "play_count": 3000,
                "like_count": 300,
                "coin_count": 50,
                "favorite_count": 90,
                "comment_count": 20,
                "share_count": 15,
            },
        ]
    )


def test_empty_question():
    assert answer_question("", sample_data()) == "请输入问题。"


def test_empty_data():
    assert "暂无视频数据" in answer_question("一共有多少视频？", sample_data().iloc[0:0])


def test_video_total():
    assert "3条视频" in answer_question("一共有多少视频？", sample_data())


def test_up_total():
    assert "2位UP主" in answer_question("一共有多少UP主？", sample_data())


def test_up_with_most_videos():
    assert "UP主甲" in answer_question("哪个UP主视频最多？", sample_data())


def test_highest_play_count_uses_real_row():
    assert "Python数据分析" in answer_question("播放量最高的视频是哪个？", sample_data())


def test_highest_like_count_uses_real_row():
    assert "Python数据分析" in answer_question("点赞最高的视频是哪个？", sample_data())


def test_highest_coin_count_uses_real_row():
    assert "Python数据分析" in answer_question("投币最高的视频是哪个？", sample_data())


def test_highest_favorite_count_uses_real_row():
    assert "大数据实战" in answer_question("收藏最高的视频是哪个？", sample_data())


def test_highest_comment_count_uses_real_row():
    assert "Python数据分析" in answer_question("评论最高的视频是哪个？", sample_data())


def test_highest_share_count_uses_real_row():
    assert "大数据实战" in answer_question("分享最高的视频是哪个？", sample_data())


def test_top_five_returns_ranked_rows():
    answer = answer_question("播放量前5的视频有哪些？", sample_data())
    assert answer.startswith("1.《Python数据分析》")
    assert "3.《大数据入门》" in answer


def test_top_ten_returns_ranked_rows():
    answer = answer_question("播放量最高的10个视频有哪些？", sample_data())
    assert answer.startswith("1.《Python数据分析》")
    assert answer.count("《") == 3


def test_title_keyword_search_returns_matching_rows():
    answer = answer_question("标题包含大数据的视频有哪些？", sample_data())
    assert "大数据入门" in answer
    assert "大数据实战" in answer
    assert "Python数据分析" not in answer


def test_unrelated_question_returns_scope_message():
    assert "主要支持B站视频数据查询" in answer_question("今天天气怎么样？", sample_data())
