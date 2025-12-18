"""Technical analysis indicators wrapper module."""

import pandas as pd
import pandas_ta_classic as ta  # noqa: F401


class TechnicalIndicators:
    """
    Wrapper for technical analysis library (pandas-ta).

    Provides a standardized interface for adding indicators to OHLCV DataFrames.
    """

    @staticmethod
    def add_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
        """
        Add the core 'Confluence Stack' indicators to the DataFrame in-place.

        Indicators added:
        - Trend: EMA (50)
        - Momentum: RSI (14)
        - Volatility: ATR (14)
        - Volume: SMA (20) on Volume

        Args:
            df: DataFrame containing 'open', 'high', 'low', 'close', 'volume' columns.
                Column names should be lowercase.

        Returns:
            pd.DataFrame: The dataframe with added indicator columns.
        """
        if df.empty:
            return df

        # Ensure we work on a copy to avoid SettingWithCopy warnings if a view is passed
        # But usually user might want in-place modification?
        # The signature returns DataFrame, so we'll return the modified one.
        # pandas-ta usually appends to the df provided if append=True.

        # We need to ensure the index is DateTime if possible,
        # but pandas-ta usually handles it.
        # We assume standard lowercase columns based on the project context.

        # 1. Trend: EMA 50
        # Column name defaults to 'EMA_50'
        df.ta.ema(length=50, append=True)

        # 2. Momentum: RSI 14
        # Column name defaults to 'RSI_14'
        df.ta.rsi(length=14, append=True)

        # 3. Volatility: ATR 14
        # Column name defaults to 'ATRr_14' given 'mamode' or just 'ATR_14'
        # basic ta.atr append=True gives 'ATRr_14' usually (True Range based).
        # Let's check standard behavior or just run it.
        # Standard ATR in pandas-ta: df.ta.atr(length=14) -> 'ATRr_14'
        df.ta.atr(length=14, append=True)

        # 4. Volume SMA 20
        # We need to run SMA on the 'volume' column.
        # df.ta.sma(close='volume', length=20, append=True) -> 'SMA_20'
        # But wait, if we have a 'close' column, default sma uses 'close'.
        # We must specify the source series.
        # pandas-ta allows passing the series directly as 'close' argument
        # or just verify if it picks it up.
        # correct usage: df.ta.sma(length=20, close=df['volume'], ...)
        # This will create 'VOL_SMA_20'
        df.ta.sma(length=20, close=df["volume"], prefix="VOL", append=True)

        # Standardize column names if needed or just rely on the generated ones.
        # Generated: 'EMA_50', 'RSI_14', 'ATRr_14', 'VOL_SMA_20'

        return df

    @staticmethod
    def validate_columns(df: pd.DataFrame) -> bool:
        """Check if required base columns exist."""
        required = {"open", "high", "low", "close", "volume"}
        return required.issubset(df.columns)
