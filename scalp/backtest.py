"""Backtest walk-forward memakai fungsi sinyal & simulasi yang SAMA dengan mesin live."""
from __future__ import annotations

import pandas as pd

from .config import Cfg, tf_minutes
from .features import build_features
from .setups import scan_signals
from .stats import summarize
from .trade import simulate


def backtest_symbol(df: pd.DataFrame, cfg: Cfg, symbol: str, btc_bias: pd.Series | None = None,
                    rejects: dict | None = None) -> list[dict]:
    f = build_features(df, cfg, btc_bias)
    warm = min(int(cfg.backtest.warmup_bars), max(0, len(f) - 50))
    sigs = scan_signals(f, cfg, symbol, start=warm, rejects=rejects)
    cool = int(cfg.signal.cooldown_bars)
    trades, busy_until, last_side_i = [], -1, {}
    for i, sg in sigs:
        if i <= busy_until:
            continue                                    # satu posisi per simbol
        if i - last_side_i.get(sg.side, -10**9) < cool:
            continue
        bars = f.iloc[i + 1:]
        if len(bars) == 0:
            continue
        res = simulate(sg.side, sg.entry, sg.sl, sg.tp1, sg.tp2, bars, cfg)
        if res["status"] in ("OPEN", "TP1"):            # belum selesai pada akhir data
            continue
        busy_until = i + res["bars"]
        last_side_i[sg.side] = i
        trades.append({"symbol": symbol, "setup": sg.setup, "side": sg.side, "level": sg.level_name,
                       "ts": sg.ts, "exit": res["exit_ts"].isoformat(), "entry": sg.entry, "sl": sg.sl,
                       "tp1": sg.tp1, "tp2": sg.tp2, "rr2": sg.rr2, "score": sg.score,
                       "status": res["status"], "r": res["r"], "bars": res["bars"]})
    return trades


def run_backtest(frames: dict[str, pd.DataFrame], cfg: Cfg, btc_bias: pd.Series | None = None) -> dict:
    trades, rejects = [], {}
    for sym, df in frames.items():
        trades += backtest_symbol(df, cfg, sym, btc_bias, rejects)
    trades.sort(key=lambda t: t["exit"])
    st = summarize([dict(t, closed_at=t["exit"]) for t in trades])
    span = {}
    if frames:
        span = {"from": min(d.index[0] for d in frames.values()).isoformat(),
                "to": max(d.index[-1] for d in frames.values()).isoformat()}
    return {"generated": pd.Timestamp.now(tz="UTC").isoformat(), "span": span, "symbols": list(frames),
            "stats": st, "rejects": rejects, "trades": trades[-int(cfg.backtest.max_trades_listed):],
            "assumptions": [
                f"entry di close candle trigger; biaya {cfg.costs.fee_bps}bps fee + {cfg.costs.slippage_bps}bps slippage per sisi",
                "SL didahulukan bila SL & TP tersentuh di candle yang sama",
                f"TP1 menutup {int(cfg.risk.tp1_fraction * 100)}% lalu SL ke BE; timeout {cfg.risk.max_hold_bars} candle",
                "satu posisi per simbol; tanpa kompounding; hasil dalam satuan R",
            ]}
