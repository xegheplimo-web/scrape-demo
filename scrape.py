#!/usr/bin/env python3
"""Polite demo scraper: fetch listing pages -> clean CSV.

Usage:
    python scrape.py --url https://books.toscrape.com --out data.csv [--pages N]

- 1s delay between requests, clear User-Agent, robots.txt enforced
- 3 retries with exponential backoff on network errors / 5xx / 429 (20s timeout)
- Rotating scrape.log (INFO) + console warnings/errors
"""

import argparse
import csv
import logging
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib import robotparser
from urllib.parse import urlparse

import requests

import sites

USER_AGENT = "vLanceDemoScraper/1.0 (+portfolio demo; polite crawler)"
DEFAULT_DELAY = 1.0
DEFAULT_TIMEOUT = 20
MAX_RETRIES = 3
BACKOFF_BASE = 1.0
LOG_FILE = "scrape.log"
MAX_LOG_BYTES = 1_000_000
LOG_BACKUPS = 3


class FetchError(RuntimeError):
    pass


class RobotsDisallowed(PermissionError):
    pass


def setup_logging() -> logging.Logger:
    logger = logging.getLogger("scrape")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    logger.propagate = False
    formatter = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s")
    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=MAX_LOG_BYTES, backupCount=LOG_BACKUPS, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.WARNING)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)
    return logger


class Scraper:
    """Polite fetcher: robots.txt check, inter-request delay, retry/backoff."""

    def __init__(
        self,
        session,
        *,
        delay=DEFAULT_DELAY,
        timeout=DEFAULT_TIMEOUT,
        max_retries=MAX_RETRIES,
        backoff=BACKOFF_BASE,
        sleep=time.sleep,
        logger=None,
    ):
        self.session = session
        self.delay = delay
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff = backoff
        self._sleep = sleep
        self.log = logger or logging.getLogger("scrape")
        self.robots = None
        self.requests_made = 0

    def allowed(self, url: str) -> bool:
        return self.robots is None or self.robots.can_fetch(USER_AGENT, url)

    def load_robots(self, start_url: str) -> None:
        """Fetch robots.txt once (no retry — failure just means 'assume allowed')."""
        parts = urlparse(start_url)
        robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
        self.requests_made += 1
        try:
            resp = self.session.get(
                robots_url,
                headers={"User-Agent": USER_AGENT},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            self.log.warning("robots.txt unreachable (%s); assuming allowed", exc)
            self.robots = self._allow_all()
            return
        self.log.info("GET %s -> %d (robots.txt)", robots_url, resp.status_code)
        if 200 <= resp.status_code < 300:
            self.robots = robotparser.RobotFileParser()
            self.robots.parse(resp.text.splitlines())
            self.log.info("robots.txt rules loaded")
        else:
            self.robots = self._allow_all()
            self.log.info("robots.txt -> HTTP %d; assuming allowed", resp.status_code)

    @staticmethod
    def _allow_all() -> robotparser.RobotFileParser:
        rp = robotparser.RobotFileParser()
        rp.parse([])
        return rp

    def get(self, url: str) -> str:
        """Fetch *url* and return the HTML text."""
        if not self.allowed(url):
            raise RobotsDisallowed(f"robots.txt disallows {url}")
        return self._request(url).text

    def _request(self, url: str):
        if self.requests_made:
            self._sleep(self.delay)
        self.requests_made += 1
        return self._get_with_retry(url)

    def _get_with_retry(self, url: str):
        attempts = self.max_retries + 1
        for attempt in range(1, attempts + 1):
            try:
                resp = self.session.get(
                    url,
                    headers={"User-Agent": USER_AGENT},
                    timeout=self.timeout,
                )
            except requests.RequestException as exc:
                self._retry_or_raise(
                    url, attempt, attempts, f"{type(exc).__name__}: {exc}"
                )
                continue
            if resp.status_code < 400:
                how = "no retry" if attempt == 1 else f"retried {attempt - 1}x"
                self.log.info(
                    "GET %s -> %d (%d bytes, attempt %d, %s)",
                    url,
                    resp.status_code,
                    len(resp.content),
                    attempt,
                    how,
                )
                return resp
            if resp.status_code == 429 or resp.status_code >= 500:
                self._retry_or_raise(url, attempt, attempts, f"HTTP {resp.status_code}")
                continue
            self.log.error(
                "GET %s -> HTTP %d (client error, not retrying)", url, resp.status_code
            )
            raise FetchError(f"{url}: HTTP {resp.status_code}")
        raise FetchError(f"{url}: exhausted retries")  # pragma: no cover

    def _retry_or_raise(self, url, attempt, attempts, error):
        if attempt >= attempts:
            self.log.error(
                "GET %s failed permanently after %d attempts: %s", url, attempts, error
            )
            raise FetchError(f"{url}: {error} (after {attempts} attempts)")
        wait = self.backoff * (2 ** (attempt - 1))
        self.log.warning(
            "GET %s attempt %d/%d failed: %s — retrying in %.0fs",
            url,
            attempt,
            attempts,
            error,
            wait,
        )
        self._sleep(wait)


def collect(scraper: Scraper, adapter, start_url: str, max_pages: int, logger):
    """Fetch listing pages until *max_pages*, a missing next link, or a URL cycle."""
    records, pages, url, seen = [], 0, start_url, set()
    while url and pages < max_pages and url not in seen:
        seen.add(url)
        html = scraper.get(url)
        pages += 1
        page_records = adapter.parse_records(html, url)
        records.extend(page_records)
        logger.info("page %d/%s -> %d records", pages, url, len(page_records))
        url = adapter.next_page_url(html, url)
    return records, pages


def write_csv(path, fields, records) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Polite demo scraper: fetch listing pages -> clean CSV."
    )
    parser.add_argument("--url", required=True, help="start URL (needs a site adapter)")
    parser.add_argument("--out", default="data.csv", help="output CSV path")
    parser.add_argument(
        "--pages", type=int, default=1, help="max listing pages to fetch (default: 1)"
    )
    args = parser.parse_args(argv)
    if "://" not in args.url:
        args.url = "https://" + args.url
    if args.pages < 1:
        parser.error("--pages must be >= 1")
    return args


def main(argv=None) -> int:
    args = parse_args(argv)
    logger = setup_logging()
    adapter = sites.get_adapter(args.url)
    if adapter is None:
        msg = f"no adapter for {args.url} (supported: {', '.join(sites.ADAPTERS)})"
        logger.error(msg)
        print(f"error: {msg}", file=sys.stderr)
        return 2

    logger.info("start: url=%s out=%s pages<=%d", args.url, args.out, args.pages)
    started = time.monotonic()
    scraper = Scraper(requests.Session(), logger=logger)
    try:
        scraper.load_robots(args.url)
        records, pages = collect(scraper, adapter, args.url, args.pages, logger)
    except (RobotsDisallowed, FetchError) as exc:
        logger.error("scrape failed: %s", exc)
        print(f"error: {exc}", file=sys.stderr)
        return 2 if isinstance(exc, RobotsDisallowed) else 1

    write_csv(args.out, adapter.FIELDS, records)
    elapsed = time.monotonic() - started
    logger.info(
        "done: %d pages, %d records -> %s in %.1fs",
        pages,
        len(records),
        args.out,
        elapsed,
    )
    print()
    print("Scrape complete")
    print(f"  pages fetched : {pages}")
    print(f"  records       : {len(records)}")
    print(f"  output        : {args.out}")
    print(f"  elapsed       : {elapsed:.1f}s")
    print(f"  log           : {LOG_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
