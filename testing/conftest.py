"""Pytest configuration shared by tests under testing/."""

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    """Add the option for running slow sample-question tests."""
    parser.addoption(
        "--run-sample-questions",
        action="store_true",
        default=False,
        help="Run sample test suite, this is a slow and expensive (LLM credits) operation.",
    )


def pytest_configure(config: pytest.Config) -> None:
    """Register the optional test marker."""
    config.addinivalue_line("markers", "optional: marks test as optional")


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    """Skip optional tests unless explicitly enabled on the command line."""
    if not config.getoption("--run-sample-questions"):
        skipper = pytest.mark.skip(reason="Skipped by default. Use --run-sample-questions to run.")
        for item in items:
            if "optional" in item.keywords:
                item.add_marker(skipper)
