from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Optional

from src.core.config import LLMConfig, load_env, load_yaml
from src.core.llm import LLMClient
from src.core.time_utils import iso_year_week, now_utc


@dataclass(frozen=True)
class BloggerConfig:
    input_summary: Optional[str]
    output_dir: str
    markdown_instructions: Optional[str]
    llm: LLMConfig


def load_config(path: str, env_path: Optional[str] = None) -> BloggerConfig:
    load_env(env_path)
    raw = load_yaml(path).get("blogger", {})
    llm = raw.get("llm", {})
    return BloggerConfig(
        input_summary=raw.get("input_summary"),
        output_dir=raw["output_dir"],
        markdown_instructions=raw.get("markdown_instructions"),
        llm=LLMConfig(
            provider=llm["provider"],
            model=llm["model"],
            api_key_env=llm["api_key_env"],
        ),
    )


def run(
    config_path: str,
    env_path: Optional[str] = None,
    summary_path: Optional[str] = None,
) -> str:
    cfg = load_config(config_path, env_path)
    log = logging.getLogger("blogger")
    if not summary_path:
        summary_path = cfg.input_summary
    if not summary_path:
        year, week = iso_year_week(now_utc())
        summary_path = f"output/news_summaries/news_{year:04d}_{week:02d}.md"

    log.info("Using summary file: %s", summary_path)
    with open(summary_path, "r", encoding="utf-8") as f:
        summary_md = f.read()

    client = LLMClient(cfg.llm)
    blog_md = client.blog_from_summary(summary_md, cfg.markdown_instructions)

    year, week = iso_year_week(now_utc())
    output_path = f"{cfg.output_dir}/blog_{year:04d}_{week:02d}.md"
    blog_md_stripped = blog_md.lstrip()
    if blog_md_stripped.startswith("---"):
        lines = blog_md_stripped.splitlines()
        end_idx = None
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                end_idx = i
                break
        if end_idx is not None:
            blog_md = "\n".join(lines[end_idx + 1 :]).lstrip()
    title = "Weekly AI News"
    for line in blog_md.splitlines():
        if line.startswith("# "):
            title = line[2:].strip() or title
            break
        if line.strip():
            break
    blog_lines = blog_md.splitlines()
    if blog_lines and blog_lines[0].startswith("# "):
        blog_lines = blog_lines[1:]
        if blog_lines and not blog_lines[0].strip():
            blog_lines = blog_lines[1:]
        blog_md = "\n".join(blog_lines).lstrip()
    run_date = now_utc().date().isoformat()
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
    summary_stem = Path(summary_path).stem
    reference = (
        "\n\n---\n\n"
        f"- [AI news summary — {year:04d}-{week:02d}]"
        f"(../weekly_news/{summary_stem})\n"
    )
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(frontmatter + blog_md + reference)
    log.info("Wrote blog file: %s", output_path)
    return output_path
