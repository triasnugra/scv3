import numpy as np
import pandas as pd
import pytest

from scalp import sample
from scalp.features import build_features, to_ns
from scalp.setups import _sweep, build_signal, find_events, scan_signals


def box(n=500, end="2026-03-18 12:00"):
    idx = pd.date_range(end=pd.Timestamp(end, tz="UTC"), periods=n, freq="15min")
    c = np.sin(np.arange(n) * 2 * np.pi / 40) * 1.5 + 102
    o = np.r_[c[0], c[:-1]]
    return pd.DataFrame({"open": o, "high": np.maximum(o, c) + 0.15, "low": np.minimum(o, c) - 0.15,
                         "close": c, "volume": 100.0}, index=idx)


def add_bar(df, o, h, l, c, v):
    t = df.index[-1] + pd.Timedelta("15min")
    out = pd.concat([df, pd.DataFrame({"open": [o], "high": [h], "low": [l], "close": [c], "volume": [v]}, index=[t])])
    out.index = to_ns(out.index)
    return out


def test_sweep_mask_long_and_short(cfg):
    f = pd.DataFrame({"open": [101, 100.2, 100.2], "high": [101.5, 100.9, 100.4], "low": [100.5, 99.8, 100.1],
                      "close": [100.4, 100.7, 100.3]})
    f["atr"] = 0.5
    f["close_pos"] = (f.close - f.low) / (f.high - f.low)
    m, ext = _sweep(f, pd.Series(100.0, index=f.index), "long", cfg)
    assert list(m) == [False, True, False] and ext.iloc[1] == 99.8
    g = pd.DataFrame({"open": [99, 99.8], "high": [99.5, 100.4], "low": [98.9, 99.1], "close": [99.4, 99.2]})
    g["atr"] = 0.5
    g["close_pos"] = (g.close - g.low) / (g.high - g.low)
    ms, _ = _sweep(g, pd.Series(100.0, index=g.index), "short", cfg)
    assert list(ms) == [False, True]


def test_sweep_too_deep_is_breakdown_not_deviation(cfg):
    f = pd.DataFrame({"open": [100.2], "high": [100.9], "low": [97.0], "close": [100.7]})
    f["atr"] = 0.5
    f["close_pos"] = (f.close - f.low) / (f.high - f.low)
    m, _ = _sweep(f, pd.Series(100.0, index=f.index), "long", cfg)
    assert not m.any()


def test_range_deviation_long_end_to_end(cfg):
    df = box()
    rl = build_features(df, cfg).h_rl.iloc[-1]
    df2 = add_bar(df, rl + 0.1, rl + 0.8, rl - 0.35, rl + 0.7, 250.0)
    f = build_features(df2, cfg)
    sg = scan_signals(f, cfg, "XTESTUSDT", len(f) - 1)
    assert len(sg) == 1
    s = sg[0][1]
    assert s.setup == "range_deviation" and s.side == "long"
    assert s.sl < rl - 0.35                      # SL di luar ekstrem sweep
    assert s.entry < s.tp1 < s.tp2
    assert s.rr1 >= cfg.risk.min_rr_tp1 and s.rr2 >= cfg.risk.min_rr_tp2
    assert s.sl_pct <= cfg.risk.max_sl_pct and s.score >= cfg.signal.min_score
    assert s.size["leverage_x"] <= cfg.account.max_leverage


def test_no_signal_in_mid_range_without_sweep(cfg):
    df = box()
    f = build_features(df, cfg)
    assert scan_signals(f, cfg, "XTESTUSDT", 400) == []   # osilasi bersih tanpa sweep -> tidak ada trade


def test_dead_volume_is_rejected(cfg):
    df = box()
    rl = build_features(df, cfg).h_rl.iloc[-1]
    df2 = add_bar(df, rl + 0.1, rl + 0.8, rl - 0.35, rl + 0.7, 5.0)   # volume sangat sepi
    f = build_features(df2, cfg)
    rej = {}
    assert scan_signals(f, cfg, "XTESTUSDT", len(f) - 1, rej) == [] and "volume_mati" in rej


def test_cost_gate_rejects_tight_stops(cfg):
    df = box()
    rl = build_features(df, cfg).h_rl.iloc[-1]
    df2 = add_bar(df, rl + 0.1, rl + 0.8, rl - 0.35, rl + 0.7, 250.0)
    f = build_features(df2, cfg)
    tight = cfg.copy_with(costs={"fee_bps": 60, "slippage_bps": 60})
    rej = {}
    assert scan_signals(f, tight, "XTESTUSDT", len(f) - 1, rej) == [] and "biaya_terlalu_besar" in rej


def test_counter_bias_lowers_score(cfg):
    df = box()
    rl = build_features(df, cfg).h_rl.iloc[-1]
    df2 = add_bar(df, rl + 0.1, rl + 0.8, rl - 0.35, rl + 0.7, 250.0)
    f = build_features(df2, cfg)
    ev = [e for e in find_events(f, cfg, len(f) - 1) if e["setup"] == "range_deviation"][0]
    base = build_signal(f, ev, cfg, "XTESTUSDT")[0].score
    f2 = f.copy(); f2["bias"] = -1
    assert build_signal(f2, ev, cfg, "XTESTUSDT")[0].score == base - 15


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_invariants_on_sample_data(cfg, seed):
    df = sample.make_ohlcv(days=30, seed=seed, end=pd.Timestamp("2026-03-18 12:00", tz="UTC"))
    f = build_features(df, cfg)
    sg = scan_signals(f, cfg, "XTESTUSDT", 400)
    assert len(sg) > 0
    for i, s in sg:
        d = 1 if s.side == "long" else -1
        assert d * (s.entry - s.sl) > 0 and d * (s.tp1 - s.entry) > 0 and d * (s.tp2 - s.tp1) > 0
        assert s.sl_pct <= cfg.risk.max_sl_pct + 1e-9 and s.score >= cfg.signal.min_score
        assert s.rr2 >= cfg.risk.min_rr_tp2 - 1e-6 and 0 <= s.score <= 100
        assert s.entry == pytest.approx(f.close.iloc[i])
