"""Fixtures for fault injection tests."""

import os
import pytest

TARGET_HOST = os.getenv("TARGET_HOST", "localhost")
PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://localhost:9090")
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")


@pytest.fixture
def fault_env():
    return {
        "target_host": TARGET_HOST,
        "prometheus_url": PROMETHEUS_URL,
        "backend_url": BACKEND_URL,
    }
