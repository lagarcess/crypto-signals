from unittest.mock import MagicMock, patch

from alpaca.trading.client import TradingClient
from crypto_signals.pipelines.trade_archival import TradeArchivalPipeline


@patch("crypto_signals.pipelines.trade_archival.get_settings")
@patch("crypto_signals.pipelines.trade_archival.firestore")
@patch("crypto_signals.pipelines.trade_archival.get_trading_client")
@patch("crypto_signals.pipelines.trade_archival.get_stock_data_client")
@patch("crypto_signals.pipelines.trade_archival.get_crypto_data_client")
@patch("crypto_signals.engine.execution.ExecutionEngine")  # Correct patch path
def test_get_actual_fees_uses_public_api(
    mock_execution_engine_cls,
    mock_get_crypto,
    mock_get_stock,
    mock_get_trading,
    mock_firestore,
    mock_settings,
):
    # Setup
    mock_settings.return_value.ENVIRONMENT = "PROD"
    mock_settings.return_value.GOOGLE_CLOUD_PROJECT = "test-project"

    # Mock Alpaca Client
    mock_alpaca = MagicMock(spec=TradingClient)
    # Ensure _get is NOT present (simulating the issue if we rely on it,
    # but MagicMock might create it unless we allow strict spec.
    # verify=True ensures we only can call existing methods of TradingClient)
    # However, python mocks are flexible.
    # The actual issue is that the real class doesn't have _get.
    # Logic: We want to ensure 'get_account_activities' is called.

    mock_get_trading.return_value = mock_alpaca

    # Initialize functionality
    pipeline = TradeArchivalPipeline()

    # Execute
    # We want to trigger _get_actual_fees
    # It constructs a list of activities.

    # Mocking the return of _request (raw dicts)
    mock_activity_dict = {
        "order_id": "test-order-id",
        "qty": "0.005",
        "price": "100.0",
        "symbol": "BTC/USD",
    }

    # We mock _request which replaces _get
    # Note: The code UNDER TEST must be changed to call _request for this mock to work.
    # checking if we should fail first. The current code calls _get.
    # So if we mock _request, code calls _get -> AttributeError (as expected for Issue 157).
    # If we fix code to call _request, then it proceeds to process activities.

    mock_alpaca._request.return_value = [mock_activity_dict]

    # Trigger method - should pass now
    pipeline._get_actual_fees("test-order-id", "BTC/USD", "buy")

    # Assertions
    mock_alpaca._request.assert_called_once()
    args, kwargs = mock_alpaca._request.call_args
    assert args[0] == "GET"
    assert args[1] == "/account/activities"
    assert kwargs.get("params") == {"activity_types": "CSD,CFEE"}
