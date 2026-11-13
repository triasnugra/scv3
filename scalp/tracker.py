"""Siklus hidup sinyal: validasi saat dibuat, pembaruan hasil, dedup, cooldown.

Menjawab masalah umum mesin sebelumnya (EXPIRED/INVALID):
  * sinyal yang SUDAH telat (harga lari jauh / sudah kena TP/SL) tidak pernah dipublikasi
  * data tidak valid ditolak di data.validate_candles
  * status dihitung ulang tiap scan dari candle (stateless) -> tidak ada status menggantung
"""
from __future__ import annotations

import pandas as pd

from .config import Cfg, tf_minutes
from .setups import Signal
from .trade import CLOSED, simulate

OPEN_STATES = {"OPEN", "TP1"}


def _bars_after(df: pd.DataFrame, ts_open: str) -> pd.DataFrame:
    return df[df.index > pd.Timestamp(ts_open)]


def refresh_open(sig: dict, df: pd.DataFrame, cfg: Cfg, now: pd.Timestamp) -> dict:
    """Hitung ulang status satu sinyal terbuka dari candle closed."""
    bars = _bars_after(df, sig["ts"])
    if len(bars) == 0:
        return sig
    res = simulate(sig["side"], sig["entry"], sig["sl"], sig["tp1"], sig["tp2"], bars, cfg)
    sig = dict(sig)
    sig["status"] = res["status"]
    sig["bars"] = res["bars"]
    if res["status"] in CLOSED:
        sig["r"] = res["r"]
        sig["closed_at"] = (res["exit_ts"] + pd.Timedelta(minutes=tf_minutes(cfg.timeframes.ltf))).isoformat()
    return sig


def is_fresh(sig: Signal, df: pd.DataFrame, cfg: Cfg) -> tuple[bool, str]:
    """Apakah sinyal (dari candle beberapa bar lalu) masih layak dieksekusi SEKARANG?"""
    bars = _bars_after(df, sig.ts)
    if len(bars) == 0:
        return True, "ok"
    res = simulate(sig.side, sig.entry, sig.sl, sig.tp1, sig.tp2, bars, cfg)
    if res["status"] != "OPEN":
        return False, f"sudah_{res['status'].lower()}"
    risk = abs(sig.entry - sig.sl)
    last = float(bars["close"].iloc[-1])
    d = 1 if sig.side == "long" else -1
    move = d * (last - sig.entry)
    if move > cfg.signal.max_drift_atr * sig.atr:
        return False, "telat_harga_sudah_lari"
    if move < -cfg.signal.max_adverse_r * risk:
        return False, "harga_sudah_mundur"
    return True, "ok"


def accept_new(existing: list[dict], new: list[Signal], frames: dict[str, pd.DataFrame],
               cfg: Cfg, notes: dict | None = None) -> list[Signal]:
    """Saring sinyal baru: dedup id, cooldown, satu sinyal terbuka per simbol, batas total."""
    notes = notes if notes is not None else {}
    ids = {s["id"] for s in existing}
    open_now = [s for s in existing if s["status"] in OPEN_STATES]
    cool = pd.Timedelta(minutes=tf_minutes(cfg.timeframes.ltf) * int(cfg.signal.cooldown_bars))
    out: list[Signal] = []
    for sg in sorted(new, key=lambda s: (-s.score, s.ts)):
        def drop(why):
            notes[why] = notes.get(why, 0) + 1

        if sg.id in ids:
            continue
        if any(o["symbol"] == sg.symbol for o in open_now):
            drop("sudah_ada_sinyal_terbuka")
            continue
        t = pd.Timestamp(sg.ts)
        if any(e["symbol"] == sg.symbol and e["side"] == sg.side and abs(pd.Timestamp(e["ts"]) - t) < cool
               for e in existing + [o.to_dict() for o in out]):
            drop("cooldown")
            continue
        if len(open_now) + len(out) >= cfg.signal.max_open_total:
            drop("batas_sinyal_terbuka")
            continue
        ok, why = is_fresh(sg, frames[sg.symbol], cfg)
        if not ok:
            drop(why)
            continue
        out.append(sg)
        ids.add(sg.id)
    return out
