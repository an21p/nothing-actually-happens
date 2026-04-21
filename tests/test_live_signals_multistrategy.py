from datetime import datetime, timedelta, timezone

from src.live.favorites import Favorite
from src.live.signals import EntrySignal, detect_snapshot_entries
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


def _add_market(session, mid: str, *, question="Will X happen by May 10, 2026?",
                created_at=None, end_date=None, category="geopolitical") -> Market:
    m = Market(
        id=mid, question=question, category=category,
        no_token_id=f"tok_{mid}",
        created_at=created_at or (NOW - timedelta(hours=24)),
        end_date=end_date,
    )
    session.add(m)
    return m


def _add_position(session, market_id: str, strategy: str, *, status="open") -> Position:
    pos = Position(
        market_id=market_id, strategy=strategy, executor="paper", status=status,
        entry_price=0.5, entry_timestamp=NOW - timedelta(days=1),
        size_shares=10.0, size_notional=5.0,
        sizing_rule="fixed_shares", sizing_params_json="{}",
    )
    session.add(pos)
    return pos


def _quote(p):
    return lambda _tok: p


def test_snapshot_detects_market_at_24h(session):
    _add_market(session, "m", created_at=NOW - timedelta(hours=24))
    session.commit()
    signals = detect_snapshot_entries(session, SNAP, now=NOW, tolerance_hours=12, quote_fn=_quote(0.45))
    assert len(signals) == 1
    s = signals[0]
    assert isinstance(s, EntrySignal)
    assert s.market.id == "m"
    assert s.entry_price == 0.45
    assert s.entry_timestamp == NOW


def test_snapshot_detects_within_tolerance(session):
    # Asymmetric window [offset, offset + tolerance] = [24, 36].
    _add_market(session, "just_past", created_at=NOW - timedelta(hours=25))
    _add_market(session, "near_ceiling", question="Other?", created_at=NOW - timedelta(hours=35))
    session.commit()
    signals = detect_snapshot_entries(session, SNAP, now=NOW, tolerance_hours=12, quote_fn=_quote(0.5))
    assert {s.market.id for s in signals} == {"just_past", "near_ceiling"}


def test_snapshot_rejects_market_just_before_offset(session):
    # Under asymmetric semantics, a market younger than `offset_hours` must
    # not fire — no early entries. 23h is just below the 24h floor.
    _add_market(session, "tooYoung", created_at=NOW - timedelta(hours=23))
    session.commit()
    signals = detect_snapshot_entries(session, SNAP, now=NOW, tolerance_hours=12, quote_fn=_quote(0.5))
    assert signals == []


def test_snapshot_skips_outside_tolerance(session):
    _add_market(session, "tooYoung", created_at=NOW - timedelta(hours=10))
    _add_market(session, "tooOld", question="Other?", created_at=NOW - timedelta(hours=40))
    session.commit()
    signals = detect_snapshot_entries(session, SNAP, now=NOW, tolerance_hours=12, quote_fn=_quote(0.5))
    assert signals == []


def test_snapshot_skips_non_geopolitical(session):
    _add_market(session, "pol", category="political", created_at=NOW - timedelta(hours=24))
    session.commit()
    signals = detect_snapshot_entries(session, SNAP, now=NOW, tolerance_hours=12, quote_fn=_quote(0.5))
    assert signals == []


def test_snapshot_per_strategy_dedup_allows_other_strategy_on_same_market(session):
    m = _add_market(session, "shared", created_at=NOW - timedelta(hours=24))
    session.flush()
    # Threshold already took this market; snapshot should still be eligible.
    _add_position(session, m.id, "threshold_0.3__earliest_created")
    session.commit()
    signals = detect_snapshot_entries(session, SNAP, now=NOW, tolerance_hours=12, quote_fn=_quote(0.5))
    assert [s.market.id for s in signals] == ["shared"]


def test_snapshot_blocks_when_same_strategy_already_entered(session):
    m = _add_market(session, "dup", created_at=NOW - timedelta(hours=24))
    session.flush()
    _add_position(session, m.id, SNAP.label)
    session.commit()
    signals = detect_snapshot_entries(session, SNAP, now=NOW, tolerance_hours=12, quote_fn=_quote(0.5))
    assert signals == []


def test_snapshot_template_dedup_prefers_earliest_created(session):
    base = NOW - timedelta(hours=24)
    _add_market(session, "earlier",
                question="Will Israel strike Gaza by January 2, 2026?",
                created_at=base - timedelta(minutes=1))
    _add_market(session, "later",
                question="Will Israel strike Gaza by January 31, 2026?",
                created_at=base)
    session.commit()
    signals = detect_snapshot_entries(session, SNAP, now=NOW, tolerance_hours=12, quote_fn=_quote(0.5))
    assert [s.market.id for s in signals] == ["earlier"]


def test_snapshot_template_block_scoped_to_strategy(session):
    old = _add_market(session, "oldT",
                      question="Will Israel strike Gaza by January 2, 2026?",
                      created_at=NOW - timedelta(days=5), end_date=NOW - timedelta(days=1))
    session.flush()
    # Threshold holds a position on the old template sibling — should NOT block snapshot.
    _add_position(session, old.id, "threshold_0.3__earliest_created")
    _add_market(session, "newT",
                question="Will Israel strike Gaza by February 28, 2026?",
                created_at=NOW - timedelta(hours=24))
    session.commit()
    signals = detect_snapshot_entries(session, SNAP, now=NOW, tolerance_hours=12, quote_fn=_quote(0.5))
    assert [s.market.id for s in signals] == ["newT"]


def test_snapshot_skips_when_quote_unavailable(session):
    _add_market(session, "noq", created_at=NOW - timedelta(hours=24))
    session.commit()
    signals = detect_snapshot_entries(session, SNAP, now=NOW, tolerance_hours=12, quote_fn=lambda _t: None)
    assert signals == []


from src.live.signals import detect_threshold_entries


THR = Favorite(
    label="threshold_0.3__earliest_created",
    strategy_name="threshold",
    params={"threshold": 0.3},
    selection_mode="earliest_created",
    starting_bankroll=1000.0,
    shares_per_trade=10.0,
)


def test_threshold_fires_when_quote_at_or_below_threshold(session):
    _add_market(session, "dip", created_at=NOW - timedelta(days=2))
    session.commit()
    signals = detect_threshold_entries(session, THR, now=NOW, quote_fn=_quote(0.28))
    assert len(signals) == 1
    assert signals[0].entry_price == 0.28


def test_threshold_fires_on_exactly_threshold(session):
    _add_market(session, "edge", created_at=NOW - timedelta(days=2))
    session.commit()
    signals = detect_threshold_entries(session, THR, now=NOW, quote_fn=_quote(0.3))
    assert [s.market.id for s in signals] == ["edge"]


def test_threshold_fires_on_market_that_opened_below(session):
    # Market opened 2h ago already below threshold — still a valid entry
    # (live policy: fire on observation, not on crossing).
    _add_market(session, "fresh", created_at=NOW - timedelta(hours=2))
    session.commit()
    signals = detect_threshold_entries(session, THR, now=NOW, quote_fn=_quote(0.15))
    assert [s.market.id for s in signals] == ["fresh"]


def test_threshold_skips_when_quote_above_threshold(session):
    _add_market(session, "up", created_at=NOW - timedelta(days=2))
    session.commit()
    signals = detect_threshold_entries(session, THR, now=NOW, quote_fn=_quote(0.45))
    assert signals == []


def test_threshold_skips_non_geopolitical(session):
    _add_market(session, "pol", category="political", created_at=NOW - timedelta(days=2))
    session.commit()
    signals = detect_threshold_entries(session, THR, now=NOW, quote_fn=_quote(0.2))
    assert signals == []


def test_threshold_per_strategy_dedup_allows_snapshot_on_same_market(session):
    m = _add_market(session, "shared", created_at=NOW - timedelta(days=2))
    session.flush()
    _add_position(session, m.id, "snapshot_24__earliest_created")
    session.commit()
    signals = detect_threshold_entries(session, THR, now=NOW, quote_fn=_quote(0.2))
    assert [s.market.id for s in signals] == ["shared"]


def test_threshold_blocks_when_same_strategy_already_entered(session):
    m = _add_market(session, "dup", created_at=NOW - timedelta(days=2))
    session.flush()
    _add_position(session, m.id, THR.label)
    session.commit()
    signals = detect_threshold_entries(session, THR, now=NOW, quote_fn=_quote(0.2))
    assert signals == []


def test_threshold_template_dedup_prefers_earliest_created(session):
    base = NOW - timedelta(days=2)
    _add_market(session, "earlier",
                question="Will Israel strike Gaza by January 2, 2026?",
                created_at=base - timedelta(minutes=1))
    _add_market(session, "later",
                question="Will Israel strike Gaza by January 31, 2026?",
                created_at=base)
    session.commit()
    signals = detect_threshold_entries(session, THR, now=NOW, quote_fn=_quote(0.2))
    assert [s.market.id for s in signals] == ["earlier"]


def test_threshold_skips_when_quote_none(session):
    _add_market(session, "noq", created_at=NOW - timedelta(days=2))
    session.commit()
    signals = detect_threshold_entries(session, THR, now=NOW, quote_fn=lambda _t: None)
    assert signals == []
