"""Notifikasi opsional (Telegram / Discord) lewat GitHub Secrets. Tanpa secret = dilewati."""
from __future__ import annotations

import logging
import os

import requests

log = logging.getLogger("scalp.notify")


def fmt_price(x: float) -> str:
    if x is None:
        return "-"
    ax = abs(x)
    d = 2 if ax >= 100 else 3 if ax >= 10 else 4 if ax >= 1 else 5 if ax >= 0.1 else 7
    return f"{x:,.{d}f}"


def signal_text(s: dict) -> str:
    icon = "🟢 LONG" if s["side"] == "long" else "🔴 SHORT"
    z = s.get("size", {})
    return (f"{icon} {s['symbol']}  |  {s['setup']}  |  skor {s['score']}\n"
            f"Level: {s['level_name']}\n"
            f"Entry {fmt_price(s['entry'])}  SL {fmt_price(s['sl'])} ({s['sl_pct']:.2f}%)\n"
            f"TP1 {fmt_price(s['tp1'])} ({s['rr1']}R, {s['tp1_basis']})  TP2 {fmt_price(s['tp2'])} ({s['rr2']}R, {s['tp2_basis']})\n"
            f"Saran ukuran: risiko ${z.get('risk_usd')}, lev {z.get('leverage_x')}x\n"
            f"Bukan nasihat finansial. Wajib pasang SL.")


def close_text(s: dict) -> str:
    return f"{'✅' if (s.get('r') or 0) > 0 else '❌'} {s['symbol']} {s['side'].upper()} ditutup: {s['status']}  {s.get('r')}R"


def send(text: str) -> None:
    tok, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if tok and chat:
        try:
            requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                          json={"chat_id": chat, "text": text}, timeout=15).raise_for_status()
        except Exception as e:  # noqa: BLE001 - jangan sampai notifikasi mematikan scan
            log.warning("telegram gagal: %s", type(e).__name__)
    hook = os.getenv("DISCORD_WEBHOOK_URL")
    if hook:
        try:
            requests.post(hook, json={"content": text[:1900]}, timeout=15).raise_for_status()
        except Exception as e:  # noqa: BLE001
            log.warning("discord gagal: %s", type(e).__name__)
