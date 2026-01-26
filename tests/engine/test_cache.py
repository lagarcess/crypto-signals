import time
from unittest.mock import Mock

import pytest
from crypto_signals.domain.schemas import AssetClass
from crypto_signals.engine.cache import PositionCountCache


@pytest.fixture
def mock_fetch_func():
    """Returns a mock callable that simulates fetching data."""
    return Mock(return_value=10)


def test_cache_miss_and_fetch(mock_fetch_func):
    """
    Verify that on a cache miss, the fetch function is called and the value is cached.
    """
    cache = PositionCountCache(ttl_seconds=10)
    asset_class = AssetClass.CRYPTO

    # First call should be a miss, triggering a fetch
    count = cache.get_or_fetch(asset_class, mock_fetch_func)

    assert count == 10
    mock_fetch_func.assert_called_once()
    assert cache.cache[asset_class] == (10, pytest.approx(time.time(), abs=1))


def test_cache_hit(mock_fetch_func):
    """
    Verify that on a cache hit, the cached value is returned and the fetch function is not called.
    """
    cache = PositionCountCache(ttl_seconds=10)
    asset_class = AssetClass.EQUITY

    # Prime the cache
    cache.get_or_fetch(asset_class, mock_fetch_func)
    mock_fetch_func.assert_called_once()  # Should be called the first time

    # Second call should be a hit
    count = cache.get_or_fetch(asset_class, mock_fetch_func)

    assert count == 10
    mock_fetch_func.assert_called_once()  # Should NOT be called again


def test_cache_expiry(mock_fetch_func):
    """
    Verify that after the TTL expires, the fetch function is called again.
    """
    cache = PositionCountCache(ttl_seconds=0.1)
    asset_class = AssetClass.CRYPTO

    # First call to populate the cache
    cache.get_or_fetch(asset_class, mock_fetch_func)
    mock_fetch_func.assert_called_once()

    # Wait for the cache to expire
    time.sleep(0.2)

    # Second call should be a miss again
    count = cache.get_or_fetch(asset_class, mock_fetch_func)

    assert count == 10
    assert mock_fetch_func.call_count == 2


def test_cache_invalidation(mock_fetch_func):
    """
    Verify that after invalidation, the fetch function is called again.
    """
    cache = PositionCountCache(ttl_seconds=10)
    asset_class = AssetClass.CRYPTO

    # Prime the cache
    cache.get_or_fetch(asset_class, mock_fetch_func)
    mock_fetch_func.assert_called_once()

    # Invalidate the cache
    cache.invalidate(asset_class)

    # This call should now be a miss
    count = cache.get_or_fetch(asset_class, mock_fetch_func)

    assert count == 10
    assert mock_fetch_func.call_count == 2


def test_cache_multiple_asset_classes():
    """
    Verify that the cache correctly handles multiple asset classes independently.
    """
    cache = PositionCountCache(ttl_seconds=10)
    crypto_class = AssetClass.CRYPTO
    equity_class = AssetClass.EQUITY

    # Mock different return values for each asset class
    def fetch_side_effect(asset_class):
        if asset_class == crypto_class:
            return 5
        elif asset_class == equity_class:
            return 15
        return 0

    # Fetch for Crypto
    crypto_count = cache.get_or_fetch(crypto_class, lambda: fetch_side_effect(crypto_class))
    assert crypto_count == 5

    # Fetch for Equity
    equity_count = cache.get_or_fetch(equity_class, lambda: fetch_side_effect(equity_class))
    assert equity_count == 15

    # Verify cache contents
    assert cache.cache[crypto_class][0] == 5
    assert cache.cache[equity_class][0] == 15

    # Verify fetch was called twice
    assert len(cache.cache) == 2


def test_fetch_exception_returns_failsafe_value(mock_fetch_func):
    """
    Verify that if the fetch function raises an exception, the cache returns a
    fail-safe value and does not store a result.
    """
    cache = PositionCountCache()
    asset_class = AssetClass.CRYPTO
    mock_fetch_func.side_effect = Exception("Firestore is down")

    # The call should handle the exception and return the fail-safe value
    count = cache.get_or_fetch(asset_class, mock_fetch_func)

    assert count == 9999
    mock_fetch_func.assert_called_once()
    # Ensure the cache does not store a value on failure
    assert asset_class not in cache.cache
