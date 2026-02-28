from unittest.mock import MagicMock

import pytest

# Local imports
from alpaca.trading.enums import AssetClass as AlpacaAssetClass
from alpaca.trading.enums import OrderSide
from alpaca.trading.models import Order, TradeAccount
from crypto_signals.config import Settings
from crypto_signals.domain.schemas import AssetClass
from crypto_signals.engine.risk import RiskEngine
from crypto_signals.market.data_provider import MarketDataProvider
from crypto_signals.repository.firestore import PositionRepository
from tests.factories import PositionFactory, SignalFactory

# Ensure AssetClass is available in module scope for test methods
CRYPTO = AssetClass.CRYPTO
EQUITY = AssetClass.EQUITY


class TestRiskEngine:
    @pytest.fixture
    def mock_settings(self):
        settings = MagicMock(spec=Settings)
        # Default Safe Settings
        settings.MAX_CRYPTO_POSITIONS = 5
        settings.MAX_EQUITY_POSITIONS = 5
        settings.MAX_DAILY_DRAWDOWN_PCT = 0.05  # 5%
        settings.MIN_ASSET_BP_USD = 100.0
        return settings

    @pytest.fixture
    def mock_repo(self):
        return MagicMock(spec=PositionRepository)

    @pytest.fixture
    def mock_market_provider(self):
        return MagicMock(spec=MarketDataProvider)

    @pytest.fixture
    def mock_client(self):
        client = MagicMock()
        # default healthy account
        account = MagicMock(spec=TradeAccount)
        account.buying_power = "20000.00"  # Equity Reg-T
        account.regt_buying_power = "20000.00"  # Explicit Reg-T
        account.non_marginable_buying_power = "5000.00"  # Crypto Cash
        account.equity = "10000.00"
        account.last_equity = "10000.00"  # No drawdown
        client.get_account.return_value = account
        return client

    @pytest.fixture
    def risk_engine(self, mock_client, mock_repo, mock_settings, mock_market_provider):
        # Patch the engine's settings property or injected dependency
        # Patch get_settings() dependency for RiskEngine
        with pytest.MonkeyPatch.context() as m:
            # Patch at module level where it's imported
            m.setattr("crypto_signals.engine.risk.get_settings", lambda: mock_settings)
            engine = RiskEngine(
                trading_client=mock_client,
                repository=mock_repo,
                market_provider=mock_market_provider,
            )
            yield engine

    @pytest.mark.parametrize(
        "asset_class, required_bp, expected_passed, expected_reason",
        [
            (CRYPTO, 1000.0, True, None),
            (CRYPTO, 6000.0, False, "Insufficient Buying Power"),
            (EQUITY, 10000.0, True, None),
        ],
    )
    def test_check_buying_power(
        self, risk_engine, asset_class, required_bp, expected_passed, expected_reason
    ):
        """Test buying power check for different asset classes and requirements."""
        # Act
        result = risk_engine.check_buying_power(asset_class, required_bp)

        # Assert
        assert (
            result.passed == expected_passed
        ), f"Expected {expected_passed} for {asset_class} with {required_bp} BP, but got {result.passed}"
        if expected_reason:
            assert (
                expected_reason in result.reason
            ), f"Expected reason '{expected_reason}' in '{result.reason}'"

    def test_check_sector_cap_crypto_fail(self, risk_engine, mock_client):
        """Test that sector limit is enforced for crypto assets."""
        # Arrange: 4 filled positions + 1 open buy order = 5 (MAX=5)
        mock_pos = MagicMock()
        mock_pos.asset_class = AlpacaAssetClass.CRYPTO
        mock_client.get_all_positions.return_value = [mock_pos] * 4

        # Mock Open Orders
        mock_order = MagicMock(spec=Order)
        mock_order.asset_class = AlpacaAssetClass.CRYPTO
        mock_order.side = OrderSide.BUY
        mock_client.get_orders.return_value = [mock_order]

        # Act
        result = risk_engine.check_sector_limit(CRYPTO)

        # Assert
        assert result.passed is False, "Expected sector limit check to fail"
        assert (
            "Max CRYPTO positions reached" in result.reason
        ), f"Expected 'Max CRYPTO positions reached' in reason, but got {result.reason}"
        mock_client.get_all_positions.assert_called_once()
        mock_client.get_orders.assert_called_once()

    def test_check_sector_cap_crypto_pass(self, risk_engine, mock_client):
        """Test that sector limit check passes when under the limit."""
        # Arrange: 4 filled positions + 0 open orders = 4 (MAX=5)
        mock_pos = MagicMock()
        mock_pos.asset_class = AlpacaAssetClass.CRYPTO
        mock_client.get_all_positions.return_value = [mock_pos] * 4

        # No open orders
        mock_client.get_orders.return_value = []

        # Act
        result = risk_engine.check_sector_limit(CRYPTO)

        # Assert
        assert result.passed is True, "Expected sector limit check to pass"

    def test_daily_drawdown_fail(self, risk_engine, mock_client):
        """Test that daily drawdown limit is enforced."""
        # Arrange: Equity 9000, Last 10000 -> 10% Drop. Max is 5%
        mock_client.get_account.return_value.equity = "9000.00"
        mock_client.get_account.return_value.last_equity = "10000.00"

        # Act
        result = risk_engine.check_daily_drawdown()

        # Assert
        assert result.passed is False, "Expected drawdown check to fail"
        assert (
            "Daily Drawdown Limit Hit" in result.reason
        ), f"Expected 'Daily Drawdown Limit Hit' in reason, but got {result.reason}"

    def test_check_duplicate_symbol_fail(self, risk_engine, mock_repo):
        """Test that duplicate positions for the same symbol are prevented."""
        # Arrange: Position exists for BTC/USD
        pos = PositionFactory.build(symbol="BTC/USD", position_id="pos_1")
        mock_repo.get_open_positions.return_value = [pos]

        # Signal for SAME symbol
        signal = SignalFactory.build(symbol="BTC/USD")

        # Act
        result = risk_engine.check_duplicate_symbol(signal)

        # Assert
        assert result.passed is False, "Expected duplicate symbol check to fail"
        assert (
            "Duplicate Position" in result.reason
        ), f"Expected 'Duplicate Position' in reason, but got {result.reason}"
