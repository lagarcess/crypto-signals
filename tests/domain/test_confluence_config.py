"""
Tests for Strategy Confluence Config Schema (Issue #232).

Verifies the new ConfluenceConfig model:
- Strict validation for known keys (rsi_period, adx_threshold)
- Sensible defaults
- Extra keys allowed (for experimental parameters)
- Backward compatibility
"""

import pytest
from crypto_signals.domain.schemas import StrategyConfig
from pydantic import ValidationError


class TestConfluenceConfig:
    """Test ConfluenceConfig schema and its integration in StrategyConfig."""

    def test_confluence_config_defaults(self):
        """Ensure defaults are applied for known parameters."""
        config = StrategyConfig(
            strategy_id="test_defaults",
            active=True,
            timeframe="1D",
            asset_class="CRYPTO",
            assets=["BTC/USD"],
            # confluence_config not provided, should use default factory
        )

        assert config.confluence_config.rsi_period == 14
        assert config.confluence_config.rsi_threshold == 70.0
        assert config.confluence_config.adx_period == 14
        assert config.confluence_config.adx_threshold == 25.0
        assert config.confluence_config.volume_threshold == 1.5
        assert config.confluence_config.sma_period == 200

    def test_confluence_config_validation_success(self):
        """Ensure valid parameters are accepted."""
        confluence_data = {
            "rsi_period": 21,
            "rsi_threshold": 65.0,
            "adx_period": 21,
            "adx_threshold": 30.0,
            "volume_threshold": 2.0,
            "sma_period": 100,
            "custom_factor": "experimental",
        }

        config = StrategyConfig(
            strategy_id="test_valid",
            active=True,
            timeframe="1D",
            asset_class="CRYPTO",
            assets=["BTC/USD"],
            confluence_config=confluence_data,
        )

        assert config.confluence_config.rsi_period == 21
        assert config.confluence_config.rsi_threshold == 65.0
        assert config.confluence_config.adx_period == 21
        assert config.confluence_config.adx_threshold == 30.0
        assert config.confluence_config.volume_threshold == 2.0
        assert config.confluence_config.sma_period == 100
        # Accessing extra fields depends on Pydantic config, but accessing via model_dump is safe
        dump = config.model_dump(mode="python")
        assert dump["confluence_config"]["custom_factor"] == "experimental"

    def test_confluence_config_validation_failure_type(self):
        """Ensure invalid types are rejected."""
        confluence_data = {
            "rsi_period": "invalid_string",  # Should be int
        }

        with pytest.raises(ValidationError) as exc_info:
            StrategyConfig(
                strategy_id="test_invalid_type",
                active=True,
                timeframe="1D",
                asset_class="CRYPTO",
                assets=["BTC/USD"],
                confluence_config=confluence_data,
            )

        assert "rsi_period" in str(exc_info.value)
        assert "Input should be a valid integer" in str(exc_info.value)

    def test_confluence_config_validation_failure_constraint(self):
        """Ensure value constraints are enforced (e.g. ge=2)."""
        confluence_data = {
            "rsi_period": 1,  # Should be >= 2
        }

        with pytest.raises(ValidationError) as exc_info:
            StrategyConfig(
                strategy_id="test_invalid_value",
                active=True,
                timeframe="1D",
                asset_class="CRYPTO",
                assets=["BTC/USD"],
                confluence_config=confluence_data,
            )

        assert "rsi_period" in str(exc_info.value)
        assert "Input should be greater than or equal to 2" in str(exc_info.value)

    def test_extra_fields_allowed(self):
        """Ensure unknown fields are allowed (extra='allow')."""
        confluence_data = {"rsi_period": 14, "new_experimental_param": 100}

        config = StrategyConfig(
            strategy_id="test_extra",
            active=True,
            timeframe="1D",
            asset_class="CRYPTO",
            assets=["BTC/USD"],
            confluence_config=confluence_data,
        )

        # Check serialization contains the extra field
        dump = config.model_dump(mode="python")
        assert dump["confluence_config"]["new_experimental_param"] == 100
        assert dump["confluence_config"]["rsi_period"] == 14

    def test_backward_compatibility_empty(self):
        """Ensure empty config loads with defaults."""
        confluence_data = {}

        config = StrategyConfig(
            strategy_id="test_empty",
            active=True,
            timeframe="1D",
            asset_class="CRYPTO",
            assets=["BTC/USD"],
            confluence_config=confluence_data,
        )

        dump = config.model_dump(mode="python")
        assert dump["confluence_config"]["rsi_period"] == 14
        assert dump["confluence_config"]["rsi_threshold"] == 70.0
        assert dump["confluence_config"]["adx_period"] == 14
        assert dump["confluence_config"]["adx_threshold"] == 25.0
        assert dump["confluence_config"]["volume_threshold"] == 1.5
        assert dump["confluence_config"]["sma_period"] == 200
