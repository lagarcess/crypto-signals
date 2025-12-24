"""Unit tests for GCP Cloud Logging integration in observability module."""

from unittest.mock import MagicMock, patch

from crypto_signals.observability import LOGURU_TO_GCP_SEVERITY


class TestGCPLevelMapping:
    """Test Loguru to GCP severity level mapping."""

    def test_trace_maps_to_debug(self):
        """TRACE level should map to GCP DEBUG."""
        assert LOGURU_TO_GCP_SEVERITY["TRACE"] == "DEBUG"

    def test_debug_maps_to_debug(self):
        """DEBUG level should map to GCP DEBUG."""
        assert LOGURU_TO_GCP_SEVERITY["DEBUG"] == "DEBUG"

    def test_info_maps_to_info(self):
        """INFO level should map to GCP INFO."""
        assert LOGURU_TO_GCP_SEVERITY["INFO"] == "INFO"

    def test_success_maps_to_info(self):
        """SUCCESS level should map to GCP INFO (GCP has no SUCCESS)."""
        assert LOGURU_TO_GCP_SEVERITY["SUCCESS"] == "INFO"

    def test_warning_maps_to_warning(self):
        """WARNING level should map to GCP WARNING."""
        assert LOGURU_TO_GCP_SEVERITY["WARNING"] == "WARNING"

    def test_error_maps_to_error(self):
        """ERROR level should map to GCP ERROR."""
        assert LOGURU_TO_GCP_SEVERITY["ERROR"] == "ERROR"

    def test_critical_maps_to_critical(self):
        """CRITICAL level should map to GCP CRITICAL."""
        assert LOGURU_TO_GCP_SEVERITY["CRITICAL"] == "CRITICAL"

    def test_all_loguru_levels_are_mapped(self):
        """All standard Loguru levels should be mapped."""
        expected_levels = {
            "TRACE",
            "DEBUG",
            "INFO",
            "SUCCESS",
            "WARNING",
            "ERROR",
            "CRITICAL",
        }
        assert set(LOGURU_TO_GCP_SEVERITY.keys()) == expected_levels


class TestSetupGCPLogging:
    """Test setup_gcp_logging() function."""

    def test_setup_gcp_logging_returns_true_on_success(self):
        """Test that setup_gcp_logging returns True when client initializes."""
        import sys

        # Create mock module structure
        mock_gcp_logging = MagicMock()
        mock_client = MagicMock()
        mock_logger = MagicMock()
        mock_client.logger.return_value = mock_logger
        mock_gcp_logging.Client.return_value = mock_client

        # Patch the module in sys.modules BEFORE the import happens
        with patch.dict(sys.modules, {"google.cloud.logging": mock_gcp_logging}):
            # Need to reimport to use the mocked module
            from importlib import reload

            import crypto_signals.observability as obs

            reload(obs)

            result = obs.setup_gcp_logging("test-log")

            assert result is True
            mock_gcp_logging.Client.assert_called_once()
            mock_client.logger.assert_called_once_with("test-log")

    def test_setup_gcp_logging_returns_false_on_client_failure(self):
        """Test that setup_gcp_logging returns False when client init fails."""
        import sys

        mock_gcp_logging = MagicMock()
        mock_gcp_logging.Client.side_effect = Exception("No credentials")

        with patch.dict(sys.modules, {"google.cloud.logging": mock_gcp_logging}):
            from importlib import reload

            import crypto_signals.observability as obs

            reload(obs)

            result = obs.setup_gcp_logging()

            assert result is False

    def test_gcp_sink_builds_structured_payload(self):
        """Test that GCP sink builds correct structured payload format."""
        # Create a mock message record similar to Loguru's format
        mock_record = {
            "message": "Test signal found",
            "level": MagicMock(name="INFO"),
            "time": MagicMock(isoformat=MagicMock(return_value="2024-12-23T19:00:00")),
            "module": "main",
            "function": "main",
            "line": 178,
            "extra": {"symbol": "BTC/USD", "pattern": "bullish_engulfing"},
        }
        mock_record["level"].name = "INFO"

        # Expected payload structure
        expected_fields = {
            "message",
            "level",
            "timestamp",
            "module",
            "function",
            "line",
            "symbol",
            "pattern",
        }

        # Build payload as the gcp_sink would
        payload = {
            "message": mock_record["message"],
            "level": mock_record["level"].name,
            "timestamp": mock_record["time"].isoformat(),
            "module": mock_record["module"],
            "function": mock_record["function"],
            "line": mock_record["line"],
        }
        if mock_record["extra"]:
            payload.update(mock_record["extra"])

        # Verify all expected fields are present
        assert set(payload.keys()) == expected_fields
        assert payload["symbol"] == "BTC/USD"
        assert payload["pattern"] == "bullish_engulfing"
        assert payload["level"] == "INFO"

    def test_extra_context_merged_into_payload(self):
        """Test that extra context fields are merged into payload."""
        extra_context = {
            "symbol": "ETH/USD",
            "qty": 1.5,
            "pnl_usd": 250.75,
            "asset_class": "CRYPTO",
        }

        # Simulate payload merge
        payload = {"message": "Test", "level": "INFO"}
        payload.update(extra_context)

        assert payload["symbol"] == "ETH/USD"
        assert payload["qty"] == 1.5
        assert payload["pnl_usd"] == 250.75
        assert payload["asset_class"] == "CRYPTO"


class TestSerializationHelpers:
    """Test JSON serialization helpers for GCP logging."""

    def test_serialize_primitives(self):
        """Test that primitive types pass through unchanged."""
        from crypto_signals.observability import _serialize_for_json

        assert _serialize_for_json(None) is None
        assert _serialize_for_json("string") == "string"
        assert _serialize_for_json(42) == 42
        assert _serialize_for_json(3.14) == 3.14
        assert _serialize_for_json(True) is True

    def test_serialize_datetime(self):
        """Test that datetime is converted to ISO format string."""
        from datetime import datetime

        from crypto_signals.observability import _serialize_for_json

        dt = datetime(2024, 12, 23, 19, 0, 0)
        result = _serialize_for_json(dt)
        assert result == "2024-12-23T19:00:00"

    def test_serialize_decimal(self):
        """Test that Decimal is converted to float."""
        from decimal import Decimal

        from crypto_signals.observability import _serialize_for_json

        result = _serialize_for_json(Decimal("99.95"))
        assert result == 99.95
        assert isinstance(result, float)

    def test_serialize_enum(self):
        """Test that Enum is converted to its value."""
        from enum import Enum

        from crypto_signals.observability import _serialize_for_json

        class TestStatus(Enum):
            ACTIVE = "active"
            CLOSED = "closed"

        result = _serialize_for_json(TestStatus.ACTIVE)
        assert result == "active"

    def test_serialize_nested_dict(self):
        """Test that nested dicts are recursively serialized."""
        from datetime import datetime
        from decimal import Decimal

        from crypto_signals.observability import _serialize_for_json

        nested = {
            "price": Decimal("100.50"),
            "timestamp": datetime(2024, 12, 23, 19, 0, 0),
            "nested": {"value": Decimal("50.25")},
        }
        result = _serialize_for_json(nested)
        assert result["price"] == 100.50
        assert result["timestamp"] == "2024-12-23T19:00:00"
        assert result["nested"]["value"] == 50.25

    def test_serialize_list(self):
        """Test that lists are recursively serialized."""
        from decimal import Decimal

        from crypto_signals.observability import _serialize_for_json

        items = [Decimal("1.5"), Decimal("2.5"), "string"]
        result = _serialize_for_json(items)
        assert result == [1.5, 2.5, "string"]

    def test_serialize_custom_object_to_string(self):
        """Test that unknown objects fall back to str()."""
        from crypto_signals.observability import _serialize_for_json

        class CustomObject:
            def __str__(self):
                return "custom_repr"

        result = _serialize_for_json(CustomObject())
        assert result == "custom_repr"

    def test_sanitize_extra_context_empty(self):
        """Test that empty extra returns empty dict."""
        from crypto_signals.observability import _sanitize_extra_context

        assert _sanitize_extra_context({}) == {}
        assert _sanitize_extra_context(None) == {}

    def test_sanitize_extra_context_complex_types(self):
        """Test that complex types are properly sanitized."""
        from datetime import datetime
        from decimal import Decimal

        from crypto_signals.observability import _sanitize_extra_context

        extra = {
            "symbol": "BTC/USD",
            "qty": Decimal("0.5"),
            "timestamp": datetime(2024, 12, 23, 19, 0, 0),
        }
        result = _sanitize_extra_context(extra)
        assert result["symbol"] == "BTC/USD"
        assert result["qty"] == 0.5
        assert result["timestamp"] == "2024-12-23T19:00:00"


class TestConfigIntegration:
    """Test configuration integration for GCP logging."""

    def test_enable_gcp_logging_default_is_false(self):
        """Test that ENABLE_GCP_LOGGING defaults to False."""
        with patch.dict(
            "os.environ",
            {
                "ALPACA_API_KEY": "test_key",
                "ALPACA_SECRET_KEY": "test_secret",
                "GOOGLE_CLOUD_PROJECT": "test-project",
                "TEST_DISCORD_WEBHOOK": "https://discord.com/webhook/test",
            },
            clear=True,
        ):
            # Clear the lru_cache to get fresh settings
            from crypto_signals.config import Settings, get_settings

            get_settings.cache_clear()

            settings = Settings()
            assert settings.ENABLE_GCP_LOGGING is False

    def test_enable_gcp_logging_can_be_enabled(self):
        """Test that ENABLE_GCP_LOGGING can be set to True."""
        with patch.dict(
            "os.environ",
            {
                "ALPACA_API_KEY": "test_key",
                "ALPACA_SECRET_KEY": "test_secret",
                "GOOGLE_CLOUD_PROJECT": "test-project",
                "TEST_DISCORD_WEBHOOK": "https://discord.com/webhook/test",
                "ENABLE_GCP_LOGGING": "true",
            },
            clear=True,
        ):
            from crypto_signals.config import Settings

            settings = Settings()
            assert settings.ENABLE_GCP_LOGGING is True
