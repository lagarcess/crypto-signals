"""
Unified Configuration Module for Crypto Sentinel.

This module provides a single source of truth for all configuration settings using
pydantic-settings for validation and environment variable loading.
"""

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, List

from alpaca.data.historical import CryptoHistoricalDataClient, StockHistoricalDataClient
from alpaca.trading.client import TradingClient
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.

    All required credentials are strictly validated on initialization. Missing or empty
    values will raise a ValidationError.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # Alpaca API Credentials (Required)
    ALPACA_API_KEY: str = Field(
        ...,
        description="Alpaca API Key for trading and market data",
        min_length=1,
    )
    ALPACA_SECRET_KEY: str = Field(
        ...,
        description="Alpaca Secret Key for authentication",
        min_length=1,
    )

    # Google Cloud Configuration (Required)
    GOOGLE_CLOUD_PROJECT: str = Field(
        ...,
        description="Google Cloud Project ID",
        min_length=1,
    )

    # Google Cloud Credentials Path (Optional - for service account auth)
    GOOGLE_APPLICATION_CREDENTIALS: str | None = Field(
        default=None,
        description="Path to Google Cloud service account JSON file",
    )

    # Discord Webhook (Required)
    DISCORD_WEBHOOK_URL: str = Field(
        ...,
        description="Discord Webhook URL for notifications",
        min_length=1,
    )

    # Optional: Alpaca Paper Trading (defaults to True for safety)
    ALPACA_PAPER_TRADING: bool = Field(
        default=True,
        description="Use Alpaca paper trading environment",
    )

    # Optional: Mock Discord Notifications (defaults to False, strict validation)
    MOCK_DISCORD: bool = Field(
        default=False,
        description="If True, log notifications instead of sending to Discord",
    )

    # Portfolio Configuration (Optional - defaults to hardcoded lists)
    CRYPTO_SYMBOLS: List[str] | str = Field(
        default=[
            "BTC/USD",
            "ETH/USD",
            "XRP/USD",
        ],
        description="List of crypto pairs to analyze",
    )
    EQUITY_SYMBOLS: List[str] | str = Field(
        default=[],
        description="List of equity symbols to analyze",
    )

    # Rate Limiting Configuration (Optional)
    RATE_LIMIT_DELAY: float = Field(
        default=0.5,
        description=(
            "Delay in seconds between processing symbols "
            "(Alpaca limit: 200 req/min = 0.3s/req minimum)"
        ),
        ge=0.0,
        le=10.0,
    )

    @field_validator("CRYPTO_SYMBOLS", "EQUITY_SYMBOLS", mode="before")
    @classmethod
    def parse_list_from_str(cls, v: Any) -> Any:
        """Parse comma-separated string into list."""
        if isinstance(v, str):
            return [item.strip() for item in v.split(",") if item.strip()]
        return v

    @field_validator(
        "ALPACA_API_KEY",
        "ALPACA_SECRET_KEY",
        "GOOGLE_CLOUD_PROJECT",
        "DISCORD_WEBHOOK_URL",
        mode="before",
    )
    @classmethod
    def validate_not_empty(cls, v: str, info) -> str:
        """Ensure required fields are not empty strings."""
        if v is None or (isinstance(v, str) and v.strip() == ""):
            raise ValueError(f"{info.field_name} cannot be empty")
        return v.strip() if isinstance(v, str) else v

    @field_validator("DISCORD_WEBHOOK_URL", mode="after")
    @classmethod
    def validate_discord_url(cls, v: str) -> str:
        """Validate Discord webhook URL format."""
        valid_prefixes = (
            "https://discord.com/api/webhooks/",
            "https://discordapp.com/api/webhooks/",
            "https://canary.discord.com/api/webhooks/",
        )
        if not v.startswith(valid_prefixes):
            raise ValueError(
                "DISCORD_WEBHOOK_URL must be a valid Discord webhook URL "
                "(discord.com, discordapp.com, or canary.discord.com)"
            )
        return v

    @property
    def project_root(self) -> Path:
        """Return the project root directory."""
        return Path(__file__).parent.parent.parent

    @property
    def is_paper_trading(self) -> bool:
        """Check if running in paper trading mode."""
        return self.ALPACA_PAPER_TRADING


@lru_cache()
def get_settings() -> Settings:
    """
    Get cached application settings.

    Uses lru_cache to ensure settings are only loaded once.
    Also bridges Pydantic settings to os.environ for Google Cloud SDKs.

    Returns:
        Settings: Validated application settings

    Raises:
        pydantic.ValidationError: If required environment variables are missing
    """
    settings = Settings()

    # BRIDGE: Force the Pydantic setting into the OS Environment for Google SDKs
    # Google Cloud libraries rely on os.environ, not Pydantic settings
    if settings.GOOGLE_APPLICATION_CREDENTIALS:
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = (
            settings.GOOGLE_APPLICATION_CREDENTIALS
        )

    # RESTRICTION: Force disable equities for Basic Alpaca Plans
    # This overrides .env settings to prevent SIP data errors
    settings.EQUITY_SYMBOLS = []

    return settings


# Convenience function for quick access
settings = get_settings


def get_trading_client() -> TradingClient:
    """
    Get an authenticated Alpaca TradingClient.

    Returns:
        TradingClient: Authenticated client
    """
    settings = get_settings()
    return TradingClient(
        api_key=settings.ALPACA_API_KEY,
        secret_key=settings.ALPACA_SECRET_KEY,
        paper=settings.is_paper_trading,
    )


def get_stock_data_client() -> StockHistoricalDataClient:
    """
    Get an authenticated Alpaca StockHistoricalDataClient.

    Returns:
        StockHistoricalDataClient: Authenticated client
    """
    settings = get_settings()
    return StockHistoricalDataClient(
        api_key=settings.ALPACA_API_KEY,
        secret_key=settings.ALPACA_SECRET_KEY,
    )


def get_crypto_data_client() -> CryptoHistoricalDataClient:
    """
    Get an authenticated Alpaca CryptoHistoricalDataClient.

    Returns:
        CryptoHistoricalDataClient: Authenticated client
    """
    settings = get_settings()
    return CryptoHistoricalDataClient(
        api_key=settings.ALPACA_API_KEY,
        secret_key=settings.ALPACA_SECRET_KEY,
    )


if __name__ == "__main__":
    # Debug output when run directly
    cfg = get_settings()
    print(f"GCP Project: {cfg.GOOGLE_CLOUD_PROJECT}")


def load_config_from_firestore() -> dict[str, list[str]]:
    """
    Load active strategy configuration from Firestore.

    Queries the 'dim_strategies' collection for strategies marked active=True.
    Extracts assets and asset classes to build dynamic portfolio lists.

    Returns:
        dict: Configuration dict containing 'CRYPTO_SYMBOLS' and 'EQUITY_SYMBOLS' lists.
              Empty dict if no active strategies found or error occurs.
    """
    import logging

    from google.cloud import firestore
    from google.cloud.firestore import FieldFilter

    logger = logging.getLogger(__name__)

    try:
        settings = get_settings()
        # Ensure we have a project ID
        if not settings.GOOGLE_CLOUD_PROJECT:
            logger.warning("No Google Cloud Project ID set. Skipping Firestore config.")
            return {}

        db = firestore.Client(project=settings.GOOGLE_CLOUD_PROJECT)
        collection_ref = db.collection("dim_strategies")

        # Query for active strategies
        query = collection_ref.where(filter=FieldFilter("active", "==", True))

        crypto_symbols = set()
        equity_symbols = set()

        logger.info("Querying Firestore for active strategies...")

        docs = list(query.stream())
        if not docs:
            logger.info("No active strategies found in Firestore.")
            return {}

        for doc in docs:
            data = doc.to_dict()
            assets = data.get("assets", [])
            asset_class = data.get("asset_class")

            if not assets:
                continue

            # Standardize asset class string check
            if asset_class == "CRYPTO":
                crypto_symbols.update(assets)
            elif asset_class == "EQUITY":
                equity_symbols.update(assets)
            else:
                logger.warning(
                    f"Unknown asset class '{asset_class}' in strategy {doc.id}"
                )

        result = {
            "CRYPTO_SYMBOLS": list(crypto_symbols),
            "EQUITY_SYMBOLS": list(equity_symbols),
        }

        logger.info(
            f"Loaded config from Firestore: "
            f"{len(crypto_symbols)} Crypto, {len(equity_symbols)} Equity"
        )
        return result

    except Exception as e:
        logger.error(f"Failed to load configuration from Firestore: {e}")
        # Return empty to trigger fallback or empty state
        return {}
