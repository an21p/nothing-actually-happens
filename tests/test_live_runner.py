from datetime import datetime, timedelta, timezone

from src.live.config import LiveConfig, StrategyConfig
from src.live.executor import PaperExecutor
from src.live.notifier import NullNotifier
from src.live.runner import run_once
from src.storage.models import FavoriteStrategy, Market, Position


NOW = datetime(2026, 4, 21, 12, tzinfo=timezone.utc)


def _cfg(**overrides) -> LiveConfig:
    base = dict(
        categories=["geopolitical"],
        tolerance_hours=12,
        executor="paper",
        strategies={
            "snapshot_24__earliest_created": StrategyConfig(
                label="snapshot_24__earliest_created",
                starting_bankroll=1000.0,
                shares_per_trade=10.0,
            ),
            "threshold_0.3__earliest_created": StrategyConfig(
                label="threshold_0.3__earliest_created",
                starting_bankroll=1000.0,
                shares_per_trade=10.0,
            ),
        },
        telegram_bot_token=None,
        telegram_chat_id=None,
    )
    base.update(overrides)
    return LiveConfig(**base)


def _add_favorites(session, labels):
    for label in labels:
        session.add(FavoriteStrategy(strategy=label))
    session.flush()


def _open_market_row(mid, *, question="Will X happen by May 10, 2026?",
                     created_at=NOW - timedelta(hours=24),
                     category="geopolitical") -> dict:
    return dict(
        id=mid, question=question, category=category,
        no_token_id=f"tok_{mid}", created_at=created_at,
        end_date=None, resolved_at=None, resolution=None,
        source_url=f"https://polymarket.com/{mid}",
    )


def test_run_once_opens_snapshot_position(session):
    _add_favorites(session, ["snapshot_24__earliest_created"])
    session.commit()

    fetched = [_open_market_row("m1")]

    stats = run_once(
        session, _cfg(), now=NOW,
        executor=PaperExecutor(session), notifier=NullNotifier(),
        fetch_open_fn=lambda cats: fetched,
        quote_fn=lambda _tok: 0.5,
    )
    session.commit()

    positions = session.query(Position).all()
    assert len(positions) == 1
    pos = positions[0]
    assert pos.strategy == "snapshot_24__earliest_created"
    assert pos.size_shares == 10.0
    assert pos.sizing_rule == "fixed_shares"
    assert pos.entry_price == 0.5
    assert stats["positions_opened"] == 1


def test_run_once_opens_threshold_position_when_quote_low(session):
    _add_favorites(session, ["threshold_0.3__earliest_created"])
    session.commit()

    fetched = [_open_market_row("t1", created_at=NOW - timedelta(days=2))]

    run_once(
        session, _cfg(), now=NOW,
        executor=PaperExecutor(session), notifier=NullNotifier(),
        fetch_open_fn=lambda cats: fetched,
        quote_fn=lambda _tok: 0.25,
    )
    session.commit()

    positions = session.query(Position).all()
    assert [p.strategy for p in positions] == ["threshold_0.3__earliest_created"]
    assert positions[0].entry_price == 0.25


def test_run_once_both_strategies_same_market(session):
    _add_favorites(session, [
        "snapshot_24__earliest_created",
        "threshold_0.3__earliest_created",
    ])
    session.commit()

    fetched = [_open_market_row("shared", created_at=NOW - timedelta(hours=24))]

    run_once(
        session, _cfg(), now=NOW,
        executor=PaperExecutor(session), notifier=NullNotifier(),
        fetch_open_fn=lambda cats: fetched,
        quote_fn=lambda _tok: 0.2,  # qualifies for both
    )
    session.commit()

    positions = session.query(Position).all()
    strategies = {p.strategy for p in positions}
    assert strategies == {
        "snapshot_24__earliest_created",
        "threshold_0.3__earliest_created",
    }


def test_run_once_gates_on_bankroll(session):
    _add_favorites(session, ["threshold_0.3__earliest_created"])
    session.commit()

    # Two markets, both would fire. Bankroll = 1.0 only covers one trade at 0.25 * 10 = 2.5.
    fetched = [
        _open_market_row(f"t{i}", question=f"Will t{i}?", created_at=NOW - timedelta(days=2))
        for i in range(2)
    ]

    cfg = _cfg(strategies={
        "threshold_0.3__earliest_created": StrategyConfig(
            label="threshold_0.3__earliest_created",
            starting_bankroll=1.0,
            shares_per_trade=10.0,
        )
    })

    run_once(
        session, cfg, now=NOW,
        executor=PaperExecutor(session), notifier=NullNotifier(),
        fetch_open_fn=lambda cats: fetched,
        quote_fn=lambda _tok: 0.25,
    )
    session.commit()

    assert session.query(Position).count() == 0  # none can afford


def test_run_once_in_memory_bankroll_prevents_double_spend(session):
    _add_favorites(session, ["threshold_0.3__earliest_created"])
    session.commit()

    # Two markets. Bankroll = 3.0. Each trade is 0.25 * 10 = 2.5.
    # First trade OK (3.0 - 2.5 = 0.5 remaining), second must be skipped.
    fetched = [
        _open_market_row(f"t{i}", question=f"Will q{i}?", created_at=NOW - timedelta(days=2))
        for i in range(2)
    ]
    cfg = _cfg(strategies={
        "threshold_0.3__earliest_created": StrategyConfig(
            label="threshold_0.3__earliest_created",
            starting_bankroll=3.0,
            shares_per_trade=10.0,
        )
    })

    run_once(
        session, cfg, now=NOW,
        executor=PaperExecutor(session), notifier=NullNotifier(),
        fetch_open_fn=lambda cats: fetched,
        quote_fn=lambda _tok: 0.25,
    )
    session.commit()

    assert session.query(Position).count() == 1


def test_run_once_marks_and_resolves_as_before(session):
    _add_favorites(session, ["snapshot_24__earliest_created"])
    m = Market(
        id="mResolve",
        question="Will Y?",
        category="geopolitical",
        no_token_id="tok_mResolve",
        created_at=NOW - timedelta(days=10),
        end_date=NOW - timedelta(days=1),
        resolved_at=NOW - timedelta(days=1),
        resolution="No",
    )
    session.add(m)
    session.flush()
    pos = Position(
        market_id="mResolve",
        strategy="snapshot_24__earliest_created",
        executor="paper",
        status="open",
        entry_price=0.4,
        entry_timestamp=NOW - timedelta(days=9),
        size_shares=10.0,
        size_notional=4.0,
        sizing_rule="fixed_shares",
        sizing_params_json="{}",
    )
    session.add(pos)
    session.commit()

    stats = run_once(
        session, _cfg(), now=NOW,
        executor=PaperExecutor(session), notifier=NullNotifier(),
        fetch_open_fn=lambda cats: [],
        quote_fn=lambda _tok: 0.99,
    )
    session.commit()

    got = session.get(Position, pos.id)
    assert got.status == "resolved"
    assert got.exit_price == 1.0
    assert got.realized_pnl == (1.0 - 0.4) * 10.0
    assert stats["positions_resolved"] == 1


def test_run_once_dry_run_writes_nothing(session):
    _add_favorites(session, ["snapshot_24__earliest_created"])
    session.commit()

    fetched = [_open_market_row("mDry")]

    stats = run_once(
        session, _cfg(), now=NOW,
        executor=PaperExecutor(session), notifier=NullNotifier(),
        fetch_open_fn=lambda cats: fetched,
        quote_fn=lambda _tok: 0.5,
        dry_run=True,
    )
    session.rollback()

    assert session.get(Market, "mDry") is None
    assert session.query(Position).count() == 0
    assert stats["dry_run"] is True
