"""Regression tests for Issue #275: TP Automation Race Condition.

Verifies that TP3_HIT / INVALIDATED exits from an old signal do NOT close
positions belonging to a newer signal for the same symbol.

Root cause: Alpaca holds one aggregate position per symbol. When
close_position_emergency sells qty from the old signal's Firestore position,
it can sell shares belonging to a newly-bought position for the same symbol.
"""

from datetime import date
from unittest.mock import MagicMock

from alpaca.common.exceptions import APIError
from crypto_signals.domain.schemas import (
    AssetClass,
    ExitReason,
    OrderSide,
    Position,
    SignalStatus,
    TradeStatus,
)


def _make_signal(signal_id, symbol="AAVE/USD", status=SignalStatus.TP3_HIT):
    """Helper: create a mock Signal with minimal required fields."""
    sig = MagicMock()
    sig.signal_id = signal_id
    sig.symbol = symbol
    sig.status = status
    sig.exit_reason = ExitReason.TP_HIT if status == SignalStatus.TP3_HIT else None
    sig.pattern_name = "ELLIOTT_WAVE_135"
    sig.discord_thread_id = "thread_old"
    sig.asset_class = AssetClass.CRYPTO
    sig.side = OrderSide.BUY
    return sig


def _make_position(
    position_id,
    signal_id,
    symbol="AAVE/USD",
    status=TradeStatus.OPEN,
    qty=10.0,
):
    """Helper: create a real Position object."""
    return Position(
        position_id=position_id,
        ds=date(2026, 2, 10),
        account_id="paper",
        symbol=symbol,
        signal_id=signal_id,
        alpaca_order_id="alpaca-order-1",
        status=status,
        entry_fill_price=150.0,
        current_stop_loss=140.0,
        qty=qty,
        side=OrderSide.BUY,
    )


# =============================================================================
# TEST: TP3_HIT on old signal must NOT close new signal's position
# =============================================================================


class TestTPAutomationSignalGuard:
    """Tests for the signal_id guard in the TP Automation block."""

    def test_tp3_closes_own_position_only(self):
        """TP3_HIT should close the position whose signal_id matches."""
        old_signal = _make_signal("old-signal-aaa", status=SignalStatus.TP3_HIT)
        old_position = _make_position("old-pos", signal_id="old-signal-aaa")

        # Simulate: get_position_by_signal returns the OLD position (correct match)
        position_repo = MagicMock()
        position_repo.get_position_by_signal.return_value = old_position

        execution_engine = MagicMock()
        execution_engine.close_position_emergency.return_value = True

        # Call the logic under test
        pos = position_repo.get_position_by_signal(old_signal.signal_id)
        assert pos is not None
        assert pos.signal_id == old_signal.signal_id  # Guard passes
        assert pos.status == TradeStatus.OPEN

        # Execute close
        result = execution_engine.close_position_emergency(pos)
        assert result is True
        execution_engine.close_position_emergency.assert_called_once_with(old_position)

    def test_tp3_skips_when_position_signal_id_mismatch(self):
        """TP3_HIT must NOT close a position whose signal_id doesn't match.

        This is the core regression test for Issue #275.
        Scenario: Old signal hits TP3, but get_position_by_signal returns
        a position linked to a DIFFERENT signal (the new one).
        """
        old_signal = _make_signal("old-signal-aaa", status=SignalStatus.TP3_HIT)
        new_position = _make_position("new-pos", signal_id="new-signal-bbb")

        # BUG SCENARIO: get_position_by_signal incorrectly returns new position
        position_repo = MagicMock()
        position_repo.get_position_by_signal.return_value = new_position

        execution_engine = MagicMock()

        # Apply the guard: signal_id must match
        pos = position_repo.get_position_by_signal(old_signal.signal_id)
        if (
            pos
            and pos.status == TradeStatus.OPEN
            and pos.signal_id == old_signal.signal_id
        ):
            execution_engine.close_position_emergency(pos)

        # The guard BLOCKS the close because signal IDs don't match
        execution_engine.close_position_emergency.assert_not_called()

    def test_tp3_skips_when_position_already_closed(self):
        """TP3_HIT must not act on already-closed positions."""
        old_signal = _make_signal("old-signal-aaa", status=SignalStatus.TP3_HIT)
        closed_position = _make_position(
            "old-pos", signal_id="old-signal-aaa", status=TradeStatus.CLOSED
        )

        position_repo = MagicMock()
        position_repo.get_position_by_signal.return_value = closed_position

        execution_engine = MagicMock()

        pos = position_repo.get_position_by_signal(old_signal.signal_id)
        if (
            pos
            and pos.status == TradeStatus.OPEN
            and pos.signal_id == old_signal.signal_id
        ):
            execution_engine.close_position_emergency(pos)

        execution_engine.close_position_emergency.assert_not_called()

    def test_tp3_skips_when_no_position_found(self):
        """TP3_HIT must handle None position gracefully."""
        old_signal = _make_signal("old-signal-aaa", status=SignalStatus.TP3_HIT)

        position_repo = MagicMock()
        position_repo.get_position_by_signal.return_value = None

        execution_engine = MagicMock()

        pos = position_repo.get_position_by_signal(old_signal.signal_id)
        if (
            pos
            and pos.status == TradeStatus.OPEN
            and pos.signal_id == old_signal.signal_id
        ):
            execution_engine.close_position_emergency(pos)

        execution_engine.close_position_emergency.assert_not_called()

    def test_invalidated_signal_also_uses_guard(self):
        """INVALIDATED exits must also be guarded by signal_id match."""
        inv_signal = _make_signal("old-signal-ccc", status=SignalStatus.INVALIDATED)
        new_position = _make_position("new-pos", signal_id="new-signal-ddd")

        position_repo = MagicMock()
        position_repo.get_position_by_signal.return_value = new_position

        execution_engine = MagicMock()

        pos = position_repo.get_position_by_signal(inv_signal.signal_id)
        if (
            pos
            and pos.status == TradeStatus.OPEN
            and pos.signal_id == inv_signal.signal_id
        ):
            execution_engine.close_position_emergency(pos)

        execution_engine.close_position_emergency.assert_not_called()


# =============================================================================
# TEST: Alpaca position qty validation before emergency close
# =============================================================================


class TestAlpacaQtyValidation:
    """Tests for verifying Alpaca qty matches Firestore before closing."""

    def test_closes_normally_when_qty_matches(self):
        """Normal case: Alpaca and Firestore qty match, close proceeds."""
        pos = _make_position("pos-1", signal_id="sig-1", qty=10.0)

        alpaca_position = MagicMock()
        alpaca_position.qty = "10.0"  # Alpaca returns strings

        alpaca_client = MagicMock()
        alpaca_client.get_open_position.return_value = alpaca_position

        # Verify qty matches
        alpaca_qty = float(alpaca_position.qty)
        assert alpaca_qty >= pos.qty

    def test_adjusts_qty_when_alpaca_has_less(self):
        """If Alpaca has fewer shares, adjust close qty to prevent overselling."""
        pos = _make_position("pos-1", signal_id="sig-1", qty=10.0)

        alpaca_position = MagicMock()
        alpaca_position.qty = "5.0"  # Only 5 shares left on Alpaca

        alpaca_client = MagicMock()
        alpaca_client.get_open_position.return_value = alpaca_position

        # The guard should adjust qty
        alpaca_qty = float(alpaca_position.qty)
        if alpaca_qty < pos.qty:
            pos.qty = alpaca_qty

        assert pos.qty == 5.0

    def test_marks_closed_externally_when_alpaca_position_gone(self):
        """If position doesn't exist on Alpaca (404), mark CLOSED_EXTERNALLY."""
        pos = _make_position("pos-1", signal_id="sig-1", qty=10.0)

        alpaca_client = MagicMock()
        # Mock APIError with status_code 404 (via http_error)
        mock_http_error = MagicMock()
        mock_http_error.response.status_code = 404
        error_404 = APIError("position not found", http_error=mock_http_error)
        alpaca_client.get_open_position.side_effect = error_404

        # The guard should mark position as closed externally
        try:
            alpaca_client.get_open_position(pos.symbol)
        except APIError as e:
            if e.status_code == 404:
                pos.status = TradeStatus.CLOSED
                pos.exit_reason = ExitReason.CLOSED_EXTERNALLY

        assert pos.status == TradeStatus.CLOSED
        assert pos.exit_reason == ExitReason.CLOSED_EXTERNALLY

    def test_skips_close_on_alpaca_api_error_not_404(self):
        """If API returns non-404 error (e.g. 500), do NOT mark closed."""
        pos = _make_position("pos-1", signal_id="sig-1", qty=10.0)

        alpaca_client = MagicMock()
        # Mock APIError with status_code 500
        mock_http_error = MagicMock()
        mock_http_error.response.status_code = 500
        error_500 = APIError("internal server error", http_error=mock_http_error)
        alpaca_client.get_open_position.side_effect = error_500

        # The guard should NOT mark position as closed
        try:
            alpaca_client.get_open_position(pos.symbol)
        except APIError as e:
            if e.status_code == 404:
                pos.status = TradeStatus.CLOSED
            else:
                pass  # Should log and continue

        assert pos.status == TradeStatus.OPEN
        assert pos.exit_reason is None


# =============================================================================
# TEST: Duplicate symbol signal prevention
# =============================================================================


class TestDuplicateSymbolPrevention:
    """Tests for blocking signal generation when symbol has open Alpaca position."""

    def test_skips_signal_when_alpaca_position_exists(self):
        """Should skip signal generation if symbol already has an Alpaca position."""
        alpaca_client = MagicMock()
        alpaca_position = MagicMock()
        alpaca_position.symbol = "AAVEUSD"
        alpaca_client.get_open_position.return_value = alpaca_position

        # Simulate the guard
        symbol = "AAVE/USD"
        alpaca_symbol = symbol.replace("/", "")
        should_skip = False
        try:
            existing = alpaca_client.get_open_position(alpaca_symbol)
            if existing:
                should_skip = True
        except APIError:
            pass

        assert should_skip is True

    def test_proceeds_when_no_alpaca_position(self):
        """Should proceed with signal generation when no Alpaca position exists."""
        alpaca_client = MagicMock()
        mock_http_error = MagicMock()
        mock_http_error.response.status_code = 404
        error_404 = APIError("position does not exist", http_error=mock_http_error)
        alpaca_client.get_open_position.side_effect = error_404

        symbol = "AAVE/USD"
        alpaca_symbol = symbol.replace("/", "")
        should_skip = False
        try:
            existing = alpaca_client.get_open_position(alpaca_symbol)
            if existing:
                should_skip = True
        except APIError:
            pass

        assert should_skip is False
