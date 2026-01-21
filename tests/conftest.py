"""Global pytest configuration and fixtures.

Mocks GCP dependencies to allow tests to run without credentials.
"""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(scope="session", autouse=True)
def mock_firestore_client():
    """Mock Firestore client globally to avoid GCP credential errors in CI.

    This fixture runs automatically (autouse=True) for the entire test session.
    It patches the firestore module before any tests import it.
    """
    with patch("google.cloud.firestore.Client"):
        yield


@pytest.fixture(scope="session", autouse=True)
def mock_gcp_credentials():
    """Mock GCP authentication to prevent DefaultCredentialsError in CI.

    Ensures tests can run without GOOGLE_APPLICATION_CREDENTIALS environment variable.
    """
    with patch("google.auth.default") as mock_auth:
        # Mock successful authentication
        mock_credentials = MagicMock()
        mock_auth.return_value = (mock_credentials, "test-project")
        yield mock_auth


@pytest.fixture(scope="session", autouse=True)
def mock_environment_variables():
    """Mock environment variables required for tests.

    Prevents EnvironmentError when running in CI without .env file.
    """
    import os

    # Set minimal required environment variables for testing
    os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "test-project")
    os.environ.setdefault("ENVIRONMENT", "DEV")  # Must be PROD or DEV
    os.environ.setdefault("ALPACA_API_KEY", "test-key")
    os.environ.setdefault("ALPACA_SECRET_KEY", "test-secret")
    os.environ.setdefault("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
    os.environ.setdefault("ENABLE_EXECUTION", "False")
    os.environ.setdefault("ALPACA_PAPER_TRADING", "True")

    yield
