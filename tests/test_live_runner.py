from datetime import datetime, timedelta, timezone

from src.live.config import LiveConfig
from src.live.executor import PaperExecutor
from src.live.notifier import NullNotifier
from src.live.runner import run_once
from src.storage.models import Market, Position


NOW = datetime(2026, 4, 15, 12, tzinfo=timezone.utc)


def _base_config(**overrides) -> LiveConfig:
    defaults = dict(
        categories=["geopolitical"],
        sizing_rule="fixed_notional",
        sizing_notional=100.0,
        sizing_shares=100.0,
        bankroll_start=10_000.0,
        max_open_positions=50,
        executor="paper",
        max_age_hours=24,
        tolerance_hours=12,
        telegram_bot_token=None,
        telegram_chat_id=None,
    )
    defaults.update(overrides)
    return LiveConfig(**defaults)


def _open_market_row(
    mid: str,
    *,
    question: str = "Will X happen by April 30, 2026?",
    created_at: datetime = NOW - timedelta(hours=24),
    end_date: datetime | None = None,
    category: str = "geopolitical",
) -> dict:
    return dict(
        id=mid,
        question=question,
        category=category,
        no_token_id=f"tok_{mid}",
        created_at=created_at,
        end_date=end_date,
        resolved_at=None,
        resolution=None,
        source_url=f"https://polymarket.com/{mid}",
    )


def test_run_once_upserts_open_markets_and_opens_positions(session):
    fetched = [_open_market_row("m24", created_at=NOW - timedelta(hours=24))]

    stats = run_once(
        session,
        _base_config(),
        now=NOW,
        executor=PaperExecutor(session),
        notifier=NullNotifier(),
        fetch_open_fn=lambda cats: fetched,
        quote_fn=lambda _tok: 0.80,
    )

    session.commit()

    assert session.get(Market, "m24") is not None
    positions = session.query(Position).all()
    assert len(positions) == 1
    pos = positions[0]
    assert pos.market_id == "m24"
    assert pos.entry_price == 0.80
    assert pos.size_notional == 100.0
    assert pos.status == "open"
    assert stats["markets_upserted"] == 1
    assert stats["positions_opened"] == 1


def test_run_once_marks_open_positions_to_market(session):
    m = Market(
        id="mMark",
        question="Will Y happen?",
        category="geopolitical",
        no_token_id="tok_mMark",
        created_at=NOW - timedelta(days=5),
        end_date=None,
        resolved_at=None,
        resolution=None,
    )
    session.add(m)
    session.flush()
    pos = Position(
        market_id="mMark",
        strategy="snapshot_24__earliest_deadline",
        executor="paper",
        status="open",
        entry_price=0.80,
        entry_timestamp=NOW - timedelta(days=4),
        size_shares=125.0,
        size_notional=100.0,
        sizing_rule="fixed_notional",
        sizing_params_json="{}",
    )
    session.add(pos)
    session.commit()

    run_once(
        session,
        _base_config(),
        now=NOW,
        executor=PaperExecutor(session),
        notifier=NullNotifier(),
        fetch_open_fn=lambda cats: [],
        quote_fn=lambda _tok: 0.90,
    )
    session.commit()

    fetched = session.get(Position, pos.id)
    assert fetched.last_mark_price == 0.90
    assert fetched.unrealized_pnl == (0.90 - 0.80) * 125.0


def test_run_once_closes_resolved_positions(session):
    m = Market(
        id="mRes",
        question="Will Z happen?",
        category="geopolitical",
        no_token_id="tok_mRes",
        created_at=NOW - timedelta(days=10),
        end_date=NOW - timedelta(days=1),
        resolved_at=NOW - timedelta(days=1),
        resolution="No",
    )
    session.add(m)
    session.flush()
    pos = Position(
        market_id="mRes",
        strategy="snapshot_24__earliest_deadline",
        executor="paper",
        status="open",
        entry_price=0.80,
        entry_timestamp=NOW - timedelta(days=9),
        size_shares=100.0,
        size_notional=80.0,
        sizing_rule="fixed_notional",
        sizing_params_json="{}",
    )
    session.add(pos)
    session.commit()

    stats = run_once(
        session,
        _base_config(),
        now=NOW,
        executor=PaperExecutor(session),
        notifier=NullNotifier(),
        fetch_open_fn=lambda cats: [],
        quote_fn=lambda _tok: 0.99,
    )
    session.commit()

    fetched = session.get(Position, pos.id)
    assert fetched.status == "resolved"
    assert fetched.exit_price == 1.0
    assert fetched.realized_pnl == (1.0 - 0.80) * 100.0
    assert stats["positions_resolved"] == 1


def test_run_once_dry_run_writes_nothing(session):
    fetched = [_open_market_row("mDry", created_at=NOW - timedelta(hours=24))]

    stats = run_once(
        session,
        _base_config(),
        now=NOW,
        executor=PaperExecutor(session),
        notifier=NullNotifier(),
        fetch_open_fn=lambda cats: fetched,
        quote_fn=lambda _tok: 0.80,
        dry_run=True,
    )
    session.rollback()

    assert session.get(Market, "mDry") is None
    assert session.query(Position).count() == 0
    assert stats["dry_run"] is True


def test_run_once_respects_max_open_positions(session):
    fetched = [
        _open_market_row(
            f"mx{i}",
            question=f"Will Q{i} happen?",
            created_at=NOW - timedelta(hours=24),
        )
        for i in range(5)
    ]
    cfg = _base_config(max_open_positions=2)
    for i in range(2):
        m = Market(
            id=f"held{i}",
            question=f"Held {i}?",
            category="geopolitical",
            no_token_id=f"tok_held{i}",
            created_at=NOW - timedelta(days=30),
            resolved_at=None,
            resolution=None,
        )
        session.add(m)
        session.flush()
        session.add(
            Position(
                market_id=m.id,
                strategy="snapshot_24__earliest_deadline",
                executor="paper",
                status="open",
                entry_price=0.7,
                entry_timestamp=NOW - timedelta(days=20),
                size_shares=10.0,
                size_notional=7.0,
                sizing_rule="fixed_notional",
                sizing_params_json="{}",
            )
        )
    session.commit()

    run_once(
        session,
        cfg,
        now=NOW,
        executor=PaperExecutor(session),
        notifier=NullNotifier(),
        fetch_open_fn=lambda cats: fetched,
        quote_fn=lambda _tok: 0.80,
    )
    session.commit()

    opened_new = session.query(Position).filter(Position.market_id.like("mx%")).count()
    assert opened_new == 0
