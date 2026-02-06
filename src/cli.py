from __future__ import annotations

import argparse
import logging
from typing import List

from src.analyzer.analyzer import run as run_analyzer
from src.blogger.blogger import run as run_blogger
from src.collector.collector import run as run_collector
from src.collector.source_inspector import run as run_source_inspector


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="AI News pipeline")
    p.add_argument(
        "--run",
        default="pipeline",
        help="Comma-separated list: collector,analyzer,blogger or 'pipeline'",
    )
    p.add_argument("--config-collector", default="configs/collector.yaml")
    p.add_argument("--config-analyzer", default="configs/analyzer.yaml")
    p.add_argument("--config-blogger", default="configs/blogger.yaml")
    p.add_argument("--env", default=".env")
    p.add_argument("--summary-file", default=None)
    p.add_argument("--inspect-source", default=None)
    p.add_argument("--list-urls", action="store_true", help="List URLs from sources")
    p.add_argument(
        "--skip-summarize",
        action="store_true",
        help="Skip LLM summary generation and only write markdown output",
    )
    p.add_argument("--log-level", default="INFO")
    return p.parse_args()


def validate_run_list(items: List[str]) -> None:
    if "collector" in items and "blogger" in items and "analyzer" not in items:
        raise ValueError("Invalid combination: collector + blogger without analyzer.")


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
    log = logging.getLogger("cli")
    if args.inspect_source:
        output = run_source_inspector(args.inspect_source, args.config_collector, args.env)
        print(output)
        return
    if args.list_urls:
        from src.collector.collector import list_source_urls

        list_source_urls(args.config_collector, args.env)
        return

    if args.run == "pipeline":
        run_list = ["collector", "analyzer", "blogger"]
    else:
        run_list = [x.strip() for x in args.run.split(",") if x.strip()]

    validate_run_list(run_list)
    log.info("Run list: %s", ",".join(run_list))

    analyzer_output: str | None = None
    if "collector" in run_list:
        log.info("Running collector")
        run_collector(args.config_collector, args.env)
    if "analyzer" in run_list:
        log.info("Running analyzer")
        analyzer_output = run_analyzer(
            args.config_analyzer, args.env, skip_summarize=args.skip_summarize
        )
    if "blogger" in run_list:
        log.info("Running blogger")
        summary_file = args.summary_file or analyzer_output
        run_blogger(args.config_blogger, args.env, summary_file)


if __name__ == "__main__":
    main()
