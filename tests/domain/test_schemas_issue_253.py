from datetime import date, datetime, timezone

import pytest
from crypto_signals.domain.schemas import (
    AssetClass,
    ExitReason,
    OrderSide,
    TradeExecution,
)


class TestTradeExecutionSchema:
    @pytest.mark.parametrize(
        "trade_input",
        [
            pytest.param({"strategy_id": None}, id="strategy_id_is_none"),
            pytest.param({}, id="strategy_id_is_missing"),
        ],
    )
    def test_trade_execution_handles_none_or_missing_strategy_id(self, trade_input):
        """TradeExecution must default strategy_id to 'UNKNOWN' if None or missing."""
        base_data = {
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
        trade_data = {**base_data, **trade_input}
        trade = TradeExecution(**trade_data)

        assert trade.strategy_id == "UNKNOWN"
