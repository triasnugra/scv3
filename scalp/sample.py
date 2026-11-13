"""Generator data sintetis (mode --demo & tes). BUKAN data pasar: hanya untuk uji alur."""
from __future__ import annotations

import numpy as np
import pandas as pd


def make_ohlcv(days: int = 30, seed: int = 1, start_price: float = 100.0, tf_min: int = 15,
               end: pd.Timestamp | None = None) -> pd.DataFrame:
    """Rezim bergantian: range (dengan deviasi/sweep di tepi) dan tren."""
    rng = np.random.default_rng(seed)
    n = days * 24 * 60 // tf_min
    end = (end or pd.Timestamp.now(tz="UTC")).floor(f"{tf_min}min")
    idx = pd.date_range(end=end, periods=n, freq=f"{tf_min}min", tz="UTC")
    closes = np.empty(n)
    hi_w = np.zeros(n)
    lo_w = np.zeros(n)
    p, i = start_price, 0
    while i < n:
        seg = int(rng.integers(120, 400))
        kind = rng.choice(["range", "range", "up", "down"])
        vol = p * rng.uniform(0.0012, 0.0022)
        center, half = p, p * rng.uniform(0.012, 0.03)
        drift = {"range": 0.0, "up": vol * 0.12, "down": -vol * 0.12}[kind]
        for j in range(i, min(n, i + seg)):
            if kind == "range":
                p += (center - p) * 0.06 + rng.normal(0, vol)
                if p > center + half:
                    p = center + half - abs(rng.normal(0, vol))
                if p < center - half:
                    p = center - half + abs(rng.normal(0, vol))
                if rng.random() < 0.035:                       # deviasi: sumbu panjang menembus tepi
                    if p > center + half * 0.7:
                        hi_w[j] = abs(rng.normal(0, vol * 3.2)) + vol
                    elif p < center - half * 0.7:
                        lo_w[j] = abs(rng.normal(0, vol * 3.2)) + vol
            else:
                p += drift + rng.normal(0, vol)
            closes[j] = p
        i += seg
    opens = np.r_[closes[0], closes[:-1]]
    body_hi, body_lo = np.maximum(opens, closes), np.minimum(opens, closes)
    noise = np.abs(rng.normal(0, 1, n)) * (closes * 0.0007)
    high = body_hi + noise + hi_w
    low = body_lo - np.abs(rng.normal(0, 1, n)) * (closes * 0.0007) - lo_w
    volume = rng.lognormal(3, 0.5, n) * (1 + 2.5 * ((hi_w > 0) | (lo_w > 0)))
    df = pd.DataFrame({"open": opens, "high": high, "low": low, "close": closes, "volume": volume}, index=idx)
    df.index = pd.DatetimeIndex(df.index).astype("datetime64[ns, UTC]")
    df.index.name = "time"
    return df


def make_universe(symbols: list[str], days: int = 30, now: pd.Timestamp | None = None) -> dict[str, pd.DataFrame]:
    now = (now or pd.Timestamp.now(tz="UTC")).floor("15min")
    out = {}
    for k, s in enumerate(symbols):
        out[s] = make_ohlcv(days=days, seed=100 + k, start_price=[60000, 3000, 150, 0.6, 0.2][k % 5], end=now)
    return out
