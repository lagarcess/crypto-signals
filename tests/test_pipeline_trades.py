from unittest.mock import MagicMock, patch

import pytest
from crypto_signals.domain.schemas import Signal, SignalStatus
from crypto_signals.engine.signal_generator import SignalGenerator
from crypto_signals.main import main
from crypto_signals.repository.firestore import SignalRepository


@pytest.fixture
def mock_repo():
    return MagicMock(spec=SignalRepository)


@pytest.fixture
def mock_generator():
    return MagicMock(spec=SignalGenerator)


@pytest.fixture
def mock_market_provider():
    mp = MagicMock()
    # Ensure dataframe is not empty so main loop proceeds
    mp.get_daily_bars.return_value.empty = False
    return mp


@pytest.fixture
def mock_discord():
    return MagicMock()


def test_active_trade_validation_loop(
    mock_repo, mock_generator, mock_market_provider, mock_discord
):
    """
    Test that the main loop checks for invalidation of active signals.
    """
    # Create mock for asset validator that passes through symbols
    mock_asset_validator = MagicMock()
    mock_asset_validator.get_valid_portfolio.side_effect = lambda s, ac: list(s)

    # Setup
    with (
        patch("crypto_signals.main.SignalRepository", return_value=mock_repo),
        patch("crypto_signals.main.SignalGenerator", return_value=mock_generator),
        patch(
            "crypto_signals.main.MarketDataProvider", return_value=mock_market_provider
        ),
        patch("crypto_signals.main.DiscordClient", return_value=mock_discord),
        patch(
            "crypto_signals.main.AssetValidationService",
            return_value=mock_asset_validator,
        ),
        patch("crypto_signals.main.init_secrets", return_value=True),
        patch("crypto_signals.main.get_settings") as mock_settings,
        patch("crypto_signals.main.get_stock_data_client"),
        patch("crypto_signals.main.get_crypto_data_client"),
        patch("crypto_signals.main.get_trading_client"),
    ):
        # Mock settings to have 1 crypto symbol
        mock_settings.return_value.CRYPTO_SYMBOLS = ["BTC/USD"]
        mock_settings.return_value.EQUITY_SYMBOLS = []
        mock_settings.return_value.RATE_LIMIT_DELAY = 0.0

        # Mock Repo to return one active signal
        active_sig = MagicMock(spec=Signal)
        active_sig.signal_id = "sig_123"
        active_sig.status = SignalStatus.INVALIDATED
        mock_repo.get_active_signals.return_value = [active_sig]

        # Mock Generator to return this signal as invalidated
        # check_exits returns list of invalidated signals
        mock_generator.check_exits.return_value = [active_sig]

        # Mock Generator to NOT return new signals
        # (to simplify test of invalidation)
        mock_generator.generate_signals.return_value = None

        # Run Main (Override sys.exit or ensure it terminates?)
        # main() runs until portfolio exhausted.
        # It loops active portfolio items once.
        main()

        # Verification
        # 1. repo.get_active_signals should be called with "BTC/USD"
        mock_repo.get_active_signals.assert_called_with("BTC/USD")

        # 2. generator.check_exits should be called
        mock_generator.check_exits.assert_called()

        # 3. repo.update_signal should be called with active_sig
        mock_repo.update_signal.assert_called_with(active_sig)
