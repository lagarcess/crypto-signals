from contextlib import ExitStack
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

    with ExitStack() as stack:
        stack.enter_context(
            patch("crypto_signals.main.SignalRepository", return_value=mock_repo)
        )
        stack.enter_context(
            patch("crypto_signals.main.SignalGenerator", return_value=mock_generator)
        )
        stack.enter_context(
            patch(
                "crypto_signals.main.MarketDataProvider",
                return_value=mock_market_provider,
            )
        )
        stack.enter_context(
            patch("crypto_signals.main.DiscordClient", return_value=mock_discord)
        )
        stack.enter_context(
            patch(
                "crypto_signals.main.AssetValidationService",
                return_value=mock_asset_validator,
            )
        )
        stack.enter_context(
            patch(
                "crypto_signals.main.PositionRepository", return_value=mock_position_repo
            )
        )
        stack.enter_context(patch("crypto_signals.main.RejectedSignalRepository"))
        mock_trade_archival = stack.enter_context(
            patch("crypto_signals.main.TradeArchivalPipeline")
        )
        mock_fee_patch = stack.enter_context(
            patch("crypto_signals.main.FeePatchPipeline")
        )
        mock_price_patch = stack.enter_context(
            patch("crypto_signals.main.PricePatchPipeline")
        )
        stack.enter_context(patch("crypto_signals.main.ExecutionEngine"))
        mock_reconciler_cls = stack.enter_context(
            patch("crypto_signals.main.StateReconciler")
        )
        stack.enter_context(patch("crypto_signals.main.init_secrets", return_value=True))
        stack.enter_context(
            patch("crypto_signals.main.load_config_from_firestore", return_value=None)
        )
        mock_settings = stack.enter_context(patch("crypto_signals.main.get_settings"))
        stack.enter_context(patch("crypto_signals.main.get_stock_data_client"))
        stack.enter_context(patch("crypto_signals.main.get_crypto_data_client"))
        stack.enter_context(patch("crypto_signals.main.get_trading_client"))
        mock_job_lock = stack.enter_context(
            patch("crypto_signals.main.JobLockRepository")
        )
        mock_job_metadata_repo = stack.enter_context(
            patch("crypto_signals.main.JobMetadataRepository")
        )
        mock_subprocess = stack.enter_context(patch("subprocess.check_output"))

        mock_job_metadata_repo.return_value.get_last_run_date.return_value = None
        mock_job_lock.return_value.acquire_lock.return_value = True
        mock_trade_archival.return_value.run.return_value = 0
        mock_fee_patch.return_value.run.return_value = 0
        mock_price_patch.return_value.run.return_value = 0
        mock_reconciler_instance = mock_reconciler_cls.return_value
        mock_reconciler_instance.reconcile.return_value = MagicMock(
            critical_issues=[], zombies=[], orphans=[], reconciled_count=0
        )
        mock_settings.return_value.CRYPTO_SYMBOLS = ["BTC/USD"]
        mock_settings.return_value.EQUITY_SYMBOLS = []
        mock_settings.return_value.RATE_LIMIT_DELAY = 0.0
        mock_settings.return_value.ENABLE_EXECUTION = False
        mock_settings.return_value.ENABLE_GCP_LOGGING = False
        mock_settings.return_value.ENVIRONMENT = "DEV"
        mock_settings.return_value.MAX_CRYPTO_POSITIONS = 5
        mock_settings.return_value.MAX_EQUITY_POSITIONS = 5
        mock_settings.return_value.RISK_PER_TRADE = 100.0
        mock_subprocess.return_value = b"test-hash"

        active_sig = SignalFactory.build(
            status=SignalStatus.INVALIDATED,
            exit_reason=None,
        )
        active_sig._trail_updated = False
        mock_repo.get_active_signals.return_value = [active_sig]
        mock_generator.check_exits.return_value = [active_sig]
        mock_generator.generate_signals.return_value = None

        main(smoke_test=False)

        mock_repo.get_active_signals.assert_called_with("BTC/USD")
        mock_generator.check_exits.assert_called()
        mock_repo.update_signal_atomic.assert_called_with(
            active_sig.signal_id, {"status": active_sig.status.value}
        )
