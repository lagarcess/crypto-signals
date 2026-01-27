from unittest.mock import MagicMock, patch

import pytest
from crypto_signals.domain.schemas import SignalStatus
from crypto_signals.engine.signal_generator import SignalGenerator
from crypto_signals.main import main
from crypto_signals.repository.firestore import SignalRepository
from tests.factories import SignalFactory


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

    # Create mock position repository
    mock_position_repo = MagicMock()
    mock_position_repo.get_open_positions.return_value = []

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
        patch("crypto_signals.main.PositionRepository", return_value=mock_position_repo),
        patch("crypto_signals.main.PositionRepository", return_value=mock_position_repo),
        patch("crypto_signals.main.RejectedSignalRepository"),
        patch("crypto_signals.main.TradeArchivalPipeline") as mock_trade_archival,
        patch("crypto_signals.main.FeePatchPipeline") as mock_fee_patch,
        patch("crypto_signals.main.PricePatchPipeline") as mock_price_patch,
        patch("crypto_signals.main.ExecutionEngine"),
        patch("crypto_signals.main.StateReconciler") as mock_reconciler_cls,
        patch("crypto_signals.main.init_secrets", return_value=True),
        patch("crypto_signals.main.load_config_from_firestore", return_value=None),
        patch("crypto_signals.main.get_settings") as mock_settings,
        patch("crypto_signals.main.get_stock_data_client"),
        patch("crypto_signals.main.get_crypto_data_client"),
        patch("crypto_signals.main.get_trading_client"),
        patch("crypto_signals.main.JobLockRepository") as mock_job_lock,
    ):
        # Configure JobLock to always succeed
        mock_job_lock.return_value.acquire_lock.return_value = True

        # Configure Pipeline mocks to return integers for run()
        mock_trade_archival.return_value.run.return_value = 0
        mock_fee_patch.return_value.run.return_value = 0
        mock_price_patch.return_value.run.return_value = 0

        # Configure StateReconciler mock to return a safe report
        mock_reconciler_instance = mock_reconciler_cls.return_value
        mock_reconciler_instance.reconcile.return_value = MagicMock(
            critical_issues=[], zombies=[], orphans=[], reconciled_count=0
        )

        # Mock settings to have 1 crypto symbol
        mock_settings.return_value.CRYPTO_SYMBOLS = ["BTC/USD"]
        mock_settings.return_value.EQUITY_SYMBOLS = []
        mock_settings.return_value.RATE_LIMIT_DELAY = 0.0
        # Disable execution and GCP logging to simplify the test
        mock_settings.return_value.ENABLE_EXECUTION = False
        mock_settings.return_value.ENABLE_GCP_LOGGING = False

        # Mock Repo to return one active signal
        active_sig = SignalFactory.build(
            status=SignalStatus.INVALIDATED,
            exit_reason=None,
        )
        mock_repo.get_active_signals.return_value = [active_sig]

        # Mock Generator to return this signal as invalidated
        # check_exits returns list of invalidated signals
        mock_generator.check_exits.return_value = [active_sig]

        # Mock Generator to NOT return new signals
        # (to simplify test of invalidation)
        mock_generator.generate_signals.return_value = None

        # Run Main (Override sys.exit or ensure it terminates?)
        # main(smoke_test=False) runs until portfolio exhausted.
        # It loops active portfolio items once.
        main(smoke_test=False)

        # Verification
        # 1. repo.get_active_signals should be called with "BTC/USD"
        mock_repo.get_active_signals.assert_called_with("BTC/USD")

        # 2. generator.check_exits should be called
        mock_generator.check_exits.assert_called()

        # 3. repo.update_signal_atomic should be called with active_sig details
        # Note: exit_reason is only included in updates if it is truthy.
        mock_repo.update_signal_atomic.assert_called_with(
            active_sig.signal_id, {"status": active_sig.status.value}
        )
