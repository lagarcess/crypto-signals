import os
from unittest.mock import patch

from crypto_signals.config import Settings


def test_settings_ttl_days_position():
    """Verify TTL_DAYS_POSITION exists and defaults to 90."""
    # Patch env vars to satisfy required fields
    with patch.dict(
        os.environ,
        {
            "ALPACA_API_KEY": "test_key",
            "ALPACA_SECRET_KEY": "test_secret",
            "GOOGLE_CLOUD_PROJECT": "test_project",
            "TEST_DISCORD_WEBHOOK": "https://discord.com/api/webhooks/test",
        },
    ):
        settings = Settings()
        assert hasattr(settings, "TTL_DAYS_POSITION")
        assert settings.TTL_DAYS_POSITION == 90


def test_settings_cooldown_scope_defaults_to_symbol():
    """Verify COOLDOWN_SCOPE defaults to SYMBOL (conservative mode)."""
    with patch.dict(
        os.environ,
        {
            "ALPACA_API_KEY": "test_key",
            "ALPACA_SECRET_KEY": "test_secret",
            "GOOGLE_CLOUD_PROJECT": "test_project",
            "TEST_DISCORD_WEBHOOK": "https://discord.com/api/webhooks/test",
        },
    ):
        settings = Settings()
        assert hasattr(settings, "COOLDOWN_SCOPE")
        assert settings.COOLDOWN_SCOPE == "SYMBOL"


def test_settings_cooldown_scope_can_be_set_to_pattern():
    """Verify COOLDOWN_SCOPE can be set to PATTERN (flexible mode)."""
    with patch.dict(
        os.environ,
        {
            "ALPACA_API_KEY": "test_key",
            "ALPACA_SECRET_KEY": "test_secret",
            "GOOGLE_CLOUD_PROJECT": "test_project",
            "TEST_DISCORD_WEBHOOK": "https://discord.com/api/webhooks/test",
            "COOLDOWN_SCOPE": "PATTERN",
        },
    ):
        settings = Settings()
        assert settings.COOLDOWN_SCOPE == "PATTERN"
