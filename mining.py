from __future__ import annotations

import pandas as pd
from mlxtend.frequent_patterns import apriori, association_rules
from sklearn.cluster import KMeans
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

from data_utils import NUMBER_COLUMNS, parse_number
from hdfs_utils import load_analysis_dataframe

FEATURES = ["play_count", "like_count", "coin_count", "favorite_count", "share_count", "comment_count"]
MODEL_FEATURES = ["like_count", "coin_count", "favorite_count", "share_count", "comment_count"]


def load_mining_data(
    cleaned_path,
    raw_path,
    hdfs_cmd="hdfs",
    hdfs_url="",
    hdfs_user="tan",
    allow_local_fallback=True,
):
    data, source = load_analysis_dataframe(
        cleaned_path,
        raw_path,
        hdfs_cmd,
        hdfs_url,
        hdfs_user,
        allow_local_fallback,
    )
    for column in NUMBER_COLUMNS:
        if column not in data:
            data[column] = 0
        data[column] = data[column].map(lambda value: max(parse_number(value), 0))
    return data, source


def run_kmeans(data):
    values = data[FEATURES].copy()
    model = KMeans(n_clusters=3, random_state=42, n_init=10)
    labels = model.fit_predict(StandardScaler().fit_transform(values))
    result = data.copy()
    result["cluster"] = labels
    averages = result.groupby("cluster")[["play_count", "like_count"]].mean().sort_values("play_count")
    names = {cluster: name for cluster, name in zip(averages.index, ["普通视频", "互动型视频", "热门视频"])}
    rows = []
    for cluster, group in result.groupby("cluster"):
        rows.append({"category": names[cluster], "count": len(group), **{f"avg_{key}": round(group[key].mean(), 2) for key in ["play_count", "like_count", "coin_count", "favorite_count"]}})
    return rows, [{"name": names[label], "value": [int(row.play_count), int(row.like_count)]} for row, label in zip(result.itertuples(), labels)]


def train_hot_model(data):
    threshold = data["play_count"].quantile(0.8)
    target = (data["play_count"] >= threshold).astype(int)
    x_train, x_test, y_train, y_test = train_test_split(data[MODEL_FEATURES], target, test_size=0.2, random_state=42, stratify=target)
    model = RandomForestClassifier(n_estimators=100, random_state=42).fit(x_train, y_train)
    predicted = model.predict(x_test)
    return model, {"total": len(data), "hot_count": int(target.sum()), "normal_count": int((1-target).sum()), "threshold": round(threshold, 2), "accuracy": round(accuracy_score(y_test, predicted), 3), "precision": round(precision_score(y_test, predicted, zero_division=0), 3), "recall": round(recall_score(y_test, predicted, zero_division=0), 3), "f1": round(f1_score(y_test, predicted, zero_division=0), 3)}


def predict_hot_video(model, values):
    frame = pd.DataFrame([values], columns=MODEL_FEATURES)
    probability = float(model.predict_proba(frame)[0][1])
    return {"label": "可能成为爆款" if probability >= 0.5 else "普通视频", "probability": round(probability * 100, 1)}


def run_association_rules(data):
    columns = {"like_count": "高点赞", "coin_count": "高投币", "favorite_count": "高收藏", "share_count": "高分享", "comment_count": "高评论"}
    basket = pd.DataFrame({label: data[column] >= data[column].median() for column, label in columns.items()})
    frequent = apriori(basket, min_support=0.1, use_colnames=True)
    if frequent.empty:
        return []
    rules = association_rules(frequent, metric="confidence", min_threshold=0.1)
    return [{"antecedents": "、".join(row.antecedents), "consequents": "、".join(row.consequents), "support": round(row.support, 3), "confidence": round(row.confidence, 3), "lift": round(row.lift, 3)} for row in rules.head(20).itertuples()]


def run_required_association_rules(data):
    definitions = (
        ("高点赞", "like_count", "高投币", "coin_count"),
        ("高点赞", "like_count", "高收藏", "favorite_count"),
        ("高投币", "coin_count", "高分享", "share_count"),
    )
    rules = []
    for antecedent_label, antecedent_field, consequent_label, consequent_field in definitions:
        antecedent_values = data[antecedent_field]
        consequent_values = data[consequent_field]
        has_signal = not data.empty and antecedent_values.max() > 0 and consequent_values.max() > 0
        if has_signal:
            antecedent = antecedent_values >= antecedent_values.median()
            consequent = consequent_values >= consequent_values.median()
            antecedent_support = float(antecedent.mean())
            consequent_support = float(consequent.mean())
            support = float((antecedent & consequent).mean())
            confidence = support / antecedent_support if antecedent_support else 0.0
            lift = confidence / consequent_support if consequent_support else 0.0
            valid = support >= 0.1 and confidence >= 0.1 and lift > 0
        else:
            support = confidence = lift = 0.0
            valid = False
        rules.append(
            {
                "antecedents": antecedent_label,
                "consequents": consequent_label,
                "support": round(support, 3),
                "confidence": round(confidence, 3),
                "lift": round(lift, 3),
                "valid": valid,
                "message": "" if valid else "当前数据下未形成有效规则",
            }
        )
    return rules
