from datetime import datetime, timedelta, timezone

from src.live.bankroll import BankrollState
from src.live.favorites import Favorite
from src.live.signals import enumerate_candidates
from src.storage.models import Market, Position


NOW = datetime(2026, 4, 21, 12, tzinfo=timezone.utc)

SNAP = Favorite(
    label="snapshot_24__earliest_created",
    strategy_name="snapshot",
    params={"offset_hours": 24},
    selection_mode="earliest_created",
    starting_bankroll=1000.0,
    shares_per_trade=10.0,
)
THR = Favorite(
    label="threshold_0.3__earliest_created",
    strategy_name="threshold",
    params={"threshold": 0.3},
    selection_mode="earliest_created",
    starting_bankroll=1000.0,
    shares_per_trade=10.0,
)


def _full_bankroll(fav: Favorite) -> BankrollState:
    return BankrollState(
        strategy=fav.label,
        starting=fav.starting_bankroll,
        locked=0.0,
        realized_pnl=0.0,
        available=fav.starting_bankroll,
        open_positions=0,
        closed_positions=0,
    )


def _add_market(session, mid, *, created_at, question=None, category="geopolitical"):
    m = Market(
        id=mid,
        question=question or f"Will {mid}?",
        category=category,
        no_token_id=f"tok_{mid}",
        created_at=created_at,
    )
    session.add(m)
    return m


def _add_position(session, market_id, strategy):
    pos = Position(
        market_id=market_id, strategy=strategy, executor="paper", status="open",
        entry_price=0.5, entry_timestamp=NOW - timedelta(hours=1),
        size_shares=10.0, size_notional=5.0,
        sizing_rule="fixed_shares", sizing_params_json="{}",
    )
    session.add(pos)
    return pos


def test_snapshot_ready_when_in_window(session):
    _add_market(session, "m", created_at=NOW - timedelta(hours=24))
    session.commit()
    bankrolls = {SNAP.label: _full_bankroll(SNAP)}
    cands = enumerate_candidates(
        session, [SNAP], now=NOW, tolerance_hours=12,
        quote_fn=lambda _t: 0.55, bankrolls=bankrolls,
    )
    by_state = {c.state for c in cands}
    assert "ready" in by_state
    ready = [c for c in cands if c.state == "ready"][0]
    assert ready.market.id == "m"
    assert ready.quote == 0.55


def test_snapshot_waiting_when_too_young(session):
    _add_market(session, "young", created_at=NOW - timedelta(hours=4))
    session.commit()
    bankrolls = {SNAP.label: _full_bankroll(SNAP)}
    cands = enumerate_candidates(
        session, [SNAP], now=NOW, tolerance_hours=12,
        quote_fn=lambda _t: 0.55, bankrolls=bankrolls,
    )
    c = [c for c in cands if c.market.id == "young"][0]
    assert c.state == "waiting"
    assert c.eta_hours is not None and c.eta_hours > 0


def test_snapshot_expired_when_too_old(session):
    _add_market(session, "old", created_at=NOW - timedelta(hours=50))
    session.commit()
    bankrolls = {SNAP.label: _full_bankroll(SNAP)}
    cands = enumerate_candidates(
        session, [SNAP], now=NOW, tolerance_hours=12,
        quote_fn=lambda _t: 0.55, bankrolls=bankrolls,
    )
    c = [c for c in cands if c.market.id == "old"][0]
    assert c.state == "expired"


def test_snapshot_entered_when_position_exists(session):
    m = _add_market(session, "has", created_at=NOW - timedelta(hours=24))
    session.flush()
    _add_position(session, m.id, SNAP.label)
    session.commit()
    bankrolls = {SNAP.label: _full_bankroll(SNAP)}
    cands = enumerate_candidates(
        session, [SNAP], now=NOW, tolerance_hours=12,
        quote_fn=lambda _t: 0.55, bankrolls=bankrolls,
    )
    c = [c for c in cands if c.market.id == "has"][0]
    assert c.state == "entered"


def test_threshold_ready_when_quote_below(session):
    _add_market(session, "dip", created_at=NOW - timedelta(days=2))
    session.commit()
    bankrolls = {THR.label: _full_bankroll(THR)}
    cands = enumerate_candidates(
        session, [THR], now=NOW, tolerance_hours=12,
        quote_fn=lambda _t: 0.25, bankrolls=bankrolls,
    )
    c = [c for c in cands if c.market.id == "dip"][0]
    assert c.state == "ready"
    assert c.target == 0.3


def test_threshold_watching_when_quote_above(session):
    _add_market(session, "hi", created_at=NOW - timedelta(days=2))
    session.commit()
    bankrolls = {THR.label: _full_bankroll(THR)}
    cands = enumerate_candidates(
        session, [THR], now=NOW, tolerance_hours=12,
        quote_fn=lambda _t: 0.6, bankrolls=bankrolls,
    )
    c = [c for c in cands if c.market.id == "hi"][0]
    assert c.state == "watching"
    assert c.quote == 0.6


def test_blocked_by_bankroll_flag(session):
    _add_market(session, "dip", created_at=NOW - timedelta(days=2))
    session.commit()
    # Bankroll too low to afford 10 shares at 0.25 = 2.5 dollars
    bankrolls = {
        THR.label: BankrollState(
            strategy=THR.label, starting=1.0, locked=0.0, realized_pnl=0.0,
            available=1.0, open_positions=0, closed_positions=0,
        )
    }
    cands = enumerate_candidates(
        session, [THR], now=NOW, tolerance_hours=12,
        quote_fn=lambda _t: 0.25, bankrolls=bankrolls,
    )
    c = [c for c in cands if c.market.id == "dip"][0]
    assert c.state == "ready"
    assert c.blocked_by_bankroll is True


def test_cross_strategy_same_market_appears_per_favorite(session):
    _add_market(session, "M", created_at=NOW - timedelta(hours=24))
    session.commit()
    bankrolls = {
        SNAP.label: _full_bankroll(SNAP),
        THR.label: _full_bankroll(THR),
    }
    cands = enumerate_candidates(
        session, [SNAP, THR], now=NOW, tolerance_hours=12,
        quote_fn=lambda _t: 0.25, bankrolls=bankrolls,
    )
    got_labels = {c.favorite.label for c in cands if c.market.id == "M"}
    assert got_labels == {SNAP.label, THR.label}
