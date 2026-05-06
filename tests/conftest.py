import pytest


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "db: marks tests that require a live TimescaleDB connection"
    )
