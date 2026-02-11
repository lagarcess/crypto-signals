from unittest.mock import MagicMock

import pytest
from alpaca.trading.models import TradeAccount
from crypto_signals.config import Settings
from crypto_signals.domain.schemas import AssetClass, Signal
from crypto_signals.engine.risk import RiskEngine
from crypto_signals.observability import MetricsCollector
from crypto_signals.repository.firestore import PositionRepository


@pytest.fixture
def mock_settings():
    settings = MagicMock(spec=Settings)
    # Default Safe Settings
    settings.MAX_CRYPTO_POSITIONS = 5
    settings.MAX_EQUITY_POSITIONS = 5
    settings.MAX_DAILY_DRAWDOWN_PCT = 0.05  # 5%
    settings.MIN_ASSET_BP_USD = 100.0
    settings.RISK_PER_TRADE = 100.0
    return settings


@pytest.fixture
def mock_metrics():
    return MagicMock(spec=MetricsCollector)


@pytest.fixture
def mock_repo():
    repo = MagicMock(spec=PositionRepository)
    # Default: 0 open positions, so sector cap passes
    repo.count_open_positions_by_class.return_value = 0
    return repo


@pytest.fixture
def mock_client():
    client = MagicMock()
    # default healthy account
    account = MagicMock(spec=TradeAccount)
    account.buying_power = "20000.00"
    account.regt_buying_power = "20000.00"
    account.non_marginable_buying_power = "5000.00"
    account.equity = "10000.00"
    account.last_equity = "10000.00"  # No drawdown
    client.get_account.return_value = account
    return client


@pytest.fixture
def risk_engine(mock_client, mock_repo, mock_settings, mock_metrics):
    with pytest.MonkeyPatch.context() as m:
        m.setattr("crypto_signals.engine.risk.get_settings", lambda: mock_settings)
        m.setattr(
            "crypto_signals.engine.risk.get_metrics_collector", lambda: mock_metrics
        )

        engine = RiskEngine(
            trading_client=mock_client,
            repository=mock_repo,
        )
        return engine


def test_validate_signal_drawdown_fail_records_metrics(
    risk_engine, mock_client, mock_metrics
):
    # Simulate Drawdown Failure
    mock_client.get_account.return_value.equity = "9000.00"
    mock_client.get_account.return_value.last_equity = "10000.00"  # 10% drawdown

    signal = MagicMock(spec=Signal)
    signal.symbol = "BTC/USD"
    signal.entry_price = 50000.0
    signal.suggested_stop = 49000.0  # 1000 diff

    result = risk_engine.validate_signal(signal)

    assert result.passed is False
    assert result.gate == "drawdown"

    # Verify metrics called
    mock_metrics.record_risk_block.assert_called_once_with("drawdown", "BTC/USD", 5000.0)


def test_validate_signal_buying_power_fail_records_metrics(
    risk_engine, mock_client, mock_metrics
):
    # Simulate Buying Power Failure
    mock_client.get_account.return_value.non_marginable_buying_power = (
        "50.00"  # Less than 100
    )

    signal = MagicMock(spec=Signal)
    signal.symbol = "ETH/USD"
    signal.asset_class = AssetClass.CRYPTO
    signal.entry_price = 3000.0
    signal.suggested_stop = 2900.0  # 100 diff

    result = risk_engine.validate_signal(signal)

    assert result.passed is False
    assert result.gate == "buying_power"

    # Verify metrics called
    mock_metrics.record_risk_block.assert_called_once_with(
        "buying_power", "ETH/USD", 3000.0
    )


def test_validate_signal_sector_cap_fail_records_metrics(
    risk_engine, mock_repo, mock_metrics
):
    # Simulate Sector Cap Failure
    mock_repo.count_open_positions_by_class.return_value = 5  # Max

    signal = MagicMock(spec=Signal)
    signal.symbol = "BTC/USD"
    signal.asset_class = AssetClass.CRYPTO
    signal.entry_price = 100.0
    signal.suggested_stop = 90.0  # 10 diff

    result = risk_engine.validate_signal(signal)

    assert result.passed is False
    assert result.gate == "sector_cap"

    mock_metrics.record_risk_block.assert_called_once_with(
        "sector_cap", "BTC/USD", 1000.0
    )
