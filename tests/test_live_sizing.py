import pytest

from src.live.sizing import (
    SIZING_RULES,
    SizingResult,
    fixed_notional,
    fixed_shares,
    kelly,
)


def test_fixed_notional_basic():
    r = fixed_notional(entry_price=0.80, bankroll=10_000, notional=100.0)
    assert isinstance(r, SizingResult)
    assert r.rule == "fixed_notional"
    assert r.notional == 100.0
    assert r.shares == pytest.approx(100.0 / 0.80)
    assert r.params == {"notional": 100.0}


def test_fixed_notional_capped_by_bankroll():
    # Can't spend more than the bankroll.
    r = fixed_notional(entry_price=0.50, bankroll=40, notional=100.0)
    assert r.notional == 40
    assert r.shares == pytest.approx(40 / 0.50)


def test_fixed_notional_zero_bankroll():
    r = fixed_notional(entry_price=0.50, bankroll=0, notional=100.0)
    assert r.shares == 0.0
    assert r.notional == 0.0


def test_fixed_shares_basic():
    r = fixed_shares(entry_price=0.80, bankroll=10_000, shares=125.0)
    assert r.rule == "fixed_shares"
    assert r.shares == 125.0
    assert r.notional == pytest.approx(0.80 * 125.0)
    assert r.params == {"shares": 125.0}


def test_fixed_shares_capped_by_bankroll():
    # Can't buy 1000 shares at $0.50 with $200; cap at bankroll.
    r = fixed_shares(entry_price=0.50, bankroll=200, shares=1000.0)
    assert r.notional == pytest.approx(200)
    assert r.shares == pytest.approx(400.0)  # 200 / 0.50


def test_kelly_positive_edge():
    # p=0.80 (buy No at 80c), true win rate 0.90 → positive edge → positive fraction.
    r = kelly(entry_price=0.80, bankroll=10_000, win_rate=0.90, kelly_fraction=1.0)
    # b = (1 - 0.80) / 0.80 = 0.25
    # f* = (0.90 * 0.25 - 0.10) / 0.25 = (0.225 - 0.10) / 0.25 = 0.5
    # notional = 0.5 * 10000 = 5000
    assert r.rule == "kelly"
    assert r.notional == pytest.approx(5000.0)
    assert r.shares == pytest.approx(5000.0 / 0.80)


def test_kelly_fractional_scales_down():
    r = kelly(entry_price=0.80, bankroll=10_000, win_rate=0.90, kelly_fraction=0.25)
    # quarter-Kelly: 0.25 * 5000 = 1250
    assert r.notional == pytest.approx(1250.0)


def test_kelly_zero_edge_sizes_to_zero():
    # win_rate == entry_price → edge = 0 → no bet.
    r = kelly(entry_price=0.80, bankroll=10_000, win_rate=0.80, kelly_fraction=1.0)
    assert r.shares == 0.0
    assert r.notional == 0.0


def test_kelly_negative_edge_sizes_to_zero():
    # true win rate below entry price → don't bet.
    r = kelly(entry_price=0.80, bankroll=10_000, win_rate=0.60, kelly_fraction=1.0)
    assert r.shares == 0.0
    assert r.notional == 0.0


def test_kelly_zero_bankroll():
    r = kelly(entry_price=0.80, bankroll=0, win_rate=0.90, kelly_fraction=0.25)
    assert r.shares == 0.0


def test_sizing_rules_registry():
    assert set(SIZING_RULES.keys()) == {"fixed_notional", "fixed_shares", "kelly"}
    # Each registered callable must accept the shared three-argument prefix.
    r = SIZING_RULES["fixed_notional"](entry_price=0.80, bankroll=10_000, notional=50.0)
    assert r.notional == 50.0
