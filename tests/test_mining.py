import pandas as pd
import pytest

from analysis import mining


def records(count=20):
    return [
        {
            "bvid": f"BV{i}",
            "title": f"视频{i}",
            "view_count": i * 100,
            "like_count": i + 1,
            "coin_count": (i % 5) + 1,
            "favorite_count": i + 2,
            "share_count": (i % 4) + 1,
        }
        for i in range(count)
    ]


def login(client):
    with client.session_transaction() as session:
        session.update(user_id=1, username="student", role="user")


def test_feature_contract_is_exact():
    assert mining.INTERACTION_FEATURES == [
        "like_count",
        "coin_count",
        "favorite_count",
        "share_count",
    ]
    assert "view_count" not in mining.INTERACTION_FEATURES


def test_kmeans_returns_three_named_groups():
    result = mining.run_kmeans(records())

    assert {item["cluster_name"] for item in result} == {
        "低互动",
        "中互动",
        "高互动",
    }
    assert sum(item["video_count"] for item in result) == 20


def test_kmeans_rejects_fewer_than_three_distinct_feature_vectors():
    duplicate_rows = records(3)
    for row in duplicate_rows:
        row.update(like_count=1, coin_count=1, favorite_count=1, share_count=1)

    with pytest.raises(
        mining.MiningDataError,
        match="数据差异不足，无法完成3类聚类",
    ):
        mining.run_kmeans(duplicate_rows)


def test_kmeans_rejects_fewer_than_three_records():
    with pytest.raises(mining.MiningDataError, match="至少需要3条数据完成聚类"):
        mining.run_kmeans(records(2))


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


def test_hot_prediction_rejects_fewer_than_ten_records():
    with pytest.raises(mining.MiningDataError, match="至少需要10条数据完成爆款预测"):
        mining.run_hot_prediction(records(9))


def test_hot_prediction_rejects_one_class_labels():
    one_class_rows = records(10)
    for row in one_class_rows:
        row["view_count"] = 100

    with pytest.raises(
        mining.MiningDataError,
        match="爆款标签只有一个类别，无法训练预测模型",
    ):
        mining.run_hot_prediction(one_class_rows)


def test_apriori_uses_only_four_high_interaction_items():
    result = mining.run_apriori(records(40), min_support=0.1, min_confidence=0.1)
    allowed = {"high_like", "high_coin", "high_favorite", "high_share"}

    for rule in result:
        assert set(rule["antecedents"]) | set(rule["consequents"]) <= allowed


def test_apriori_returns_no_rules_for_empty_records():
    assert mining.run_apriori([]) == []


def test_apriori_returns_no_rules_for_non_empty_records():
    assert mining.run_apriori(records(10), min_support=0.6) == []


def test_mining_page_reads_selected_date_once(client, monkeypatch):
    login(client)
    requested = []
    monkeypatch.setattr("app.read_from_hdfs", lambda date: requested.append(date) or records())

    response = client.get("/mining?date=2026-08-01")

    assert response.status_code == 200
    assert requested == ["2026-08-01"]


def test_mining_page_displays_an_algorithm_error_without_failing(client, monkeypatch):
    login(client)
    monkeypatch.setattr("app.read_from_hdfs", lambda date: records())

    def failed_kmeans(rows):
        raise mining.MiningDataError("聚类数据不足")

    monkeypatch.setattr("app.run_kmeans", failed_kmeans)

    response = client.get("/mining?date=2026-08-01")

    assert response.status_code == 200
    assert "聚类数据不足" in response.get_data(as_text=True)


def test_mining_page_uses_all_records_but_renders_twenty_prediction_examples(
    client, monkeypatch
):
    login(client)
    rows = records(25)
    monkeypatch.setattr("app.read_from_hdfs", lambda date: rows)
    monkeypatch.setattr(
        "app.run_kmeans",
        lambda videos: [
            {
                "cluster_name": "低互动",
                "video_count": len(videos),
                "avg_view_count": 100.0,
                "avg_like_count": 10.0,
            }
        ],
    )
    monkeypatch.setattr(
        "app.run_hot_prediction",
        lambda videos: {
            "threshold": 100.0,
            "accuracy": 0.8,
            "precision": 0.75,
            "recall": 0.7,
            "predictions": [
                {
                    "bvid": row["bvid"],
                    "title": row["title"],
                    "predicted_hot": False,
                }
                for row in videos
            ],
        },
    )
    monkeypatch.setattr("app.run_apriori", lambda videos: [])

    page = client.get("/mining?date=2026-08-14").get_data(as_text=True)

    assert "模型基于全部 25 条正式数据计算" in page
    assert "BV19" in page
    assert "BV20" not in page
    assert "预测结果示例" in page
