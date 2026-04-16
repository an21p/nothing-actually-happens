from datetime import datetime, timedelta, timezone

from src.storage.models import Market, Position
from src.live.signals import detect_entries, EntrySignal


NOW = datetime(2026, 4, 15, 12, tzinfo=timezone.utc)


def _add_market(
    session,
    mid: str,
    *,
    question: str = "Will X happen by April 30, 2026?",
    created_at: datetime | None = None,
    end_date: datetime | None = None,
    category: str = "geopolitical",
    resolved_at: datetime | None = None,
    resolution: str | None = None,
) -> Market:
    m = Market(
        id=mid,
        question=question,
        category=category,
        no_token_id=f"tok_{mid}",
        created_at=created_at or (NOW - timedelta(hours=24)),
        end_date=end_date,
        resolved_at=resolved_at,
        resolution=resolution,
    )
    session.add(m)
    return m


def _add_position(
    session,
    market_id: str,
    *,
    status: str = "open",
    entry_timestamp: datetime | None = None,
    exit_timestamp: datetime | None = None,
) -> Position:
    pos = Position(
        market_id=market_id,
        strategy="snapshot_24__earliest_deadline",
        executor="paper",
        status=status,
        entry_price=0.80,
        entry_timestamp=entry_timestamp or (NOW - timedelta(days=3)),
        size_shares=100.0,
        size_notional=80.0,
        sizing_rule="fixed_notional",
        sizing_params_json='{}',
        exit_timestamp=exit_timestamp,
    )
    session.add(pos)
    return pos


def _quote_fn_const(price: float):
    return lambda _tok: price


def test_detects_market_aged_exactly_24h(session):
    _add_market(session, "m24", created_at=NOW - timedelta(hours=24))
    session.commit()

    signals = detect_entries(
        session, now=NOW, categories=["geopolitical"], quote_fn=_quote_fn_const(0.80)
    )
    assert len(signals) == 1
    s = signals[0]
    assert isinstance(s, EntrySignal)
    assert s.market.id == "m24"
    assert s.entry_price == 0.80
    assert s.entry_timestamp == NOW


def test_detects_within_tolerance(session):
    _add_market(session, "m20", created_at=NOW - timedelta(hours=20))
    _add_market(session, "m35", question="Other?", created_at=NOW - timedelta(hours=35))
    session.commit()
    signals = detect_entries(session, now=NOW, categories=["geopolitical"], quote_fn=_quote_fn_const(0.80))
    assert {s.market.id for s in signals} == {"m20", "m35"}


def test_skips_outside_tolerance(session):
    _add_market(session, "too_young", created_at=NOW - timedelta(hours=10))
    _add_market(session, "too_old", question="Other?", created_at=NOW - timedelta(hours=40))
    session.commit()
    signals = detect_entries(session, now=NOW, categories=["geopolitical"], quote_fn=_quote_fn_const(0.80))
    assert signals == []


def test_skips_market_with_existing_position(session):
    m = _add_market(session, "hasPos", created_at=NOW - timedelta(hours=24))
    session.flush()
    _add_position(session, m.id, status="open")
    session.commit()
    signals = detect_entries(session, now=NOW, categories=["geopolitical"], quote_fn=_quote_fn_const(0.80))
    assert signals == []


def test_skips_market_outside_categories(session):
    _add_market(session, "mpol", category="political", created_at=NOW - timedelta(hours=24))
    session.commit()
    signals = detect_entries(session, now=NOW, categories=["geopolitical"], quote_fn=_quote_fn_const(0.80))
    assert signals == []


def test_template_duplicates_pick_earliest_deadline(session):
    # Same creation time, same template, different end dates.
    base_create = NOW - timedelta(hours=24)
    _add_market(
        session,
        "dup_late",
        question="Will Israel strike Gaza by January 31, 2026?",
        created_at=base_create,
        end_date=NOW + timedelta(days=30),
    )
    _add_market(
        session,
        "dup_early",
        question="Will Israel strike Gaza by January 2, 2026?",
        created_at=base_create,
        end_date=NOW + timedelta(days=5),
    )
    session.commit()
    signals = detect_entries(session, now=NOW, categories=["geopolitical"], quote_fn=_quote_fn_const(0.80))
    assert [s.market.id for s in signals] == ["dup_early"]


def test_blocks_template_duplicate_when_sibling_has_open_position(session):
    old = _add_market(
        session,
        "oldTmpl",
        question="Will Israel strike Gaza by January 2, 2026?",
        created_at=NOW - timedelta(days=10),
        end_date=NOW - timedelta(days=1),
    )
    session.flush()
    _add_position(session, old.id, status="open")  # still holding
    _add_market(
        session,
        "newTmpl",
        question="Will Israel strike Gaza by February 28, 2026?",
        created_at=NOW - timedelta(hours=24),
        end_date=NOW + timedelta(days=30),
    )
    session.commit()
    signals = detect_entries(session, now=NOW, categories=["geopolitical"], quote_fn=_quote_fn_const(0.80))
    assert signals == []


def test_allows_new_template_cohort_when_prior_resolved(session):
    old = _add_market(
        session,
        "oldRes",
        question="Will Israel strike Gaza by January 2, 2026?",
        created_at=NOW - timedelta(days=30),
        end_date=NOW - timedelta(days=20),
        resolved_at=NOW - timedelta(days=20),
        resolution="No",
    )
    session.flush()
    _add_position(
        session,
        old.id,
        status="resolved",
        entry_timestamp=NOW - timedelta(days=29),
        exit_timestamp=NOW - timedelta(days=20),
    )
    # New market in the same template, created AFTER old one resolved.
    _add_market(
        session,
        "newOk",
        question="Will Israel strike Gaza by March 15, 2026?",
        created_at=NOW - timedelta(hours=24),
        end_date=NOW + timedelta(days=45),
    )
    session.commit()
    signals = detect_entries(session, now=NOW, categories=["geopolitical"], quote_fn=_quote_fn_const(0.80))
    assert [s.market.id for s in signals] == ["newOk"]


def test_skips_when_quote_unavailable(session):
    _add_market(session, "noquote", created_at=NOW - timedelta(hours=24))
    session.commit()
    signals = detect_entries(session, now=NOW, categories=["geopolitical"], quote_fn=lambda _t: None)
    assert signals == []
