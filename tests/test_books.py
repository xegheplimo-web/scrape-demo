"""Offline tests for the books.toscrape.com adapter.

Uses a saved copy of the catalogue page — no network access in tests.
"""

from pathlib import Path

from sites import books

FIXTURE = Path(__file__).parent / "fixtures" / "books_page.html"
BASE_URL = "https://books.toscrape.com/"


def fixture_html() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def test_fields_order():
    assert books.FIELDS == ["title", "price", "availability", "rating", "url"]


def test_parse_records_returns_all_books_on_page():
    records = books.parse_records(fixture_html(), BASE_URL)
    assert len(records) == 20


def test_first_record_fields():
    record = books.parse_records(fixture_html(), BASE_URL)[0]
    assert record == {
        "title": "A Light in the Attic",
        "price": "51.77",
        "availability": "In stock",
        "rating": 3,
        "url": "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html",
    }


def test_records_have_absolute_urls():
    records = books.parse_records(fixture_html(), BASE_URL)
    assert all(r["url"].startswith("https://books.toscrape.com/") for r in records)


def test_next_page_url():
    assert books.next_page_url(fixture_html(), BASE_URL) == (
        "https://books.toscrape.com/catalogue/page-2.html"
    )


def test_no_next_page_on_last_page():
    html = '<ul class="pager"><li class="current">Page 50 of 50</li></ul>'
    assert books.next_page_url(html, BASE_URL) is None
