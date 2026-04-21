import pytest

from src.live.favorites import parse_label


def test_parse_snapshot_label():
    name, params, mode = parse_label("snapshot_24__earliest_created")
    assert name == "snapshot"
    assert params == {"offset_hours": 24}
    assert mode == "earliest_created"


def test_parse_threshold_label():
    name, params, mode = parse_label("threshold_0.3__earliest_created")
    assert name == "threshold"
    assert params == {"threshold": 0.3}
    assert mode == "earliest_created"


def test_rejects_unsupported_strategy():
    with pytest.raises(ValueError, match="unsupported strategy"):
        parse_label("limit_0.5__earliest_created")


def test_rejects_unsupported_selection_mode():
    with pytest.raises(ValueError, match="selection mode"):
        parse_label("snapshot_24__earliest_deadline")


def test_rejects_malformed_label():
    with pytest.raises(ValueError):
        parse_label("not_a_valid_label")


from src.live.config import LiveConfig, StrategyConfig
from src.live.favorites import Favorite, load_favorites
from src.storage.models import FavoriteStrategy


def _cfg_with(strategies: dict[str, StrategyConfig]) -> LiveConfig:
    return LiveConfig(
        categories=["geopolitical"],
        tolerance_hours=12,
        executor="paper",
        strategies=strategies,
    )


def test_load_favorites_merges_db_and_config(session):
    session.add(FavoriteStrategy(strategy="snapshot_24__earliest_created"))
    session.add(FavoriteStrategy(strategy="threshold_0.3__earliest_created"))
    session.commit()

    cfg = _cfg_with(
        {
            "snapshot_24__earliest_created": StrategyConfig(
                label="snapshot_24__earliest_created",
                starting_bankroll=1000.0,
                shares_per_trade=10.0,
            ),
            "threshold_0.3__earliest_created": StrategyConfig(
                label="threshold_0.3__earliest_created",
                starting_bankroll=500.0,
                shares_per_trade=5.0,
            ),
        }
    )
    favs = load_favorites(session, cfg)
    assert len(favs) == 2
    by_label = {f.label: f for f in favs}
    snap = by_label["snapshot_24__earliest_created"]
    assert isinstance(snap, Favorite)
    assert snap.strategy_name == "snapshot"
    assert snap.params == {"offset_hours": 24}
    assert snap.starting_bankroll == 1000.0
    assert snap.shares_per_trade == 10.0
    thr = by_label["threshold_0.3__earliest_created"]
    assert thr.strategy_name == "threshold"
    assert thr.params == {"threshold": 0.3}
    assert thr.shares_per_trade == 5.0


def test_load_favorites_skips_fav_missing_from_config(session, caplog):
    session.add(FavoriteStrategy(strategy="snapshot_24__earliest_created"))
    session.commit()
    cfg = _cfg_with({})  # no config entry
    with caplog.at_level("WARNING"):
        favs = load_favorites(session, cfg)
    assert favs == []
    assert any("no entry in live_config.yaml" in r.message for r in caplog.records)


def test_load_favorites_skips_unparseable_label(session, caplog):
    session.add(FavoriteStrategy(strategy="limit_0.5__earliest_created"))
    session.commit()
    cfg = _cfg_with({})
    with caplog.at_level("WARNING"):
        favs = load_favorites(session, cfg)
    assert favs == []
    assert any("unparseable favorite" in r.message for r in caplog.records)
