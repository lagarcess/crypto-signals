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
from pydantic import Field, SecretStr, field_validator, model_validator
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

    # Discord Webhooks (Multi-destination routing)
    TEST_DISCORD_WEBHOOK: SecretStr = Field(
        ...,
        description="Discord Webhook URL for test/development messages (always required)",
    )
    LIVE_CRYPTO_DISCORD_WEBHOOK_URL: SecretStr | None = Field(
        default=None,
        description="Discord Webhook URL for live CRYPTO signals (required when TEST_MODE=False)",
    )
    LIVE_STOCK_DISCORD_WEBHOOK_URL: SecretStr | None = Field(
        default=None,
        description="Discord Webhook URL for live EQUITY signals (required when TEST_MODE=False)",
    )

    # Discord Bot Configuration (for Thread Recovery / Reading)
    DISCORD_BOT_TOKEN: SecretStr | None = Field(
        default=None,
        description="Discord Bot Token for reading threads (optional, enabling recovery)",
    )
    DISCORD_CHANNEL_ID_CRYPTO: str | None = Field(
        default=None,
        description="Channel ID for Crypto signals (required for recovery)",
    )
    DISCORD_CHANNEL_ID_STOCK: str | None = Field(
        default=None,
        description="Channel ID for Stock signals (required for recovery)",
    )
    DISCORD_SHADOW_WEBHOOK_URL: SecretStr | None = Field(
        default=None,
        description="Discord Webhook URL for shadow (rejected) signals",
    )
    DISCORD_DEPLOYS: SecretStr | None = Field(
        default=None,
        description="Discord Webhook URL for CI/CD deployment notifications (used in GitHub Actions)",
    )

    # Environment Mode (defaults to True for safety - all traffic goes to test webhook)
    TEST_MODE: bool = Field(
        default=True,
        description="If True, all traffic routes to TEST_DISCORD_WEBHOOK",
    )

    ALPACA_PAPER_TRADING: bool = Field(
        default=True,
        description="Use Alpaca paper trading environment",
    )

    # Google Cloud Logging (for production environments)
    ENABLE_GCP_LOGGING: bool = Field(
        default=False,
        description="Enable Google Cloud Logging sink (for Cloud Run/GKE)",
    )

    # Environment Mode (PROD or DEV)
    ENVIRONMENT: str = Field(
        default="DEV",
        description="Execution Environment (PROD or DEV). Controls DB routing and TTL.",
        pattern="^(PROD|DEV)$",
    )

    # TTL Configuration (Days)
    TTL_DAYS_PROD: int = Field(
        default=30, description="TTL for Production signals (days)."
    )
    TTL_DAYS_DEV: int = Field(default=7, description="TTL for Dev signals (days).")

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

    # Execution Configuration
    RISK_PER_TRADE: float = Field(
        default=100.0,
        description=(
            "Fixed dollar amount to risk per trade. Position size is calculated as "
            "RISK_PER_TRADE / (entry_price - stop_loss), ensuring you lose exactly "
            "this amount if the stop is hit."
        ),
        ge=10.0,
        le=10000.0,
    )

    ENABLE_EXECUTION: bool = Field(
        default=False,
        description="Enable order execution (requires ALPACA_PAPER_TRADING=True)",
    )

    ENABLE_EQUITIES: bool = Field(
        default=False,
        description=(
            "Enable equity (stock) trading. Requires Alpaca paid plan with SIP data "
            "access. Set to True only if you have SIP data subscription."
        ),
    )

    CLEANUP_ON_FAILURE: bool = Field(
        default=True,
        description="Auto-delete documents from Firestore if they fail Pydantic validation",
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
        mode="before",
    )
    @classmethod
    def validate_not_empty(cls, v: str, info) -> str:
        """Ensure required fields are not empty strings."""
        if v is None or (isinstance(v, str) and v.strip() == ""):
            raise ValueError(f"{info.field_name} cannot be empty")
        return v.strip() if isinstance(v, str) else v

    @model_validator(mode="after")
    def validate_live_webhooks(self) -> "Settings":
        """Ensure live webhooks are provided when TEST_MODE is False."""
        if not self.TEST_MODE:
            if not self.LIVE_CRYPTO_DISCORD_WEBHOOK_URL:
                raise ValueError(
                    "LIVE_CRYPTO_DISCORD_WEBHOOK_URL is required when TEST_MODE=False"
                )
            if not self.LIVE_STOCK_DISCORD_WEBHOOK_URL:
                raise ValueError(
                    "LIVE_STOCK_DISCORD_WEBHOOK_URL is required when TEST_MODE=False"
                )
        return self

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

    # Equities disabled by configuration (Basic Alpaca Plans can't access SIP data)
    # Users with paid plans can set ENABLE_EQUITIES=true to enable stock trading
    if not settings.ENABLE_EQUITIES:
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
    from google.cloud import firestore
    from google.cloud.firestore import FieldFilter
    from loguru import logger

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
