from datetime import datetime
from unittest.mock import MagicMock

import pandas as pd
import pytest
from alpaca.trading.client import TradingClient
from crypto_signals.domain.schemas import (
    AssetClass,
    Position,
    Signal,
    SignalStatus,
    TradeStatus,
)
from crypto_signals.engine.risk import RiskEngine
from crypto_signals.market.data_provider import MarketDataProvider
from crypto_signals.repository.firestore import PositionRepository
from tests.factories import PositionFactory, SignalFactory


class TestRiskCorrelation:
    @pytest.fixture
    def mock_market_provider(self):
        return MagicMock(spec=MarketDataProvider)

    @pytest.fixture
    def mock_repo(self):
        return MagicMock(spec=PositionRepository)

    @pytest.fixture
    def mock_client(self):
        return MagicMock(spec=TradingClient)

    @pytest.fixture
    def risk_engine(self, mock_client, mock_repo, mock_market_provider):
        # We need to mock get_settings as well
        with pytest.MonkeyPatch.context() as m:
            settings = MagicMock()
            settings.MAX_CRYPTO_POSITIONS = 5
            settings.MAX_EQUITY_POSITIONS = 5
            settings.MAX_DAILY_DRAWDOWN_PCT = 0.05
            settings.MIN_ASSET_BP_USD = 100.0
            m.setattr("crypto_signals.engine.risk.get_settings", lambda: settings)
            return RiskEngine(
                trading_client=mock_client,
                repository=mock_repo,
                market_provider=mock_market_provider,
            )

    def create_signal(self, symbol="BTC/USD"):
        """Utility to create a signal for testing correlation."""
        return SignalFactory.build(
            signal_id="sig_1",
            ds=datetime.now().date(),
            strategy_id="test_strat",
            symbol=symbol,
            asset_class=AssetClass.CRYPTO,
            pattern_name="TestPattern",
            pattern_classification="Bullish",
            pattern_duration_days=10,
            pattern_quality_score=90,
            confidence=0.9,
            status=SignalStatus.WAITING,
            entry_price=50000.0,
            take_profit_1=55000.0,
            suggested_stop=45000.0,
            timestamp=datetime.now(),
        )

    def create_position(self, symbol="ETH/USD"):
        """Utility to create a position for testing correlation."""
        return PositionFactory.build(
            position_id="pos_1",
            ds=datetime.now().date(),
            account_id="paper",
            signal_id="sig_old",
            symbol=symbol,
            asset_class=AssetClass.CRYPTO,
            status=TradeStatus.OPEN,
            entry_fill_price=3000.0,
            qty=1.0,
            side="buy",
            current_stop_loss=2500.0,
            alpaca_order_id="order_1",
        )

    def test_check_correlation_no_positions(self, risk_engine, mock_repo):
        """Verify correlation check passes when no other positions are open."""
        # Arrange
        mock_repo.get_open_positions.return_value = []
        signal = self.create_signal()

        # Act
        result = risk_engine.check_correlation(signal)

        # Assert
        assert result.passed is True, f"Expected correlation check to pass, but got fail: {result.reason}"

    def test_check_correlation_high(self, risk_engine, mock_repo, mock_market_provider):
        """Verify correlation check fails when candidate is highly correlated with existing positions."""
        # Arrange
        mock_repo.get_open_positions.return_value = [
            self.create_position(symbol="ETH/USD")
        ]
        signal = self.create_signal(symbol="BTC/USD")

        dates = pd.date_range(end=datetime.now(), periods=90)
        btc_prices = [100 + i for i in range(90)]
        eth_prices = [10 + i for i in range(90)]

        btc_df = pd.DataFrame({"close": btc_prices}, index=dates)
        eth_df = pd.DataFrame({"close": eth_prices}, index=dates)

        def get_bars_side_effect(symbol, asset_class, lookback_days=90):
            if isinstance(symbol, list):
                dfs = []
                keys = []
                for s in symbol:
                    if s == "BTC/USD":
                        dfs.append(btc_df)
                        keys.append(s)
                    elif s == "ETH/USD":
                        dfs.append(eth_df)
                        keys.append(s)
                if not dfs:
                    return pd.DataFrame()
                return pd.concat(dfs, keys=keys, names=["symbol", "timestamp"])
            return btc_df if symbol == "BTC/USD" else eth_df

        mock_market_provider.get_daily_bars.side_effect = get_bars_side_effect

        # Act
        result = risk_engine.check_correlation(signal)

        # Assert
        assert result.passed is False, "Expected correlation check to fail for perfectly correlated assets"
        assert (
            "highly correlated" in result.reason.lower()
            or "correlation" in result.reason.lower()
        ), f"Expected 'highly correlated' in reason, but got: {result.reason}"

    def test_check_correlation_low(self, risk_engine, mock_repo, mock_market_provider):
        """Verify correlation check passes when assets are uncorrelated or inversely correlated."""
        # Arrange
        mock_repo.get_open_positions.return_value = [
            self.create_position(symbol="ETH/USD")
        ]
        signal = self.create_signal(symbol="BTC/USD")

        dates = pd.date_range(end=datetime.now(), periods=90)
        btc_prices = [100 + i for i in range(90)]
        eth_prices = [100 - i for i in range(90)]  # Inverse correlation

        btc_df = pd.DataFrame({"close": btc_prices}, index=dates)
        eth_df = pd.DataFrame({"close": eth_prices}, index=dates)

        def get_bars_side_effect(symbol, asset_class, lookback_days=90):
            if isinstance(symbol, list):
                dfs = []
                keys = []
                for s in symbol:
                    if s == "BTC/USD":
                        dfs.append(btc_df)
                        keys.append(s)
                    elif s == "ETH/USD":
                        dfs.append(eth_df)
                        keys.append(s)
                if not dfs:
                    return pd.DataFrame()
                return pd.concat(dfs, keys=keys, names=["symbol", "timestamp"])
            return btc_df if symbol == "BTC/USD" else eth_df

        mock_market_provider.get_daily_bars.side_effect = get_bars_side_effect

        # Act
        result = risk_engine.check_correlation(signal)

        # Assert
        assert result.passed is True, f"Expected correlation check to pass for uncorrelated assets, but got fail: {result.reason}"

    def test_check_correlation_market_data_failure(
        self, risk_engine, mock_repo, mock_market_provider
    ):
        """Verify correlation check fails safe when market data retrieval fails."""
        # Arrange
        mock_repo.get_open_positions.return_value = [
            self.create_position(symbol="ETH/USD")
        ]
        signal = self.create_signal(symbol="BTC/USD")

        mock_market_provider.get_daily_bars.side_effect = Exception("API Error")

        # Act
        result = risk_engine.check_correlation(signal)

        # Assert
        assert result.passed is False, "Expected correlation check to fail safe on API error"
        assert (
            "error checking correlation" in result.reason.lower()
            or "market data missing" in result.reason.lower()
        ), f"Expected 'error checking correlation' or 'market data missing' in reason, but got: {result.reason}"
