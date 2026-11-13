"""Pemuat konfigurasi (YAML) dengan akses titik: cfg.risk.max_sl_pct"""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "config.yaml"
STATE_DIR = ROOT / "state"


class Cfg(dict):
    """dict yang bisa diakses lewat atribut (rekursif)."""

    def __getattr__(self, item: str) -> Any:
        try:
            v = self[item]
        except KeyError as e:  # pragma: no cover
            raise AttributeError(item) from e
        return Cfg(v) if isinstance(v, dict) and not isinstance(v, Cfg) else v

    def copy_with(self, **over) -> "Cfg":
        d = copy.deepcopy(dict(self))
        _merge(d, over)
        return Cfg(d)


def _merge(base: dict, over: dict) -> None:
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v


def load_config(path: str | Path | None = None) -> Cfg:
    p = Path(path) if path else DEFAULT_CONFIG
    with open(p, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return Cfg(raw)


def tf_minutes(tf: str) -> int:
    tf = tf.strip().lower()
    unit = tf[-1]
    n = int(tf[:-1])
    return n * {"m": 1, "h": 60, "d": 1440}[unit]
