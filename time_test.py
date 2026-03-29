import time
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from crypto_signals.analysis.patterns import PatternAnalyzer

n = 1000
start_time = datetime(2023, 1, 1)
dates = [start_time + timedelta(days=i) for i in range(n)]

np.random.seed(42)
prices = 100 * np.cumprod(np.random.lognormal(mean=0, sigma=0.01, size=n))
high = prices * (1 + np.abs(np.random.normal(0, 0.005, n)))
low = prices * (1 - np.abs(np.random.normal(0, 0.005, n)))
open_price = prices * (1 + np.random.normal(0, 0.002, n))
close = prices

df = pd.DataFrame(
    {
        "timestamp": dates,
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "volume": np.random.randint(100, 10000, n).astype(float),
    }
)
df.set_index("timestamp", inplace=True)


class PatternAnalyzerOpt(PatternAnalyzer):
    def _calculate_candle_shapes(self):
        o = self.df["open"].to_numpy()
        c = self.df["close"].to_numpy()
        h = self.df["high"].to_numpy()
        l = self.df["low"].to_numpy()

        body_size = np.abs(c - o)
        total_range = h - l

        # Shifts for multi-candle logic
        o1 = np.roll(o, 1)
        o1[0] = np.nan
        c1 = np.roll(c, 1)
        c1[0] = np.nan
        h1 = np.roll(h, 1)
        h1[0] = np.nan
        l1 = np.roll(l, 1)
        l1[0] = np.nan

        o2 = np.roll(o, 2)
        o2[:2] = np.nan
        c2 = np.roll(c, 2)
        c2[:2] = np.nan

        # Use DataFrame.assign which is faster than multiple column assignments
        # Wait, assign is fast if columns don't exist. If they do, they are overwritten.
        # But doing it with kwargs is cleaner.
        self.df = self.df.assign(
            body_size=body_size,
            upper_wick=h - np.maximum(c, o),
            lower_wick=np.minimum(c, o) - l,
            total_range=total_range,
            body_pct=body_size / total_range,
            is_green=c > o,
            is_red=c < o,
            open_1=o1,
            close_1=c1,
            high_1=h1,
            low_1=l1,
            open_2=o2,
            close_2=c2,
        )


print("Original:")
analyzer = PatternAnalyzer(df)
start = time.perf_counter()
for _ in range(1000):
    analyzer._calculate_candle_shapes()
print(f"{(time.perf_counter() - start) * 1000:.3f} ms")

print("Optimized:")
analyzer_opt = PatternAnalyzerOpt(df)
start = time.perf_counter()
for _ in range(1000):
    analyzer_opt._calculate_candle_shapes()
print(f"{(time.perf_counter() - start) * 1000:.3f} ms")
