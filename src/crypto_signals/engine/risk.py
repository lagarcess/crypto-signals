from typing import NamedTuple, Optional

from alpaca.trading.client import TradingClient
from alpaca.trading.models import TradeAccount
from crypto_signals.config import get_settings
from crypto_signals.domain.schemas import AssetClass, Signal
from crypto_signals.market.data_provider import MarketDataProvider
from crypto_signals.repository.firestore import PositionRepository
from loguru import logger


class RiskCheckResult(NamedTuple):
    passed: bool
    reason: Optional[str] = None


class RiskEngine:
    """
    Capital Preservation Layer.

    Enforces pre-trade risk checks:
    1. Buying Power Checks (Reg-T vs Cash)
    2. Sector Exposure Limits (Max Positions)
    3. Daily Account Drawdown Limits
    """

    def __init__(
        self,
        trading_client: TradingClient,
        repository: PositionRepository,
        market_provider: Optional[MarketDataProvider] = None,
    ):
        self.alpaca = trading_client
        self.repo = repository
        self.market_provider = market_provider
        self.settings = get_settings()

    def validate_signal(self, signal: Signal) -> RiskCheckResult:
        """
        Orchestrate all risk checks for a signal.
        order matters: Fail fast on cheapest checks first.
        """
        # 1. Daily Drawdown (Protect Capital First)
        drawdown_check = self.check_daily_drawdown()
        if not drawdown_check.passed:
            return drawdown_check

        # 2. Sector Limits (Portfolio Balance)
        sector_check = self.check_sector_limit(signal.asset_class)
        if not sector_check.passed:
            return sector_check

        # 3. Correlation Risk (Portfolio Diversification) - Expensive (Data Fetch)
        correlation_check = self.check_correlation(signal)
        if not correlation_check.passed:
            return correlation_check

        # 4. Buying Power (Broker Constraints) - Most expensive call (API) if not cached
        # Note: We need an estimated cost. Using RISK_PER_TRADE is a safe floor,
        # but ideally we use (entry * qty). Since we haven't calc'd qty yet,
        # we check if we have at least MIN_ASSET_BP_USD available.
        bp_check = self.check_buying_power(
            signal.asset_class, self.settings.MIN_ASSET_BP_USD
        )
        if not bp_check.passed:
            return bp_check

        return RiskCheckResult(passed=True)

    def check_daily_drawdown(self) -> RiskCheckResult:
        """
        Gate: Daily Account Drawdown.
        Formula: (Equity - LastEquity) / LastEquity
        """
        try:
            account = self.alpaca.get_account()
            if not isinstance(account, TradeAccount):
                logger.warning(
                    "Could not verify drawdown - account object is not a TradeAccount."
                )
                return RiskCheckResult(passed=True)  # Fail open if account fetch fails
            equity = float(account.equity)
            last_equity = float(account.last_equity)

            # Avoid div by zero
            if last_equity == 0:
                return RiskCheckResult(passed=True)

            drawdown_pct = (equity - last_equity) / last_equity

            # Drawdown is negative value. e.g. -0.05 is 5% loss.
            # Limit is positive float e.g. 0.02 (2%)
            # If current drawdown is -0.05, and limit is 0.02 (-0.02 threshold)

            threshold = -abs(self.settings.MAX_DAILY_DRAWDOWN_PCT)
            if drawdown_pct < threshold:
                reason = f"Daily Drawdown Limit Hit: {drawdown_pct:.2%} < {threshold:.2%}"
                logger.warning(reason)
                return RiskCheckResult(passed=False, reason=reason)

            return RiskCheckResult(passed=True)

        except Exception as e:
            logger.error(f"Risk Check Failed (Drawdown): {e}")
            # Fail safe: If we can't verify risk, we block.
            return RiskCheckResult(passed=False, reason=f"Error checking drawdown: {e}")

    def check_sector_limit(self, asset_class: AssetClass) -> RiskCheckResult:
        """
        Gate: Max Open Positions by Asset Class.
        """
        try:
            limit = (
                self.settings.MAX_CRYPTO_POSITIONS
                if asset_class == AssetClass.CRYPTO
                else self.settings.MAX_EQUITY_POSITIONS
            )

            current_count = self.repo.count_open_positions_by_class(asset_class)

            if current_count >= limit:
                reason = (
                    f"Max {asset_class.value} positions reached: {current_count}/{limit}"
                )
                logger.warning(reason)
                return RiskCheckResult(passed=False, reason=reason)

            return RiskCheckResult(passed=True)

        except Exception as e:
            logger.error(f"Risk Check Failed (Sector Cap): {e}")
            return RiskCheckResult(passed=False, reason=f"Error checking sector cap: {e}")

    def check_correlation(self, signal: Signal) -> RiskCheckResult:
        """
        Gate: Correlation Risk.
        Rejects trade if highly correlated (>0.8) with any open position.
        """
        if not self.market_provider:
            return RiskCheckResult(passed=True, reason="Skipped: No Market Provider")

        try:
            open_positions = self.repo.get_open_positions()
            if not open_positions:
                return RiskCheckResult(passed=True)

            # Fetch candidate history
            # Use 90 days for robust correlation
            candidate_bars = self.market_provider.get_daily_bars(
                signal.symbol, signal.asset_class, lookback_days=90
            )

            if "close" in candidate_bars.columns:
                candidate_series = candidate_bars["close"]
            else:
                return RiskCheckResult(
                    passed=False,
                    reason=f"Market data missing close price for {signal.symbol}",
                )

            for pos in open_positions:
                if pos.symbol == signal.symbol:
                    continue  # Skip self

                try:
                    pos_bars = self.market_provider.get_daily_bars(
                        pos.symbol, pos.asset_class, lookback_days=90
                    )
                    if "close" not in pos_bars.columns:
                        logger.warning(
                            f"Market data for existing position {pos.symbol} is missing 'close' price. Blocking trade as a precaution."
                        )
                        return RiskCheckResult(
                            passed=False,
                            reason=f"Could not verify correlation due to missing data for {pos.symbol}",
                        )

                    pos_series = pos_bars["close"]

                    # Pandas corr handles alignment via index (dates)
                    correlation = candidate_series.corr(pos_series)

                    # Check for high correlation (>0.8)
                    # Note: Handle NaN if series don't overlap enough
                    if correlation is not None and correlation > 0.8:
                        reason = (
                            f"Correlation Risk: {signal.symbol} is {correlation:.2f} "
                            f"correlated with existing position {pos.symbol}"
                        )
                        logger.warning(reason)
                        return RiskCheckResult(passed=False, reason=reason)

                except Exception as e:
                    # Fail safe: Block if we can't verify correlation
                    logger.warning(f"Could not calc correlation for {pos.symbol}: {e}")
                    return RiskCheckResult(
                        passed=False,
                        reason=f"Error checking correlation with {pos.symbol}: {e}",
                    )

            return RiskCheckResult(passed=True)

        except Exception as e:
            logger.error(f"Risk Check Failed (Correlation): {e}")
            return RiskCheckResult(
                passed=False, reason=f"Error checking correlation: {e}"
            )

    def check_buying_power(
        self, asset_class: AssetClass, required_amount: float
    ) -> RiskCheckResult:
        """
        Gate: Buying Power.
        Crypto -> non_marginable_buying_power (Cash)
        Equity -> regt_buying_power (Overnight hold safety)
        """
        try:
            account = self.alpaca.get_account()

            if not isinstance(account, TradeAccount):
                logger.warning(
                    "Could not verify buying power - account object is not a TradeAccount."
                )
                return RiskCheckResult(passed=True)
            if asset_class == AssetClass.CRYPTO:
                available = float(account.non_marginable_buying_power)
                bp_type = "Cash (Crypto)"
            else:
                # Use Reg-T for safety against PDT/Overnight holds
                available = float(account.regt_buying_power)
                bp_type = "Reg-T Margin (Equity)"

            if available < required_amount:
                reason = (
                    f"Insufficient Buying Power ({bp_type}): "
                    f"${available:.2f} < ${required_amount:.2f} (Min Req)"
                )
                logger.warning(reason)
                return RiskCheckResult(passed=False, reason=reason)

            return RiskCheckResult(passed=True)

        except Exception as e:
            logger.error(f"Risk Check Failed (Buying Power): {e}")
            return RiskCheckResult(
                passed=False, reason=f"Error checking buying power: {e}"
            )
