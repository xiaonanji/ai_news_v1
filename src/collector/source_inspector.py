from __future__ import annotations

from typing import Any, Optional, Tuple, List

import logging
import yaml
import feedparser
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from src.core.config import LLMConfig, load_env, load_yaml
from src.core.llm import LLMClient


def run(url: str, config_path: str, env_path: Optional[str] = None) -> str:
    load_env(env_path)
    raw = load_yaml(config_path).get("collector", {})
    llm = raw.get("llm", {})
    llm_cfg = LLMConfig(
        provider=llm["provider"],
        model=llm["model"],
        api_key_env=llm["api_key_env"],
    )

    content = _fetch_content(url)
    client = LLMClient(llm_cfg)
    output = client.analyze_source(url, content)

    try:
        _validate_output(output)
        output = _quote_all_strings(output)
    except Exception as exc:
        log = logging.getLogger("collector.source_inspector")
        log.warning("Inspector output may be invalid: %s", exc)
        log.warning("Raw output:\n%s", output)
    return output


def _fetch_content(url: str) -> str:
    # Prefer JSON if available; otherwise render HTML with Playwright.
    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        try:
            data = resp.json()
            return yaml.safe_dump(data, sort_keys=False)[:20000]
        except Exception:
            pass
        html = resp.text
        if html and len(html) > 20000:
            return html[:20000]
    except Exception:
        pass

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(url, wait_until="networkidle")
            page.wait_for_timeout(1000)
            html = page.content()
            browser.close()
        return html[:20000] if html else ""
    except Exception:
        return ""


def _dynamic_inspect(url: str) -> Optional[str]:
    rss_snippet = _try_rss_inspect(url)
    if rss_snippet:
        return rss_snippet

    api_snippet = _try_api_inspect(url)
    if api_snippet:
        return api_snippet

    html_snippet = _try_html_or_js_inspect(url)
    if html_snippet:
        return html_snippet

    return None


def _try_rss_inspect(url: str) -> Optional[str]:
    try:
        feed = feedparser.parse(url)
    except Exception:
        return None

    if not feed or not getattr(feed, "entries", None):
        return None

    snippet = [
        {
            "name": _guess_name_from_url(url),
            "url": url,
            "type": "rss",
            "howto": {
                "rss": {
                    "item_limit": 50,
                    "date_field": "published",
                }
            },
        }
    ]
    return yaml.safe_dump(snippet, sort_keys=False).strip()


def _try_api_inspect(url: str) -> Optional[str]:
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return None

    items_path, items = _find_items_list(data)
    if items_path is None or not items:
        return None

    url_field, title_field, date_field, content_field = _infer_fields(items)
    if not url_field or not title_field:
        return None

    if items_path == "":
        items_path = "$"

    snippet = [
        {
            "name": _guess_name_from_url(url),
            "url": url,
            "type": "api",
            "howto": {
                "api": {
                    "items_path": items_path,
                    "url_field": url_field,
                    "title_field": title_field,
                    "date_field": date_field or "",
                    "content_field": content_field or "",
                }
            },
        }
    ]
    api_cfg = snippet[0]["howto"]["api"]
    if not api_cfg["date_field"]:
        api_cfg.pop("date_field")
    if not api_cfg["content_field"]:
        api_cfg.pop("content_field")
    return yaml.safe_dump(snippet, sort_keys=False).strip()


def _find_items_list(data: Any) -> Tuple[Optional[str], Optional[list]]:
    if isinstance(data, list):
        return "", data
    if isinstance(data, dict):
        for key in ("items", "data", "results", "articles", "posts", "news"):
            val = data.get(key)
            if isinstance(val, list) and val and isinstance(val[0], dict):
                return key, val
    if isinstance(data, dict):
        for key, val in data.items():
            if isinstance(val, dict):
                sub_path, sub_items = _find_items_list(val)
                if sub_items is not None:
                    path = f"{key}.{sub_path}" if sub_path else key
                    return path, sub_items
    return None, None


def _infer_fields(items: list) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    sample = items[0] if items else {}
    if not isinstance(sample, dict):
        return None, None, None, None

    url_field = _pick_field(sample, ["canonical_url", "url", "link", "href", "permalink"])
    title_field = _pick_field(sample, ["title", "headline", "name"])
    date_field = _pick_field(
        sample,
        [
            "post_date",
            "date",
            "published",
            "published_at",
            "publishedAt",
            "created_at",
            "createdAt",
            "updated_at",
            "updatedAt",
        ],
    )
    content_field = _pick_field(
        sample,
        [
            "body_html",
            "body_json",
            "truncated_body_text",
            "description",
            "content",
            "summary",
            "body",
            "text",
        ],
    )
    return url_field, title_field, date_field, content_field


def _pick_field(sample: dict, candidates: list[str]) -> Optional[str]:
    for key in candidates:
        if key in sample:
            return key
    return None


def _guess_name_from_url(url: str) -> str:
    return url.replace("https://", "").replace("http://", "").strip("/")


def _try_html_or_js_inspect(url: str) -> Optional[str]:
    rendered_html = _render_page(url)
    if not rendered_html:
        return None

    soup = BeautifulSoup(rendered_html, "lxml")
    link_selector = _infer_list_selector(soup)
    if not link_selector:
        return None

    title_selector = _infer_title_selector(soup)
    date_selector = _infer_date_selector(soup)
    content_selector = _infer_content_selector(soup)

    is_js = _likely_js_rendered(url, link_selector)
    source_type = "js" if is_js else "html"
    howto_key = "js" if is_js else "html"

    snippet = [
        {
            "name": _guess_name_from_url(url),
            "url": url,
            "type": source_type,
            "howto": {
                howto_key: {
                    "list_selector": link_selector,
                    "title_selector": title_selector,
                    "date_selector": date_selector,
                    "content_selector": content_selector,
                    **(
                        {
                            "wait_for": link_selector,
                            "wait_ms": 1000,
                            "strategy": "browser_automation",
                            "notes": "Auto-detected via rendered HTML.",
                        }
                        if is_js
                        else {}
                    ),
                }
            },
        }
    ]
    return yaml.safe_dump(snippet, sort_keys=False).strip()


def _render_page(url: str) -> Optional[str]:
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(url, wait_until="networkidle")
            page.wait_for_timeout(1000)
            html = page.content()
            browser.close()
        return html
    except Exception:
        return None


def _infer_list_selector(soup: BeautifulSoup) -> Optional[str]:
    anchors = soup.select("a[href]")
    if not anchors:
        return None

    candidates: dict[str, List[str]] = {}
    for a in anchors:
        text = " ".join(a.get_text(separator=" ").split())
        href = a.get("href", "")
        if not text or len(text) < 10:
            continue
        classes = [c for c in (a.get("class") or []) if c]
        if not classes:
            continue
        selector = "a." + ".".join(classes)
        candidates.setdefault(selector, []).append(href)

    if not candidates:
        return "a[href]"

    best = max(candidates.items(), key=lambda kv: len(set(kv[1])))
    return best[0]


def _infer_title_selector(soup: BeautifulSoup) -> str:
    return "h1" if soup.select_one("h1") else "title"


def _infer_date_selector(soup: BeautifulSoup) -> str:
    if soup.select_one("time"):
        return "time"
    for cls in ("date", "published", "timestamp"):
        if soup.select_one(f".{cls}"):
            return f".{cls}"
    return "time"


def _infer_content_selector(soup: BeautifulSoup) -> str:
    if soup.select_one("article"):
        return "article"
    if soup.select_one("main"):
        return "main"
    return "body"


def _likely_js_rendered(url: str, selector: str) -> bool:
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        return selector not in resp.text
    except Exception:
        return True


def _validate_output(yaml_text: str) -> None:
    try:
        data = yaml.safe_load(yaml_text)
    except Exception as exc:
        raise ValueError("Inspector output is not valid YAML.") from exc

    if not isinstance(data, list) or not data:
        raise ValueError("Inspector output must be a YAML list with one source item.")

    item = data[0]
    if not isinstance(item, dict):
        raise ValueError("Inspector output must contain a mapping for the source item.")

    for field in ("name", "url", "type", "howto"):
        if field not in item:
            raise ValueError(f"Inspector output missing required field: {field}")

    source_type = item["type"]
    howto = item.get("howto") or {}
    if not isinstance(howto, dict):
        raise ValueError("Inspector output 'howto' must be a mapping.")

    if source_type == "rss":
        _require_fields(howto.get("rss"), ["item_limit", "date_field"], "howto.rss")
    elif source_type == "html":
        _require_fields(
            howto.get("html"),
            ["list_selector", "title_selector", "date_selector", "content_selector"],
            "howto.html",
        )
    elif source_type == "js":
        _require_fields(
            howto.get("js"),
            [
                "list_selector",
                "title_selector",
                "date_selector",
                "content_selector",
                "wait_for",
                "wait_ms",
                "strategy",
                "notes",
            ],
            "howto.js",
        )
    elif source_type == "api":
        _require_fields(
            howto.get("api"),
            ["items_path", "url_field", "title_field"],
            "howto.api",
        )
    else:
        raise ValueError("Inspector output 'type' must be one of: rss, html, js, api.")


def _require_fields(section: Any, fields: list[str], prefix: str) -> None:
    if not isinstance(section, dict):
        raise ValueError(f"Inspector output missing required section: {prefix}")
    for f in fields:
        if f not in section:
            raise ValueError(f"Inspector output missing required field: {prefix}.{f}")


def _quote_all_strings(yaml_text: str) -> str:
    data = yaml.safe_load(yaml_text)
    return yaml.safe_dump(data, sort_keys=False, default_style='"').strip()
