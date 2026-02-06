VENV=.\.venv
PY=$(VENV)\Scripts\python.exe
PIP=$(VENV)\Scripts\pip.exe

.PHONY: help venv install test run pipeline collector analyzer blogger inspect

help:
	@echo "Targets:"
	@echo "  venv        Create virtual environment"
	@echo "  install     Install requirements"
	@echo "  test        Run pytest"
	@echo "  run         Run pipeline (collector->analyzer->blogger)"
	@echo "  collector   Run collector only"
	@echo "  analyzer    Run analyzer only"
	@echo "  blogger     Run blogger only (requires summary file)"
	@echo "  inspect     Inspect a source URL (set URL=...)"

venv:
	python -m venv .venv

install:
	$(PIP) install -r requirements.txt

test:
	$(PY) -m pytest -q

run:
	$(PY) -m src.cli --run pipeline

collector:
	$(PY) -m src.cli --run collector

analyzer:
	$(PY) -m src.cli --run analyzer

blogger:
	$(PY) -m src.cli --run blogger --summary-file $(FILE)

inspect:
	$(PY) -m src.cli --inspect-source $(URL)
