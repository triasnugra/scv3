"""Statistik performa dari daftar trade (live maupun backtest)."""
from __future__ import annotations

import numpy as np


def _block(rs: list[float]) -> dict:
    n = len(rs)
    if n == 0:
        return {"n": 0, "win_rate": None, "avg_r": None, "total_r": 0.0, "profit_factor": None}
    a = np.array(rs, float)
    gp, gl = a[a > 0].sum(), -a[a < 0].sum()
    return {"n": n, "win_rate": round(float((a > 0).mean() * 100), 1), "avg_r": round(float(a.mean()), 3),
            "total_r": round(float(a.sum()), 2),
            "profit_factor": round(float(gp / gl), 2) if gl > 0 else (None if gp == 0 else 999.0)}


def summarize(trades: list[dict]) -> dict:
    """trades: dict dengan kunci r (float), side, setup, symbol, closed_at/exit (untuk urutan)."""
    done = [t for t in trades if t.get("r") is not None]
    done.sort(key=lambda t: t.get("closed_at") or t.get("exit") or "")
    rs = [t["r"] for t in done]
    eq, peak, mdd, cur = [], 0.0, 0.0, 0.0
    for r in rs:
        cur += r
        peak = max(peak, cur)
        mdd = max(mdd, peak - cur)
        eq.append(round(cur, 3))
    out = {"overall": _block(rs), "max_drawdown_r": round(mdd, 2), "equity_r": eq[-600:]}
    for key in ("side", "setup", "symbol"):
        grp: dict[str, list[float]] = {}
        for t in done:
            grp.setdefault(str(t.get(key)), []).append(t["r"])
        out[f"by_{key}"] = {k: _block(v) for k, v in sorted(grp.items())}
    return out
