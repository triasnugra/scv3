import json

import pandas as pd

from conftest import bars
from scalp import sample
from scalp.backtest import run_backtest
from scalp.pipeline import build_site, run_backtest_cmd, run_scan
from scalp.setups import Signal
from scalp.tracker import accept_new, is_fresh, refresh_open


def mk(side="long", ts="2026-01-01 00:00", entry=100, sl=99, tp1=101, tp2=102, sym="BTCUSDT", score=70):
    t = pd.Timestamp(ts, tz="UTC")
    return Signal(id=f"{sym}-x-{side}-{t:%H%M}", symbol=sym, setup="range_deviation", side=side, level_name="L",
                  ts=t.isoformat(), bar_close=(t + pd.Timedelta("15min")).isoformat(), entry=entry, sl=sl,
                  tp1=tp1, tp2=tp2, rr1=1, rr2=2, tp1_basis="a", tp2_basis="b", sl_pct=1.0, atr=0.5, score=score)


def test_fresh_rejects_already_stopped_or_drifted(cfg):
    s = mk()
    df = bars([(100, 100.2, 99.9, 100.0), (100, 100.3, 98.5, 99.0)])          # bar ke-2 kena SL
    assert is_fresh(s, df, cfg) == (False, "sudah_loss")
    df = bars([(100, 100.3, 99.9, 100.0), (100, 100.9, 100.0, 100.8)])        # lari 0.8 > 0.35*ATR
    assert is_fresh(s, df, cfg) == (False, "telat_harga_sudah_lari")
    df = bars([(100, 100.1, 99.4, 99.45), (99.5, 99.6, 99.4, 99.45)])         # mundur 0.55R
    assert is_fresh(s, df, cfg) == (False, "harga_sudah_mundur")
    df = bars([(100, 100.1, 99.8, 100.05), (100, 100.1, 99.9, 100.05)])
    assert is_fresh(s, df, cfg)[0] is True


def test_accept_new_dedup_cooldown_and_limits(cfg):
    df = bars([(100, 100.1, 99.9, 100.0)] * 6)
    frames = {"BTCUSDT": df, "ETHUSDT": df}
    a = mk()
    assert accept_new([a.to_dict()], [a], frames, cfg) == []                     # id sama
    b = mk(ts="2026-01-01 00:15")
    assert accept_new([], [a, b], frames, cfg) == [a] or len(accept_new([], [a, b], frames, cfg)) == 1   # satu per simbol
    opened = a.to_dict()
    c = mk(sym="ETHUSDT")
    out = accept_new([opened], [c], frames, cfg)
    assert out == [c]
    cfg2 = cfg.copy_with(signal={"max_open_total": 1})
    assert accept_new([opened], [c], frames, cfg2) == []


def test_refresh_open_closes_on_tp2(cfg):
    s = mk().to_dict()
    df = bars([(100, 100.2, 99.9, 100.0), (100, 101.2, 100.1, 101.0), (101, 102.3, 100.9, 102.0)])
    out = refresh_open(s, df, cfg, pd.Timestamp.now(tz="UTC"))
    assert out["status"] == "WIN" and out["r"] > 0 and out["closed_at"]


def test_demo_scan_backtest_site(cfg, tmp_path):
    c = cfg.copy_with(backtest={"days": 20})
    now = pd.Timestamp("2026-03-18 12:07", tz="UTC")
    run_scan(c, demo=True, send_notifications=False, state_dir=tmp_path, now=now)
    for n in ("signals", "market", "meta"):
        assert (tmp_path / f"{n}.json").exists()
    m = json.loads((tmp_path / "market.json").read_text())
    assert len(m["markets"]) == len(c.symbols) and all(v["ok"] for v in m["data_report"].values())
    bt = run_backtest_cmd(c, demo=True, state_dir=tmp_path, now=now)
    assert {"stats", "trades", "assumptions", "rejects"} <= set(bt)
    for t in bt["trades"]:
        assert t["status"] in ("WIN", "LOSS", "BE", "TIMEOUT")
    out = build_site(tmp_path / "pub", tmp_path)
    assert (out / "index.html").exists() and (out / "data" / "backtest.json").exists()
    # idempoten: scan kedua pada waktu sama tidak menggandakan sinyal
    r2 = run_scan(c, demo=True, send_notifications=False, state_dir=tmp_path, now=now)
    sig = json.loads((tmp_path / "signals.json").read_text())["signals"]
    assert len({s["id"] for s in sig}) == len(sig) and r2["new"] == []


def test_backtest_no_overlap_per_symbol(cfg):
    df = sample.make_ohlcv(days=40, seed=9, end=pd.Timestamp("2026-03-18 12:00", tz="UTC"))
    out = run_backtest({"AAAUSDT": df}, cfg)
    tr = out["trades"]
    for a, b in zip(tr, tr[1:]):
        assert pd.Timestamp(b["ts"]) >= pd.Timestamp(a["exit"]) - pd.Timedelta("15min")
