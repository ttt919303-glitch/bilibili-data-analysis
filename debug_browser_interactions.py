"""Inspect the live Bilibili detail-page interaction selectors without writing data."""

from __future__ import annotations

import argparse

from browser_crawler import BROWSER_CHANNEL, launch_persistent_browser
from browser_interaction_backfill import DETAIL_METRIC_SELECTORS, _load_detail_metrics, get_video_data_path
from data_utils import load_video_data


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser", choices=(BROWSER_CHANNEL,), default=BROWSER_CHANNEL)
    return parser.parse_args()


def main() -> None:
    parse_args()
    data = load_video_data(get_video_data_path())
    video_urls = [str(value).strip() for value in data.get("video_url", []) if str(value).strip()]
    if not video_urls:
        raise ValueError("videos.csv does not contain a video URL for detail-page diagnostics")

    session = launch_persistent_browser()
    try:
        page = session.context.pages[0] if session.context.pages else session.context.new_page()
        metrics = _load_detail_metrics(page, video_urls[0])
        print("[browser interaction diagnostic]")
        print(f"browser={BROWSER_CHANNEL}")
        print(f"URL={page.url}")
        print(f"title={page.title()}")
        for field, selector in DETAIL_METRIC_SELECTORS.items():
            print(f"{field}_selector={selector}")
            print(f"{field}={metrics[field]}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
