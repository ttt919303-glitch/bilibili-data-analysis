import pytest

from knowledge.qa import KnowledgeBaseError, answer_question, build_documents


RECORDS = [
    {
        "title": "Spark A",
        "up_name": "甲",
        "view_count": 100,
        "like_count": 20,
        "coin_count": 5,
        "favorite_count": 8,
        "share_count": 3,
        "bvid": "BV1",
    },
    {
        "title": "Hadoop B",
        "up_name": "甲",
        "view_count": 300,
        "like_count": 10,
        "coin_count": 30,
        "favorite_count": 6,
        "share_count": 2,
        "bvid": "BV2",
    },
    {
        "title": "Python C",
        "up_name": "乙",
        "view_count": 200,
        "like_count": 50,
        "coin_count": 4,
        "favorite_count": 7,
        "share_count": 1,
        "bvid": "BV3",
    },
]


def login(client):
    with client.session_transaction() as session:
        session.update(user_id=1, username="student", role="user")


def test_documents_contain_real_video_metrics():
    documents = build_documents(RECORDS)

    assert len(documents) == 3
    assert "Spark A" in documents[0].page_content
    assert documents[0].metadata == {"bvid": "BV1", "title": "Spark A", "up_name": "甲"}
    assert "comment" not in documents[0].page_content.casefold()


def test_answers_required_structured_questions():
    assert "甲" in answer_question(RECORDS, "哪个UP主视频最多？")
    assert "Hadoop B" in answer_question(RECORDS, "播放量最高的视频是哪个？")

    answer = answer_question(RECORDS, "哪些视频点赞投币最高？")

    assert "Python C" in answer
    assert "Hadoop B" in answer


def test_other_question_uses_local_retriever():
    answer = answer_question(RECORDS, "我想了解 Spark")

    assert "Spark A" in answer


def test_likes_and_coins_question_without_maximum_uses_local_retriever():
    answer = answer_question(RECORDS, "Spark A 的点赞和投币是多少？")

    assert "Spark A" in answer
    assert "点赞：20" in answer
    assert "投币：5" in answer


def test_empty_records_raise_required_error():
    with pytest.raises(KnowledgeBaseError, match="^该日期暂无数据$"):
        answer_question([], "我想了解 Spark")


def test_knowledge_page_reads_selected_date_and_answers_question(client, monkeypatch):
    login(client)
    requested_dates = []
    monkeypatch.setattr(
        "app.read_from_hdfs", lambda value: requested_dates.append(value) or RECORDS
    )

    response = client.post(
        "/knowledge?date=2026-08-09",
        data={"date": "2026-08-09", "question": "我想了解 Spark"},
    )

    assert response.status_code == 200
    assert requested_dates == ["2026-08-09"]
    assert "Spark A" in response.get_data(as_text=True)


def test_knowledge_page_post_uses_submitted_date_over_url_date(client, monkeypatch):
    login(client)
    requested_dates = []
    monkeypatch.setattr(
        "app.read_from_hdfs", lambda value: requested_dates.append(value) or RECORDS
    )

    response = client.post(
        "/knowledge?date=2026-08-08",
        data={"date": "2026-08-09", "question": "我想了解 Spark"},
    )

    assert response.status_code == 200
    assert requested_dates == ["2026-08-09"]


def test_knowledge_page_rejects_empty_question(client, monkeypatch):
    login(client)
    monkeypatch.setattr("app.read_from_hdfs", lambda value: RECORDS)

    response = client.post("/knowledge?date=2026-08-09", data={"question": "   "})

    assert response.status_code == 400


def test_knowledge_page_displays_build_failure(client, monkeypatch):
    login(client)
    monkeypatch.setattr("app.read_from_hdfs", lambda value: [])

    response = client.get("/knowledge?date=2026-08-09")

    assert response.status_code == 200
    assert "知识库构建失败" in response.get_data(as_text=True)
