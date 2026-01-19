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
