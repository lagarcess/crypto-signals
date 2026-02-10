from unittest.mock import MagicMock, patch

import pytest
from crypto_signals.config import Settings
from crypto_signals.notifications.discord import DiscordClient
from pydantic import SecretStr

@pytest.fixture
def mock_settings():
    settings = MagicMock(spec=Settings)
    settings.TEST_MODE = True
    settings.TEST_DISCORD_WEBHOOK = SecretStr("https://discord.com/api/webhooks/test")
    settings.DISCORD_USE_FORUMS = False
    return settings

@pytest.fixture
def discord_client(mock_settings):
    return DiscordClient(settings=mock_settings)

@patch("crypto_signals.notifications.discord.requests.post")
def test_send_risk_summary(mock_post, discord_client):
    # Setup
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_post.return_value = mock_response

    risk_summary = {
        "total_blocked": 5,
        "capital_protected": 25000.0,
        "by_gate": {
            "drawdown": 1,
            "sector_cap": 2,
            "buying_power": 2
        },
        "blocked_symbols": ["BTC/USD", "ETH/USD"]
    }

    # Act
    result = discord_client.send_risk_summary(risk_summary)

    # Assert
    assert result is True
    mock_post.assert_called_once()

    _, kwargs = mock_post.call_args
    content = kwargs["json"]["content"]

    assert "🛡️ **RISK GATES SUMMARY** 🛡️" in content
    assert "Total Blocked:** 5" in content
    assert "Capital Protected:** $25,000.00" in content
    assert "• drawdown: 1" in content
    assert "• sector_cap: 2" in content
    assert "• buying_power: 2" in content
