from unittest.mock import MagicMock

import pytest

# Local imports
from alpaca.trading.models import TradeAccount
from crypto_signals.config import Settings
from crypto_signals.domain.schemas import AssetClass
from crypto_signals.engine.risk import RiskEngine
from crypto_signals.repository.firestore import PositionRepository

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
    def risk_engine(self, mock_client, mock_repo, mock_settings):
        # Patch the engine's settings property or injected dependency
        # Since RiskEngine uses get_settings(), we need to patch that import
        with pytest.MonkeyPatch.context() as m:
            # Patch at module level where it's imported
            m.setattr("crypto_signals.engine.risk.get_settings", lambda: mock_settings)
            engine = RiskEngine(trading_client=mock_client, repository=mock_repo)
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
