
import unittest
from unittest.mock import MagicMock, patch
from alpaca.trading.client import TradingClient
from alpaca.trading.models import Order
from alpaca.trading.enums import OrderSide as AlpacaOrderSide
from alpaca.common.exceptions import APIError

from src.pipelines.trade_archival import TradeArchivalPipeline

class TestTradeArchivalPipeline(unittest.TestCase):
    
    def setUp(self):
        # Patch dependencies before initializing the pipeline
        self.patcher_settings = patch('src.pipelines.trade_archival.settings')
        self.mock_settings = self.patcher_settings.start()
        self.mock_settings.return_value.GOOGLE_CLOUD_PROJECT = "test-project"
        
        self.patcher_firestore = patch('src.pipelines.trade_archival.firestore.Client')
        self.mock_firestore_cls = self.patcher_firestore.start()
        self.mock_firestore_client = self.mock_firestore_cls.return_value
        
        self.patcher_alpaca = patch('src.pipelines.trade_archival.get_trading_client')
        self.mock_get_alpaca = self.patcher_alpaca.start()
        self.mock_alpaca_client = self.mock_get_alpaca.return_value
        
        # Initialize Pipeline
        self.pipeline = TradeArchivalPipeline()

    def tearDown(self):
        self.patcher_settings.stop()
        self.patcher_firestore.stop()
        self.patcher_alpaca.stop()

    def test_init(self):
        """Test pipeline initialization."""
        self.assertEqual(self.pipeline.job_name, "trade_archival")
        self.mock_firestore_cls.assert_called_with(project="test-project")
        self.mock_get_alpaca.assert_called_once()

    def test_extract(self):
        """Test extraction logic (filtering for CLOSED)."""
        # Mock Firestore query stream
        mock_doc = MagicMock()
        mock_doc.to_dict.return_value = {"position_id": "123", "status": "CLOSED"}
        
        self.pipeline.firestore_client.collection.return_value.where.return_value.stream.return_value = [mock_doc]
        
        result = self.pipeline.extract()
        
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["position_id"], "123")
        
        # Verify Query: collection('live_positions').where('status', '==', 'CLOSED')
        self.pipeline.firestore_client.collection.assert_called_with("live_positions")
        self.pipeline.firestore_client.collection().where.assert_called_with(
            field_path="status", op_string="==", value="CLOSED"
        )


    @patch('src.pipelines.trade_archival.time.sleep') 
    def test_transform_success(self, mock_sleep):
        """Test successful enrichment and transformation."""
        # Input Data
        raw_data = [{
            "position_id": "order_123",
            "ds": "2025-01-01",
            "account_id": "acc_1",
            "strategy_id": "strat_A",
            "symbol": "BTC/USD",
            "side": "buy",
            "entry_fill_price": 49000.0, # Deliberately different from Alpaca truth
            "exit_fill_price": 52000.0,
            "entry_time": "2025-01-01T10:00:00+00:00",
            "exit_time": "2025-01-01T11:00:00+00:00",
            "asset_class": "CRYPTO"
        }]
        
        # Mock Alpaca Response
        mock_order = MagicMock(spec=Order)
        mock_order.id = "order_123"
        mock_order.client_order_id = "order_123"
        mock_order.filled_avg_price = Decimal("50000.0") # Truth is 50k
        mock_order.filled_qty = Decimal("1.0")
        # filled_qty aliases to qty in some models but let's be safe as per refactor
        
        self.mock_alpaca_client.get_order_by_client_order_id.return_value = mock_order
        
        # Execute
        transformed = self.pipeline.transform(raw_data)
        
        self.assertEqual(len(transformed), 1)
        trade = transformed[0]
        
        # Validation
        self.assertEqual(trade["trade_id"], "order_123")
        self.assertEqual(trade["entry_price"], 50000.0) # Should use Alpaca Truth
        self.assertEqual(trade["pnl_usd"], 2000.0) # (52000 - 50000) * 1
        self.assertEqual(trade["fees_usd"], 0.0) 
        
        # Ensure Alpaca was called
        self.mock_alpaca_client.get_order_by_client_order_id.assert_called_with("order_123")
        # Ensure sleep was called
        mock_sleep.assert_called_once_with(0.1)

    @patch('src.pipelines.trade_archival.time.sleep')
    def test_transform_skip_not_found(self, mock_sleep):
        """Test that we skip records where Alpaca returns 404/Not Found."""
        raw_data = [{"position_id": "ghost_order"}]
        
        # Mock Side Effect: Raise APIError with 404
        # APIError(error, http_error) requires an object with status_code if it extracts it
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_error = APIError("Order not found", http_error=mock_response)
        
        self.mock_alpaca_client.get_order_by_client_order_id.side_effect = mock_error
        
        transformed = self.pipeline.transform(raw_data)
        
        self.assertEqual(len(transformed), 0) # Should be empty, not error
        self.mock_alpaca_client.get_order_by_client_order_id.assert_called_with("ghost_order")

    def test_cleanup(self):
        """Test batch deletion in cleanup."""
        data = [{"trade_id": "id_1"}, {"trade_id": "id_2"}]
        
        # Mock Batch
        mock_batch = MagicMock()
        self.pipeline.firestore_client.batch.return_value = mock_batch
        
        self.pipeline.cleanup(data)
        
        # Ensure delete called twice
        self.assertEqual(mock_batch.delete.call_count, 2)
        # Ensure commit called (once for < 400 items)
        mock_batch.commit.assert_called_once()


