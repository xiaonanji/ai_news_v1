AI News Pipeline

Quick start

1. Create and activate venv, then install requirements
2. Set OPENAI_API_KEY in .env
3. Configure sources in configs/collector.yaml

Run modes

Pipeline (collector -> analyzer -> blogger)
python -m src.cli --run pipeline

Collector only
python -m src.cli --run collector

Analyzer only
python -m src.cli --run analyzer

Blogger only (requires summary file)
python -m src.cli --run blogger --summary-file output/news_summaries/news_2026_06.md

Analyzer + Blogger
python -m src.cli --run analyzer,blogger

Collector + Analyzer
python -m src.cli --run collector,analyzer

Source inspector
python -m src.cli --inspect-source https://example.com/news
