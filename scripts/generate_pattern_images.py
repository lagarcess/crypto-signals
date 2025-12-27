"""
Generate candlestick pattern visualizations for documentation.
Uses mplfinance to create professional-looking chart pattern images.
"""

from datetime import datetime, timedelta
from pathlib import Path

import mplfinance as mpf
import pandas as pd

# Output directory
OUTPUT_DIR = Path(__file__).parent.parent / "docs" / "images" / "patterns"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Custom dark style matching our docs
DARK_STYLE = mpf.make_mpf_style(
    base_mpf_style="nightclouds",
    marketcolors=mpf.make_marketcolors(
        up="#00ff88",  # Green for bullish
        down="#ff4444",  # Red for bearish
        edge={"up": "#00ff88", "down": "#ff4444"},
        wick={"up": "#00ff88", "down": "#ff4444"},
        volume={"up": "#00ff88", "down": "#ff4444"},
    ),
    facecolor="#0d1117",  # Dark background
    figcolor="#0d1117",
    gridcolor="#21262d",
    gridstyle="--",
    gridaxis="both",
)


def create_ohlc_data(patterns: list[tuple]) -> pd.DataFrame:
    """Create OHLC DataFrame from pattern tuples (open, high, low, close)."""
    dates = [datetime(2024, 1, 1) + timedelta(days=i) for i in range(len(patterns))]
    data = {
        "Open": [p[0] for p in patterns],
        "High": [p[1] for p in patterns],
        "Low": [p[2] for p in patterns],
        "Close": [p[3] for p in patterns],
        "Volume": [1000000] * len(patterns),
    }
    df = pd.DataFrame(data, index=pd.DatetimeIndex(dates))
    df.index.name = "Date"
    return df


def save_pattern(df: pd.DataFrame, name: str, title: str = "") -> None:
    """Save pattern chart to file."""
    filepath = OUTPUT_DIR / f"{name}.png"
    mpf.plot(
        df,
        type="candle",
        style=DARK_STYLE,
        title=title,
        ylabel="",
        figsize=(4, 3),
        savefig=dict(fname=filepath, dpi=100, bbox_inches="tight", pad_inches=0.1),
        axisoff=True,
    )
    print(f"Saved: {filepath}")


# ============================================================================
# SINGLE CANDLE PATTERNS
# ============================================================================


def generate_hammer():
    """Hammer: small body at top, long lower wick."""
    # (open, high, low, close)
    data = [
        (100, 101, 95, 98),  # Context: bearish
        (98, 99, 92, 94),  # Context: bearish
        (94, 95, 85, 94.5),  # HAMMER: opens low area, long lower wick, closes near high
    ]
    save_pattern(create_ohlc_data(data), "hammer", "Hammer")


def generate_inverted_hammer():
    """Inverted Hammer: small body at bottom, long upper wick."""
    data = [
        (100, 101, 95, 96),  # Context: bearish
        (96, 97, 90, 91),  # Context: bearish
        (91, 99, 90, 92),  # INVERTED HAMMER: long upper wick, small body at bottom
    ]
    save_pattern(create_ohlc_data(data), "inverted_hammer", "Inverted Hammer")


def generate_dragonfly_doji():
    """Dragonfly Doji: open=close=high, long lower shadow."""
    data = [
        (100, 101, 95, 96),  # Context: bearish
        (96, 97, 90, 91),  # Context: bearish
        (95, 95.2, 85, 95),  # DRAGONFLY: open≈close≈high, long lower shadow
    ]
    save_pattern(create_ohlc_data(data), "dragonfly_doji", "Dragonfly Doji")


def generate_belt_hold():
    """Bullish Belt Hold: opens at low, large green body, no lower wick."""
    data = [
        (100, 101, 95, 96),  # Context: bearish
        (96, 97, 90, 91),  # Context: bearish
        (88, 98, 88, 97),  # BELT HOLD: opens at low, closes near high
    ]
    save_pattern(create_ohlc_data(data), "belt_hold", "Bullish Belt Hold")


def generate_marubozu():
    """Bullish Marubozu: full body, no wicks."""
    data = [
        (95, 96, 93, 94),  # Context
        (94, 95, 92, 93),  # Context
        (93, 103, 93, 103),  # MARUBOZU: open=low, close=high
    ]
    save_pattern(create_ohlc_data(data), "marubozu", "Bullish Marubozu")


# ============================================================================
# TWO CANDLE PATTERNS
# ============================================================================


def generate_bullish_engulfing():
    """Bullish Engulfing: green candle completely covers previous red."""
    data = [
        (100, 101, 95, 96),  # Context: bearish
        (96, 97, 92, 93),  # Small red candle
        (92, 100, 91, 99),  # ENGULFING: large green covers the red
    ]
    save_pattern(create_ohlc_data(data), "bullish_engulfing", "Bullish Engulfing")


def generate_bullish_harami():
    """Bullish Harami: small green inside large red."""
    data = [
        (100, 101, 95, 96),  # Context
        (98, 99, 88, 89),  # Large red candle
        (92, 94, 91, 93),  # HARAMI: small green inside the red body
    ]
    save_pattern(create_ohlc_data(data), "bullish_harami", "Bullish Harami")


def generate_bullish_kicker():
    """Bullish Kicker: gap up from red to green."""
    data = [
        (100, 101, 95, 96),  # Context
        (96, 97, 90, 91),  # Red candle
        (98, 108, 97, 107),  # KICKER: gap up, large green
    ]
    save_pattern(create_ohlc_data(data), "bullish_kicker", "Bullish Kicker")


def generate_piercing_line():
    """Piercing Line: green opens below, closes above midpoint of red."""
    data = [
        (100, 101, 95, 96),  # Context
        (98, 99, 88, 89),  # Large red: open 98, close 89, mid=93.5
        (87, 96, 86, 95),  # PIERCING: opens below 89, closes above 93.5
    ]
    save_pattern(create_ohlc_data(data), "piercing_line", "Piercing Line")


def generate_tweezer_bottoms():
    """Tweezer Bottoms: two candles with matching lows."""
    data = [
        (100, 101, 95, 96),  # Context
        (96, 97, 88, 89),  # First candle: low at 88
        (89, 95, 88, 94),  # TWEEZER: matching low at 88, bullish close
    ]
    save_pattern(create_ohlc_data(data), "tweezer_bottoms", "Tweezer Bottoms")


# ============================================================================
# THREE CANDLE PATTERNS
# ============================================================================


def generate_morning_star():
    """Morning Star: large red, small doji, large green."""
    data = [
        (100, 101, 90, 91),  # Large red candle
        (89, 90, 86, 87),  # Small star/doji (gap down)
        (89, 99, 88, 98),  # Large green candle (gap up from star)
    ]
    save_pattern(create_ohlc_data(data), "morning_star", "Morning Star")


def generate_three_white_soldiers():
    """Three White Soldiers: three ascending green candles."""
    data = [
        (90, 95, 89, 94),  # First soldier
        (93, 99, 92, 98),  # Second soldier (opens within previous body)
        (97, 104, 96, 103),  # Third soldier
    ]
    save_pattern(create_ohlc_data(data), "three_white_soldiers", "Three White Soldiers")


def generate_three_inside_up():
    """Three Inside Up: large red, small green harami, green confirmation."""
    data = [
        (100, 101, 88, 89),  # Large red
        (92, 95, 91, 94),  # Small green harami (inside red body)
        (94, 102, 93, 101),  # Green confirmation (closes above red open)
    ]
    save_pattern(create_ohlc_data(data), "three_inside_up", "Three Inside Up")


def generate_rising_three_methods():
    """Rising Three Methods: large green, 3 small reds inside, green breakout."""
    data = [
        (90, 100, 89, 99),  # Large green trend candle
        (98, 99, 94, 95),  # Small red 1 (inside range)
        (95, 96, 92, 93),  # Small red 2
        (93, 94, 91, 92),  # Small red 3
        (92, 105, 91, 104),  # Large green breakout (closes above first candle high)
    ]
    save_pattern(create_ohlc_data(data), "rising_three_methods", "Rising Three Methods")


# ============================================================================
# CHART PATTERNS (Multi-day)
# ============================================================================


def generate_double_bottom():
    """Double Bottom: W-shape pattern."""
    data = [
        (100, 101, 98, 99),  # Decline start
        (99, 100, 94, 95),  # Decline
        (95, 96, 88, 89),  # First bottom
        (89, 95, 88, 94),  # Rally to neckline
        (94, 97, 93, 96),  # Neckline area
        (96, 97, 89, 90),  # Decline to second bottom
        (90, 91, 87, 88),  # Second bottom (≈ first)
        (88, 96, 87, 95),  # Rally
        (95, 102, 94, 101),  # Breakout above neckline
    ]
    save_pattern(create_ohlc_data(data), "double_bottom", "Double Bottom")


def generate_cup_and_handle():
    """Cup and Handle: U-shape with small handle consolidation."""
    data = [
        (100, 101, 98, 99),  # Left rim
        (99, 100, 94, 95),  # Cup descent
        (95, 96, 88, 89),  # Cup bottom
        (89, 92, 88, 91),  # Cup bottom
        (91, 94, 90, 93),  # Cup ascent
        (93, 97, 92, 96),  # Approaching right rim
        (96, 100, 95, 99),  # Right rim (≈ left rim)
        (99, 100, 96, 97),  # Handle: slight pullback
        (97, 98, 95, 96),  # Handle consolidation
        (96, 105, 95, 104),  # Breakout
    ]
    save_pattern(create_ohlc_data(data), "cup_and_handle", "Cup and Handle")


def generate_ascending_triangle():
    """Ascending Triangle: flat resistance, rising support."""
    data = [
        (92, 100, 91, 99),  # Test resistance
        (99, 100, 94, 95),  # Pullback
        (95, 100, 94, 99),  # Test resistance again
        (99, 100, 96, 97),  # Higher low pullback
        (97, 100, 96, 99),  # Test resistance
        (99, 100, 97, 98),  # Higher low
        (98, 105, 97, 104),  # Breakout above resistance
    ]
    save_pattern(create_ohlc_data(data), "ascending_triangle", "Ascending Triangle")


def generate_falling_wedge():
    """Falling Wedge: converging downward trendlines with breakout."""
    data = [
        (100, 101, 95, 96),  # Start high
        (96, 98, 92, 97),  # Lower high, higher low (converging)
        (97, 98, 90, 91),  # Decline
        (91, 94, 88, 93),  # Lower high
        (93, 94, 87, 88),  # Decline
        (88, 91, 86, 90),  # Narrow range (wedge apex)
        (90, 98, 89, 97),  # Breakout above upper trendline
    ]
    save_pattern(create_ohlc_data(data), "falling_wedge", "Falling Wedge")


def generate_bull_flag():
    """Bull Flag: strong rally (flagpole) then slight consolidation (flag)."""
    data = [
        (80, 85, 79, 84),  # Flagpole start
        (84, 92, 83, 91),  # Flagpole rally
        (91, 100, 90, 99),  # Flagpole peak
        (99, 100, 96, 97),  # Flag: slight decline
        (97, 98, 95, 96),  # Flag consolidation
        (96, 97, 94, 95),  # Flag consolidation
        (95, 105, 94, 104),  # Breakout
    ]
    save_pattern(create_ohlc_data(data), "bull_flag", "Bull Flag")


def generate_inverse_head_shoulders():
    """Inverse Head and Shoulders: three troughs with middle lowest."""
    data = [
        (100, 101, 95, 96),  # Decline
        (96, 97, 88, 89),  # Left shoulder low
        (89, 95, 88, 94),  # Rally to neckline
        (94, 95, 90, 91),  # Decline toward head
        (91, 92, 82, 83),  # HEAD (lowest point)
        (83, 92, 82, 91),  # Rally to neckline
        (91, 95, 90, 94),  # Neckline area
        (94, 95, 87, 88),  # Right shoulder low (≈ left shoulder)
        (88, 96, 87, 95),  # Rally
        (95, 103, 94, 102),  # Breakout above neckline
    ]
    save_pattern(create_ohlc_data(data), "inverse_head_shoulders", "Inverse H&S")


def main():
    """Generate all pattern visualizations."""
    print("Generating pattern visualizations...")

    # Single candle
    generate_hammer()
    generate_inverted_hammer()
    generate_dragonfly_doji()
    generate_belt_hold()
    generate_marubozu()

    # Two candle
    generate_bullish_engulfing()
    generate_bullish_harami()
    generate_bullish_kicker()
    generate_piercing_line()
    generate_tweezer_bottoms()

    # Three candle
    generate_morning_star()
    generate_three_white_soldiers()
    generate_three_inside_up()
    generate_rising_three_methods()

    # Chart patterns
    generate_double_bottom()
    generate_cup_and_handle()
    generate_ascending_triangle()
    generate_falling_wedge()
    generate_bull_flag()
    generate_inverse_head_shoulders()

    print(f"\nAll patterns saved to: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
