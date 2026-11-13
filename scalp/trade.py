"""Simulasi hasil trade (dipakai backtest DAN pelacak sinyal live -> logika identik).

Aturan konservatif:
  * satu candle menyentuh SL dan TP sekaligus -> SL dianggap lebih dulu
  * candle yang menyentuh TP1 tidak dipakai untuk mengecek TP2/BE (urutan tak diketahui)
  * setelah TP1: tp1_fraction posisi ditutup, SL sisa digeser ke entry (BE)
  * lewat max_hold_bars -> ditutup di close candle terakhir (TIMEOUT)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import Cfg

CLOSED = {"WIN", "LOSS", "BE", "TIMEOUT"}


def cost_r(entry: float, risk: float, cfg: Cfg) -> float:
    bps = 2 * (cfg.costs.fee_bps + cfg.costs.slippage_bps)
    return bps / 1e4 * entry / risk if risk > 0 else 0.0


def simulate(side: str, entry: float, sl: float, tp1: float, tp2: float,
             bars: pd.DataFrame, cfg: Cfg) -> dict:
    """bars: candle CLOSED setelah candle trigger (kolom open/high/low/close)."""
    d = 1 if side == "long" else -1
    risk = abs(entry - sl)
    f = float(cfg.risk.tp1_fraction)
    rr1 = abs(tp1 - entry) / risk
    rr2 = abs(tp2 - entry) / risk
    max_hold = int(cfg.risk.max_hold_bars)
    cr = cost_r(entry, risk, cfg)
    stage = 0
    hi, lo, cl = bars["high"].to_numpy(float), bars["low"].to_numpy(float), bars["close"].to_numpy(float)

    def fin(status, r, n):
        return {"status": status, "r": round(float(r - cr), 4), "bars": n, "tp1_hit": stage == 1 or status == "WIN",
                "exit_ts": bars.index[n - 1] if n else None}

    for n in range(1, min(len(bars), max_hold) + 1):
        h, l, c = hi[n - 1], lo[n - 1], cl[n - 1]
        sl_hit = (l <= sl) if d == 1 else (h >= sl)
        tp1_hit = (h >= tp1) if d == 1 else (l <= tp1)
        tp2_hit = (h >= tp2) if d == 1 else (l <= tp2)
        be_hit = (l <= entry) if d == 1 else (h >= entry)
        if stage == 0:
            if sl_hit:
                return fin("LOSS", -1.0, n)
            if tp1_hit:
                stage = 1
        else:
            if be_hit:
                return fin("BE", f * rr1, n)
            if tp2_hit:
                return fin("WIN", f * rr1 + (1 - f) * rr2, n)
        if n == max_hold:
            rem = d * (c - entry) / risk
            r = rem if stage == 0 else f * rr1 + (1 - f) * rem
            return fin("TIMEOUT", r, n)
    return {"status": "TP1" if stage == 1 else "OPEN", "r": None, "bars": min(len(bars), max_hold),
            "tp1_hit": stage == 1, "exit_ts": None}


def position_size(entry: float, sl: float, cfg: Cfg) -> dict:
    a = cfg.account
    dist = abs(entry - sl)
    risk_usd = a.equity_usd * a.risk_pct / 100.0
    qty = risk_usd / dist
    lev = qty * entry / a.equity_usd
    if lev > a.max_leverage:
        qty = a.max_leverage * a.equity_usd / entry
        lev = a.max_leverage
        risk_usd = qty * dist
    return {"qty": float(f"{qty:.6g}"), "notional_usd": round(qty * entry, 2),
            "leverage_x": round(lev, 2), "risk_usd": round(risk_usd, 2)}
