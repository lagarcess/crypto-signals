import os
from unittest.mock import MagicMock, patch

import pytest
from crypto_signals.config import Settings, get_settings, load_config_from_firestore
from pydantic import ValidationError


@pytest.fixture
def base_env():
    return {
        "ALPACA_API_KEY": "test_key",
        "ALPACA_SECRET_KEY": "test_secret",
        "GOOGLE_CLOUD_PROJECT": "test_project",
        "TEST_DISCORD_WEBHOOK": "https://discord.com/api/webhooks/test",
        "TEST_MODE": "True",
    }


def test_settings_ttl_days_position(base_env):
    """Verify TTL_DAYS_POSITION exists and defaults to 90."""
    with patch.dict(os.environ, base_env):
        settings = Settings()
        assert hasattr(settings, "TTL_DAYS_POSITION")
        assert settings.TTL_DAYS_POSITION == 90


def test_settings_cooldown_scope_defaults_to_symbol(base_env):
    """Verify COOLDOWN_SCOPE defaults to SYMBOL (conservative mode)."""
    with patch.dict(os.environ, base_env):
        settings = Settings()
        assert hasattr(settings, "COOLDOWN_SCOPE")
        assert settings.COOLDOWN_SCOPE == "SYMBOL"


def test_settings_cooldown_scope_can_be_set_to_pattern(base_env):
    """Verify COOLDOWN_SCOPE can be set to PATTERN (flexible mode)."""
    env = base_env.copy()
    env["COOLDOWN_SCOPE"] = "PATTERN"
    with patch.dict(os.environ, env):
        settings = Settings()
        assert settings.COOLDOWN_SCOPE == "PATTERN"


def test_validate_not_empty(base_env):
    """Test that required fields cannot be empty."""
    env = base_env.copy()
    env["ALPACA_API_KEY"] = " "
    with patch.dict(os.environ, env):
        with pytest.raises(ValidationError):
            Settings()


def test_parse_list_from_str(base_env):
    """Test comma-separated string parsing for symbols."""
    env = base_env.copy()
    env["CRYPTO_SYMBOLS"] = "BTC/USD, ETH/USD ,  XRP/USD"
    with patch.dict(os.environ, env):
        settings = Settings()
        assert settings.CRYPTO_SYMBOLS == ["BTC/USD", "ETH/USD", "XRP/USD"]


def test_validate_live_webhooks_failure(base_env):
    """Test that live mode requires live webhooks (direct instantiation)."""
    with pytest.raises(ValidationError) as excinfo:
        Settings(
            _env_file=None,
            ALPACA_API_KEY="key",
            ALPACA_SECRET_KEY="secret",
            GOOGLE_CLOUD_PROJECT="project",
            TEST_DISCORD_WEBHOOK="https://test",
            TEST_MODE=False,
        )

    assert "LIVE_CRYPTO_DISCORD_WEBHOOK_URL is required" in str(excinfo.value)


def test_get_settings_bridge(base_env):
    """Test that get_settings bridges credentials to os.environ."""
    env = base_env.copy()
    env["GOOGLE_APPLICATION_CREDENTIALS"] = "/path/to/creds.json"
    with patch.dict(os.environ, env):
        get_settings.cache_clear()
        settings = get_settings()
        assert os.environ["GOOGLE_APPLICATION_CREDENTIALS"] == "/path/to/creds.json"
        assert settings.GOOGLE_APPLICATION_CREDENTIALS == "/path/to/creds.json"


def test_load_config_from_firestore_success(base_env):
    """Test loading configuration from Firestore mocked."""
    mock_doc = MagicMock()
    mock_doc.id = "strat1"
    mock_doc.to_dict.return_value = {
        "active": True,
        "assets": ["BTC/USD", "ETH/USD"],
        "asset_class": "CRYPTO",
    }

    with (
        patch.dict(os.environ, base_env),
        patch("google.cloud.firestore.Client") as mock_client_cls,
    ):
        mock_db = mock_client_cls.return_value
        mock_db.collection.return_value.where.return_value.stream.return_value = [
            mock_doc
        ]

        config = load_config_from_firestore()
        assert "BTC/USD" in config["CRYPTO_SYMBOLS"]
        assert "ETH/USD" in config["CRYPTO_SYMBOLS"]


def test_load_config_from_firestore_error(base_env):
    """Test load_config_from_firestore graceful failure."""
    with (
        patch.dict(os.environ, base_env),
        patch("google.cloud.firestore.Client", side_effect=Exception("DB DOWN")),
    ):
        config = load_config_from_firestore()
        assert config == {}
