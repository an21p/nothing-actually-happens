import json
from datetime import datetime, timezone

import pytest

from src.storage.models import Market, Position
from src.live.executor import LiveExecutor, PaperExecutor, get_executor
from src.live.sizing import SizingResult


def _seed_market(session) -> Market:
    m = Market(
        id="0xexec",
        question="Will Z happen?",
        category="political",
        no_token_id="tok_exec",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        end_date=datetime(2026, 3, 1, tzinfo=timezone.utc),
    )
    session.add(m)
    session.flush()
    return m


def test_paper_executor_open_position_persists(session):
    market = _seed_market(session)
    exe = PaperExecutor(session)
    sizing = SizingResult(shares=125.0, notional=100.0, rule="fixed_notional", params={"notional": 100.0})

    pos = exe.open_position(
        market=market,
        entry_price=0.80,
        entry_timestamp=datetime(2026, 1, 2, tzinfo=timezone.utc),
        sizing_result=sizing,
        strategy="snapshot_24__earliest_deadline",
    )
    session.commit()

    fetched = session.query(Position).filter_by(market_id=market.id).one()
    assert fetched.status == "open"
    assert fetched.entry_price == 0.80
    assert fetched.size_shares == 125.0
    assert fetched.size_notional == 100.0
    assert fetched.sizing_rule == "fixed_notional"
    assert json.loads(fetched.sizing_params_json) == {"notional": 100.0}
    assert fetched.executor == "paper"
    assert fetched.exit_price is None
    assert fetched.realized_pnl is None
    assert pos.id == fetched.id


def test_paper_executor_mark_position_updates_unrealized(session):
    market = _seed_market(session)
    exe = PaperExecutor(session)
    sizing = SizingResult(shares=100.0, notional=80.0, rule="fixed_notional", params={"notional": 80.0})
    pos = exe.open_position(
        market=market,
        entry_price=0.80,
        entry_timestamp=datetime(2026, 1, 2, tzinfo=timezone.utc),
        sizing_result=sizing,
        strategy="snapshot_24__earliest_deadline",
    )
    session.commit()

    mark_ts = datetime(2026, 1, 3, tzinfo=timezone.utc)
    exe.mark_position(pos, mid=0.90, at=mark_ts)
    session.commit()

    fetched = session.get(Position, pos.id)
    assert fetched.last_mark_price == 0.90
    assert fetched.last_mark_timestamp is not None
    # long No at 0.80 → unrealized = (0.90 - 0.80) * 100 = 10
    assert fetched.unrealized_pnl == pytest.approx(10.0)


def test_paper_executor_close_position_realizes_pnl(session):
    market = _seed_market(session)
    exe = PaperExecutor(session)
    sizing = SizingResult(shares=100.0, notional=80.0, rule="fixed_notional", params={"notional": 80.0})
    pos = exe.open_position(
        market=market,
        entry_price=0.80,
        entry_timestamp=datetime(2026, 1, 2, tzinfo=timezone.utc),
        sizing_result=sizing,
        strategy="snapshot_24__earliest_deadline",
    )
    session.commit()

    exit_ts = datetime(2026, 3, 1, tzinfo=timezone.utc)
    exe.close_position(pos, exit_price=1.0, exit_timestamp=exit_ts)
    session.commit()

    fetched = session.get(Position, pos.id)
    assert fetched.status == "resolved"
    assert fetched.exit_price == 1.0
    # realized = (1.0 - 0.80) * 100 = 20
    assert fetched.realized_pnl == pytest.approx(20.0)
    assert fetched.unrealized_pnl is None


def test_live_executor_raises_not_implemented():
    exe = LiveExecutor()
    with pytest.raises(NotImplementedError):
        exe.open_position(
            market=None,
            entry_price=0.8,
            entry_timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
            sizing_result=SizingResult(0, 0, "x", {}),
            strategy="x",
        )
    with pytest.raises(NotImplementedError):
        exe.mark_position(None, mid=0.5, at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    with pytest.raises(NotImplementedError):
        exe.close_position(None, exit_price=1.0, exit_timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc))


def test_get_executor_paper_returns_paper(session):
    assert isinstance(get_executor("paper", session), PaperExecutor)


def test_get_executor_live_returns_live(session):
    assert isinstance(get_executor("live", session), LiveExecutor)


def test_get_executor_unknown_raises(session):
    with pytest.raises(ValueError):
        get_executor("bogus", session)
