"""
Account Snapshot Pipeline.

This pipeline runs daily to capture the state of the trading account (Equity, Cash)
and calculate performance metrics (Drawdown, Calmar Ratio) based on the equity curve.

Pattern: "Extract-Transform-Load"
1. Extract: Fetch current Account and Portfolio History (1 Year) from Alpaca.
2. Transform: Calculate Peak Equity, Drawdown %, and Calmar Ratio.
3. Load: Push to BigQuery via BasePipeline (Truncate->Staging->Merge).
"""

import logging
from datetime import datetime, timezone
from typing import Any, List

from alpaca.common.exceptions import APIError

from crypto_signals.config import get_trading_client, settings
from crypto_signals.domain.schemas import StagingAccount
from crypto_signals.pipelines.base import BigQueryPipelineBase

logger = logging.getLogger(__name__)


class AccountSnapshotPipeline(BigQueryPipelineBase):
    """Pipeline to snapshot account state and performance metrics."""

    def __init__(self):
        """Initialize pipeline with configuration."""
        super().__init__(
            job_name="account_snapshot",
            staging_table_id=(
                f"{settings().GOOGLE_CLOUD_PROJECT}.crypto_sentinel.stg_accounts_import"
            ),
            fact_table_id=(
                f"{settings().GOOGLE_CLOUD_PROJECT}.crypto_sentinel.snapshot_accounts"
            ),
            id_column="account_id",
            partition_column="ds",
            schema_model=StagingAccount,
        )

        # Initialize Alpaca Client
        self.alpaca = get_trading_client()

    def extract(self) -> List[Any]:
        """
        Fetch Account Snapshot and History from Alpaca.

        Returns:
            List[dict]: A single-item list containing the combined account data.
                        (Pipeline expects a list).
        """
        logger.info(f"[{self.job_name}] Fetching account data from Alpaca...")

        try:
            # 1. Get Current Account State (Equity, Cash, ID)
            account = self.alpaca.get_account()

            # 2. Get Portfolio History (1 Year) to calculate Peak Equity
            # We need this for Drawdown calculation (Peak - Current / Peak)
            history = self.alpaca.get_portfolio_history(
                period="1A",
                timeframe="1D",
                date_end=None,  # Default to now
                extended_hours=False,
            )

            # Combine into a single raw payload
            raw_data = {"account": account, "history": history}

            return [raw_data]

        except APIError as e:
            logger.error(f"[{self.job_name}] Alpaca API Error: {e}")
            raise

    def transform(self, raw_data: List[Any]) -> List[dict]:
        """
        Calculate metrics and shape data for BigQuery.

        Includes defensive math (Guardrails) for new or empty accounts.

        Args:
            raw_data: List containing the single raw_data dict from extract.

        Returns:
            List[dict]: Transformed data matching StagingAccount schema.
        """
        transformed = []

        for item in raw_data:
            account = item["account"]
            history = item["history"]

            # -----------------------------------------------------------------
            # 1. Parse Basic Account Info
            # -----------------------------------------------------------------
            account_id = str(account.id)
            current_equity = float(account.equity) if account.equity else 0.0
            cash = float(account.cash) if account.cash else 0.0

            # -----------------------------------------------------------------
            # 2. Calculate Drawdown (Current)
            # -----------------------------------------------------------------
            # history.equity is a list of float values
            equity_curve = history.equity or []

            # Peak Equity should include current equity
            all_equities = equity_curve + [current_equity]
            peak_equity = max(all_equities) if all_equities else current_equity

            # Guardrail: If peak <= 0, we can't have a drawdown (div zero)
            if peak_equity > 0:
                # Math: (Peak - Current) / Peak
                drawdown_pct = (peak_equity - current_equity) / peak_equity * 100.0
            else:
                drawdown_pct = 0.0

            # -----------------------------------------------------------------
            # 3. Calculate Calmar Ratio
            # Formula: Annualized Return / Max Drawdown
            # Guardrails:
            #   1. History < 30 days -> 0.0 (Too specific/unstable)
            #   2. Start Equity <= 0 -> 0.0 (Div zero)
            #   3. Max Drawdown == 0 -> 0.0 (Infinite ratio)
            # -----------------------------------------------------------------
            calmar_ratio = 0.0

            # Check 1: History Length
            # Alpaca history returns only business days, so 30 days history is roughly
            # 20-22 biz days? User specified "If history length < 30 days".
            # We'll stick to literal length of the list (days of data).
            if len(equity_curve) >= 30:

                # Check 2: Start Equity
                start_equity = equity_curve[0]
                if start_equity > 0:

                    # Calculate Return
                    (current_equity - start_equity) / start_equity

                    # Annualize Return
                    # ((1 + TotalReturn) ^ (365 / Days)) - 1
                    # Use len(equity_curve) as proxy for trading days ~ 252/year
                    days = len(equity_curve)
                    if days > 0:
                        annualized_return = (
                            (current_equity / start_equity) ** (252 / days)
                        ) - 1
                    else:
                        annualized_return = 0.0

                    # Calculate Max Drawdown (The denominator)
                    # We need the max drawdown seen throughout the period
                    running_peak = 0.0
                    max_dd = 0.0

                    for eq in equity_curve:
                        if eq > running_peak:
                            running_peak = eq

                        if running_peak > 0:
                            dd = (running_peak - eq) / running_peak
                            if dd > max_dd:
                                max_dd = dd

                    # Check current DD
                    current_dd = (
                        (peak_equity - current_equity) / peak_equity
                        if peak_equity > 0
                        else 0
                    )
                    if current_dd > max_dd:
                        max_dd = current_dd

                    # Debug Log
                    # Debug Log
                    logger.info(
                        f"CALMAR DEBUG: Start={start_equity} End={current_equity} "
                        f"Days={len(equity_curve)} AnnRet={annualized_return} "
                        f"MaxDD={max_dd}"
                    )

                    # Check 3: Max Drawdown
                    if max_dd > 0:
                        # Calmar = Annualized Return / Max Drawdown
                        # Note: Return is 0.20 (20%), MaxDD is 0.10 (10%) -> 2.0
                        calmar_ratio = annualized_return / max_dd

            # Clamping Calmar to reasonable limits?
            # Or just let it be. 100 is effectively infinite good.
            # Avoid complex number crash if return is negative in power?
            # Python ** of negative base to float power returns complex.
            # (current / start) must be positive.
            # If current < 0 (bankruptcy), current/start < 0.
            # Equity can assume >= 0.

            # Final Validation
            calmar_ratio = float(calmar_ratio)
            # Handle potential complex numbers if something weird happened
            if isinstance(calmar_ratio, complex):
                calmar_ratio = 0.0

            # -----------------------------------------------------------------
            # 4. Construct Output
            # -----------------------------------------------------------------
            snapshot_date = datetime.now(timezone.utc).date()

            record = StagingAccount(
                ds=snapshot_date,
                account_id=account_id,
                equity=round(current_equity, 2),
                cash=round(cash, 2),
                calmar_ratio=round(calmar_ratio, 2),
                drawdown_pct=round(drawdown_pct, 4),
            )

            transformed.append(record.model_dump(mode="json"))

        return transformed

    def cleanup(self, data: List[Any]) -> None:
        """No cleanup required for Account Snapshot (Read-Only API)."""

    def run(self) -> None:
        """
        Run the pipeline. Overrides Base to skip cleanup validation.

        Since extract() returns raw Alpaca objects that don't match StagingAccount, and
        we don't need cleanup (read-only), we strictly perform ELT: Extract -> Transform
        -> Load -> Merge.
        """
        logger.info(f"[{self.job_name}] Starting pipeline execution...")

        try:
            # 1. Extract
            raw_data = self.extract()
            if not raw_data:
                logger.info(f"[{self.job_name}] No data found. Exiting.")
                return

            # 2. Transform
            transformed_data = self.transform(raw_data)

            # 3. Truncate Staging
            self._truncate_staging()

            # 4. Load to Staging
            self._load_to_staging(transformed_data)

            # 5. Execute Merge
            self._execute_merge()

            # 6. Cleanup - Skipped for Snapshot
            logger.info(f"[{self.job_name}] Pipeline finished successfully.")

        except Exception as e:
            logger.error(f"[{self.job_name}] Pipeline FAILED: {str(e)}", exc_info=True)
            raise
