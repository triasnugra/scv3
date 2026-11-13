"""Orkestrasi: scan live, backtest, dan pembuatan situs."""
from __future__ import annotations

import json
import logging
import math
import shutil
from pathlib import Path

import numpy as np
import pandas as pd

from . import __version__, notify, sample
from .backtest import run_backtest
from .config import ROOT, STATE_DIR, Cfg, tf_minutes
from .data import fetch_all, validate_candles
from .features import build_features
from .notify import fmt_price
from .setups import SETUP_LABEL, scan_signals
from .stats import summarize
from .tracker import OPEN_STATES, accept_new, refresh_open

log = logging.getLogger("scalp.pipeline")


# ------------------------------------------------------------------ util
def _clean(o):
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        return None if (math.isnan(o) or math.isinf(o)) else float(o)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, pd.Timestamp):
        return o.isoformat()
    return o


def dump_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_clean(obj), ensure_ascii=False, indent=1), encoding="utf-8")


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


# --------------------------------------------------------------- snapshot
def snapshot(f: pd.DataFrame, symbol: str) -> dict:
    r = f.iloc[-1]
    has = "h_rh" in f.columns and np.isfinite(r.get("h_rh", np.nan))
    if has and bool(r.h_ok):
        regime = "RANGE"
    elif bool(r.squeeze_recent):
        regime = "SQUEEZE"
    elif has and r.h_adx > 25:
        regime = "TREND_UP" if r.bias >= 0 and r.ema20 > r.ema50 else "TREND_DOWN"
    else:
        regime = "CHOP"
    rpos = float(r.rpos) if has and np.isfinite(r.get("rpos", np.nan)) else None
    if regime == "RANGE" and rpos is not None:
        if rpos <= 0.3:
            plan = (f"Dekat Range Low {fmt_price(r.h_rl)}: tunggu sweep di bawahnya lalu reclaim → LONG scalp "
                    f"(target tengah {fmt_price(r.h_mid)}). Jangan kejar harga.")
        elif rpos >= 0.7:
            plan = (f"Dekat Range High {fmt_price(r.h_rh)}: tunggu sweep di atasnya lalu reclaim → SHORT scalp "
                    f"(target tengah {fmt_price(r.h_mid)}). Jangan kejar harga.")
        else:
            plan = (f"Tengah range — tidak ada edge. Tunggu harga ke {fmt_price(r.h_rl)} / {fmt_price(r.h_rh)} "
                    "dan sweep + reclaim.")
    elif regime == "SQUEEZE":
        plan = "Squeeze: tunggu close di luar Bollinger dengan volume ≥1.5x. Sebelum itu jangan masuk."
    elif regime.startswith("TREND"):
        plan = ("Tren naik: cari retest level breakout searah, hindari short tanpa trigger."
                if regime == "TREND_UP" else
                "Tren turun: cari retest level breakdown searah, hindari long tanpa trigger.")
    else:
        plan = "Tidak ada struktur jelas. Lebih baik di luar pasar sampai ada trigger."
    return {
        "symbol": symbol, "price": float(r.close), "time": f.index[-1].isoformat(), "regime": regime,
        "bias_h4": int(r.bias), "bias_btc": int(r.btc_bias), "rsi": float(r.rsi), "relvol": float(r.relvol),
        "adx_h1": float(r.h_adx) if has else None,
        "range_low": float(r.h_rl) if has else None, "range_high": float(r.h_rh) if has else None,
        "range_ok": bool(r.h_ok) if has else False, "range_pos": rpos,
        "pdh": r.pdh, "pdl": r.pdl, "plan": plan,
    }


# -------------------------------------------------------------------- scan
def _frames(cfg: Cfg, demo: bool, now: pd.Timestamp, bars: int):
    if demo:
        raw = sample.make_universe(list(cfg.symbols), days=max(5, bars * 15 // 1440 + 1), now=now)
        frames, rep = {}, {}
        for s, d in raw.items():
            frames[s], iss = validate_candles(d, cfg.timeframes.ltf, now)
            rep[s] = {"ok": True, "source": "DEMO-sintetis", "bars": len(frames[s]), "issues": iss}
        return frames, rep
    return fetch_all(list(cfg.symbols), cfg.timeframes.ltf, bars, list(cfg.exchange_priority), now)


def run_scan(cfg: Cfg, demo: bool = False, send_notifications: bool = True,
             state_dir: Path = STATE_DIR, now: pd.Timestamp | None = None) -> dict:
    now = (now or pd.Timestamp.now(tz="UTC")).tz_convert("UTC")
    frames, report = _frames(cfg, demo, now, int(cfg.candles.live_bars))
    if not frames:
        dump_json(state_dir / "market.json", {"updated": now.isoformat(), "mode": "demo" if demo else "live",
                                              "data_report": report, "markets": []})
        raise RuntimeError("Tidak ada data satu pun: " + json.dumps(report)[:500])

    btc_bias = None
    feats: dict[str, pd.DataFrame] = {}
    if "BTCUSDT" in frames:
        feats["BTCUSDT"] = build_features(frames["BTCUSDT"], cfg)
        btc_bias = feats["BTCUSDT"]["bias"]
    for s, d in frames.items():
        if s not in feats:
            feats[s] = build_features(d, cfg, btc_bias)

    lb = int(cfg.signal.lookback_bars)
    candidates, markets, rejects = [], [], {}
    for s, f in feats.items():
        markets.append(snapshot(f, s))
        candidates += [sg for _, sg in scan_signals(f, cfg, s, start=max(0, len(f) - lb), rejects=rejects)]

    sig_path = state_dir / "signals.json"
    old = load_json(sig_path, {"signals": []})["signals"]
    # perbarui hasil sinyal terbuka; sinyal yang simbolnya gagal diunduh dibiarkan
    refreshed, newly_closed = [], []
    for s in old:
        if s["status"] in OPEN_STATES and s["symbol"] in frames:
            ns = refresh_open(s, frames[s["symbol"]], cfg, now)
            if ns["status"] not in OPEN_STATES:
                newly_closed.append(ns)
            s = ns
        refreshed.append(s)

    notes: dict = {}
    fresh = accept_new(refreshed, candidates, frames, cfg, notes)
    for sg in fresh:
        sg.created_at = now.isoformat()
        sg.status = "OPEN"
    allsig = refreshed + [sg.to_dict() for sg in fresh]
    # sinyal baru yang langsung selesai pada scan yang sama tidak mungkin (is_fresh menolak), aman.
    allsig = allsig[-1000:]
    closed = [s for s in allsig if s["status"] not in OPEN_STATES and s.get("r") is not None]
    dump_json(sig_path, {"updated": now.isoformat(), "mode": "demo" if demo else "live",
                         "signals": allsig, "stats": summarize(closed)})
    dump_json(state_dir / "market.json", {"updated": now.isoformat(), "mode": "demo" if demo else "live",
                                          "data_report": report, "markets": sorted(markets, key=lambda m: m["symbol"]),
                                          "filtered": {**rejects, **{f"tracker:{k}": v for k, v in notes.items()}}})
    dump_json(state_dir / "meta.json", {"version": __version__, "updated": now.isoformat(),
                                        "mode": "demo" if demo else "live",
                                        "ltf": cfg.timeframes.ltf, "htf": cfg.timeframes.htf,
                                        "min_score": cfg.signal.min_score,
                                        "setups": {k: SETUP_LABEL[k] for k in SETUP_LABEL if cfg.setups.get(k, True)}})
    if send_notifications and not demo:
        for sg in fresh:
            notify.send(notify.signal_text(sg.to_dict()))
        for s in newly_closed:
            notify.send(notify.close_text(s))
    log.info("scan selesai: %d simbol, %d sinyal baru, %d ditutup", len(frames), len(fresh), len(newly_closed))
    return {"new": [s.to_dict() for s in fresh], "closed": newly_closed, "report": report}


# ---------------------------------------------------------------- backtest
def run_backtest_cmd(cfg: Cfg, demo: bool = False, days: int | None = None,
                     state_dir: Path = STATE_DIR, now: pd.Timestamp | None = None) -> dict:
    now = (now or pd.Timestamp.now(tz="UTC")).tz_convert("UTC")
    days = int(days or cfg.backtest.days)
    bars = days * 24 * 60 // tf_minutes(cfg.timeframes.ltf) + int(cfg.backtest.warmup_bars)
    frames, report = _frames(cfg, demo, now, bars)
    btc_bias = None
    if "BTCUSDT" in frames:
        btc_bias = build_features(frames["BTCUSDT"], cfg)["bias"]
    out = run_backtest(frames, cfg, btc_bias)
    out["mode"] = "demo" if demo else "live"
    out["days"] = days
    out["data_report"] = report
    dump_json(state_dir / "backtest.json", out)
    return out


# --------------------------------------------------------------------- site
def build_site(out_dir: Path, state_dir: Path = STATE_DIR) -> Path:
    out_dir = Path(out_dir)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    shutil.copytree(ROOT / "site", out_dir)
    data = out_dir / "data"
    data.mkdir(parents=True, exist_ok=True)
    for name in ("signals", "market", "backtest", "meta"):
        p = state_dir / f"{name}.json"
        if p.exists():
            shutil.copy(p, data / p.name)
    (out_dir / ".nojekyll").write_text("")
    return out_dir
