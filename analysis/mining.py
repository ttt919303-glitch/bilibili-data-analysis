from typing import Dict, List

import pandas as pd
from mlxtend.frequent_patterns import apriori, association_rules
from sklearn.cluster import KMeans
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, classification_report, precision_score, recall_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler


INTERACTION_FEATURES = [
    "like_count",
    "coin_count",
    "favorite_count",
    "share_count",
]
HIGH_FEATURES = {
    "like_count": "high_like",
    "coin_count": "high_coin",
    "favorite_count": "high_favorite",
    "share_count": "high_share",
}
CLUSTER_NAMES = ["低互动", "中互动", "高互动"]


class MiningDataError(ValueError):
    pass


def run_kmeans(records: List[Dict]) -> List[Dict]:
    if len(records) < 3:
        raise MiningDataError("至少需要3条数据完成聚类")

    data = pd.DataFrame(records)
    features = data[INTERACTION_FEATURES]
    if len(features.drop_duplicates()) < 3:
        raise MiningDataError("数据差异不足，无法完成3类聚类")

    scaler = StandardScaler()
    scaled_features = scaler.fit_transform(features)
    model = KMeans(n_clusters=3, random_state=42, n_init=10)
    labels = model.fit_predict(scaled_features)
    center_sums = scaler.inverse_transform(model.cluster_centers_).sum(axis=1)
    cluster_names = {
        cluster: CLUSTER_NAMES[position]
        for position, cluster in enumerate(center_sums.argsort())
    }

    grouped = data.assign(cluster=labels).groupby("cluster", sort=False)
    return [
        {
            "cluster_name": cluster_names[cluster],
            "video_count": int(group["bvid"].count()),
            "avg_view_count": float(group["view_count"].mean()),
            "avg_like_count": float(group["like_count"].mean()),
        }
        for cluster, group in grouped
    ]


def run_hot_prediction(records: List[Dict]) -> Dict:
    if len(records) < 10:
        raise MiningDataError("至少需要10条数据完成爆款预测")

    data = pd.DataFrame(records)
    threshold = data["view_count"].quantile(0.8)
    labels = data["view_count"] >= threshold
    if labels.nunique() < 2:
        raise MiningDataError("爆款标签只有一个类别，无法训练预测模型")

    features = data[INTERACTION_FEATURES]
    X_train, X_test, y_train, y_test = train_test_split(
        features,
        labels,
        test_size=0.25,
        random_state=42,
        stratify=labels,
    )
    model = RandomForestClassifier(n_estimators=100, random_state=42)
    model.fit(X_train, y_train)
    predictions = model.predict(X_test)
    all_predictions = model.predict(features)

    return {
        "threshold": float(threshold),
        "accuracy": float(accuracy_score(y_test, predictions)),
        "precision": float(precision_score(y_test, predictions, zero_division=0)),
        "recall": float(recall_score(y_test, predictions, zero_division=0)),
        "classification_report": classification_report(
            y_test,
            predictions,
            output_dict=True,
            zero_division=0,
        ),
        "predictions": [
            {
                "bvid": record["bvid"],
                "title": record["title"],
                "predicted_hot": bool(prediction),
            }
            for record, prediction in zip(records, all_predictions)
        ],
    }


def run_apriori(
    records: List[Dict], min_support: float = 0.2, min_confidence: float = 0.6
) -> List[Dict]:
    if not records:
        return []

    data = pd.DataFrame(records)
    transaction_data = pd.DataFrame(
        {
            high_feature: data[feature] >= data[feature].median()
            for feature, high_feature in HIGH_FEATURES.items()
        }
    )
    frequent_itemsets = apriori(transaction_data, min_support=min_support, use_colnames=True)
    if frequent_itemsets.empty:
        return []

    rules = association_rules(
        frequent_itemsets,
        metric="confidence",
        min_threshold=min_confidence,
    )
    return [
        {
            "antecedents": sorted(rule["antecedents"]),
            "consequents": sorted(rule["consequents"]),
            "support": float(rule["support"]),
            "confidence": float(rule["confidence"]),
            "lift": float(rule["lift"]),
        }
        for _, rule in rules.iterrows()
    ]
