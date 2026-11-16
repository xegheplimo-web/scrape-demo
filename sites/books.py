"""Adapter for https://books.toscrape.com — a public site built for scraping practice."""

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

FIELDS = ["title", "price", "availability", "rating", "url"]

RATINGS = {"One": 1, "Two": 2, "Three": 3, "Four": 4, "Five": 5}


def parse_records(html: str, base_url: str) -> list[dict]:
    """Extract one record per book pod on a catalogue listing page."""
    soup = BeautifulSoup(html, "html.parser")
    records = []
    for pod in soup.select("article.product_pod"):
        link = pod.select_one("h3 a")
        if link is None:
            continue
        records.append(
            {
                "title": link.get("title") or link.get_text(strip=True),
                "price": _price(pod.select_one("p.price_color")),
                "availability": _text(pod.select_one("p.availability")),
                "rating": _rating(pod.select_one("p.star-rating")),
                "url": urljoin(base_url, link["href"]),
            }
        )
    return records


def next_page_url(html: str, base_url: str) -> str | None:
    """Return the absolute URL of the next listing page, or None on the last page."""
    soup = BeautifulSoup(html, "html.parser")
    link = soup.select_one("ul.pager li.next a")
    if link is None or not link.get("href"):
        return None
    return urljoin(base_url, link["href"])


def _text(node) -> str:
    return node.get_text(" ", strip=True) if node else ""


def _price(node) -> str:
    """'£51.77' -> '51.77' (site is GBP-only; keeps the CSV numeric-clean)."""
    if node is None:
        return ""
    return re.sub(r"[^\d.]", "", node.get_text(strip=True))


def _rating(node) -> int | None:
    """<p class="star-rating Three"> -> 3."""
    if node is None:
        return None
    for css_class in node.get("class", []):
        if css_class in RATINGS:
            return RATINGS[css_class]
    return None
