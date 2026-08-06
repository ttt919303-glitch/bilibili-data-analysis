from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from date_utils import InvalidBusinessDateError, filter_by_publish_date, resolve_business_date
from hdfs_utils import DataSourceUnavailableError, load_analysis_dataframe


CSV_TEXT = (
    "title,video_url,up_name,play_count,like_count,coin_count,favorite_count,share_count,comment_count,publish_time,crawl_date\n"
    "昨日视频,https://www.bilibili.com/video/BV1,UP甲,100,10,2,3,4,5,2026-08-06,2026-08-07\n"
)


def test_default_business_date_is_yesterday_in_configured_timezone():
    now = datetime(2026, 8, 7, 0, 30, tzinfo=ZoneInfo("Asia/Shanghai"))

    assert resolve_business_date(None, "Asia/Shanghai", now=now) == "2026-08-06"


def test_invalid_business_date_has_friendly_validation_error():
    with pytest.raises(InvalidBusinessDateError, match="YYYY-MM-DD"):
        resolve_business_date("2026-02-30", "Asia/Shanghai")


def test_publish_time_filter_keeps_only_selected_date():
    data = pd.DataFrame(
        {"title": ["目标", "其他", "时间戳"], "publish_time": ["2026-08-06", "2026-08-05", "2026-08-06 12:30:00"]}
    )

    filtered = filter_by_publish_date(data, "2026-08-06")

    assert filtered["title"].tolist() == ["目标", "时间戳"]


def test_webhdfs_read_returns_complete_dataframe(tmp_path: Path):
    with patch("hdfs_utils._read_webhdfs_text", return_value=CSV_TEXT):
        data, source = load_analysis_dataframe(
            tmp_path / "cleaned.csv",
            tmp_path / "raw.csv",
            "hdfs",
            "http://namenode:50070",
            "tan",
            allow_local_fallback=False,
        )

    assert data["title"].tolist() == ["昨日视频"]
    assert source == "HDFS（WebHDFS）"


def test_hdfs_cli_cat_is_used_when_webhdfs_is_not_configured(tmp_path: Path):
    with patch("hdfs_utils._run_hdfs", return_value=(True, CSV_TEXT, "")) as run:
        data, source = load_analysis_dataframe(
            tmp_path / "cleaned.csv", tmp_path / "raw.csv", "hdfs", "", "tan", False
        )

    assert len(data) == 1
    assert source == "HDFS（命令行）"
    assert run.call_args.args[0] == ["hdfs", "dfs", "-cat", "/bilibili/videos_cleaned.csv"]


def test_hdfs_failure_falls_back_to_cleaned_then_raw_csv(tmp_path: Path):
    cleaned_path = tmp_path / "cleaned.csv"
    raw_path = tmp_path / "raw.csv"
    cleaned_path.write_text(CSV_TEXT.replace("昨日视频", "清洗数据"), encoding="utf-8")
    raw_path.write_text(CSV_TEXT.replace("昨日视频", "原始数据"), encoding="utf-8")

    with patch("hdfs_utils._run_hdfs", return_value=(False, "", "offline")):
        data, source = load_analysis_dataframe(cleaned_path, raw_path, "hdfs", "", "tan", True)

    assert data["title"].tolist() == ["清洗数据"]
    assert source == "本地清洗CSV（HDFS不可用，已回退）"


def test_hdfs_failure_without_local_fallback_raises(tmp_path: Path):
    with patch("hdfs_utils._run_hdfs", return_value=(False, "", "offline")):
        with pytest.raises(DataSourceUnavailableError, match="offline"):
            load_analysis_dataframe(tmp_path / "cleaned.csv", tmp_path / "raw.csv", "hdfs", "", "tan", False)


def test_mining_uses_unified_analysis_source(tmp_path: Path):
    from mining import load_mining_data

    expected = pd.DataFrame({"title": ["统一来源"], "play_count": [1]})
    with patch("mining.load_analysis_dataframe", return_value=(expected, "HDFS（WebHDFS）")) as load:
        data, source = load_mining_data(tmp_path / "cleaned.csv", tmp_path / "raw.csv", "hdfs", "url", "tan")

    assert data["title"].tolist() == ["统一来源"]
    assert source == "HDFS（WebHDFS）"
    load.assert_called_once()
