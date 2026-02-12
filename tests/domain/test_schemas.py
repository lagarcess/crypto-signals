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
    ExitReason,
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

    def test_same_input_produces_same_output(self):
        """Identical inputs MUST produce identical UUIDs."""
        id_1 = get_deterministic_id("A")
        id_2 = get_deterministic_id("A")

        assert id_1 == id_2, "Same input must produce same UUID"

    def test_different_inputs_produce_different_outputs(self):
        """Different inputs MUST produce different UUIDs."""
        id_a = get_deterministic_id("A")
        id_b = get_deterministic_id("B")

        assert id_a != id_b, "Different inputs must produce different UUIDs"

    def test_complex_key_is_deterministic(self):
        """Real-world signal key pattern must be deterministic."""
        key = "2024-01-15|momentum|BTC/USD"

        id_1 = get_deterministic_id(key)
        id_2 = get_deterministic_id(key)

        assert id_1 == id_2

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

    def test_accepts_crypto_asset_class(self):
        """Ensure StrategyConfig accepts AssetClass.CRYPTO."""
        config = StrategyConfig(
            strategy_id="test_strategy",
            active=True,
            timeframe="1D",
            asset_class=AssetClass.CRYPTO,
            assets=["BTC/USD", "ETH/USD"],
            risk_params={"stop_loss_pct": 0.02},
        )

        assert config.asset_class == AssetClass.CRYPTO
        assert config.asset_class.value == "CRYPTO"

    def test_accepts_equity_asset_class(self):
        """Ensure StrategyConfig accepts AssetClass.EQUITY."""
        config = StrategyConfig(
            strategy_id="equity_strategy",
            active=True,
            timeframe="1D",
            asset_class=AssetClass.EQUITY,
            assets=["AAPL", "GOOGL"],
            risk_params={},
        )

        assert config.asset_class == AssetClass.EQUITY
        assert config.asset_class.value == "EQUITY"

    def test_accepts_string_value_for_asset_class(self):
        """Ensure StrategyConfig accepts valid string values for asset_class."""
        config = StrategyConfig(
            strategy_id="test_strategy",
            active=True,
            timeframe="1D",
            asset_class="CRYPTO",  # String instead of enum
            assets=["BTC/USD"],
            risk_params={},
        )

        assert config.asset_class == AssetClass.CRYPTO

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

    def test_position_with_qty_and_side(self):
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
            qty=0.5,
            side=OrderSide.BUY,
        )

        assert position.qty == 0.5
        assert position.side == OrderSide.BUY

    def test_position_accepts_sell_side(self):
        """Position must accept OrderSide.SELL."""
        position = Position(
            position_id="order_456",
            ds=date(2024, 1, 15),
            account_id="account_abc",
            symbol="BTC/USD",
            signal_id="signal_xyz",
            status=TradeStatus.OPEN,
            entry_fill_price=50000.00,
            current_stop_loss=52000.00,
            qty=1.0,
            side=OrderSide.SELL,
        )

        assert position.side == OrderSide.SELL
        assert position.side.value == "sell"

    def test_position_fails_without_qty(self):
        """Position must fail validation if qty is missing."""
        with pytest.raises(ValidationError) as exc_info:
            Position(
                position_id="order_789",
                ds=date(2024, 1, 15),
                account_id="account_abc",
                symbol="BTC/USD",
                signal_id="signal_xyz",
                status=TradeStatus.OPEN,
                entry_fill_price=50000.00,
                current_stop_loss=48000.00,
                # qty is missing!
                side=OrderSide.BUY,
            )

        error_str = str(exc_info.value)
        assert "qty" in error_str.lower()

    def test_position_fails_without_side(self):
        """Position must fail validation if side is missing."""
        with pytest.raises(ValidationError) as exc_info:
            Position(
                position_id="order_789",
                ds=date(2024, 1, 15),
                account_id="account_abc",
                symbol="BTC/USD",
                signal_id="signal_xyz",
                status=TradeStatus.OPEN,
                entry_fill_price=50000.00,
                current_stop_loss=48000.00,
                qty=0.5,
                # side is missing!
            )

        error_str = str(exc_info.value)
        assert "side" in error_str.lower()

    def test_position_discord_thread_id_optional(self):
        """Position must allow discord_thread_id to be None."""
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
            discord_thread_id=None,  # Explicitly None
        )

        assert position.discord_thread_id is None

    def test_position_accepts_discord_thread_id(self):
        """Position must accept a valid discord_thread_id."""
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
            discord_thread_id="1234567890",
        )

        assert position.discord_thread_id == "1234567890"


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

    def test_signal_discord_thread_id_optional(self):
        """Signal must allow discord_thread_id to be None (default)."""
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

        assert signal.discord_thread_id is None

    def test_signal_accepts_discord_thread_id(self):
        """Signal must accept a valid discord_thread_id for lifecycle threading."""
        signal = Signal(
            signal_id="test_signal",
            ds=date(2024, 1, 15),
            strategy_id="momentum",
            symbol="BTC/USD",
            asset_class=AssetClass.CRYPTO,
            entry_price=50000.0,
            pattern_name="bullish_engulfing",
            suggested_stop=48000.00,
            discord_thread_id="1234567890123456789",
        )

        assert signal.discord_thread_id == "1234567890123456789"

    def test_signal_discord_thread_id_serializes_to_json(self):
        """Signal discord_thread_id must be included in JSON serialization."""
        signal = Signal(
            signal_id="test_signal",
            ds=date(2024, 1, 15),
            strategy_id="momentum",
            symbol="BTC/USD",
            asset_class=AssetClass.CRYPTO,
            entry_price=50000.0,
            pattern_name="bullish_engulfing",
            suggested_stop=48000.00,
            discord_thread_id="9876543210987654321",
        )

        serialized = signal.model_dump(mode="json")

        assert "discord_thread_id" in serialized
        assert serialized["discord_thread_id"] == "9876543210987654321"

    def test_signal_legacy_fallback_created_at_standard_pattern(self):
        """Signal must populate created_at from valid_until for STANDARD patterns (Issue 99)."""
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
            pattern_classification="STANDARD_PATTERN",
            created_at=None,  # Missing (simulating legacy data)
        )

        # Fallback: created_at = valid_until - 48h for STANDARD patterns
        expected_created_at = valid_until - timedelta(hours=48)
        assert signal.created_at == expected_created_at

    def test_signal_legacy_fallback_created_at_macro_pattern(self):
        """Signal must populate created_at from valid_until for MACRO patterns (Issue 99)."""
        valid_until = datetime(2024, 1, 16, 12, 0, tzinfo=timezone.utc)
        signal = Signal(
            signal_id="legacy_signal_macro",
            ds=date(2024, 1, 15),
            strategy_id="momentum",
            symbol="BTC/USD",
            asset_class=AssetClass.CRYPTO,
            entry_price=50000.0,
            pattern_name="ABCD",
            suggested_stop=48000.00,
            valid_until=valid_until,
            pattern_classification="MACRO_PATTERN",
            created_at=None,  # Missing (simulating legacy data)
        )

        # Fallback: created_at = valid_until - 120h for MACRO patterns
        expected_created_at = valid_until - timedelta(hours=120)
        assert signal.created_at == expected_created_at

    def test_signal_legacy_fallback_created_at_no_classification(self):
        """Signal must use conservative 120h TTL for legacy signals without classification (Issue 99)."""
        valid_until = datetime(2024, 1, 16, 12, 0, tzinfo=timezone.utc)
        signal = Signal(
            signal_id="legacy_signal_no_class",
            ds=date(2024, 1, 15),
            strategy_id="momentum",
            symbol="BTC/USD",
            asset_class=AssetClass.CRYPTO,
            entry_price=50000.0,
            pattern_name="bullish_hammer",
            suggested_stop=48000.00,
            valid_until=valid_until,
            pattern_classification=None,  # No classification (legacy)
            created_at=None,  # Missing (simulating legacy data)
        )

        # Fallback: created_at = valid_until - 120h for safety (conservative)
        expected_created_at = valid_until - timedelta(hours=120)
        assert signal.created_at == expected_created_at


# =============================================================================
# TRADE EXECUTION MODEL TESTS
# =============================================================================


class TestTradeExecutionModel:
    """Test TradeExecution model for pnl_usd field validation."""

    def test_trade_execution_requires_pnl_usd(self):
        """TradeExecution must require pnl_usd field."""
        with pytest.raises(ValidationError) as exc_info:
            TradeExecution(
                ds=date(2024, 1, 15),
                trade_id="trade_123",
                account_id="account_abc",
                strategy_id="momentum",
                asset_class=AssetClass.CRYPTO,
                symbol="BTC/USD",
                side=OrderSide.BUY,
                qty=1.0,
                entry_price=50000.0,
                exit_price=52000.0,
                entry_time=datetime(2024, 1, 15, 10, 0, tzinfo=timezone.utc),
                exit_time=datetime(2024, 1, 16, 10, 0, tzinfo=timezone.utc),
                exit_reason=ExitReason.TP1,
                pnl_pct=4.0,
                # pnl_usd is missing!
                fees_usd=10.0,
                slippage_pct=0.1,
                trade_duration=86400,
            )

        error_str = str(exc_info.value)
        assert "pnl_usd" in error_str.lower()

    def test_trade_execution_accepts_pnl_usd(self):
        """TradeExecution must accept pnl_usd alongside pnl_pct."""
        trade = TradeExecution(
            ds=date(2024, 1, 15),
            trade_id="trade_123",
            account_id="account_abc",
            strategy_id="momentum",
            asset_class=AssetClass.CRYPTO,
            symbol="BTC/USD",
            side=OrderSide.BUY,
            qty=1.0,
            entry_price=50000.0,
            exit_price=52000.0,
            entry_time=datetime(2024, 1, 15, 10, 0, tzinfo=timezone.utc),
            exit_time=datetime(2024, 1, 16, 10, 0, tzinfo=timezone.utc),
            exit_reason=ExitReason.TP1,
            pnl_pct=4.0,
            pnl_usd=2000.0,
            fees_usd=10.0,
            slippage_pct=0.1,
            trade_duration=86400,
        )

        assert trade.pnl_usd == 2000.0
        assert trade.pnl_pct == 4.0

    def test_trade_execution_both_pnl_fields_required(self):
        """TradeExecution must have both pnl_pct and pnl_usd."""
        # Missing pnl_pct
        with pytest.raises(ValidationError) as exc_info:
            TradeExecution(
                ds=date(2024, 1, 15),
                trade_id="trade_123",
                account_id="account_abc",
                strategy_id="momentum",
                asset_class=AssetClass.CRYPTO,
                symbol="BTC/USD",
                side=OrderSide.BUY,
                qty=1.0,
                entry_price=50000.0,
                exit_price=52000.0,
                entry_time=datetime(2024, 1, 15, 10, 0, tzinfo=timezone.utc),
                exit_time=datetime(2024, 1, 16, 10, 0, tzinfo=timezone.utc),
                exit_reason=ExitReason.TP1,
                # pnl_pct is missing!
                pnl_usd=2000.0,
                fees_usd=10.0,
                slippage_pct=0.1,
                trade_duration=86400,
            )

        error_str = str(exc_info.value)
        assert "pnl_pct" in error_str.lower()

    def test_trade_execution_accepts_exit_order_id(self):
        """TradeExecution must accept exit_order_id for exit order tracking."""
        trade = TradeExecution(
            ds=date(2024, 1, 15),
            trade_id="trade_123",
            account_id="account_abc",
            strategy_id="momentum",
            asset_class=AssetClass.CRYPTO,
            symbol="BTC/USD",
            side=OrderSide.BUY,
            qty=1.0,
            entry_price=50000.0,
            exit_price=52000.0,
            entry_time=datetime(2024, 1, 15, 10, 0, tzinfo=timezone.utc),
            exit_time=datetime(2024, 1, 16, 10, 0, tzinfo=timezone.utc),
            exit_reason=ExitReason.TP1,
            pnl_pct=4.0,
            pnl_usd=2000.0,
            fees_usd=10.0,
            slippage_pct=0.1,
            trade_duration=86400,
            exit_order_id="exit-order-uuid-12345",
        )

        assert trade.exit_order_id == "exit-order-uuid-12345"

    def test_trade_execution_exit_order_id_optional(self):
        """TradeExecution exit_order_id must default to None (backward compatible)."""
        trade = TradeExecution(
            ds=date(2024, 1, 15),
            trade_id="trade_456",
            account_id="account_abc",
            strategy_id="momentum",
            asset_class=AssetClass.CRYPTO,
            symbol="BTC/USD",
            side=OrderSide.BUY,
            qty=1.0,
            entry_price=50000.0,
            exit_price=52000.0,
            entry_time=datetime(2024, 1, 15, 10, 0, tzinfo=timezone.utc),
            exit_time=datetime(2024, 1, 16, 10, 0, tzinfo=timezone.utc),
            exit_reason=ExitReason.TP1,
            pnl_pct=4.0,
            pnl_usd=2000.0,
            fees_usd=10.0,
            slippage_pct=0.1,
            trade_duration=86400,
            # exit_order_id not provided (should default to None)
        )

        assert trade.exit_order_id is None

    def test_trade_execution_exit_order_id_serializes_to_json(self):
        """TradeExecution exit_order_id must be included in JSON serialization."""
        trade = TradeExecution(
            ds=date(2024, 1, 15),
            trade_id="trade_789",
            account_id="account_abc",
            strategy_id="momentum",
            asset_class=AssetClass.CRYPTO,
            symbol="BTC/USD",
            side=OrderSide.BUY,
            qty=1.0,
            entry_price=50000.0,
            exit_price=52000.0,
            entry_time=datetime(2024, 1, 15, 10, 0, tzinfo=timezone.utc),
            exit_time=datetime(2024, 1, 16, 10, 0, tzinfo=timezone.utc),
            exit_reason=ExitReason.TP1,
            pnl_pct=4.0,
            pnl_usd=2000.0,
            fees_usd=10.0,
            slippage_pct=0.1,
            trade_duration=86400,
            exit_order_id="serialized-exit-order-id",
        )

        serialized = trade.model_dump(mode="json")

        assert "exit_order_id" in serialized
        assert serialized["exit_order_id"] == "serialized-exit-order-id"


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
        assert serialized["confluence_config"] == ConfluenceConfig().model_dump(mode="json")
        assert "pattern_overrides" in serialized
        assert serialized["pattern_overrides"] == {}
