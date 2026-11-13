"""Lapisan indikator.

Memakai `pandas_ta_classic` bila terpasang. Jika gagal di-import (atau sebuah
indikator error) otomatis jatuh ke implementasi pandas murni di bawah, sehingga
mesin tidak pernah berhenti hanya karena library indikator bermasalah.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

try:  # pragma: no cover - tergantung lingkungan
    import pandas_ta_classic as ta

    HAS_TA = True
except Exception:  # pragma: no cover
    ta = None
    HAS_TA = False

USE_TA = HAS_TA  # bisa dimatikan oleh tes untuk menguji fallback


def _wilder(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()


def ema(close: pd.Series, n: int) -> pd.Series:
    if USE_TA:
        try:
            r = ta.ema(close, length=n)
            if r is not None:
                return r.astype(float)
        except Exception:
            pass
    return close.ewm(span=n, adjust=False, min_periods=n).mean()


def sma(x: pd.Series, n: int) -> pd.Series:
    return x.rolling(n, min_periods=n).mean()


def atr(high, low, close, n: int = 14) -> pd.Series:
    if USE_TA:
        try:
            r = ta.atr(high, low, close, length=n)
            if r is not None:
                return r.astype(float)
        except Exception:
            pass
    pc = close.shift(1)
    tr = pd.concat([high - low, (high - pc).abs(), (low - pc).abs()], axis=1).max(axis=1)
    return _wilder(tr, n)


def rsi(close, n: int = 14) -> pd.Series:
    if USE_TA:
        try:
            r = ta.rsi(close, length=n)
            if r is not None:
                return r.astype(float)
        except Exception:
            pass
    d = close.diff()
    up = _wilder(d.clip(lower=0), n)
    dn = _wilder((-d).clip(lower=0), n)
    rs = up / dn.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(100.0).where(up.notna())


def adx(high, low, close, n: int = 14) -> pd.Series:
    if USE_TA:
        try:
            r = ta.adx(high, low, close, length=n)
            if r is not None:
                col = [c for c in r.columns if c.startswith("ADX")][0]
                return r[col].astype(float)
        except Exception:
            pass
    up = high.diff()
    dn = -low.diff()
    plus = np.where((up > dn) & (up > 0), up, 0.0)
    minus = np.where((dn > up) & (dn > 0), dn, 0.0)
    pc = close.shift(1)
    tr = pd.concat([high - low, (high - pc).abs(), (low - pc).abs()], axis=1).max(axis=1)
    atr_ = _wilder(tr, n)
    pdi = 100 * _wilder(pd.Series(plus, index=high.index), n) / atr_
    mdi = 100 * _wilder(pd.Series(minus, index=high.index), n) / atr_
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return _wilder(dx.fillna(0), n)


def bbands(close, n: int = 20, std: float = 2.0) -> pd.DataFrame:
    """Kolom: lower, mid, upper, width (=(upper-lower)/mid*100)."""
    if USE_TA:
        try:
            r = ta.bbands(close, length=n, std=std)
            if r is not None:
                def pick(prefix):
                    return r[[c for c in r.columns if c.startswith(prefix)][0]].astype(float)

                return pd.DataFrame(
                    {"lower": pick("BBL"), "mid": pick("BBM"), "upper": pick("BBU"), "width": pick("BBB")}
                )
        except Exception:
            pass
    mid = close.rolling(n, min_periods=n).mean()
    sd = close.rolling(n, min_periods=n).std(ddof=0)
    up, lo = mid + std * sd, mid - std * sd
    return pd.DataFrame({"lower": lo, "mid": mid, "upper": up, "width": (up - lo) / mid * 100})
