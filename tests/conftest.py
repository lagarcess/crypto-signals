"""Global pytest fixtures and environment overrides.

This file establishes the baseline test environment, ensuring that NO real
network calls or authentications are performed during the test suite, while
avoiding non-thread-safe global MagicMocks that conflict with concurrent executors.
"""

import os
import pytest

@pytest.fixture(autouse=True)
def mock_env_vars():
    """Set standard mock environment variables for isolated testing."""
    os.environ["ALPACA_API_KEY"] = "test_alpaca_key"
    os.environ["ALPACA_API_SECRET"] = "test_alpaca_secret"
    os.environ["ALPACA_PAPER_TRADING"] = "True"
    os.environ["DISCORD_WEBHOOK"] = "https://discord.com/api/webhooks/test"
    os.environ["GOOGLE_CLOUD_PROJECT"] = "test-project-id"

    # CRUCIAL: Setting the emulator host cleanly bypasses Google Application 
    # Default Credentials (ADC) without requiring a `MagicMock` globally.
    # This prevents `DefaultCredentialsError` in CI environments and avoids 
    # ThreadPoolExecutor dictionary iteration crashes.
    os.environ["FIRESTORE_EMULATOR_HOST"] = "127.0.0.1:8080"
