from conftest import bars
from scalp.trade import position_size, simulate


def run(cfg, side, rows, entry=100, sl=99, tp1=101, tp2=102):
    c = cfg.copy_with(costs={"fee_bps": 0, "slippage_bps": 0})
    return simulate(side, entry, sl, tp1, tp2, bars(rows), c)


def test_long_sl_first(cfg):
    r = run(cfg, "long", [(100, 100.5, 98.9, 99.5)])
    assert r["status"] == "LOSS" and r["r"] == -1.0


def test_same_bar_sl_and_tp_is_loss(cfg):
    r = run(cfg, "long", [(100, 102.5, 98.5, 100)])
    assert r["status"] == "LOSS"


def test_tp1_then_tp2(cfg):
    r = run(cfg, "long", [(100, 101.2, 100.1, 101), (101, 102.2, 100.9, 102)])
    assert r["status"] == "WIN" and abs(r["r"] - (0.5 * 1 + 0.5 * 2)) < 1e-9


def test_tp1_then_be(cfg):
    r = run(cfg, "long", [(100, 101.2, 100.1, 101), (101, 101.4, 99.9, 100)])
    assert r["status"] == "BE" and abs(r["r"] - 0.5) < 1e-9


def test_tp1_bar_does_not_check_tp2_or_be(cfg):
    r = run(cfg, "long", [(100, 102.5, 99.5, 101)])  # menyentuh TP1+TP2+BE di satu candle
    assert r["status"] == "TP1"


def test_short_symmetry(cfg):
    r = run(cfg, "short", [(100, 100.2, 98.8, 99), (99, 99.1, 97.8, 98)], entry=100, sl=101, tp1=99, tp2=98)
    assert r["status"] == "WIN" and abs(r["r"] - 1.5) < 1e-9


def test_timeout_closes_at_close(cfg):
    c = cfg.copy_with(risk={"max_hold_bars": 3}, costs={"fee_bps": 0, "slippage_bps": 0})
    rows = [(100, 100.4, 99.6, 100.3)] * 3
    r = simulate("long", 100, 99, 101, 102, bars(rows), c)
    assert r["status"] == "TIMEOUT" and abs(r["r"] - 0.3) < 1e-9


def test_open_when_nothing_happens(cfg):
    assert run(cfg, "long", [(100, 100.4, 99.6, 100.1)])["status"] == "OPEN"


def test_costs_reduce_r(cfg):
    r0 = run(cfg, "long", [(100, 100.5, 98.9, 99.5)])
    r1 = simulate("long", 100, 99, 101, 102, bars([(100, 100.5, 98.9, 99.5)]), cfg)
    assert r1["r"] < r0["r"]


def test_position_size_caps_leverage(cfg):
    z = position_size(100, 99.9, cfg)         # SL sangat rapat -> leverage kena batas
    assert z["leverage_x"] <= cfg.account.max_leverage + 1e-9
    z2 = position_size(100, 99, cfg)
    assert abs(z2["risk_usd"] - cfg.account.equity_usd * cfg.account.risk_pct / 100) < 0.01
