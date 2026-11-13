import numpy as np
import pandas as pd

from scalp import sample
from scalp.features import build_features, key_levels, resample_ohlcv

END = pd.Timestamp("2026-03-18 12:00", tz="UTC")   # Rabu


def test_resample_drops_incomplete_buckets():
    df = sample.make_ohlcv(days=3, seed=2, end=END)
    h = resample_ohlcv(df.iloc[1:-1], "15m", "1h")
    assert (h.index.minute == 0).all()
    full = resample_ohlcv(df, "15m", "1h")
    assert len(full) >= len(h)


def test_no_lookahead_htf_values(cfg):
    """Mengubah candle MASA DEPAN tidak boleh mengubah fitur masa lalu."""
    df = sample.make_ohlcv(days=20, seed=3, end=END)
    cut = len(df) - 200
    a = build_features(df.iloc[:cut], cfg)
    b_df = df.copy()
    b_df.iloc[cut:, b_df.columns.get_indexer(["high", "low", "close"])] *= 1.5   # ubah masa depan
    b_df["high"] = np.maximum(b_df.high, b_df.close)
    b = build_features(b_df, cfg).iloc[:cut]
    cols = ["h_rh", "h_rl", "h_ok", "bias", "ema20", "atr", "pdh", "pdl", "h_bu_level", "squeeze_recent", "mon_h"]
    pd.testing.assert_frame_equal(a[cols].iloc[:-8], b[cols].iloc[:-8], check_dtype=False)


def test_htf_bar_visible_only_after_close(cfg):
    df = sample.make_ohlcv(days=10, seed=4, end=END)
    f = build_features(df, cfg)
    h = resample_ohlcv(df, "15m", "1h")
    t = h.index[100]                       # candle H1 buka t, close t+1h
    first_visible = f.index[f["h_rh"].notna() & (f.index >= t)][0]
    # bar LTF yang CLOSE tepat di t+1h adalah bar buka t+45m; sebelum itu candle H1 ini belum dihitung
    bar_before = f.loc[t + pd.Timedelta("30min"), "h_rh"]
    bar_at = f.loc[t + pd.Timedelta("45min"), "h_rh"]
    prev_rh = h.high.rolling(int(cfg.range.lookback_htf)).max()
    assert bar_at == prev_rh.loc[t]
    assert bar_before == prev_rh.loc[t - pd.Timedelta("1h")]


def test_key_levels_prior_day_and_monday():
    df = sample.make_ohlcv(days=16, seed=5, end=END)
    kl = key_levels(df, "15m")
    day = df.index.floor("D")
    d_hi = df.groupby(day).high.max()
    last_day = day[-1]
    prev = last_day - pd.Timedelta("1D")
    assert abs(kl["pdh"].iloc[-1] - d_hi.loc[prev]) < 1e-9
    wk = last_day - pd.Timedelta(days=last_day.weekday())
    assert abs(kl["mon_h"].iloc[-1] - d_hi.loc[wk]) < 1e-9
    monday_rows = kl[day == wk]
    assert monday_rows["mon_h"].isna().all()                 # Monday level belum valid pada hari Senin


def test_fallback_indicators_match_ta_roughly(cfg):
    from scalp import ind
    df = sample.make_ohlcv(days=10, seed=6, end=END)
    if not ind.HAS_TA:
        return
    ind.USE_TA = False
    try:
        a_fb = ind.atr(df.high, df.low, df.close, 14)
        r_fb = ind.rsi(df.close, 14)
        e_fb = ind.ema(df.close, 20)
        x_fb = ind.adx(df.high, df.low, df.close, 14)
        b_fb = ind.bbands(df.close, 20, 2.0)
    finally:
        ind.USE_TA = True
    a, r, e = ind.atr(df.high, df.low, df.close, 14), ind.rsi(df.close, 14), ind.ema(df.close, 20)
    assert (abs(a - a_fb) / a).dropna().tail(300).max() < 0.02
    assert (abs(r - r_fb)).dropna().tail(300).max() < 1.5
    assert (abs(e - e_fb) / e).dropna().tail(300).max() < 1e-3
    assert x_fb.dropna().between(0, 100).all() and b_fb.dropna().shape[0] > 100
