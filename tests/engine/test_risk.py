from unittest.mock import MagicMock

import pandas as pd
import pytest

# Local imports
from alpaca.trading.models import TradeAccount
from crypto_signals.config import Settings
from crypto_signals.domain.schemas import AssetClass, Position, Signal
from crypto_signals.engine.risk import RiskEngine
from crypto_signals.repository.firestore import PositionRepository

# Ensure AssetClass is available in module scope for test methods
CRYPTO = AssetClass.CRYPTO
EQUITY = AssetClass.EQUITY


def create_mock_signal(symbol="BTC/USD"):
    return Signal(
        signal_id="test_signal",
        ds="2023-01-01",
        strategy_id="test_strategy",
        symbol=symbol,
        asset_class=AssetClass.CRYPTO,
        entry_price=50000.0,
        pattern_name="test_pattern",
        suggested_stop=49000.0,
    )


def create_mock_position(symbol="ETH/USD"):
    return Position(
        position_id="test_position",
        ds="2023-01-01",
        account_id="test_account",
        symbol=symbol,
        signal_id="test_signal",
        entry_fill_price=3000.0,
        current_stop_loss=2900.0,
        qty=1.0,
        side="buy",
    )


def create_bars_dataframe(data, symbol):
    df = pd.DataFrame(data)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.set_index("timestamp")
    # Add other necessary columns if the code uses them
    for col in ["open", "high", "low", "volume"]:
        if col not in df.columns:
            df[col] = 0
    return df


class TestRiskEngine:
    @pytest.fixture
    def mock_settings(self):
        settings = MagicMock(spec=Settings)
        # Default Safe Settings
        settings.MAX_CRYPTO_POSITIONS = 5
        settings.MAX_EQUITY_POSITIONS = 5
        settings.MAX_DAILY_DRAWDOWN_PCT = 0.05  # 5%
        settings.MIN_ASSET_BP_USD = 100.0
        settings.MAX_ASSET_CORRELATION = 0.8
        return settings

    @pytest.fixture
    def mock_repo(self):
        return MagicMock(spec=PositionRepository)

    @pytest.fixture
    def mock_market_data_provider(self):
        return MagicMock()

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
    def risk_engine(self, mock_client, mock_repo, mock_market_data_provider, mock_settings):
        # Patch the engine's settings property or injected dependency
        # Patch get_settings() dependency for RiskEngine
        with pytest.MonkeyPatch.context() as m:
            # Patch at module level where it's imported
            m.setattr("crypto_signals.engine.risk.get_settings", lambda: mock_settings)
            engine = RiskEngine(
                trading_client=mock_client,
                repository=mock_repo,
                market_data_provider=mock_market_data_provider,
            )
            yield engine

    def test_check_buying_power_crypto_pass(self, risk_engine):
        # Crypto uses non_marginable_buying_power
        # Req: 1000, Avail: 5000 -> Pass
        result = risk_engine.check_buying_power(CRYPTO, 1000.0)
        assert result.passed is True

    def test_check_buying_power_crypto_fail(self, risk_engine):
        # Req: 6000, Avail: 5000 -> Fail
        result = risk_engine.check_buying_power(CRYPTO, 6000.0)
        assert result.passed is False
        assert "Insufficient Buying Power" in result.reason

    def test_check_buying_power_equity_pass_regt(self, risk_engine):
        # Equity uses regt_buying_power
        # Req: 10000, Avail: 20000 -> Pass
        result = risk_engine.check_buying_power(EQUITY, 10000.0)
        assert result.passed is True

    def test_check_sector_cap_crypto_fail(self, risk_engine, mock_repo):
        # Mock repo to return MAX
        mock_repo.count_open_positions_by_class.return_value = 5  # Match Max

        result = risk_engine.check_sector_limit(CRYPTO)
        assert result.passed is False
        assert "Max CRYPTO positions reached" in result.reason

    def test_daily_drawdown_fail(self, risk_engine, mock_client):
        # Equity 9000, Last 10000 -> 10% Drop. Max is 5%
        mock_client.get_account.return_value.equity = "9000.00"
        mock_client.get_account.return_value.last_equity = "10000.00"

        result = risk_engine.check_daily_drawdown()
        assert result.passed is False
        assert "Daily Drawdown Limit Hit" in result.reason

    def test_check_correlation_risk_no_open_positions(self, risk_engine):
        risk_engine.repo.get_open_positions.return_value = []
        signal = create_mock_signal()
        result = risk_engine.check_correlation_risk(signal)
        assert result.passed is True

    def test_check_correlation_risk_high_correlation(
        self, risk_engine, mock_market_data_provider
    ):
        risk_engine.repo.get_open_positions.return_value = [
            create_mock_position("ETH/USD")
        ]
        signal = create_mock_signal("BTC/USD")

        btc_bars = create_bars_dataframe(
            {
                "timestamp": ["2023-01-01", "2023-01-02", "2023-01-03"],
                "close": [50000, 51000, 52000],
            },
            "BTC/USD",
        )
        eth_bars = create_bars_dataframe(
            {
                "timestamp": ["2023-01-01", "2023-01-02", "2023-01-03"],
                "close": [3000, 3100, 3200],
            },
            "ETH/USD",
        )

        mock_market_data_provider.get_daily_bars.side_effect = [btc_bars, eth_bars]

        result = risk_engine.check_correlation_risk(signal)
        assert result.passed is False
        assert "High correlation" in result.reason

    def test_check_correlation_risk_low_correlation(
        self, risk_engine, mock_market_data_provider
    ):
        risk_engine.repo.get_open_positions.return_value = [
            create_mock_position("LTC/USD")
        ]
        signal = create_mock_signal("BTC/USD")

        btc_bars = create_bars_dataframe(
            {
                "timestamp": ["2023-01-01", "2023-01-02", "2023-01-03"],
                "close": [50000, 51000, 49000],
            },
            "BTC/USD",
        )
        ltc_bars = create_bars_dataframe(
            {
                "timestamp": ["2023-01-01", "2023-01-02", "2023-01-03"],
                "close": [150, 140, 160],
            },
            "LTC/USD",
        )

        mock_market_data_provider.get_daily_bars.side_effect = [btc_bars, ltc_bars]

        result = risk_engine.check_correlation_risk(signal)
        assert result.passed is True

    def test_check_correlation_risk_data_provider_error(
        self, risk_engine, mock_market_data_provider
    ):
        risk_engine.repo.get_open_positions.return_value = [
            create_mock_position("ETH/USD")
        ]
        signal = create_mock_signal("BTC/USD")
        mock_market_data_provider.get_daily_bars.side_effect = Exception("API error")

        result = risk_engine.check_correlation_risk(signal)
        assert result.passed is False
        assert "Error checking correlation" in result.reason
