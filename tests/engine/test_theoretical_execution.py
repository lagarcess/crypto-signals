from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from crypto_signals.domain.schemas import (
    AssetClass,
    OrderSide,
    TradeType,
)
from crypto_signals.engine.execution import ExecutionEngine
from tests.factories import SignalFactory


@pytest.fixture
def mock_settings():
    with patch("crypto_signals.engine.execution.get_settings") as mock_get:
        settings = MagicMock()
        settings.ENVIRONMENT = "DEV"
        settings.ENABLE_EXECUTION = False
        settings.is_paper_trading = True
        settings.THEORETICAL_SLIPPAGE_PCT = 0.01  # 1%
        settings.TTL_DAYS_POSITION = 90
        settings.RISK_PER_TRADE = 100.0
        settings.MIN_ORDER_NOTIONAL_USD = 15.0
        mock_get.return_value = settings
        yield settings


@pytest.fixture
def mock_trading_client():
    return MagicMock()


@pytest.fixture
def execution_engine(mock_trading_client):
    with patch("crypto_signals.engine.execution.RiskEngine") as MockRiskEngine:
        # Default behavior: Risk Checks PASS
        from crypto_signals.engine.risk import RiskCheckResult

        MockRiskEngine.return_value.validate_signal.return_value = RiskCheckResult(
            passed=True
        )

        mock_repo = MagicMock()
        yield ExecutionEngine(trading_client=mock_trading_client, repository=mock_repo)


def test_theoretical_execution_long(execution_engine, mock_settings, mock_trading_client):
    """Verify that a LONG signal creates a THEORETICAL position with positive slippage."""
    # Arrange
    mock_settings.ENVIRONMENT = "DEV"
    mock_settings.ENABLE_EXECUTION = False  # Should trigger theoretical path

    signal = SignalFactory.build(
        signal_id="test_sig_001",
        ds=date.today(),
        strategy_id="strat_1",
        symbol="BTC/USD",
        asset_class=AssetClass.CRYPTO,
        entry_price=100.0,
        suggested_stop=95.0,  # Risk = 5.0
        pattern_name="TEST_PATTERN",
        take_profit_1=110.0,
        side=OrderSide.BUY,
    )

    # Act
    position = execution_engine.execute_signal(signal)

    # Assert
    assert position is not None, "Execution failed to return a position object"
    assert (
        position.trade_type == TradeType.THEORETICAL.value
    ), f"Expected trade type THEORETICAL, but got {position.trade_type}"
    assert position.status == "OPEN", f"Expected position status OPEN, but got {position.status}"

    # Check synthetic slippage (1% of 100 = 1.0)
    # Long: Fill Price = Entry + Slippage = 101.0
    assert (
        position.entry_fill_price == 101.0
    ), f"Expected fill price 101.0, but got {position.entry_fill_price}"
    assert (
        position.entry_slippage_pct == 1.0
    ), f"Expected slippage 1.0%, but got {position.entry_slippage_pct}%"

    # Check that NO broker order was submitted
    mock_trading_client.submit_order.assert_not_called()


def test_theoretical_execution_short(
    execution_engine, mock_settings, mock_trading_client
):
    """Verify that a SHORT signal creates a THEORETICAL position with negative slippage."""
    # Arrange
    mock_settings.ENVIRONMENT = "DEV"
    mock_settings.ENABLE_EXECUTION = False

    signal = SignalFactory.build(
        signal_id="test_sig_002",
        ds=date.today(),
        strategy_id="strat_1",
        symbol="ETH/USD",
        asset_class=AssetClass.CRYPTO,
        entry_price=100.0,
        suggested_stop=105.0,
        pattern_name="TEST_PATTERN",
        take_profit_1=90.0,
        side=OrderSide.SELL,
    )

    # Act
    position = execution_engine.execute_signal(signal)

    # Assert
    assert position is not None, "Execution failed to return a position object"
    assert (
        position.trade_type == TradeType.THEORETICAL.value
    ), f"Expected trade type THEORETICAL, but got {position.trade_type}"

    # Check synthetic slippage (1% of 100 = 1.0)
    # Short: Fill Price = Entry * (1 - Slippage) = 99.0
    assert (
        position.entry_fill_price == 99.0
    ), f"Expected fill price 99.0, but got {position.entry_fill_price}"
    assert (
        position.entry_slippage_pct == -1.0
    ), f"Expected slippage -1.0%, but got {position.entry_slippage_pct}%"

    # Check that NO broker order was submitted
    mock_trading_client.submit_order.assert_not_called()


def test_execution_gating_prod_live(execution_engine, mock_settings, mock_trading_client):
    """Verify that PROD + ENABLE_EXECUTION triggers LIVE execution (not theoretical)."""
    # Arrange
    mock_settings.ENVIRONMENT = "PROD"
    mock_settings.ENABLE_EXECUTION = True

    # Mock submit_order return
    mock_order = MagicMock()
    mock_order.id = "mock_order_id"
    mock_order.status = "new"
    mock_trading_client.submit_order.return_value = mock_order

    signal = SignalFactory.build(
        signal_id="test_sig_003",
        ds=date.today(),
        strategy_id="strat_1",
        symbol="BTC/USD",
        asset_class=AssetClass.CRYPTO,
        entry_price=100.0,
        suggested_stop=95.0,
        pattern_name="TEST_PATTERN",
        take_profit_1=110.0,
        side=OrderSide.BUY,
    )

    # Act
    position = execution_engine.execute_signal(signal)

    # Assert
    assert position is not None, "Execution failed to return a position object"
    assert (
        position.trade_type != TradeType.THEORETICAL.value
    ), f"Expected live trade type, but got {position.trade_type}"

    # Check that broker order WAS submitted
    mock_trading_client.submit_order.assert_called_once()
