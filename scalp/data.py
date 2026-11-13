"""Pengambilan & validasi data candle dari bursa publik (tanpa API key)."""
from __future__ import annotations

import logging
import time
from typing import Callable

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import tf_minutes

log = logging.getLogger("scalp.data")

OHLCV = ["open", "high", "low", "close", "volume"]


class DataError(Exception):
    pass


def make_session() -> requests.Session:
    s = requests.Session()
    retry = Retry(total=3, backoff_factor=0.8, status_forcelist=(429, 500, 502, 503, 504),
                  allowed_methods=("GET",))
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.headers.update({"User-Agent": "eliz-scalp-engine/1.0"})
    return s


def _frame(rows: list[list], cols_idx=(0, 1, 2, 3, 4, 5)) -> pd.DataFrame:
    """rows: [[ts_ms, o, h, l, c, v], ...] -> DataFrame index UTC (ns)."""
    if not rows:
        return pd.DataFrame(columns=OHLCV)
    arr = [[r[i] for i in cols_idx] for r in rows]
    df = pd.DataFrame(arr, columns=["ts"] + OHLCV)
    df["ts"] = pd.to_numeric(df["ts"], errors="coerce")
    for c in OHLCV:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["ts"])
    df.index = pd.DatetimeIndex(pd.to_datetime(df["ts"].astype("int64"), unit="ms", utc=True)).astype(
        "datetime64[ns, UTC]"
    )
    df.index.name = "time"
    return df[OHLCV]


# ---------------------------------------------------------------- providers
class Provider:
    name = "base"
    page = 1000

    def __init__(self, session: requests.Session | None = None):
        self.s = session or make_session()

    def get_json(self, url: str, params: dict):
        r = self.s.get(url, params=params, timeout=15)
        r.raise_for_status()
        return r.json()

    def fetch_page(self, symbol: str, tf: str, end_ms: int | None) -> pd.DataFrame:  # pragma: no cover
        raise NotImplementedError

    def fetch(self, symbol: str, tf: str, bars: int) -> pd.DataFrame:
        frames, end = [], None
        step = tf_minutes(tf) * 60_000
        for _ in range(40):
            df = self.fetch_page(symbol, tf, end)
            if df.empty:
                break
            frames.append(df)
            if sum(len(f) for f in frames) >= bars:
                break
            new_end = int(df.index.min().value // 1_000_000) - step
            if end is not None and new_end >= end:
                break
            end = new_end
            time.sleep(0.15)
        if not frames:
            return pd.DataFrame(columns=OHLCV)
        out = pd.concat(frames)
        out = out[~out.index.duplicated(keep="last")].sort_index()
        return out.tail(bars)


class BinanceLike(Provider):
    base = "https://api.binance.com"
    name = "binance"
    page = 1000

    def fetch_page(self, symbol, tf, end_ms):
        p = {"symbol": symbol, "interval": tf, "limit": self.page}
        if end_ms:
            p["endTime"] = end_ms
        return _frame(self.get_json(f"{self.base}/api/v3/klines", p))


class BinanceVision(BinanceLike):
    base = "https://data-api.binance.vision"
    name = "binance_vision"


class Okx(Provider):
    name = "okx"
    base = "https://www.okx.com"
    bars = {"1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m", "1h": "1H", "4h": "4H", "1d": "1D"}

    @staticmethod
    def inst(symbol: str) -> str:
        for q in ("USDT", "USDC", "USD"):
            if symbol.endswith(q):
                return f"{symbol[:-len(q)]}-{q}"
        return symbol

    def fetch_page(self, symbol, tf, end_ms):
        p = {"instId": self.inst(symbol), "bar": self.bars[tf]}
        if end_ms is None:
            url, p["limit"] = f"{self.base}/api/v5/market/candles", 300
        else:
            url, p["limit"], p["after"] = f"{self.base}/api/v5/market/history-candles", 100, end_ms + 1
        j = self.get_json(url, p)
        if str(j.get("code", "0")) != "0":
            raise DataError(f"okx error: {j.get('msg')}")
        rows = [r for r in j.get("data", []) if len(r) < 9 or str(r[8]) == "1"]  # hanya candle closed
        return _frame(rows)


class Bybit(Provider):
    name = "bybit"
    base = "https://api.bybit.com"
    page = 1000
    ivl = {"1m": "1", "5m": "5", "15m": "15", "30m": "30", "1h": "60", "4h": "240", "1d": "D"}

    def fetch_page(self, symbol, tf, end_ms):
        p = {"category": "linear", "symbol": symbol, "interval": self.ivl[tf], "limit": self.page}
        if end_ms:
            p["end"] = end_ms
        j = self.get_json(f"{self.base}/v5/market/kline", p)
        if j.get("retCode", 0) != 0:
            raise DataError(f"bybit error: {j.get('retMsg')}")
        return _frame(j.get("result", {}).get("list", []))


PROVIDERS = {c.name: c for c in (BinanceVision, Okx, Bybit, BinanceLike)}


# ------------------------------------------------------------ validasi
def validate_candles(df: pd.DataFrame, tf: str, now: pd.Timestamp | None = None,
                     max_stale_bars: int = 3, drop_open: bool = True) -> tuple[pd.DataFrame, list[str]]:
    """Bersihkan data dan buang yang tidak valid SEBELUM analisis (anti-INVALID).

    - buang NaN / harga <= 0 / high<low / duplikat
    - buang candle terakhir bila belum closed
    - tolak bila data basi (candle terakhir terlalu lama)
    """
    issues: list[str] = []
    if df is None or df.empty:
        raise DataError("data kosong")
    n0 = len(df)
    df = df.copy()
    df = df[~df.index.duplicated(keep="last")].sort_index()
    bad = (df[OHLCV].isna().any(axis=1) | (df[["open", "high", "low", "close"]] <= 0).any(axis=1)
           | (df["high"] < df["low"]) | (df["volume"] < 0))
    if bad.any():
        issues.append(f"{int(bad.sum())} candle invalid dibuang")
        df = df[~bad]
    if df.empty:
        raise DataError("semua candle invalid")
    delta = pd.Timedelta(minutes=tf_minutes(tf))
    now = (now or pd.Timestamp.now(tz="UTC")).tz_convert("UTC")
    if drop_open:
        df = df[df.index + delta <= now]          # buang SEMUA candle yang belum closed
    if df.empty:
        raise DataError("tidak ada candle closed")
    if df.index[-1] + delta * (max_stale_bars + 1) < now:
        raise DataError(f"data basi: candle terakhir {df.index[-1]}")
    gaps = (df.index.to_series().diff().dropna() > delta * 1.5).sum()
    if gaps:
        issues.append(f"{int(gaps)} gap candle")
    if len(df) < n0 * 0.5:
        raise DataError("terlalu banyak candle dibuang")
    return df, issues


def fetch_symbol(symbol: str, tf: str, bars: int, priority: list[str],
                 session: requests.Session | None = None, min_bars: int = 500) -> tuple[pd.DataFrame, str]:
    errors = []
    for name in priority:
        cls = PROVIDERS.get(name)
        if cls is None:
            continue
        try:
            df = cls(session).fetch(symbol, tf, bars)
            if len(df) >= min(min_bars, bars):
                return df, name
            errors.append(f"{name}: hanya {len(df)} candle")
        except Exception as e:  # noqa: BLE001
            errors.append(f"{name}: {type(e).__name__}: {str(e)[:80]}")
    raise DataError(f"{symbol} gagal di semua bursa -> " + " | ".join(errors))


def fetch_all(symbols: list[str], tf: str, bars: int, priority: list[str],
              now: pd.Timestamp | None = None,
              fetcher: Callable[..., tuple[pd.DataFrame, str]] = fetch_symbol):
    """Return (frames, report). report[symbol] = {ok, source, issues/error}."""
    sess = make_session()
    frames, report = {}, {}
    for sym in symbols:
        try:
            raw, src = fetcher(sym, tf, bars, priority, sess)
            df, issues = validate_candles(raw, tf, now)
            frames[sym] = df
            report[sym] = {"ok": True, "source": src, "bars": len(df), "issues": issues}
        except Exception as e:  # noqa: BLE001
            log.warning("%s dilewati: %s", sym, e)
            report[sym] = {"ok": False, "error": str(e)[:300]}
    return frames, report
