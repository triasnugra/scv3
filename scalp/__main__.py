"""CLI:  python -m scalp {scan|backtest|build-site|demo}"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .config import ROOT, STATE_DIR, load_config
from .pipeline import build_site, run_backtest_cmd, run_scan


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="scalp", description="Mesin analisis scalping crypto (materi Eliz)")
    ap.add_argument("--config", default=None, help="path config.yaml")
    ap.add_argument("--state-dir", default=str(STATE_DIR), help="folder penyimpanan state (default: state/)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan", help="scan live, perbarui sinyal & pasar")
    s.add_argument("--demo", action="store_true", help="pakai data sintetis (tanpa internet)")
    s.add_argument("--no-notify", action="store_true")
    b = sub.add_parser("backtest", help="backtest walk-forward")
    b.add_argument("--demo", action="store_true")
    b.add_argument("--days", type=int, default=None)
    w = sub.add_parser("build-site", help="rakit situs statis dari folder state/")
    w.add_argument("--out", default=str(ROOT / "public"))
    d = sub.add_parser("demo", help="scan + backtest + situs dengan data sintetis")
    d.add_argument("--out", default=str(ROOT / "public"))
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = load_config(args.config)
    sd = Path(args.state_dir)
    try:
        if args.cmd == "scan":
            r = run_scan(cfg, demo=args.demo, send_notifications=not args.no_notify, state_dir=sd)
            print(f"sinyal baru: {len(r['new'])} | ditutup: {len(r['closed'])}")
        elif args.cmd == "backtest":
            r = run_backtest_cmd(cfg, demo=args.demo, days=args.days, state_dir=sd)
            o = r["stats"]["overall"]
            print(f"backtest: {o['n']} trade | winrate {o['win_rate']}% | avgR {o['avg_r']} | PF {o['profit_factor']}")
        elif args.cmd == "build-site":
            print("situs dirakit di", build_site(Path(args.out), sd))
        elif args.cmd == "demo":
            run_scan(cfg, demo=True, send_notifications=False, state_dir=sd)
            run_backtest_cmd(cfg, demo=True, state_dir=sd)
            print("situs demo dirakit di", build_site(Path(args.out), sd))
    except Exception as e:  # noqa: BLE001
        print(f"GAGAL: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
