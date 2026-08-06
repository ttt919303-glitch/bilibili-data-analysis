"""Run the Phase B Edge search diagnostic without writing project data."""

from __future__ import annotations

import argparse

from browser_crawler import BROWSER_CHANNEL, crawl_bilibili_browser, diagnose_search


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser", choices=(BROWSER_CHANNEL,), default=BROWSER_CHANNEL)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--search", metavar="KEYWORD")
    mode.add_argument("--crawl", metavar="KEYWORD")
    parser.add_argument("--limit", type=int, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.search:
        if args.limit != 5:
            raise ValueError("search diagnostics require limit=5")
        result = diagnose_search(args.search, args.limit)
        print("[browser search diagnostic]")
        print(f"browser={args.browser}")
        print(f"keyword={result['keyword']}")
        print(f"URL={result['page_url']}")
        print(f"title={result['page_title']}")
        print(f"page_state={result['status']}")
        print(f"video_cards={result['card_count']}")
        print(f"unique_video_links={result['video_link_count']}")
        for index, video in enumerate(result["videos"], start=1):
            print(f"{index}.")
            print(f"title: {video['title']}")
            print(f"video_url: {video['video_url']}")
            print(f"up_name: {video['up_name']}")
            print(f"play_count: {video['play_count']}")
            print(f"publish_time: {video['publish_time']}")
        return

    print("[formal browser collection] data/videos.csv will be appended")

    def print_page_progress(progress: dict[str, int]) -> None:
        print(
            f"page={progress['page']} parsed={progress['parsed_count']} "
            f"skipped={progress['skipped_count']} new={progress['new_count']} "
            f"saved={progress['saved_count']}/{progress['planned_count']}"
        )

    result = crawl_bilibili_browser(args.crawl, args.limit, progress=print_page_progress)
    print("[browser collection result]")
    print(f"browser={args.browser}")
    print(f"keyword={result['keyword']}")
    print(f"planned_count={result['planned_count']}")
    print(f"parsed_count={result['parsed_count']}")
    print(f"skipped_count={result['skipped_count']}")
    print(f"saved_count={result['saved_count']}")
    print(f"page_count={result['page_count']}")
    print(f"status={result['status']}")
    print(f"message={result['message']}")


if __name__ == "__main__":
    main()
