"""Offline tests for the scraper core: retry, robots.txt, delay, CSV.

A FakeSession stands in for requests.Session — no network in tests.
"""

import csv
import logging
from types import SimpleNamespace
from typing import ClassVar
from urllib import robotparser

import pytest
import requests

import scrape


def response(status=200, text="ok"):
    return SimpleNamespace(status_code=status, text=text, content=text.encode())


class FakeSession:
    """Routes each URL to a response, an exception, or a list popped per call."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def get(self, url, headers=None, timeout=None):
        self.calls.append(url)
        route = self.routes[url]
        if isinstance(route, list):
            route = route.pop(0)
        if isinstance(route, Exception):
            raise route
        return route


@pytest.fixture
def scraper():
    s = scrape.Scraper(
        FakeSession({}),
        delay=0,
        backoff=0,
        sleep=lambda _: None,
        logger=logging.getLogger("test"),
    )
    s.robots = robotparser.RobotFileParser()
    s.robots.parse([])  # no rules -> allow everything
    return s


def test_get_success_single_attempt(scraper):
    scraper.session.routes["http://x/"] = response(200, "hello")
    assert scraper.get("http://x/") == "hello"
    assert scraper.session.calls == ["http://x/"]


def test_get_retries_on_network_error(scraper):
    scraper.session.routes["http://x/"] = [
        requests.ConnectTimeout("boom"),
        requests.ConnectTimeout("boom"),
        response(200, "finally"),
    ]
    assert scraper.get("http://x/") == "finally"
    assert len(scraper.session.calls) == 3


def test_get_gives_up_after_max_retries(scraper):
    scraper.session.routes["http://x/"] = requests.ConnectTimeout("always")
    with pytest.raises(scrape.FetchError):
        scraper.get("http://x/")
    assert len(scraper.session.calls) == scrape.MAX_RETRIES + 1


def test_get_retries_on_5xx(scraper):
    scraper.session.routes["http://x/"] = [response(503), response(200, "ok")]
    assert scraper.get("http://x/") == "ok"
    assert len(scraper.session.calls) == 2


def test_get_does_not_retry_on_4xx(scraper):
    scraper.session.routes["http://x/"] = response(404)
    with pytest.raises(scrape.FetchError):
        scraper.get("http://x/")
    assert len(scraper.session.calls) == 1


def test_get_respects_robots_disallow():
    session = FakeSession(
        {
            "http://x/robots.txt": response(200, "User-agent: *\nDisallow: /private\n"),
            "http://x/private/page": response(200),
        }
    )
    s = scrape.Scraper(
        session,
        delay=0,
        backoff=0,
        sleep=lambda _: None,
        logger=logging.getLogger("test"),
    )
    s.load_robots("http://x/")
    with pytest.raises(scrape.RobotsDisallowed):
        s.get("http://x/private/page")
    assert "http://x/private/page" not in session.calls


def test_robots_404_means_allow_all():
    session = FakeSession(
        {
            "http://x/robots.txt": response(404),
            "http://x/page": response(200, "content"),
        }
    )
    s = scrape.Scraper(
        session,
        delay=0,
        backoff=0,
        sleep=lambda _: None,
        logger=logging.getLogger("test"),
    )
    s.load_robots("http://x/")
    assert s.get("http://x/page") == "content"


def test_robots_unreachable_means_allow_all():
    session = FakeSession(
        {
            "http://x/robots.txt": requests.ConnectTimeout("down"),
            "http://x/page": response(200, "content"),
        }
    )
    s = scrape.Scraper(
        session,
        delay=0,
        backoff=0,
        sleep=lambda _: None,
        logger=logging.getLogger("test"),
    )
    s.load_robots("http://x/")
    assert s.get("http://x/page") == "content"


def test_delay_between_requests():
    sleeps = []
    s = scrape.Scraper(
        FakeSession(
            {
                "http://x/a": response(200),
                "http://x/b": response(200),
            }
        ),
        delay=10,
        backoff=0,
        sleep=sleeps.append,
        logger=logging.getLogger("test"),
    )
    s.robots = robotparser.RobotFileParser()
    s.robots.parse([])
    s.get("http://x/a")
    s.get("http://x/b")
    assert sleeps == [10]


def test_collect_stops_on_next_page_cycle():
    class LoopAdapter:
        FIELDS: ClassVar[list[str]] = ["x"]

        def parse_records(self, html, url):
            return [{"x": url}]

        def next_page_url(self, html, url):
            return url  # buggy pager: always points at itself

    scraper = SimpleNamespace(get=lambda url: "<html></html>")
    records, pages = scrape.collect(
        scraper,
        LoopAdapter(),
        "http://x/",
        max_pages=10,
        logger=logging.getLogger("test"),
    )
    assert pages == 1
    assert records == [{"x": "http://x/"}]


def test_write_csv(tmp_path):
    out = tmp_path / "out.csv"
    scrape.write_csv(out, ["a", "b"], [{"a": "1", "b": "x"}, {"a": "2", "b": "y"}])
    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    assert rows == [{"a": "1", "b": "x"}, {"a": "2", "b": "y"}]
