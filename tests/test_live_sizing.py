import pytest

from src.live.sizing import (
    SIZING_RULES,
    SizingResult,
    fixed_notional,
    fixed_shares,
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


def test_sizing_rules_registry():
    assert set(SIZING_RULES.keys()) == {"fixed_notional", "fixed_shares"}
    # Each registered callable must accept the shared three-argument prefix.
    r = SIZING_RULES["fixed_notional"](entry_price=0.80, bankroll=10_000, notional=50.0)
    assert r.notional == 50.0
