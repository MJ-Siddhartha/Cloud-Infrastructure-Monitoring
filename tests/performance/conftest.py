"""Configuration and fixtures for performance testing."""

import os
import pytest

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")


@pytest.fixture
def backend_url():
    return BACKEND_URL
