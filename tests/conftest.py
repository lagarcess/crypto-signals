import os
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def mock_env_vars():
    """Set mock environment variables for all tests."""
    os.environ["ALPACA_API_KEY"] = "test_key"
    os.environ["ALPACA_SECRET_KEY"] = "test_secret"
    os.environ["GOOGLE_CLOUD_PROJECT"] = "test-project"
    os.environ["TEST_DISCORD_WEBHOOK"] = "https://discord.com/api/webhooks/test"
    os.environ["ALPACA_PAPER_TRADING"] = "true"


@pytest.fixture(autouse=True)
def mock_firestore_client():
    with patch("google.cloud.firestore.Client") as mock:
        yield mock


@pytest.fixture(autouse=True)
def mock_bq_client():
    with patch("google.cloud.bigquery.Client") as mock:
        yield mock


# Expose helpers for easy access in tests
