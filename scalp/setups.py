"""4 setup scalping yang diturunkan dari materi Eliz.

A. range_deviation   : deviasi (stop run) high/low range H1 lalu reclaim -> scalp balik ke tengah/sisi lawan
B. level_sweep       : stop run PDH/PDL, Monday high/low, PWH/PWL lalu reclaim
C. breakout_retest   : close H1 keluar dari range, retest level, bertahan -> lanjutan
D. squeeze_expansion : squeeze Bollinger lalu ekspansi dengan volume

Prinsip yang dipaksakan di semua setup (kutipan inti Eliz):
  - tunggu trigger/konfirmasi, jangan kejar harga, jangan prediksi
  - tidak ada trade di tengah range (hanya di tepi / saat sweep)
  - invalidasi harus kecil & jelas (SL di luar ekstrem sweep), RR harus layak
  - volume mati = melawan bot -> skor turun / sinyal dibuang
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd

from .config import Cfg
from .trade import cost_r, position_size

SETUP_LABEL = {
    "range_deviation": "Deviasi Range",
    "level_sweep": "Stop Run Level",
    "breakout_retest": "Breakout-Retest",
    "squeeze_expansion": "Squeeze Ekspansi",
}


@dataclass
class Signal:
    id: str
    symbol: str
    setup: str
    side: str
    level_name: str
    ts: str                  # waktu OPEN candle trigger (ISO UTC)
    bar_close: str           # waktu CLOSE candle trigger (saat sinyal valid)
    entry: float
    sl: float
    tp1: float
    tp2: float
    rr1: float
    rr2: float
    tp1_basis: str
    tp2_basis: str
    sl_pct: float
    atr: float
    score: int
    reasons: list = field(default_factory=list)
    size: dict = field(default_factory=dict)
    status: str = "OPEN"
    r: float | None = None
    bars: int = 0
    closed_at: str | None = None
    created_at: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


# ------------------------------------------------------------------ events
def _sweep(f: pd.DataFrame, level: pd.Series, side: str, cfg: Cfg) -> tuple[pd.Series, pd.Series]:
    """Event 'sweep lalu reclaim' terhadap sebuah level. Return (mask, ekstrem sweep)."""
    sw = cfg.sweep
    w = int(sw.window)
    if side == "long":
        ext = f.low.rolling(w, min_periods=1).min()
        depth = (level - ext) / f.atr
        single = (f.low < level) & (f.close > level)
        multi = (f.close.shift(1) <= level) & (f.close > level) & (ext < level)
        shape = (f.close > f.open) & (f.close_pos >= sw.min_close_pos)
    else:
        ext = f.high.rolling(w, min_periods=1).max()
        depth = (ext - level) / f.atr
        single = (f.high > level) & (f.close < level)
        multi = (f.close.shift(1) >= level) & (f.close < level) & (ext > level)
        shape = (f.close < f.open) & (f.close_pos <= 1 - sw.min_close_pos)
    m = (single | multi) & shape & (depth >= sw.min_depth_atr) & (depth <= sw.max_depth_atr)
    return m.fillna(False), ext


def find_events(f: pd.DataFrame, cfg: Cfg, start: int = 0) -> list[dict]:
    """Semua event mentah (belum disaring RR/skor) pada posisi >= start."""
    ev: list[dict] = []
    on = cfg.setups
    has_h = "h_rh" in f.columns

    def add(mask: pd.Series, setup: str, side: str, level_name: str, level: pd.Series, ext: pd.Series):
        pos = np.flatnonzero(mask.to_numpy(bool))
        for i in pos[pos >= start]:
            ev.append({"i": int(i), "setup": setup, "side": side, "level_name": level_name,
                       "level": float(level.iloc[i]), "ext": float(ext.iloc[i])})

    if on.get("range_deviation", True) and has_h:
        for side, col, nm in (("long", "h_rl", "Range Low H1"), ("short", "h_rh", "Range High H1")):
            m, ext = _sweep(f, f[col], side, cfg)
            add(m & f.h_ok, "range_deviation", side, nm, f[col], ext)

    if on.get("level_sweep", True):
        for side, cols in (("long", (("pwl", "PWL"), ("mon_l", "Monday Low"), ("pdl", "PDL"))),
                           ("short", (("pwh", "PWH"), ("mon_h", "Monday High"), ("pdh", "PDH")))):
            for col, nm in cols:
                m, ext = _sweep(f, f[col], side, cfg)
                add(m, "level_sweep", side, nm, f[col], ext)

    if on.get("breakout_retest", True) and has_h:
        bc, sw = cfg.breakout_retest, cfg.sweep
        tol = bc.retest_tol_atr * f.atr
        lvl = f.h_bu_level
        m = ((f.low <= lvl + tol) & (f.close > lvl) & (f.close > f.open) & (f.low >= lvl - sw.max_depth_atr * f.atr)
             & (f.close_pos >= sw.min_close_pos))
        add(m.fillna(False), "breakout_retest", "long", "Breakout H1 (retest)", lvl, np.minimum(f.low, lvl))
        lvl = f.h_bd_level
        m = ((f.high >= lvl - tol) & (f.close < lvl) & (f.close < f.open) & (f.high <= lvl + sw.max_depth_atr * f.atr)
             & (f.close_pos <= 1 - sw.min_close_pos))
        add(m.fillna(False), "breakout_retest", "short", "Breakdown H1 (retest)", lvl, np.maximum(f.high, lvl))

    if on.get("squeeze_expansion", True):
        sq = cfg.squeeze
        first_up = (f.close > f.bb_up) & (f.close.shift(1) <= f.bb_up.shift(1))
        first_dn = (f.close < f.bb_lo) & (f.close.shift(1) >= f.bb_lo.shift(1))
        m = (f.squeeze_recent & first_up & (f.relvol >= sq.min_relvol) & (f.close > f.open) & (f.close_pos >= 0.7))
        add(m.fillna(False), "squeeze_expansion", "long", "BB Upper", f.bb_up, np.minimum(f.low, f.bb_mid))
        m = (f.squeeze_recent & first_dn & (f.relvol >= sq.min_relvol) & (f.close < f.open) & (f.close_pos <= 0.3))
        add(m.fillna(False), "squeeze_expansion", "short", "BB Lower", f.bb_lo, np.maximum(f.high, f.bb_mid))
    return ev


# ------------------------------------------------------------ target & risk
def _targets(row: pd.Series, side: str, entry: float) -> list[tuple[str, float]]:
    c: list[tuple[str, float]] = []

    def put(name, v):
        if v is not None and np.isfinite(v):
            c.append((name, float(v)))

    if bool(row.get("h_ok", False)):
        put("Tengah range", row.get("h_mid"))
        put("Range High" if side == "long" else "Range Low", row.get("h_rh") if side == "long" else row.get("h_rl"))
    names = ("pdh", "pwh", "mon_h") if side == "long" else ("pdl", "pwl", "mon_l")
    pretty = {"pdh": "PDH", "pwh": "PWH", "mon_h": "Monday High", "pdl": "PDL", "pwl": "PWL", "mon_l": "Monday Low"}
    for n in names:
        put(pretty[n], row.get(n))
    if side == "long" and np.isfinite(row.get("h_bu_level", np.nan)):
        put("Measured move", row["h_bu_level"] + row["h_bu_h"])
    if side == "short" and np.isfinite(row.get("h_bd_level", np.nan)):
        put("Measured move", row["h_bd_level"] - row["h_bd_h"])
    d = 1 if side == "long" else -1
    c = [(n, v) for n, v in c if d * (v - entry) > 0]
    c.sort(key=lambda x: d * (x[1] - entry))
    return c


def _pick_tps(cands, side, entry, risk, rc: Cfg):
    d = 1 if side == "long" else -1
    r_of = lambda v: d * (v - entry) / risk  # noqa: E731
    tp1 = next(((n, v) for n, v in cands if rc.min_rr_tp1 <= r_of(v) <= 3.0), None)
    if tp1 is None:
        tp1 = ("1R", entry + d * risk * max(1.0, rc.min_rr_tp1))
    need2 = max(rc.min_rr_tp2, r_of(tp1[1]) + 0.5)
    tp2 = next(((n, v) for n, v in cands if need2 <= r_of(v) <= 5.0), None)
    if tp2 is None:
        tp2 = (f"{need2:.1f}R", entry + d * risk * need2)
    return tp1, tp2


# ------------------------------------------------------------------ build
def build_signal(f: pd.DataFrame, ev: dict, cfg: Cfg, symbol: str) -> tuple[Signal | None, str]:
    """Ubah event jadi Signal lengkap atau (None, alasan_ditolak)."""
    i, side, setup = ev["i"], ev["side"], ev["setup"]
    row = f.iloc[i]
    entry, atr = float(row.close), float(row.atr)
    if not np.isfinite(atr) or atr <= 0 or not np.isfinite(entry) or entry <= 0:
        return None, "data_invalid"
    rc, sc = cfg.risk, cfg.signal
    if not (row.relvol >= sc.min_rel_volume):
        return None, "volume_mati"
    d = 1 if side == "long" else -1
    sl = ev["ext"] - d * rc.sl_buffer_atr * atr
    if d * (entry - sl) < rc.min_sl_atr * atr:
        sl = entry - d * rc.min_sl_atr * atr
    risk = d * (entry - sl)
    sl_pct = risk / entry * 100
    if sl_pct > rc.max_sl_pct:
        return None, "sl_terlalu_lebar"
    if cost_r(entry, risk, cfg) > rc.max_cost_r:
        return None, "biaya_terlalu_besar"
    cands = _targets(row, side, entry)
    tp1, tp2 = _pick_tps(cands, side, entry, risk, rc)
    rr1, rr2 = abs(tp1[1] - entry) / risk, abs(tp2[1] - entry) / risk

    # ------------------ skor konfluensi
    score, why = {"range_deviation": 52, "level_sweep": 50, "breakout_retest": 50, "squeeze_expansion": 45}[setup], []

    def bump(n, txt):
        nonlocal score
        score += n
        why.append(f"{'+' if n >= 0 else ''}{n} {txt}")

    bias = int(row.bias)
    if bias == d:
        bump(10, "searah bias H4")
    elif bias == -d:
        bump(-15, "melawan bias H4")
    if not symbol.startswith("BTC"):
        if int(row.btc_bias) == d:
            bump(5, "searah bias BTC")
        elif int(row.btc_bias) == -d:
            bump(-10, "melawan bias BTC")
    w = int(cfg.sweep.window)
    rv = float(f.relvol.iloc[max(0, i - w + 1): i + 1].max())
    if setup in ("range_deviation", "level_sweep") and rv >= 1.5:
        bump(10, f"volume sweep {rv:.1f}x")
    if setup == "squeeze_expansion" and row.relvol >= 2.0:
        bump(10, f"volume ekspansi {row.relvol:.1f}x")
    strong = row.close_pos >= 0.75 if d == 1 else row.close_pos <= 0.25
    if strong:
        bump(8, "candle trigger kuat")
    if setup in ("range_deviation", "level_sweep"):
        if (d == 1 and row.rsi < 35) or (d == -1 and row.rsi > 65):
            bump(8, f"RSI ekstrem {row.rsi:.0f}")
    elif setup == "breakout_retest":
        if (row.ema20 - row.ema50) * d > 0:
            bump(8, "EMA20/50 searah")
    if rr2 >= 3:
        bump(8, f"RR TP2 {rr2:.1f}")
    if setup == "range_deviation":
        t = row.h_touch_lo if side == "long" else row.h_touch_hi
        if t >= 3:
            bump(5, f"{int(t)}x sentuhan sisi range")
        if row.h_adx > 22:
            bump(-10, "ADX H1 mulai trending")
    if setup == "level_sweep" and bool(row.get("h_ok", False)):
        edge = row.h_rl if side == "long" else row.h_rh
        if abs(ev["level"] - edge) <= 0.3 * row.h_atr:
            bump(6, "level = tepi range H1")
    if row.relvol < 0.8:
        bump(-10, "volume sepi")
    score = int(max(0, min(100, score)))

    ts = f.index[i]
    ltf_delta = f.index[1] - f.index[0] if len(f) > 1 else pd.Timedelta(minutes=15)
    sig = Signal(
        id=f"{symbol}-{setup}-{side}-{ts:%Y%m%d%H%M}", symbol=symbol, setup=setup, side=side,
        level_name=ev["level_name"], ts=ts.isoformat(), bar_close=(ts + ltf_delta).isoformat(),
        entry=entry, sl=float(sl), tp1=float(tp1[1]), tp2=float(tp2[1]), rr1=round(rr1, 2), rr2=round(rr2, 2),
        tp1_basis=tp1[0], tp2_basis=tp2[0], sl_pct=round(sl_pct, 3), atr=atr, score=score, reasons=why,
        size=position_size(entry, sl, cfg),
    )
    return sig, "ok"


def scan_signals(f: pd.DataFrame, cfg: Cfg, symbol: str, start: int = 0,
                 rejects: dict | None = None) -> list[tuple[int, Signal]]:
    """Semua sinyal lolos filter pada posisi >= start, terurut waktu.

    Satu (candle, arah) hanya boleh menghasilkan satu sinyal (skor tertinggi).
    """
    best: dict[tuple[int, str], tuple[Signal, int]] = {}
    for ev in find_events(f, cfg, start):
        sig, why = build_signal(f, ev, cfg, symbol)
        if sig is None:
            if rejects is not None:
                rejects[why] = rejects.get(why, 0) + 1
            continue
        if sig.score < cfg.signal.min_score:
            if rejects is not None:
                rejects["skor_rendah"] = rejects.get("skor_rendah", 0) + 1
            continue
        k = (ev["i"], ev["side"])
        if k not in best or sig.score > best[k][0].score:
            best[k] = (sig, ev["i"])
    return sorted(((i, s) for s, i in best.values()), key=lambda x: (x[0], x[1].side))
