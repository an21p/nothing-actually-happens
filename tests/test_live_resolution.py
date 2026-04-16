from datetime import datetime, timezone

from src.storage.models import Market, Position
from src.live.executor import PaperExecutor
from src.live.resolution import sync_resolutions


NOW = datetime(2026, 5, 1, tzinfo=timezone.utc)


def _seed(session, *, resolution: str | None, resolved_at: datetime | None):
    m = Market(
        id="0xres",
        question="Will R happen?",
        category="political",
        no_token_id="tok_r",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        end_date=datetime(2026, 5, 1, tzinfo=timezone.utc),
        resolved_at=resolved_at,
        resolution=resolution,
    )
    session.add(m)
    session.flush()
    pos = Position(
        market_id=m.id,
        strategy="snapshot_24__earliest_deadline",
        executor="paper",
        status="open",
        entry_price=0.80,
        entry_timestamp=datetime(2026, 1, 2, tzinfo=timezone.utc),
        size_shares=100.0,
        size_notional=80.0,
        sizing_rule="fixed_notional",
        sizing_params_json='{}',
    )
    session.add(pos)
    session.commit()
    return m, pos


def test_sync_closes_no_resolution_positions(session):
    m, pos = _seed(session, resolution="No", resolved_at=datetime(2026, 4, 30, tzinfo=timezone.utc))
    exe = PaperExecutor(session)

    closed = sync_resolutions(session, exe, now=NOW)
    session.commit()

    assert len(closed) == 1
    fetched = session.get(Position, pos.id)
    assert fetched.status == "resolved"
    assert fetched.exit_price == 1.0
    assert fetched.realized_pnl == (1.0 - 0.80) * 100.0
    assert fetched.exit_timestamp == datetime(2026, 4, 30, tzinfo=timezone.utc) \
        or fetched.exit_timestamp.replace(tzinfo=timezone.utc) == datetime(2026, 4, 30, tzinfo=timezone.utc)


def test_sync_closes_yes_resolution_with_loss(session):
    m, pos = _seed(session, resolution="Yes", resolved_at=datetime(2026, 4, 30, tzinfo=timezone.utc))
    exe = PaperExecutor(session)
    closed = sync_resolutions(session, exe, now=NOW)
    session.commit()
    assert len(closed) == 1
    fetched = session.get(Position, pos.id)
    assert fetched.exit_price == 0.0
    assert fetched.realized_pnl == (0.0 - 0.80) * 100.0


def test_sync_ignores_positions_with_unresolved_markets(session):
    m, pos = _seed(session, resolution=None, resolved_at=None)
    exe = PaperExecutor(session)
    closed = sync_resolutions(session, exe, now=NOW)
    assert closed == []
    assert session.get(Position, pos.id).status == "open"


def test_sync_ignores_already_closed_positions(session):
    m, pos = _seed(session, resolution="No", resolved_at=datetime(2026, 4, 30, tzinfo=timezone.utc))
    pos.status = "resolved"
    pos.exit_price = 1.0
    pos.exit_timestamp = datetime(2026, 4, 30, tzinfo=timezone.utc)
    pos.realized_pnl = 20.0
    session.commit()

    exe = PaperExecutor(session)
    closed = sync_resolutions(session, exe, now=NOW)
    assert closed == []


def test_sync_uses_now_when_resolved_at_missing(session):
    m, pos = _seed(session, resolution="No", resolved_at=None)
    exe = PaperExecutor(session)
    closed = sync_resolutions(session, exe, now=NOW)
    session.commit()
    assert len(closed) == 1
    fetched = session.get(Position, pos.id)
    assert fetched.exit_timestamp.replace(tzinfo=timezone.utc) == NOW
