"""
Centralized retry logic for outbound I/O calls using Tenacity.
"""

import logging
import os

from loguru import logger
from tenacity import before_sleep_log, retry, stop_after_attempt, wait_exponential


def _is_test_env():
    return os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("TEST_MODE") == "True"


# Retry settings for test environment
_TEST_RETRY_ATTEMPTS = 3
_TEST_RETRY_WAIT_MULTIPLIER = 0.1
_TEST_RETRY_WAIT_MIN = 0.1
_TEST_RETRY_WAIT_MAX = 0.5

# Retry settings for production environment
_PROD_RETRY_ATTEMPTS = 6
_PROD_RETRY_WAIT_MULTIPLIER = 3
_PROD_RETRY_WAIT_MIN = 4
_PROD_RETRY_WAIT_MAX = 70


def dynamic_stop(retry_state):
    """Dynamic stop condition based on environment."""
    if _is_test_env():
        return stop_after_attempt(_TEST_RETRY_ATTEMPTS)(retry_state)
    return stop_after_attempt(_PROD_RETRY_ATTEMPTS)(retry_state)


def dynamic_wait(retry_state):
    """Dynamic wait condition based on environment."""
    if _is_test_env():
        return wait_exponential(
            multiplier=_TEST_RETRY_WAIT_MULTIPLIER,
            min=_TEST_RETRY_WAIT_MIN,
            max=_TEST_RETRY_WAIT_MAX,
        )(retry_state)
    return wait_exponential(
        multiplier=_PROD_RETRY_WAIT_MULTIPLIER,
        min=_PROD_RETRY_WAIT_MIN,
        max=_PROD_RETRY_WAIT_MAX,
    )(retry_state)


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
