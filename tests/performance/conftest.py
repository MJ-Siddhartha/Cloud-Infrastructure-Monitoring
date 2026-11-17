"""Configuration and fixtures for performance testing."""

import os
import pytest

BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8000")


@pytest.fixture
def backend_url():
    return BACKEND_URL
