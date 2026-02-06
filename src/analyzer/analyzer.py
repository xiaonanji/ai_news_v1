from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Optional

from src.core.config import LLMConfig, load_env, load_yaml
from src.core.db import connect, ensure_schema, fetch_by_collected_range, update_summary
from src.core.llm import LLMClient
from src.core.time_utils import iso_week_bounds, iso_year_week, now_utc, to_iso


@dataclass(frozen=True)
class AnalyzerConfig:
    db_path: str
    output_dir: str
    llm: LLMConfig


def load_config(path: str, env_path: Optional[str] = None) -> AnalyzerConfig:
    load_env(env_path)
    raw = load_yaml(path).get("analyzer", {})
    llm = raw.get("llm", {})
    return AnalyzerConfig(
        db_path=raw["db_path"],
        output_dir=raw["output_dir"],
        llm=LLMConfig(
            provider=llm["provider"],
            model=llm["model"],
            api_key_env=llm["api_key_env"],
        ),
    )


def run(
    config_path: str, env_path: Optional[str] = None, *, skip_summarize: bool = False
) -> str:
    cfg = load_config(config_path, env_path)
    conn = connect(cfg.db_path)
    ensure_schema(conn)

    log = logging.getLogger("analyzer")
    now = now_utc()
    year, week = iso_year_week(now)
    start, end = iso_week_bounds(now)

    rows = fetch_by_collected_range(conn, to_iso(start), to_iso(end))
    client = None if skip_summarize else LLMClient(cfg.llm)

    title = f"News Summary ({year:04d}-{week:02d})"
    lines: list[str] = []
    for row in rows:
        summary = row["summary"]
        if not summary and not skip_summarize:
            log.info("Summarizing: %s", row["title"])
            summary = client.summarize_zh(row["content"])
            update_summary(conn, row["url"], summary)

        lines.extend(
            [
                f"#### {row['title']}",
                f"- URL: {row['url']}",
                f"- Published: {row['published_date'] or 'unknown'}",
                f"- Collected: {row['collected_date']}",
                "- Summary:",
                f"  {summary or ''}",
                "",
            ]
        )

    output_path = f"{cfg.output_dir}/news_{year:04d}_{week:02d}.md"
    run_date = now.date().isoformat()
    frontmatter = "\n".join(
        [
            "---",
            f"title: {title}",
            "description:",
            f"date: {run_date}",
            f"scheduled: {run_date}",
            "tags:",
            "  - AI",
            "  - Jeremy",
            "layout: layouts/post.njk",
            "---",
            "",
        ]
    )
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(frontmatter + "\n".join(lines))
    log.info("Wrote summary file: %s", output_path)
    return output_path
