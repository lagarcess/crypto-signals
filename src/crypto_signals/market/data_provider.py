"""
Market Data Provider.

This module abstracts the Alpaca API to provide clean, validated market data
(Candles/Bars) and real-time prices for both Stocks and Crypto.
"""

import time
from datetime import datetime, timedelta, timezone
from functools import wraps

import pandas as pd
from alpaca.data.historical import CryptoHistoricalDataClient, StockHistoricalDataClient
from alpaca.data.requests import (
    CryptoBarsRequest,
    CryptoLatestTradeRequest,
    StockBarsRequest,
    StockLatestTradeRequest,
)
from alpaca.data.timeframe import TimeFrame
from crypto_signals.domain.schemas import AssetClass
from crypto_signals.market.exceptions import MarketDataError


def retry_with_backoff(max_retries=3, initial_delay=1.0, backoff_factor=2.0):
    """
    Decorator to retry functions with exponential backoff.

    Args:
        max_retries: Maximum number of retry attempts
        initial_delay: Initial delay in seconds between retries
        backoff_factor: Multiplier for delay after each retry

    Returns:
        Decorated function with retry logic
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            delay = initial_delay
            last_exception = None

            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        # Log retry attempt
                        import logging

                        logger = logging.getLogger(__name__)
                        logger.warning(
                            f"Attempt {attempt + 1}/{max_retries} failed for "
                            f"{func.__name__}: {e}. Retrying in {delay}s..."
                        )
                        time.sleep(delay)
                        delay *= backoff_factor
                    else:
                        # Last attempt failed, raise the exception
                        raise MarketDataError(
                            f"{func.__name__} failed after {max_retries} attempts"
                        ) from last_exception

            # Should not reach here, but if it does, raise the last exception
            raise MarketDataError(
                f"{func.__name__} failed after {max_retries} attempts"
            ) from last_exception

        return wrapper

    return decorator


class MarketDataProvider:
    """
    Provider for market data (Stocks and Crypto).

    Wraps Alpaca's historical data clients.
    """

    def __init__(
        self,
        stock_client: StockHistoricalDataClient,
        crypto_client: CryptoHistoricalDataClient,
    ):
        """
        Initialize with data clients.

        Args:
            stock_client: Alpaca Stock client
            crypto_client: Alpaca Crypto client
        """
        self.stock_client = stock_client
        self.crypto_client = crypto_client

    @retry_with_backoff(max_retries=3, initial_delay=1.0, backoff_factor=2.0)
    def get_daily_bars(
        self,
        symbol: str,
        asset_class: AssetClass,
        lookback_days: int = 365,
    ) -> pd.DataFrame:
        """
        Fetch daily bars for a symbol.

        Args:
            symbol: Ticker symbol (e.g. "BTC/USD", "AAPL")
            asset_class: Asset class (CRYPTO or EQUITY)
            lookback_days: Number of days of history to fetch

        Returns:
            pd.DataFrame: DataFrame indexed by date (UTC)

        Raises:
            MarketDataError: If data is empty or fetch fails
        """
        try:
            end_dt = datetime.now(timezone.utc)
            start_dt = end_dt - timedelta(days=lookback_days)

            if asset_class == AssetClass.CRYPTO:
                # Crypto Request
                request = CryptoBarsRequest(
                    symbol_or_symbols=symbol,
                    timeframe=TimeFrame.Day,
                    start=start_dt,
                    end=end_dt,
                )
                bars = self.crypto_client.get_crypto_bars(request)
            elif asset_class == AssetClass.EQUITY:
                # Stock Request
                request = StockBarsRequest(
                    symbol_or_symbols=symbol,
                    timeframe=TimeFrame.Day,
                    start=start_dt,
                    end=end_dt,
                    adjustment="split",  # Adjust for splits
                )
                bars = self.stock_client.get_stock_bars(request)
            else:
                raise MarketDataError(f"Unsupported asset class: {asset_class}")

            # Convert to DataFrame
            df = bars.df

            if df.empty:
                raise MarketDataError(f"No daily bars found for {symbol}")

            # Reset index if multi-indexed (symbol, date) -> just date
            # Alpaca bars.df usually has MultiIndex [symbol, timestamp]
            if isinstance(df.index, pd.MultiIndex):
                df = df.reset_index(level=0, drop=True)

            return df

        except MarketDataError:
            raise
        except Exception as e:
            raise MarketDataError(f"Failed to fetch daily bars for {symbol}: {e}") from e

    @retry_with_backoff(max_retries=3, initial_delay=1.0, backoff_factor=2.0)
    def get_latest_price(self, symbol: str, asset_class: AssetClass) -> float:
        """
        Fetch the absolute latest trade price (real-time).

        Args:
            symbol: Ticker symbol
            asset_class: Asset class

        Returns:
            float: Latest trade price

        Raises:
            MarketDataError: If data fetching fails or the asset class is unsupported.
        """
        try:
            if asset_class == AssetClass.CRYPTO:
                req = CryptoLatestTradeRequest(symbol_or_symbols=symbol)
                trade = self.crypto_client.get_crypto_latest_trade(req)
                if not trade or symbol not in trade:
                    raise MarketDataError(
                        f"Latest crypto trade data for {symbol} "
                        "not found in API response"
                    )
                return float(trade[symbol].price)

            elif asset_class == AssetClass.EQUITY:
                req = StockLatestTradeRequest(symbol_or_symbols=symbol)
                trade = self.stock_client.get_stock_latest_trade(req)
                if not trade or symbol not in trade:
                    raise MarketDataError(
                        f"Latest equity trade data for {symbol} "
                        "not found in API response"
                    )
                return float(trade[symbol].price)

            else:
                raise MarketDataError(f"Unsupported asset class: {asset_class}")

        except MarketDataError:
            raise
        except Exception as e:
            raise MarketDataError(
                f"Failed to fetch latest price for {symbol}: {e}"
            ) from e
