from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Iterable, Optional


@dataclass(frozen=True)
class NewsItem:
    url: str
    title: str
    published_date: Optional[str]
    collected_date: str
    content: str
    summary: Optional[str] = None


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS news (
  url TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  published_date TEXT NULL,
  collected_date TEXT NOT NULL,
  content TEXT NOT NULL,
  summary TEXT NULL
);
CREATE INDEX IF NOT EXISTS idx_news_title ON news(title);
CREATE INDEX IF NOT EXISTS idx_news_collected ON news(collected_date);
"""


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    with conn:
        conn.executescript(SCHEMA_SQL)


def exists_by_url_or_title(conn: sqlite3.Connection, url: str, title: str) -> bool:
    cur = conn.execute(
        "SELECT 1 FROM news WHERE url = ? OR title = ? LIMIT 1",
        (url, title),
    )
    return cur.fetchone() is not None


def insert_news(conn: sqlite3.Connection, item: NewsItem) -> bool:
    if exists_by_url_or_title(conn, item.url, item.title):
        return False
    with conn:
        conn.execute(
            """
            INSERT INTO news (url, title, published_date, collected_date, content, summary)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                item.url,
                item.title,
                item.published_date,
                item.collected_date,
                item.content,
                item.summary,
            ),
        )
    return True


def update_summary(conn: sqlite3.Connection, url: str, summary: str) -> None:
    with conn:
        conn.execute(
            "UPDATE news SET summary = ? WHERE url = ?",
            (summary, url),
        )


def fetch_by_collected_range(
    conn: sqlite3.Connection, start_iso: str, end_iso: str
) -> Iterable[sqlite3.Row]:
    cur = conn.execute(
        """
        SELECT url, title, published_date, collected_date, content, summary
        FROM news
        WHERE collected_date >= ? AND collected_date < ?
        ORDER BY collected_date ASC
        """,
        (start_iso, end_iso),
    )
    return cur.fetchall()
