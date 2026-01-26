import time
from typing import Callable, Dict, Tuple

from crypto_signals.domain.schemas import AssetClass
from loguru import logger


class PositionCountCache:
    """In-memory cache for sector position counts with a TTL."""

    def __init__(self, ttl_seconds: int = 300):
        """
        Initialize the cache.
        Args:
            ttl_seconds: Time-to-live for cache entries in seconds.
        """
        self.cache: Dict[AssetClass, Tuple[int, float]] = {}
        self.ttl_seconds = ttl_seconds

    def get_or_fetch(self, asset_class: AssetClass, fetch_func: Callable[[], int]) -> int:
        """
        Get count from cache or fetch from the source if expired/missing.
        Args:
            asset_class: The asset class to look up.
            fetch_func: A callable that fetches the count from the repository.
        Returns:
            The position count.
        """
        cached_data = self.cache.get(asset_class)
        if cached_data:
            count, timestamp = cached_data
            if time.time() - timestamp < self.ttl_seconds:
                return count

        try:
            # Fetch from the underlying source (e.g., Firestore)
            count = fetch_func()
            self.cache[asset_class] = (count, time.time())
            return count
        except Exception as e:
            logger.error(f"Failed to fetch position count for {asset_class} for cache: {e}")
            # Fail-safe: Return a high number to block trading if the fetch fails.
            # This prevents a data source issue from allowing risky trades.
            return 9999

    def invalidate(self, asset_class: AssetClass) -> None:
        """
        Invalidate the cache for a specific asset class.
        """
        self.cache.pop(asset_class, None)
