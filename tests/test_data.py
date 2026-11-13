import pandas as pd
import pytest

from scalp import data
from scalp.data import DataError, validate_candles

T0 = 1_760_000_000_000 - (1_760_000_000_000 % 900_000)


def rows(n, step=900_000, t0=T0):
    return [[t0 + i * step, 100 + i, 101 + i, 99 + i, 100.5 + i, 10] for i in range(n)]


class FakeResp:
    def __init__(self, payload): self.p = payload
    def raise_for_status(self): pass
    def json(self): return self.p


class FakeSession:
    def __init__(self, payload_fn): self.fn, self.calls = payload_fn, []
    def get(self, url, params=None, timeout=None):
        self.calls.append((url, dict(params or {})))
        return FakeResp(self.fn(url, params or {}))


def test_binance_parse_and_paginate():
    allrows = rows(1500)
    def fn(url, p):
        end = p.get("endTime")
        sel = [r for r in allrows if end is None or r[0] <= end][-p["limit"]:]
        return [[r[0], str(r[1]), str(r[2]), str(r[3]), str(r[4]), str(r[5]), 0] for r in sel]
    s = FakeSession(fn)
    df = data.BinanceVision(s).fetch("BTCUSDT", "15m", 1200)
    assert len(df) == 1200 and df.index.is_monotonic_increasing and df.index.tz is not None
    assert "data-api.binance.vision" in s.calls[0][0]
    assert str(df.index.dtype) == "datetime64[ns, UTC]"


def test_okx_parse_confirm_and_inst():
    assert data.Okx.inst("PEPEUSDT") == "PEPE-USDT"
    allrows = rows(400)
    def fn(url, p):
        sel = list(reversed(allrows))[:p["limit"]] if "history" not in url else \
            [r for r in reversed(allrows) if r[0] < p["after"]][:p["limit"]]
        out = [[str(r[0]), r[1], r[2], r[3], r[4], r[5], 0, 0, "1"] for r in sel]
        out[0][8] = "0"                       # candle terbaru belum confirm -> harus dibuang
        return {"code": "0", "data": out}
    df = data.Okx(FakeSession(fn)).fetch("BTCUSDT", "15m", 350)
    assert len(df) >= 300 and df.index.is_monotonic_increasing


def test_bybit_error_raises():
    s = FakeSession(lambda u, p: {"retCode": 10001, "retMsg": "bad"})
    with pytest.raises(DataError):
        data.Bybit(s).fetch("BTCUSDT", "15m", 10)


def test_validate_drops_open_candle_and_bad_rows():
    now = pd.Timestamp("2026-01-01 10:07", tz="UTC")
    idx = pd.date_range("2026-01-01 08:00", periods=10, freq="15min", tz="UTC")   # terakhir 10:15? -> 08:00..10:15
    df = pd.DataFrame({"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 1.0}, index=idx)
    df.iloc[2, df.columns.get_loc("high")] = 0.1            # high < low
    out, issues = validate_candles(df, "15m", now)
    assert out.index[-1] + pd.Timedelta("15min") <= now
    assert len(out) < len(df) and any("invalid" in i for i in issues)


def test_validate_rejects_stale():
    now = pd.Timestamp("2026-01-02 10:00", tz="UTC")
    idx = pd.date_range("2026-01-01 00:00", periods=20, freq="15min", tz="UTC")
    df = pd.DataFrame({"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 1.0}, index=idx)
    with pytest.raises(DataError):
        validate_candles(df, "15m", now)


def test_fetch_symbol_falls_back(monkeypatch):
    class Bad(data.Provider):
        name = "bad"
        def fetch(self, *a, **k): raise RuntimeError("451")
    class Good(data.Provider):
        name = "good"
        def fetch(self, symbol, tf, bars):
            return data._frame(rows(600))
    monkeypatch.setitem(data.PROVIDERS, "bad", Bad)
    monkeypatch.setitem(data.PROVIDERS, "good", Good)
    df, src = data.fetch_symbol("BTCUSDT", "15m", 600, ["bad", "good"], session=object())
    assert src == "good" and len(df) == 600
    with pytest.raises(DataError):
        data.fetch_symbol("BTCUSDT", "15m", 600, ["bad"], session=object())
