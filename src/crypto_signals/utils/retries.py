"""
Centralized retry logic for outbound I/O calls using Tenacity.
"""

import logging
import os

from loguru import logger
from tenacity import before_sleep_log, retry, stop_after_attempt, wait_exponential


def _is_test_env():
    return os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("TEST_MODE") == "True"


def dynamic_stop(retry_state):
    """Dynamic stop condition based on environment."""
    if _is_test_env():
        return stop_after_attempt(3)(retry_state)
    return stop_after_attempt(6)(retry_state)


def dynamic_wait(retry_state):
    """Dynamic wait condition based on environment."""
    if _is_test_env():
        return wait_exponential(multiplier=0.1, min=0.1, max=0.5)(retry_state)
    return wait_exponential(multiplier=3, min=4, max=70)(retry_state)


def dynamic_before_sleep(retry_state):
    """Dynamic logging based on environment."""
    if _is_test_env():
        # Minimal logging in tests
        pass
    else:
        # tenacity.before_sleep_log expects standard logging levels (int)
        return before_sleep_log(logger, logging.WARNING)(retry_state)


# Specialized decorators for Alpaca and Firestore
retry_alpaca = retry(
    stop=dynamic_stop,
    wait=dynamic_wait,
    before_sleep=dynamic_before_sleep,
    reraise=True,
)

retry_firestore = retry(
    stop=dynamic_stop,
    wait=dynamic_wait,
    before_sleep=dynamic_before_sleep,
    reraise=True,
)
