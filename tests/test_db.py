import os
import sqlite3

from src.core.db import NewsItem, connect, ensure_schema, insert_news, fetch_by_collected_range


def test_insert_and_dedup(tmp_path):
    db_path = os.path.join(tmp_path, "news.db")
    conn = connect(db_path)
    ensure_schema(conn)

    item = NewsItem(
        url="https://example.com/a",
        title="Title A",
        published_date=None,
        collected_date="2026-02-06T00:00:00+00:00",
        content="Hello world",
        summary=None,
    )
    assert insert_news(conn, item) is True
    assert insert_news(conn, item) is False


def test_fetch_by_collected_range(tmp_path):
    db_path = os.path.join(tmp_path, "news.db")
    conn = connect(db_path)
    ensure_schema(conn)

    items = [
        NewsItem(
            url="https://example.com/a",
            title="A",
            published_date=None,
            collected_date="2026-02-05T00:00:00+00:00",
            content="A",
            summary=None,
        ),
        NewsItem(
            url="https://example.com/b",
            title="B",
            published_date=None,
            collected_date="2026-02-07T00:00:00+00:00",
            content="B",
            summary=None,
        ),
    ]
    for it in items:
        insert_news(conn, it)

    rows = fetch_by_collected_range(
        conn, "2026-02-06T00:00:00+00:00", "2026-02-08T00:00:00+00:00"
    )
    assert len(rows) == 1
    assert rows[0]["url"] == "https://example.com/b"
