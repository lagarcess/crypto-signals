"""Tests for centralized retry logic."""

from unittest.mock import MagicMock

import pytest
from crypto_signals.utils.retries import retry_alpaca, retry_firestore


class TestRetries:
    """Tests for tenacity-based retry decorators."""

    def test_retry_alpaca_success_after_failure(self):
        """Verify retry_alpaca retries and succeeds."""
        mock_func = MagicMock()
        # Fail twice, then succeed
        mock_func.side_effect = [Exception("Fail 1"), Exception("Fail 2"), "Success"]

        decorated = retry_alpaca(mock_func)
        result = decorated()

        assert result == "Success"
        assert mock_func.call_count == 3

    def test_retry_alpaca_exhausted_raises(self):
        """Verify retry_alpaca raises after exhausting retries."""
        mock_func = MagicMock()
        mock_func.side_effect = Exception("Persistent failure")

        decorated = retry_alpaca(mock_func)

        # In test mode, it should stop after 3 attempts
        with pytest.raises(Exception, match="Persistent failure"):
            decorated()

        assert mock_func.call_count == 3

    def test_retry_firestore_success_after_failure(self):
        """Verify retry_firestore retries and succeeds."""
        mock_func = MagicMock()
        mock_func.side_effect = [Exception("Fail 1"), "Success"]

        decorated = retry_firestore(mock_func)
        result = decorated()

        assert result == "Success"
        assert mock_func.call_count == 2

    def test_retry_firestore_exhausted_raises(self):
        """Verify retry_firestore raises after exhausting retries."""
        mock_func = MagicMock()
        mock_func.side_effect = Exception("Persistent firestore failure")

        decorated = retry_firestore(mock_func)

        with pytest.raises(Exception, match="Persistent firestore failure"):
            decorated()

        assert mock_func.call_count == 3
