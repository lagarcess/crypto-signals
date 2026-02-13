from datetime import datetime
from unittest.mock import MagicMock

import numpy as np
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


class TestRiskCorrelationBatching:
    @pytest.fixture
    def mock_components(self):
        client = MagicMock(spec=TradingClient)
        repo = MagicMock(spec=PositionRepository)
        market = MagicMock(spec=MarketDataProvider)

        # Mock settings
        with pytest.MonkeyPatch.context() as m:
            settings = MagicMock()
            settings.MAX_CRYPTO_POSITIONS = 5
            settings.MAX_EQUITY_POSITIONS = 5
            settings.MAX_DAILY_DRAWDOWN_PCT = 0.05
            settings.MIN_ASSET_BP_USD = 100.0
            m.setattr("crypto_signals.engine.risk.get_settings", lambda: settings)

            risk = RiskEngine(client, repo, market)
            return risk, repo, market

    def create_signal(self, symbol="BTC/USD"):
        return Signal(
            signal_id="sig_1",
            ds=datetime.now().date(),
            strategy_id="strat",
            symbol=symbol,
            asset_class=AssetClass.CRYPTO,
            pattern_name="p",
            pattern_classification="Bullish",
            pattern_duration_days=1,
            pattern_quality_score=1,
            confidence=0.9,
            status=SignalStatus.WAITING,
            entry_price=100,
            take_profit_1=110,
            suggested_stop=90,
            timestamp=datetime.now(),
        )

    def create_position(self, symbol="ETH/USD"):
        return Position(
            position_id="p1",
            ds=datetime.now().date(),
            account_id="a1",
            signal_id="s1",
            symbol=symbol,
            asset_class=AssetClass.CRYPTO,
            status=TradeStatus.OPEN,
            entry_fill_price=100,
            qty=1,
            side="buy",
            current_stop_loss=90,
            alpaca_order_id="o1",
        )

    def test_check_correlation_batches_calls(self, mock_components):
        risk_engine, mock_repo, mock_market = mock_components

        # Setup: 1 open position (ETH) + 1 Candidate (BTC) -> Both Crypto
        # Should result in 1 call to get_daily_bars with list ["BTC/USD", "ETH/USD"] (order doesn't matter)

        mock_repo.get_open_positions.return_value = [self.create_position("ETH/USD")]
        signal = self.create_signal("BTC/USD")

        # Mock market response
        dates = pd.date_range(end=datetime.now(), periods=90)
        iterables = [["BTC/USD", "ETH/USD"], dates]
        index = pd.MultiIndex.from_product(iterables, names=["symbol", "timestamp"])

        # Use different patterns for each symbol to avoid constant-data warnings
        data = np.concatenate([np.linspace(100, 110, 90), np.linspace(110, 100, 90)])
        df = pd.DataFrame({"close": data}, index=index)
        mock_market.get_daily_bars.return_value = df

        result = risk_engine.check_correlation(signal)

        assert result.passed is True

        mock_market.get_daily_bars.assert_called_once()
        args, kwargs = mock_market.get_daily_bars.call_args

        # Check first arg is list
        fetched_symbols = args[0]
        assert isinstance(fetched_symbols, list)
        assert len(fetched_symbols) == 2
        assert "BTC/USD" in fetched_symbols
        assert "ETH/USD" in fetched_symbols
        assert args[1] == AssetClass.CRYPTO

    def test_check_correlation_mixed_assets(self, mock_components):
        risk_engine, mock_repo, mock_market = mock_components

        # Setup: 1 Crypto Position, Candidate is Equity
        # Should batch separately?
        # Candidate = AAPL (Equity)
        # Position = ETH/USD (Crypto)

        mock_repo.get_open_positions.return_value = [self.create_position("ETH/USD")]
        signal = self.create_signal("AAPL")
        signal.asset_class = AssetClass.EQUITY

        # We expect 2 calls: one for Equity (AAPL), one for Crypto (ETH)
        # Or does logic group them?
        # Logic iterates symbols_by_class.

        # Mock returns
        def side_effect(symbols, asset_class, lookback_days=90):
            if asset_class == AssetClass.CRYPTO:
                # ETH
                idx = pd.MultiIndex.from_product(
                    [["ETH/USD"], pd.date_range("2023-01-01", periods=90)]
                )
                return pd.DataFrame({"close": np.linspace(10, 12, 90)}, index=idx)
            else:
                # AAPL
                idx = pd.MultiIndex.from_product(
                    [["AAPL"], pd.date_range("2023-01-01", periods=90)]
                )
                return pd.DataFrame({"close": np.linspace(150, 160, 90)}, index=idx)

        mock_market.get_daily_bars.side_effect = side_effect

        risk_engine.check_correlation(signal)

        assert mock_market.get_daily_bars.call_count == 2
