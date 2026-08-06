from __future__ import annotations

import pandas as pd

from mining import run_required_association_rules


def test_required_association_rules_always_return_three_named_slots():
    data = pd.DataFrame(
        {
            "like_count": [0, 10, 20, 30],
            "coin_count": [0, 5, 10, 15],
            "favorite_count": [0, 4, 8, 12],
            "share_count": [0, 2, 4, 6],
        }
    )

    rules = run_required_association_rules(data)

    assert [(rule["antecedents"], rule["consequents"]) for rule in rules] == [
        ("高点赞", "高投币"),
        ("高点赞", "高收藏"),
        ("高投币", "高分享"),
    ]
    assert all({"support", "confidence", "lift", "valid"}.issubset(rule) for rule in rules)


def test_required_rule_explicitly_marks_no_effective_rule_for_zero_data():
    data = pd.DataFrame({name: [0, 0, 0] for name in ("like_count", "coin_count", "favorite_count", "share_count")})

    rules = run_required_association_rules(data)

    assert all(not rule["valid"] for rule in rules)
    assert all(rule["message"] == "当前数据下未形成有效规则" for rule in rules)
