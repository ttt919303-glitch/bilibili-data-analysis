from __future__ import annotations

import html
import importlib.util
import re
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

import browser_crawler


REAL_SEARCH_CARD_HTML = """
<div class="bili-video-card">
  <a href="//www.bilibili.com/video/BV1rpWjevEip/"><div class="bili-video-card__image"></div></a>
  <div class="bili-video-card__info">
    <a href="//www.bilibili.com/video/BV1rpWjevEip/"><h3 class="bili-video-card__info--tit" title="Python教程"><em class="keyword">Python</em>教程</h3></a>
    <div class="bili-video-card__info--bottom"><a class="bili-video-card__info--owner"><span class="bili-video-card__info--author">Python官方课程</span><span class="bili-video-card__info--date">· 2024-08-22</span></a></div>
  </div>
  <div class="bili-video-card__stats--left"><span class="bili-video-card__stats--item">1838.8万</span><span class="bili-video-card__stats--item">12.1万</span></div>
</div>
"""


class FakeLocator:
    def __init__(self, *, text="", count=1, attributes=None, texts=None):
        self._text = text
        self._count = count
        self._attributes = attributes or {}
        self._texts = texts if texts is not None else [text]

    @property
    def first(self):
        return self

    def all_inner_texts(self):
        return self._texts

    def count(self):
        return self._count

    def get_attribute(self, name):
        return self._attributes.get(name)

    def inner_text(self):
        return self._text


class FakeCard:
    def __init__(self, *, title, href, up_name, play_count, publish_time="", title_attribute=None):
        self._locators = {
            "h3.bili-video-card__info--tit": FakeLocator(
                text=title,
                attributes={"title": title_attribute},
            ),
            "a[href*='/video/']": FakeLocator(attributes={"href": href}),
            "span.bili-video-card__info--author": FakeLocator(text=up_name),
            "div.bili-video-card__stats--left span.bili-video-card__stats--item": FakeLocator(
                texts=[play_count] if play_count else [],
                count=1 if play_count else 0,
            ),
            "span.bili-video-card__info--date": FakeLocator(
                text=publish_time,
                count=1 if publish_time else 0,
            ),
        }

    def locator(self, selector):
        return self._locators[selector]


class FakeCardList:
    def __init__(self, cards):
        self._cards = cards

    def count(self):
        return len(self._cards)

    def nth(self, index):
        return self._cards[index]


class FakeSearchPage:
    def __init__(self, *, cards=(), visible_texts=()):
        self._cards = FakeCardList(cards)
        self._visible_texts = set(visible_texts)

    def get_by_text(self, text, exact=False):
        return FakeLocator(count=1 if text in self._visible_texts else 0)

    def locator(self, selector):
        assert selector == "div.bili-video-card:has(a[href*='/video/'])"
        return self._cards


def card_from_real_html(card_html=REAL_SEARCH_CARD_HTML, **overrides):
    def attribute(pattern):
        match = re.search(pattern, card_html)
        return html.unescape(match.group(1)) if match else ""

    def text(pattern):
        match = re.search(pattern, card_html, re.DOTALL)
        return re.sub(r"<[^>]+>", "", html.unescape(match.group(1))).strip() if match else ""

    values = {
        "title": text(r'<h3 class="bili-video-card__info--tit"[^>]*>(.*?)</h3>'),
        "href": attribute(r'<a href="(//www\.bilibili\.com/video/BV[^"]+)"'),
        "up_name": text(r'<span class="bili-video-card__info--author">(.*?)</span>'),
        "play_count": text(r'<span class="bili-video-card__stats--item">(.*?)</span>'),
        "publish_time": text(r'<span class="bili-video-card__info--date">(.*?)</span>'),
        "title_attribute": attribute(r'<h3 class="bili-video-card__info--tit" title="([^"]*)"'),
    }
    values.update(overrides)
    return FakeCard(**values)


def test_browser_crawler_module_exists():
    assert importlib.util.find_spec("browser_crawler") is not None


def test_browser_data_dir_is_under_project_root():
    browser_data_dir = browser_crawler.get_browser_data_dir()

    assert isinstance(browser_data_dir, Path)
    assert browser_data_dir == Path(browser_crawler.__file__).resolve().parent / "browser_data"
    assert "AppData" not in str(browser_data_dir)


def test_launch_uses_visible_project_local_edge_persistent_context(monkeypatch, tmp_path):
    context = Mock()
    manager = Mock()
    manager.chromium.launch_persistent_context.return_value = context
    runner = Mock()
    runner.start.return_value = manager
    monkeypatch.setattr(browser_crawler, "get_browser_data_dir", lambda: tmp_path / "browser_data")
    monkeypatch.setattr(browser_crawler, "_sync_playwright_factory", lambda: lambda: runner)

    session = browser_crawler.launch_persistent_browser()

    assert session.context is context
    manager.chromium.launch_persistent_context.assert_called_once_with(
        user_data_dir=str(tmp_path / "browser_data"),
        channel="msedge",
        headless=False,
    )


def test_build_search_url_encodes_keyword_for_normal_search_page():
    assert browser_crawler.build_search_url("Python 基础") == "https://search.bilibili.com/all?keyword=Python+%E5%9F%BA%E7%A1%80"


def test_parse_real_search_card_extracts_plain_text_and_required_fields():
    video = browser_crawler.parse_video_card(card_from_real_html())

    assert video == {
        "title": "Python教程",
        "video_url": "https://www.bilibili.com/video/BV1rpWjevEip/",
        "up_name": "Python官方课程",
        "play_count": 18388000,
        "publish_time": "2024-08-22",
    }


@pytest.mark.parametrize(("displayed", "expected"), [("1838.8万", 18388000), ("1848", 1848)])
def test_parse_video_card_converts_real_displayed_play_count(displayed, expected):
    video = browser_crawler.parse_video_card(card_from_real_html(play_count=displayed))

    assert video["play_count"] == expected


def test_parse_video_card_keeps_card_when_play_count_is_missing():
    video = browser_crawler.parse_video_card(card_from_real_html(play_count=""))

    assert video["play_count"] == 0


@pytest.mark.parametrize(
    ("publish_time", "expected"),
    [("· 2024-08-22", "2024-08-22"), ("· 07-28", "07-28"), ("", "")],
)
def test_parse_video_card_lightly_normalizes_publish_time(publish_time, expected):
    video = browser_crawler.parse_video_card(card_from_real_html(publish_time=publish_time))

    assert video["publish_time"] == expected


def test_parse_video_cards_deduplicates_video_urls_and_skips_empty_titles():
    unique_card = card_from_real_html(href="https://www.bilibili.com/video/BV1qW4y1a7fU/", title="第二条", title_attribute="第二条")
    videos = browser_crawler.parse_video_cards(
        FakeSearchPage(cards=[card_from_real_html(), card_from_real_html(), card_from_real_html(title="", title_attribute=""), unique_card]),
        limit=5,
    )

    assert [video["video_url"] for video in videos] == [
        "https://www.bilibili.com/video/BV1rpWjevEip/",
        "https://www.bilibili.com/video/BV1qW4y1a7fU/",
    ]


def test_detect_page_state_reports_no_results_only_for_explicit_page_text():
    assert browser_crawler.detect_page_state(FakeSearchPage(visible_texts={"没有搜索结果"})) == "no_results"


def test_detect_page_state_stops_for_verification_text():
    assert browser_crawler.detect_page_state(FakeSearchPage(visible_texts={"安全验证"})) == "verification_required"


def test_detect_page_state_distinguishes_missing_dom_from_no_results():
    assert browser_crawler.detect_page_state(FakeSearchPage()) == "page_structure_error"


def test_gitignore_excludes_browser_session_and_debug_artifacts():
    ignored_paths = (Path(browser_crawler.__file__).resolve().parent / ".gitignore").read_text(encoding="utf-8")

    for expected in ("browser_data/", "debug/", "playwright/.auth/", "__pycache__/", "*.pyc", ".pytest_cache/"):
        assert expected in ignored_paths


def test_existing_application_module_still_imports():
    import app

    assert callable(app.create_app)


def test_diagnostic_delegates_search_to_browser_crawler(monkeypatch, capsys):
    import debug_browser_crawler

    monkeypatch.setattr(
        debug_browser_crawler,
        "diagnose_search",
        lambda keyword, limit: {
            "status": "success",
            "keyword": keyword,
            "page_url": "https://search.bilibili.com/all?keyword=Python",
            "page_title": "Python-哔哩哔哩_bilibili",
            "card_count": 35,
            "video_link_count": 35,
            "videos": [
                {
                    "title": "Python教程",
                    "video_url": "https://www.bilibili.com/video/BV1rpWjevEip/",
                    "up_name": "Python官方课程",
                    "play_count": 18388000,
                    "publish_time": "2024-08-22",
                }
            ],
        },
    )
    monkeypatch.setattr(sys, "argv", ["debug_browser_crawler.py", "--browser", "msedge", "--search", "Python", "--limit", "5"])

    debug_browser_crawler.main()

    output = capsys.readouterr().out
    assert "browser=msedge" in output
    assert "unique_video_links=35" in output
    assert "video_url: https://www.bilibili.com/video/BV1rpWjevEip/" in output

