from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Optional

from src.core.config import LLMConfig, load_env, load_yaml
from src.core.llm import LLMClient
from src.core.time_utils import iso_year_week, now_utc


@dataclass(frozen=True)
class BloggerConfig:
    input_summary: Optional[str]
    output_dir: str
    llm: LLMConfig


def load_config(path: str, env_path: Optional[str] = None) -> BloggerConfig:
    load_env(env_path)
    raw = load_yaml(path).get("blogger", {})
    llm = raw.get("llm", {})
    return BloggerConfig(
        input_summary=raw.get("input_summary"),
        output_dir=raw["output_dir"],
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
    blog_md = client.blog_from_summary(summary_md)

    year, week = iso_year_week(now_utc())
    output_path = f"{cfg.output_dir}/blog_{year:04d}_{week:02d}.md"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(blog_md)
    log.info("Wrote blog file: %s", output_path)
    return output_path
