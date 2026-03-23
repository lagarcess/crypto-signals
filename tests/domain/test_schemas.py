"""
Tests for Crypto Sentinel Data Schemas.

Verifies the data contract defined in src/schemas.py:
- Deterministic ID generation (P0 Risk)
- Asset class validation (Refinement)
- Position model completeness
"""

from datetime import date, datetime, timedelta, timezone

import pytest
from crypto_signals.domain.schemas import (
    AssetClass,
    ConfluenceConfig,
    DrawdownMetrics,
    ExitReason,
    FactTheoreticalSignal,
    OrderSide,
    Position,
    Signal,
    SignalStatus,
    StrategyConfig,
    TradeExecution,
    TradeStatus,
    get_deterministic_id,
)
from pydantic import ValidationError

# =============================================================================
# P0 RISK - DETERMINISTIC IDS
# =============================================================================


class TestDeterministicIds:
    """Test get_deterministic_id for idempotency guarantees."""

    @pytest.mark.parametrize(
        "input_a,input_b,expected_equal",
        [
            pytest.param("A", "A", True, id="same_input"),
            pytest.param("A", "B", False, id="different_input"),
            pytest.param(
                "2024-01-15|momentum|BTC/USD",
                "2024-01-15|momentum|BTC/USD",
                True,
                id="complex_key",
            ),
        ],
    )
    def test_deterministic_id_idempotency(self, input_a, input_b, expected_equal):
        """Verify that get_deterministic_id is deterministic or different based on input."""
        id_1 = get_deterministic_id(input_a)
        id_2 = get_deterministic_id(input_b)

        assert (id_1 == id_2) is expected_equal

    def test_returns_valid_uuid_string(self):
        """Output must be a valid UUID string format."""
        result = get_deterministic_id("test")

        # UUID format: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
        assert len(result) == 36
        assert result.count("-") == 4


# =============================================================================
# REFINEMENT - ASSET CLASS VALIDATION
# =============================================================================


class TestAssetClassValidation:
    """Test AssetClass enum validation in StrategyConfig."""

    @pytest.mark.parametrize(
        "asset_class,expected_enum,expected_value",
        [
            pytest.param(
                AssetClass.CRYPTO, AssetClass.CRYPTO, "CRYPTO", id="crypto_enum"
            ),
            pytest.param(
                AssetClass.EQUITY, AssetClass.EQUITY, "EQUITY", id="equity_enum"
            ),
            pytest.param("CRYPTO", AssetClass.CRYPTO, "CRYPTO", id="crypto_string"),
        ],
    )
    def test_strategy_config_accepts_valid_asset_classes(
        self, asset_class, expected_enum, expected_value
    ):
        """Ensure StrategyConfig accepts valid AssetClass values."""
        config = StrategyConfig(
            strategy_id="test_strategy",
            active=True,
            timeframe="1D",
            asset_class=asset_class,
            assets=["BTC/USD"],
            risk_params={},
        )
        assert config.asset_class == expected_enum
        assert config.asset_class.value == expected_value

    def test_rejects_invalid_asset_class(self):
        """Ensure StrategyConfig rejects invalid asset class like 'FOREX'."""
        with pytest.raises(ValidationError) as exc_info:
            StrategyConfig(
                strategy_id="invalid_strategy",
                active=True,
                timeframe="1D",
                asset_class="FOREX",  # Invalid!
                assets=["EUR/USD"],
                risk_params={},
            )

        # Verify the error mentions the invalid value
        error_str = str(exc_info.value)
        assert "asset_class" in error_str.lower() or "FOREX" in error_str


# =============================================================================
# COMPLETENESS - POSITION MODEL
# =============================================================================


class TestPositionModel:
    """Test Position model for required fields and validation."""

    @pytest.mark.parametrize(
        "side,qty,expected_side_value",
        [
            pytest.param(OrderSide.BUY, 0.5, "buy", id="buy_side"),
            pytest.param(OrderSide.SELL, 1.0, "sell", id="sell_side"),
        ],
    )
    def test_position_valid_qty_and_side(self, side, qty, expected_side_value):
        """Position must accept qty and side fields."""
        position = Position(
            position_id="order_123",
            ds=date(2024, 1, 15),
            account_id="account_abc",
            symbol="BTC/USD",
            signal_id="signal_xyz",
            status=TradeStatus.OPEN,
            entry_fill_price=50000.00,
            current_stop_loss=48000.00,
            qty=qty,
            side=side,
        )

        assert position.qty == qty
        assert position.side == side
        assert position.side.value == expected_side_value

    @pytest.mark.parametrize("missing_field", ["qty", "side"])
    def test_position_fails_missing_required_fields(self, missing_field):
        """Position must fail validation if required fields are missing."""
        base_data = {
            "position_id": "order_789",
            "ds": date(2024, 1, 15),
            "account_id": "account_abc",
            "symbol": "BTC/USD",
            "signal_id": "signal_xyz",
            "status": TradeStatus.OPEN,
            "entry_fill_price": 50000.00,
            "current_stop_loss": 48000.00,
            "qty": 0.5,
            "side": OrderSide.BUY,
        }
        del base_data[missing_field]

        with pytest.raises(ValidationError) as exc_info:
            Position(**base_data)

        assert missing_field in str(exc_info.value).lower()

    @pytest.mark.parametrize("discord_id", [None, "1234567890"])
    def test_position_discord_thread_id(self, discord_id):
        """Position must handle discord_thread_id (optional)."""
        position = Position(
            position_id="order_123",
            ds=date(2024, 1, 15),
            account_id="account_abc",
            symbol="BTC/USD",
            signal_id="signal_xyz",
            status=TradeStatus.OPEN,
            entry_fill_price=50000.00,
            current_stop_loss=48000.00,
            qty=0.5,
            side=OrderSide.BUY,
            discord_thread_id=discord_id,
        )

        assert position.discord_thread_id == discord_id


# =============================================================================
# BONUS - SIGNAL MODEL TESTS
# =============================================================================


class TestSignalModel:
    """Additional tests for Signal model completeness."""

    def test_signal_with_suggested_stop(self):
        """Signal must include suggested_stop field."""
        signal = Signal(
            signal_id=get_deterministic_id("2024-01-15|momentum|BTC/USD"),
            ds=date(2024, 1, 15),
            strategy_id="momentum",
            symbol="BTC/USD",
            asset_class=AssetClass.CRYPTO,
            confluence_factors=[],
            entry_price=50000.0,
            pattern_name="bullish_engulfing",
            status=SignalStatus.WAITING,
            suggested_stop=48000.00,
            valid_until=datetime(2024, 1, 16, tzinfo=timezone.utc),
        )

        assert signal.suggested_stop == 48000.00

    def test_signal_status_default(self):
        """Signal status should default to WAITING."""
        signal = Signal(
            signal_id="test_signal",
            ds=date(2024, 1, 15),
            strategy_id="momentum",
            symbol="BTC/USD",
            asset_class=AssetClass.CRYPTO,
            entry_price=50000.0,
            pattern_name="bullish_engulfing",
            suggested_stop=48000.00,
        )

        assert signal.status == SignalStatus.WAITING

    @pytest.mark.parametrize("discord_id", [None, "1234567890"])
    def test_signal_discord_thread_id(self, discord_id):
        """Signal must handle discord_thread_id (optional)."""
        signal = Signal(
            signal_id="test_signal",
            ds=date(2024, 1, 15),
            strategy_id="momentum",
            symbol="BTC/USD",
            asset_class=AssetClass.CRYPTO,
            entry_price=50000.0,
            pattern_name="bullish_engulfing",
            suggested_stop=48000.00,
            discord_thread_id=discord_id,
        )

        assert signal.discord_thread_id == discord_id

        serialized = signal.model_dump(mode="json")
        assert serialized["discord_thread_id"] == discord_id

    @pytest.mark.parametrize(
        "classification,expected_delta_hours",
        [
            pytest.param("STANDARD_PATTERN", 48, id="standard"),
            pytest.param("MACRO_PATTERN", 120, id="macro"),
            pytest.param(None, 120, id="none_fallback"),
        ],
    )
    def test_signal_legacy_fallback_created_at(
        self, classification, expected_delta_hours
    ):
        """Signal must populate created_at from valid_until for legacy data (Issue 99)."""
        valid_until = datetime(2024, 1, 16, 12, 0, tzinfo=timezone.utc)
        signal = Signal(
            signal_id="legacy_signal",
            ds=date(2024, 1, 15),
            strategy_id="momentum",
            symbol="BTC/USD",
            asset_class=AssetClass.CRYPTO,
            entry_price=50000.0,
            pattern_name="bullish_engulfing",
            suggested_stop=48000.00,
            valid_until=valid_until,
            pattern_classification=classification,
            created_at=None,
        )

        expected_created_at = valid_until - timedelta(hours=expected_delta_hours)
        assert signal.created_at == expected_created_at


# =============================================================================
# TRADE EXECUTION MODEL TESTS
# =============================================================================


class TestTradeExecutionModel:
    """Test TradeExecution model for pnl_usd field validation."""

    @pytest.mark.parametrize("missing_pnl_field", ["pnl_pct", "pnl_usd"])
    def test_trade_execution_pnl_fields_required(
        self, missing_pnl_field, trade_execution_base_data
    ):
        """TradeExecution must require both pnl_pct and pnl_usd."""
        data = trade_execution_base_data.copy()
        del data[missing_pnl_field]

        with pytest.raises(ValidationError) as exc_info:
            TradeExecution(**data)

        assert missing_pnl_field in str(exc_info.value).lower()

    @pytest.mark.parametrize("exit_order_id", [None, "exit-order-123"])
    def test_trade_execution_exit_order_id(
        self, exit_order_id, trade_execution_base_data
    ):
        """TradeExecution must handle exit_order_id (optional)."""
        data = trade_execution_base_data.copy()
        if exit_order_id:
            data["exit_order_id"] = exit_order_id

        trade = TradeExecution(**data)
        assert trade.exit_order_id == exit_order_id

        serialized = trade.model_dump(mode="json")
        assert serialized.get("exit_order_id") == exit_order_id

    @pytest.fixture
    def trade_execution_base_data(self):
        """Base data for TradeExecution tests."""
        return {
            "ds": date(2024, 1, 15),
            "trade_id": "trade_123",
            "account_id": "account_abc",
            "asset_class": AssetClass.CRYPTO,
            "symbol": "BTC/USD",
            "side": OrderSide.BUY,
            "qty": 1.0,
            "entry_price": 50000.0,
            "exit_price": 52000.0,
            "entry_time": datetime(2024, 1, 15, 10, 0, tzinfo=timezone.utc),
            "exit_time": datetime(2024, 1, 16, 10, 0, tzinfo=timezone.utc),
            "exit_reason": ExitReason.TP1,
            "pnl_pct": 4.0,
            "pnl_usd": 2000.0,
            "fees_usd": 10.0,
            "slippage_pct": 0.1,
            "trade_duration": 86400,
        }

    @pytest.mark.parametrize(
        "trade_input",
        [
            pytest.param({"strategy_id": None}, id="strategy_id_is_none"),
            pytest.param({}, id="strategy_id_is_missing"),
        ],
    )
    def test_trade_execution_defaults_strategy_id_to_unknown(
        self, trade_input, trade_execution_base_data
    ):
        """TradeExecution must default strategy_id to 'UNKNOWN' if None or missing (Issue #253)."""
        trade_data = {**trade_execution_base_data, **trade_input}
        trade = TradeExecution(**trade_data)

        assert trade.strategy_id == "UNKNOWN"


# =============================================================================
# STRATEGY CONFIG MODEL TESTS (Issue #198)
# =============================================================================


class TestStrategyConfigDefaults:
    """Tests for StrategyConfig defaults and completeness."""

    def test_strategy_config_defaults(self):
        """Test that new fields default to empty dicts when missing."""
        config = StrategyConfig(
            strategy_id="test_strategy",
            active=True,
            timeframe="1D",
            asset_class=AssetClass.CRYPTO,
            assets=["BTC/USD"],
            risk_params={"stop_loss_pct": 0.02},
        )

        assert config.confluence_config == ConfluenceConfig()
        assert isinstance(config.confluence_config, ConfluenceConfig)
        assert config.pattern_overrides == {}
        assert isinstance(config.pattern_overrides, dict)

    def test_strategy_config_explicit_values(self):
        """Test that new fields accept explicit values."""
        confluence_config = {"rsi_period": 14}
        pattern_overrides = {"bullish_engulfing": {"priority": 1}}

        config = StrategyConfig(
            strategy_id="test_strategy",
            active=True,
            timeframe="1D",
            asset_class=AssetClass.CRYPTO,
            assets=["BTC/USD"],
            risk_params={"stop_loss_pct": 0.02},
            confluence_config=confluence_config,
            pattern_overrides=pattern_overrides,
        )

        # ConfluenceConfig defaults will be applied to missing fields
        assert config.confluence_config.rsi_period == 14
        assert config.confluence_config.adx_threshold == 25.0
        assert config.pattern_overrides == pattern_overrides

    def test_strategy_config_json_serialization(self):
        """Verify JSON serialization for BigQuery compatibility."""
        confluence_config = {"rsi_period": 14}
        pattern_overrides = {"bullish_engulfing": {"priority": 1}}

        config = StrategyConfig(
            strategy_id="test_strategy",
            active=True,
            timeframe="1D",
            asset_class=AssetClass.CRYPTO,
            assets=["BTC/USD"],
            risk_params={"stop_loss_pct": 0.02},
            confluence_config=confluence_config,
            pattern_overrides=pattern_overrides,
        )

        serialized = config.model_dump(mode="json")

        assert "confluence_config" in serialized
        # ConfluenceConfig defaults are included
        assert serialized["confluence_config"]["rsi_period"] == 14
        assert serialized["confluence_config"]["adx_threshold"] == 25.0
        assert "pattern_overrides" in serialized
        assert serialized["pattern_overrides"] == pattern_overrides

    def test_strategy_config_json_serialization_defaults(self):
        """Verify JSON serialization includes defaults."""
        config = StrategyConfig(
            strategy_id="test_strategy",
            active=True,
            timeframe="1D",
            asset_class=AssetClass.CRYPTO,
            assets=["BTC/USD"],
            risk_params={"stop_loss_pct": 0.02},
        )

        serialized = config.model_dump(mode="json")

        # Usually defaults are included by default in model_dump unless exclude_defaults=True.
        # We want them included for BigQuery schema consistency.
        assert "confluence_config" in serialized
        # Should contain default values for ConfluenceConfig
        assert serialized["confluence_config"] == ConfluenceConfig().model_dump(
            mode="json"
        )
        assert "pattern_overrides" in serialized
        assert serialized["pattern_overrides"] == {}


# =============================================================================
# FACT THEORETICAL SIGNAL (BQ NESTED FIELDS)
# =============================================================================


class TestFactTheoreticalSignal:
    """Tests for BigQuery schema serialization of FactTheoreticalSignal."""

    def test_bq_serialization_of_nested_fields(self):
        """Ensure nested fields serialize properly to BQ-compatible primitives via model_dump."""
        signal = FactTheoreticalSignal(
            doc_id="test_doc",
            ds=date(2024, 1, 15),
            signal_id="sig_123",
            strategy_id="strat_abc",
            symbol="BTC/USD",
            asset_class=AssetClass.CRYPTO,
            side=OrderSide.BUY,
            entry_price=50000.0,
            suggested_stop=48000.0,
            valid_until=datetime(2024, 1, 16, tzinfo=timezone.utc),
            status=SignalStatus.EXPIRED,
            created_at=datetime(2024, 1, 15, tzinfo=timezone.utc),
            confluence_factors={"RSI_14": 30.5, "MACD_hist": -1.2},
            exit_reasons=["TP1_HIT", "TRAILING_STOP_HIT"],
            drawdown_metrics=DrawdownMetrics(max_dd_pct=-5.2, duration_hours=12),
        )

        serialized = signal.model_dump(mode="json")

        # JSON mapping check
        assert serialized["confluence_factors"]["RSI_14"] == 30.5
        assert serialized["confluence_factors"]["MACD_hist"] == -1.2

        # REPEATED STRING mapping check
        assert isinstance(serialized["exit_reasons"], list)
        assert "TP1_HIT" in serialized["exit_reasons"]

        # RECORD mapping check
        assert isinstance(serialized["drawdown_metrics"], dict)
        assert serialized["drawdown_metrics"]["max_dd_pct"] == -5.2
        assert serialized["drawdown_metrics"]["duration_hours"] == 12

    def test_bq_serialization_empty_defaults(self):
        """Ensure defaults play nicely with BigQuery missing/empty constraints."""
        signal = FactTheoreticalSignal(
            ds=date(2024, 1, 15),
            signal_id="sig_123",
            strategy_id="strat_abc",
            symbol="BTC/USD",
            asset_class=AssetClass.CRYPTO,
            side=OrderSide.BUY,
            entry_price=50000.0,
            suggested_stop=48000.0,
            valid_until=datetime(2024, 1, 16, tzinfo=timezone.utc),
            status=SignalStatus.EXPIRED,
            created_at=datetime(2024, 1, 15, tzinfo=timezone.utc),
        )

        serialized = signal.model_dump(mode="json")
        assert serialized["confluence_factors"] == {}
        assert serialized["exit_reasons"] == []
        assert serialized["drawdown_metrics"] is None
