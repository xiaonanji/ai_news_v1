from __future__ import annotations

from dataclasses import dataclass
import logging
from datetime import timedelta, timezone
from email.utils import parsedate_to_datetime
from datetime import datetime
from urllib.parse import urlsplit, urlunsplit
from typing import Any, Dict, Iterable, Optional

import feedparser
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from src.core.config import LLMConfig, load_env, load_yaml
from src.core.db import NewsItem, connect, ensure_schema, insert_news
from src.core.time_utils import now_utc, to_iso


@dataclass(frozen=True)
class CollectorConfig:
    db_path: str
    lookback_days: int
    max_items_per_source: int
    llm: LLMConfig
    sources: list[Dict[str, Any]]


def load_config(path: str, env_path: Optional[str] = None) -> CollectorConfig:
    load_env(env_path)
    raw = load_yaml(path).get("collector", {})
    llm = raw.get("llm", {})
    return CollectorConfig(
        db_path=raw["db_path"],
        lookback_days=int(raw["lookback_days"]),
        max_items_per_source=int(raw["max_items_per_source"]),
        llm=LLMConfig(
            provider=llm["provider"],
            model=llm["model"],
            api_key_env=llm["api_key_env"],
        ),
        sources=raw.get("sources", []),
    )


def run(config_path: str, env_path: Optional[str] = None) -> None:
    cfg = load_config(config_path, env_path)
    conn = connect(cfg.db_path)
    ensure_schema(conn)

    log = logging.getLogger("collector")
    for source in cfg.sources:
        source_type = source.get("type")
        log.info("Fetching source: %s (%s)", source.get("name") or source.get("url"), source_type)
        if source_type == "rss":
            items = fetch_rss(source, cfg.max_items_per_source, cfg.lookback_days)
        elif source_type == "html":
            items = fetch_html(source, cfg.max_items_per_source)
        elif source_type == "js":
            items = fetch_js(source, cfg.max_items_per_source)
        elif source_type == "api":
            items = fetch_api(source, cfg.max_items_per_source)
        else:
            raise ValueError(f"Unknown source type: {source_type}")

        for item in items:
            news = NewsItem(
                url=item["url"],
                title=item["title"],
                published_date=item.get("published_date"),
                collected_date=to_iso(now_utc()),
                content=item["content"],
                summary=None,
            )
            inserted = insert_news(conn, news)
            if inserted:
                log.info("Saved: %s", news.title)
            else:
                log.info("Duplicate skipped: %s", news.title)


def list_source_urls(config_path: str, env_path: Optional[str] = None) -> None:
    cfg = load_config(config_path, env_path)
    log = logging.getLogger("collector.urls")
    for source in cfg.sources:
        source_type = source.get("type")
        name = source.get("name") or source.get("url")
        log.info("Listing URLs for source: %s (%s)", name, source_type)
        if source_type == "rss":
            urls = list_rss_urls(source, cfg.max_items_per_source, cfg.lookback_days)
        elif source_type == "html":
            urls = list_html_urls(source, cfg.max_items_per_source)
        elif source_type == "js":
            urls = list_js_urls(source, cfg.max_items_per_source)
        elif source_type == "api":
            urls = list_api_urls(source, cfg.max_items_per_source)
        else:
            raise ValueError(f"Unknown source type: {source_type}")

        print(f"\nSource: {name}")
        for url in urls:
            print(url)


def fetch_rss(
    source: Dict[str, Any], limit: int, lookback_days: int
) -> Iterable[Dict[str, Any]]:
    url = source["url"]
    source_norm = _normalize_url(url)
    feed = feedparser.parse(url)
    now = now_utc()
    cutoff = now - timedelta(days=lookback_days)
    items: list[Dict[str, Any]] = []

    for entry in feed.entries:
        if len(items) >= limit:
            break

        published_dt = _parse_entry_datetime(entry)
        if published_dt is not None and published_dt < cutoff:
            continue

        link = entry.get("link")
        title = entry.get("title", "").strip()
        if not link or not title:
            continue
        if _is_same_url(link, source_norm):
            continue

        content_html = _extract_entry_html(entry)
        content_text = _html_to_text(content_html) if content_html else ""
        # Always try to fetch full article text; fall back to feed content if fetch fails.
        full_text = _fetch_article_text(link)
        if full_text:
            content_text = full_text

        items.append(
            {
                "url": link,
                "title": title,
                "published_date": published_dt.astimezone(timezone.utc).isoformat()
                if published_dt
                else None,
                "content": content_text,
            }
        )

    return items


def fetch_html(source: Dict[str, Any], limit: int) -> Iterable[Dict[str, Any]]:
    howto = (source.get("howto") or {}).get("html") or {}
    list_selector = howto.get("list_selector")
    title_selector = howto.get("title_selector", "h1")
    date_selector = howto.get("date_selector")
    content_selector = howto.get("content_selector", "article")

    if not list_selector:
        raise ValueError("HTML source missing howto.html.list_selector")

    base_url = source["url"]
    base_norm = _normalize_url(base_url)
    try:
        resp = requests.get(base_url, timeout=15)
        resp.raise_for_status()
    except Exception as exc:
        raise RuntimeError(f"Failed to fetch HTML source: {base_url}") from exc

    soup = BeautifulSoup(resp.text, "lxml")
    links = soup.select(list_selector)
    items: list[Dict[str, Any]] = []

    for link in links:
        if len(items) >= limit:
            break
        href = link.get("href")
        if not href:
            continue
        url = requests.compat.urljoin(base_url, href)
        if _is_same_url(url, base_norm):
            continue
        item = _fetch_html_article(url, title_selector, date_selector, content_selector)
        if not item:
            continue
        items.append(item)

    return items


def fetch_js(source: Dict[str, Any], limit: int) -> Iterable[Dict[str, Any]]:
    howto = (source.get("howto") or {}).get("js") or {}
    list_selector = howto.get("list_selector")
    title_selector = howto.get("title_selector", "h1")
    date_selector = howto.get("date_selector")
    content_selector = howto.get("content_selector", "article")
    wait_for = howto.get("wait_for")
    wait_ms = int(howto.get("wait_ms", 0))

    if not list_selector:
        raise ValueError("JS source missing howto.js.list_selector")

    base_url = source["url"]
    base_norm = _normalize_url(base_url)
    items: list[Dict[str, Any]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(base_url, wait_until="networkidle")
        if wait_for:
            page.wait_for_selector(wait_for, timeout=15000)
        if wait_ms > 0:
            page.wait_for_timeout(wait_ms)

        link_els = page.query_selector_all(list_selector)
        hrefs: list[str] = []
        for el in link_els:
            href = el.get_attribute("href")
            if href:
                full = requests.compat.urljoin(base_url, href)
                if _is_same_url(full, base_norm):
                    continue
                hrefs.append(full)
            if len(hrefs) >= limit:
                break

        for url in hrefs:
            if len(items) >= limit:
                break
            item = _fetch_js_article(
                page, url, title_selector, date_selector, content_selector
            )
            if item:
                items.append(item)

        browser.close()

    return items


def fetch_api(source: Dict[str, Any], limit: int) -> Iterable[Dict[str, Any]]:
    howto = (source.get("howto") or {}).get("api") or {}
    items_path = howto.get("items_path") or "$"
    url_field = howto.get("url_field")
    title_field = howto.get("title_field")
    date_field = howto.get("date_field")
    content_field = howto.get("content_field")

    if not url_field or not title_field:
        raise ValueError("API source missing howto.api.url_field/title_field")

    source_url = source["url"]
    source_norm = _normalize_url(source_url)
    resp = requests.get(source_url, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    items = _get_path(data, items_path)
    if not isinstance(items, list):
        raise ValueError("API items_path did not resolve to a list.")

    results: list[Dict[str, Any]] = []
    for item in items:
        if len(results) >= limit:
            break
        if not isinstance(item, dict):
            continue
        url = item.get(url_field)
        title = item.get(title_field)
        if not url or not title:
            continue
        if _is_same_url(url, source_norm):
            continue
        published_date = item.get(date_field) if date_field else None
        content = item.get(content_field) if content_field else ""
        results.append(
            {
                "url": url,
                "title": str(title).strip(),
                "published_date": published_date,
                "content": str(content).strip() if content is not None else "",
            }
        )
    return results


def list_rss_urls(
    source: Dict[str, Any], limit: int, lookback_days: int
) -> Iterable[str]:
    url = source["url"]
    source_norm = _normalize_url(url)
    feed = feedparser.parse(url)
    now = now_utc()
    cutoff = now - timedelta(days=lookback_days)
    urls: list[str] = []

    for entry in feed.entries:
        if len(urls) >= limit:
            break
        published_dt = _parse_entry_datetime(entry)
        if published_dt is not None and published_dt < cutoff:
            continue
        link = entry.get("link")
        if link and not _is_same_url(link, source_norm):
            urls.append(link)
    return urls


def list_html_urls(source: Dict[str, Any], limit: int) -> Iterable[str]:
    howto = (source.get("howto") or {}).get("html") or {}
    list_selector = howto.get("list_selector")
    if not list_selector:
        raise ValueError("HTML source missing howto.html.list_selector")

    base_url = source["url"]
    base_norm = _normalize_url(base_url)
    try:
        resp = requests.get(base_url, timeout=15)
        resp.raise_for_status()
    except Exception as exc:
        raise RuntimeError(f"Failed to fetch HTML source: {base_url}") from exc

    soup = BeautifulSoup(resp.text, "lxml")
    links = soup.select(list_selector)
    urls: list[str] = []
    for link in links:
        if len(urls) >= limit:
            break
        href = link.get("href")
        if href:
            full = requests.compat.urljoin(base_url, href)
            if _is_same_url(full, base_norm):
                continue
            urls.append(full)
    return urls


def list_js_urls(source: Dict[str, Any], limit: int) -> Iterable[str]:
    howto = (source.get("howto") or {}).get("js") or {}
    list_selector = howto.get("list_selector")
    wait_for = howto.get("wait_for")
    wait_ms = int(howto.get("wait_ms", 0))
    if not list_selector:
        raise ValueError("JS source missing howto.js.list_selector")

    base_url = source["url"]
    base_norm = _normalize_url(base_url)
    urls: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(base_url, wait_until="networkidle")
        if wait_for:
            try:
                page.wait_for_selector(wait_for, timeout=15000)
            except PlaywrightTimeoutError:
                logging.getLogger("collector.urls").warning(
                    "Timeout waiting for selector '%s' on %s. Continuing.",
                    wait_for,
                    base_url,
                )
        if wait_ms > 0:
            page.wait_for_timeout(wait_ms)

        link_els = page.query_selector_all(list_selector)
        for el in link_els:
            if len(urls) >= limit:
                break
            href = el.get_attribute("href")
            if href:
                full = requests.compat.urljoin(base_url, href)
                if _is_same_url(full, base_norm):
                    continue
                urls.append(full)
        browser.close()
    return urls


def list_api_urls(source: Dict[str, Any], limit: int) -> Iterable[str]:
    howto = (source.get("howto") or {}).get("api") or {}
    items_path = howto.get("items_path") or "$"
    url_field = howto.get("url_field")

    source_url = source["url"]
    source_norm = _normalize_url(source_url)
    resp = requests.get(source_url, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    items = _get_path(data, items_path)
    if not isinstance(items, list):
        raise ValueError("API items_path did not resolve to a list.")

    urls: list[str] = []
    if not url_field and items and isinstance(items[0], dict):
        for key in ("canonical_url", "url", "link", "href", "permalink"):
            if key in items[0]:
                url_field = key
                break
    if not url_field:
        raise ValueError("API source missing howto.api.url_field")
    for item in items:
        if len(urls) >= limit:
            break
        if isinstance(item, dict) and item.get(url_field):
            candidate = item[url_field]
            if not _is_same_url(candidate, source_norm):
                urls.append(candidate)
    return urls


def _parse_entry_datetime(entry: Any) -> Optional[datetime]:
    for key in ("published", "updated", "created"):
        if key in entry:
            try:
                dt = parsedate_to_datetime(entry[key])
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except Exception:
                continue
    return None


def _extract_entry_html(entry: Any) -> Optional[str]:
    if "content" in entry and entry.content:
        return entry.content[0].value
    if "summary" in entry:
        return entry.summary
    return None


def _html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    return " ".join(soup.get_text(separator=" ").split())


def _fetch_article_text(url: str) -> str:
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
    except Exception:
        return ""

    soup = BeautifulSoup(resp.text, "lxml")
    article = soup.find("article")
    if article:
        text = article.get_text(separator=" ")
    else:
        text = soup.get_text(separator=" ")
    return " ".join(text.split())


def _fetch_html_article(
    url: str,
    title_selector: str,
    date_selector: Optional[str],
    content_selector: str,
) -> Optional[Dict[str, Any]]:
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
    except Exception:
        return None

    soup = BeautifulSoup(resp.text, "lxml")
    title_el = soup.select_one(title_selector)
    if not title_el:
        return None
    title = " ".join(title_el.get_text(separator=" ").split())
    if not title:
        return None

    published_date = None
    if date_selector:
        date_el = soup.select_one(date_selector)
        if date_el:
            date_text = " ".join(date_el.get_text(separator=" ").split())
            if date_text:
                published_date = date_text

    content_el = soup.select_one(content_selector)
    if content_el:
        content = content_el.get_text(separator=" ")
    else:
        content = soup.get_text(separator=" ")
    content = " ".join(content.split())
    if not content:
        return None

    return {
        "url": url,
        "title": title,
        "published_date": published_date,
        "content": content,
    }


def _fetch_js_article(
    page: Any,
    url: str,
    title_selector: str,
    date_selector: Optional[str],
    content_selector: str,
) -> Optional[Dict[str, Any]]:
    try:
        page.goto(url, wait_until="networkidle")
    except Exception:
        return None

    title_el = page.query_selector(title_selector)
    if not title_el:
        return None
    title = " ".join((title_el.inner_text() or "").split())
    if not title:
        return None

    published_date = None
    if date_selector:
        date_el = page.query_selector(date_selector)
        if date_el:
            date_text = " ".join((date_el.inner_text() or "").split())
            if date_text:
                published_date = date_text

    content_el = page.query_selector(content_selector)
    if content_el:
        content = content_el.inner_text() or ""
    else:
        content = page.inner_text("body") or ""
    content = " ".join(content.split())
    if not content:
        return None

    return {
        "url": url,
        "title": title,
        "published_date": published_date,
        "content": content,
    }


def _get_path(data: Any, path: str) -> Any:
    if not path or path == "$":
        return data
    current = data
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list):
            try:
                idx = int(part)
                current = current[idx]
            except Exception:
                return None
        else:
            return None
    return current


def _normalize_url(url: str) -> str:
    try:
        parts = urlsplit(url)
        scheme = parts.scheme.lower()
        netloc = parts.netloc.lower()
        path = parts.path or "/"
        if path != "/" and path.endswith("/"):
            path = path[:-1]
        return urlunsplit((scheme, netloc, path, "", ""))
    except Exception:
        return url


def _is_same_url(candidate: str, source_norm: str) -> bool:
    return _normalize_url(candidate) == source_norm
