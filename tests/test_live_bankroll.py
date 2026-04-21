from datetime import datetime, timedelta, timezone

from src.live.bankroll import BankrollState, compute_bankroll
from src.storage.models import Market, Position


NOW = datetime(2026, 4, 21, 12, tzinfo=timezone.utc)


def _market(session, mid: str) -> Market:
    m = Market(
        id=mid,
        question=f"Q {mid}",
        category="geopolitical",
        no_token_id=f"tok_{mid}",
        created_at=NOW - timedelta(days=1),
    )
    session.add(m)
    session.flush()
    return m


def _open_position(session, market_id: str, strategy: str, entry: float, shares: float) -> Position:
    pos = Position(
        market_id=market_id,
        strategy=strategy,
        executor="paper",
        status="open",
        entry_price=entry,
        entry_timestamp=NOW - timedelta(hours=12),
        size_shares=shares,
        size_notional=entry * shares,
        sizing_rule="fixed_shares",
        sizing_params_json="{}",
    )
    session.add(pos)
    session.flush()
    return pos


def _closed_position(
    session, market_id: str, strategy: str, entry: float, shares: float, exit_price: float
) -> Position:
    pos = _open_position(session, market_id, strategy, entry, shares)
    pos.status = "resolved"
    pos.exit_price = exit_price
    pos.exit_timestamp = NOW - timedelta(hours=1)
    pos.realized_pnl = (exit_price - entry) * shares
    pos.unrealized_pnl = None
    return pos


def test_bankroll_empty_history(session):
    state = compute_bankroll(session, "snapshot_24__earliest_created", starting=1000.0)
    assert state == BankrollState(
        strategy="snapshot_24__earliest_created",
        starting=1000.0,
        locked=0.0,
        realized_pnl=0.0,
        available=1000.0,
        open_positions=0,
        closed_positions=0,
    )


def test_bankroll_only_open_positions(session):
    _market(session, "a")
    _market(session, "b")
    _open_position(session, "a", "snapshot_24__earliest_created", entry=0.4, shares=10)
    _open_position(session, "b", "snapshot_24__earliest_created", entry=0.25, shares=10)
    session.commit()

    state = compute_bankroll(session, "snapshot_24__earliest_created", starting=1000.0)
    # locked = 0.4*10 + 0.25*10 = 6.5
    assert state.locked == 6.5
    assert state.realized_pnl == 0.0
    assert state.available == 1000.0 - 6.5
    assert state.open_positions == 2
    assert state.closed_positions == 0


def test_bankroll_wins_compound(session):
    _market(session, "w1")
    _closed_position(
        session, "w1", "snapshot_24__earliest_created",
        entry=0.3, shares=10, exit_price=1.0,
    )  # realized_pnl = (1 - 0.3) * 10 = 7
    session.commit()

    state = compute_bankroll(session, "snapshot_24__earliest_created", starting=1000.0)
    assert state.locked == 0.0
    assert state.realized_pnl == 7.0
    assert state.available == 1007.0
    assert state.closed_positions == 1


def test_bankroll_losses_deduct(session):
    _market(session, "L1")
    _closed_position(
        session, "L1", "snapshot_24__earliest_created",
        entry=0.6, shares=10, exit_price=0.0,
    )  # realized_pnl = (0 - 0.6) * 10 = -6
    session.commit()

    state = compute_bankroll(session, "snapshot_24__earliest_created", starting=1000.0)
    assert state.realized_pnl == -6.0
    assert state.available == 994.0


def test_bankroll_scoped_by_strategy(session):
    _market(session, "shared")
    _open_position(session, "shared", "snapshot_24__earliest_created", entry=0.4, shares=10)
    _market(session, "other")
    _open_position(session, "other", "threshold_0.3__earliest_created", entry=0.25, shares=5)
    session.commit()

    snap = compute_bankroll(session, "snapshot_24__earliest_created", starting=1000.0)
    thr = compute_bankroll(session, "threshold_0.3__earliest_created", starting=500.0)
    assert snap.locked == 4.0
    assert snap.open_positions == 1
    assert thr.locked == 1.25
    assert thr.open_positions == 1


def test_bankroll_mixed_open_and_closed(session):
    _market(session, "o1")
    _open_position(session, "o1", "snapshot_24__earliest_created", entry=0.4, shares=10)  # locked 4
    _market(session, "c1")
    _closed_position(session, "c1", "snapshot_24__earliest_created", entry=0.3, shares=10, exit_price=1.0)  # +7
    _market(session, "c2")
    _closed_position(session, "c2", "snapshot_24__earliest_created", entry=0.5, shares=10, exit_price=0.0)  # -5
    session.commit()

    state = compute_bankroll(session, "snapshot_24__earliest_created", starting=1000.0)
    assert state.locked == 4.0
    assert state.realized_pnl == 2.0  # 7 - 5
    assert state.available == 1000.0 - 4.0 + 2.0
    assert state.open_positions == 1
    assert state.closed_positions == 2
