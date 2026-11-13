"""Fitur & level: indikator LTF, range H1, bias H4, level harian/mingguan.

Aturan anti look-ahead: nilai HTF (H1/H4) baru terlihat oleh candle LTF setelah
candle HTF tersebut CLOSED (merge_asof backward pada waktu close).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

from . import ind
from .config import Cfg, tf_minutes

NS = "datetime64[ns, UTC]"


def to_ns(idx) -> pd.DatetimeIndex:
    idx = pd.DatetimeIndex(idx)
    idx = idx.tz_localize("UTC") if idx.tz is None else idx.tz_convert("UTC")
    return idx.astype(NS)


def resample_ohlcv(df: pd.DataFrame, tf_from: str, tf_to: str) -> pd.DataFrame:
    """Resample ke TF lebih besar; bucket yang belum lengkap dibuang."""
    m = tf_minutes(tf_to)
    r = df.resample(f"{m}min", label="left", closed="left")
    out = r.agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
    cnt = r["close"].count()
    need = m // tf_minutes(tf_from)
    out = out[cnt >= need].dropna()
    out.index = to_ns(out.index)
    return out


# ---------------------------------------------------------------- H1 (range)
def htf_frame(h: pd.DataFrame, cfg: Cfg) -> pd.DataFrame:
    rc, bc = cfg.range, cfg.breakout_retest
    L = int(rc.lookback_htf)
    o = pd.DataFrame(index=h.index)
    o["atr"] = ind.atr(h.high, h.low, h.close, 14)
    o["adx"] = ind.adx(h.high, h.low, h.close, 14)
    o["rh"] = h.high.rolling(L).max()
    o["rl"] = h.low.rolling(L).min()
    o["mid"] = (o.rh + o.rl) / 2
    o["width_atr"] = (o.rh - o.rl) / o.atr

    n = len(h)
    th = np.zeros(n)
    tl = np.zeros(n)
    if n >= L:
        hi = sliding_window_view(h.high.to_numpy(float), L)
        lo = sliding_window_view(h.low.to_numpy(float), L)
        tol = (rc.touch_atr * o.atr).to_numpy(float)[L - 1:]
        rh = o.rh.to_numpy(float)[L - 1:]
        rl = o.rl.to_numpy(float)[L - 1:]
        th[L - 1:] = (hi >= (rh - tol)[:, None]).sum(axis=1)
        tl[L - 1:] = (lo <= (rl + tol)[:, None]).sum(axis=1)
    o["touch_hi"], o["touch_lo"] = th, tl
    o["ok"] = ((o.touch_hi >= rc.min_touches) & (o.touch_lo >= rc.min_touches)
               & (o.width_atr >= rc.min_width_atr) & (o.width_atr <= rc.max_width_atr)
               & (o.adx <= rc.max_adx)).fillna(False)

    # state-machine breakout (setup C): level breakout bertahan N candle H1
    prev_rh, prev_rl, prev_ok = o.rh.shift(1), o.rl.shift(1), o.ok.shift(1, fill_value=False)
    c, a = h.close.to_numpy(float), o.atr.to_numpy(float)
    K = int(bc.lookback_htf_bars)
    res = {k: np.full(n, np.nan) for k in ("bu_level", "bu_h", "bu_age", "bd_level", "bd_h", "bd_age")}
    st = {"u": None, "d": None}  # (level, height, age)
    prh, prl, pok = prev_rh.to_numpy(float), prev_rl.to_numpy(float), prev_ok.to_numpy(bool)
    for k in range(n):
        if np.isnan(a[k]):
            continue
        for side, key in (("u", "bu"), ("d", "bd")):
            s = st[side]
            if s is not None:
                lvl, ht, age = s
                age += 1
                broke_back = (c[k] < lvl - bc.invalid_atr * a[k]) if side == "u" else (c[k] > lvl + bc.invalid_atr * a[k])
                st[side] = None if (broke_back or age > K) else (lvl, ht, age)
            if pok[k] and not np.isnan(prh[k]):
                if side == "u" and c[k] > prh[k] + 0.1 * a[k]:
                    st[side] = (prh[k], prh[k] - prl[k], 0)
                if side == "d" and c[k] < prl[k] - 0.1 * a[k]:
                    st[side] = (prl[k], prh[k] - prl[k], 0)
            s = st[side]
            if s is not None:
                res[f"{key}_level"][k], res[f"{key}_h"][k], res[f"{key}_age"][k] = s
    for k, v in res.items():
        o[k] = v
    return o


def bias_frame(h4: pd.DataFrame) -> pd.DataFrame:
    o = pd.DataFrame(index=h4.index)
    e20, e50 = ind.ema(h4.close, 20), ind.ema(h4.close, 50)
    o["bias"] = np.where((e20 > e50) & (h4.close > e50), 1, np.where((e20 < e50) & (h4.close < e50), -1, 0))
    o.loc[e50.isna(), "bias"] = 0
    return o


# ------------------------------------------------------------ level hari/pekan
def key_levels(df: pd.DataFrame, ltf: str) -> pd.DataFrame:
    """PDH/PDL (hari UTC sebelumnya), Monday high/low (valid Selasa+), PWH/PWL."""
    idx = df.index
    day = idx.floor("D")
    per_day = (1440 // tf_minutes(ltf))
    g = df.groupby(day).agg(high=("high", "max"), low=("low", "min"), n=("close", "count"))
    g.loc[g.n < per_day * 0.9, ["high", "low"]] = np.nan  # hari tidak lengkap
    pdh, pdl = g.high.shift(1), g.low.shift(1)

    wk = day - pd.to_timedelta(day.weekday, unit="D")
    gw = df.groupby(wk).agg(high=("high", "max"), low=("low", "min"), n=("close", "count"))
    gw.loc[gw.n < per_day * 7 * 0.9, ["high", "low"]] = np.nan
    pwh, pwl = gw.high.shift(1), gw.low.shift(1)

    mon = g[g.index.weekday == 0]
    mon_wk = mon.index  # senin = awal pekan
    mh = pd.Series(mon.high.to_numpy(), index=mon_wk)
    ml = pd.Series(mon.low.to_numpy(), index=mon_wk)

    out = pd.DataFrame(index=idx)
    out["pdh"] = pdh.reindex(day).to_numpy()
    out["pdl"] = pdl.reindex(day).to_numpy()
    out["pwh"] = pwh.reindex(wk).to_numpy()
    out["pwl"] = pwl.reindex(wk).to_numpy()
    valid = day.weekday >= 1
    out["mon_h"] = np.where(valid, mh.reindex(wk).to_numpy(), np.nan)
    out["mon_l"] = np.where(valid, ml.reindex(wk).to_numpy(), np.nan)
    return out


# ------------------------------------------------------------- gabungan
def _asof(left_idx: pd.DatetimeIndex, left_delta: pd.Timedelta, right: pd.DataFrame,
          right_delta: pd.Timedelta, prefix: str) -> pd.DataFrame:
    l = pd.DataFrame({"t": to_ns(left_idx + left_delta)})
    r = right.copy()
    r.insert(0, "avail", to_ns(r.index + right_delta))
    r.columns = ["avail"] + [prefix + c for c in right.columns]
    m = pd.merge_asof(l, r.sort_values("avail"), left_on="t", right_on="avail", direction="backward")
    m.index = left_idx
    return m.drop(columns=["t", "avail"])


def build_features(df: pd.DataFrame, cfg: Cfg, btc_bias: pd.Series | None = None) -> pd.DataFrame:
    ltf, htf, btf = cfg.timeframes.ltf, cfg.timeframes.htf, cfg.timeframes.bias
    df = df.copy()
    df.index = to_ns(df.index)
    f = df.copy()
    f["ema20"], f["ema50"] = ind.ema(df.close, 20), ind.ema(df.close, 50)
    f["atr"] = ind.atr(df.high, df.low, df.close, 14)
    f["rsi"] = ind.rsi(df.close, 14)
    f["relvol"] = df.volume / df.volume.rolling(20, min_periods=10).mean()
    rng = (df.high - df.low).replace(0, np.nan)
    f["close_pos"] = ((df.close - df.low) / rng).fillna(0.5)
    sc = cfg.squeeze
    bb = ind.bbands(df.close, int(sc.bb_len), float(sc.bb_std))
    f["bb_lo"], f["bb_mid"], f["bb_up"], f["bb_w"] = bb.lower, bb.mid, bb.upper, bb.width
    rank = f.bb_w.rolling(int(sc.pct_window), min_periods=50).rank(pct=True)
    f["squeeze_recent"] = (rank <= sc.squeeze_pct).shift(1, fill_value=False).astype(float) \
        .rolling(int(sc.lookback_bars), min_periods=1).max().fillna(0).astype(bool)

    f = f.join(key_levels(df, ltf))

    ld = pd.Timedelta(minutes=tf_minutes(ltf))
    h = resample_ohlcv(df, ltf, htf)
    h4 = resample_ohlcv(df, ltf, btf)
    hf = htf_frame(h, cfg) if len(h) else pd.DataFrame(index=h.index)
    f = f.join(_asof(df.index, ld, hf, pd.Timedelta(minutes=tf_minutes(htf)), "h_"))
    if len(h4):
        f = f.join(_asof(df.index, ld, bias_frame(h4), pd.Timedelta(minutes=tf_minutes(btf)), "b_"))
    else:
        f["b_bias"] = 0
    f = f.rename(columns={"b_bias": "bias"})
    f["bias"] = f["bias"].fillna(0).astype(int)
    f["btc_bias"] = btc_bias.reindex(f.index).ffill().fillna(0).astype(int) if btc_bias is not None else f["bias"]
    if "h_rh" in f:
        f["h_ok"] = f["h_ok"].fillna(False).astype(bool)
        f["rpos"] = (f.close - f.h_rl) / (f.h_rh - f.h_rl)
    return f
