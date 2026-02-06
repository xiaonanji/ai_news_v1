import pytest

from src.cli import validate_run_list


def test_validate_run_list_allows_pipeline_combo():
    validate_run_list(["collector", "analyzer", "blogger"])


def test_validate_run_list_blocks_collector_blogger():
    with pytest.raises(ValueError):
        validate_run_list(["collector", "blogger"])
