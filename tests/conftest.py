"""Global pytest fixtures and environment overrides.

This file establishes the baseline test environment, ensuring that NO real
network calls or authentications are performed during the test suite, while
avoiding non-thread-safe global MagicMocks that conflict with concurrent executors.
"""

import os

import pytest

# CRUCIAL: Set env vars at the module level so they are loaded BEFORE any
# test modules or Google Cloud libraries are imported. This prevents
# DefaultCredentialsError during test discovery and initialization.
os.environ["ALPACA_API_KEY"] = "test_alpaca_key"
os.environ["ALPACA_API_SECRET"] = "test_alpaca_secret"
os.environ["ALPACA_PAPER_TRADING"] = "True"
os.environ["DISCORD_WEBHOOK"] = "https://discord.com/api/webhooks/test"
os.environ["GOOGLE_CLOUD_PROJECT"] = "test-project-id"

# Setting the emulator host cleanly bypasses Google Application
# Default Credentials (ADC) without requiring a `MagicMock` globally.
# This prevents `DefaultCredentialsError` in CI environments and avoids
# ThreadPoolExecutor dictionary iteration crashes.
os.environ["FIRESTORE_EMULATOR_HOST"] = "127.0.0.1:8080"


@pytest.fixture(autouse=True)
def mock_env_vars():
    """
    Keep the fixture to ensure variables remain reset for every test,
    in case a specific test modifies os.environ and doesn't clean up.
    """
    os.environ["ALPACA_API_KEY"] = "test_alpaca_key"
    os.environ["ALPACA_API_SECRET"] = "test_alpaca_secret"
    os.environ["ALPACA_PAPER_TRADING"] = "True"
    os.environ["DISCORD_WEBHOOK"] = "https://discord.com/api/webhooks/test"
    os.environ["GOOGLE_CLOUD_PROJECT"] = "test-project-id"
    os.environ["FIRESTORE_EMULATOR_HOST"] = "127.0.0.1:8080"
