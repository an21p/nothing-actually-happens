"""Favorite-strategy records: parse DB labels into typed records, and
merge with LiveConfig per-strategy settings.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from src.live.config import LiveConfig
from src.storage.models import FavoriteStrategy

logger = logging.getLogger(__name__)

SUPPORTED_SELECTION_MODES = {"earliest_created"}


def parse_label(label: str) -> tuple[str, dict, str]:
    """Parse a favorite label into (strategy_name, params, selection_mode).

    Grammar:
        snapshot_<N>__<mode>        → ("snapshot", {"offset_hours": N}, mode)
        threshold_<p>__<mode>       → ("threshold", {"threshold": p}, mode)
    """
    if "__" not in label:
        raise ValueError(f"malformed label (missing __): {label}")
    strategy_part, mode = label.split("__", 1)
    if mode not in SUPPORTED_SELECTION_MODES:
        raise ValueError(f"unsupported selection mode: {mode!r} in {label}")
    if "_" not in strategy_part:
        raise ValueError(f"malformed strategy part: {strategy_part}")
    name, _, raw_param = strategy_part.partition("_")
    if name == "snapshot":
        try:
            offset = int(raw_param)
        except ValueError as exc:
            raise ValueError(f"snapshot offset not an int: {raw_param!r}") from exc
        return name, {"offset_hours": offset}, mode
    if name == "threshold":
        try:
            threshold = float(raw_param)
        except ValueError as exc:
            raise ValueError(f"threshold not a float: {raw_param!r}") from exc
        return name, {"threshold": threshold}, mode
    raise ValueError(f"unsupported strategy: {name!r} in {label}")


@dataclass(frozen=True)
class Favorite:
    label: str
    strategy_name: str
    params: dict
    selection_mode: str
    starting_bankroll: float
    shares_per_trade: float


def load_favorites(session: Session, config: LiveConfig) -> list[Favorite]:
    rows = session.query(FavoriteStrategy).all()
    favorites: list[Favorite] = []
    for row in rows:
        try:
            name, params, mode = parse_label(row.strategy)
        except ValueError as exc:
            logger.warning("skipping unparseable favorite %r: %s", row.strategy, exc)
            continue
        sc = config.strategies.get(row.strategy)
        if sc is None:
            logger.warning(
                "skipping favorite %r: no entry in live_config.yaml", row.strategy
            )
            continue
        favorites.append(
            Favorite(
                label=row.strategy,
                strategy_name=name,
                params=params,
                selection_mode=mode,
                starting_bankroll=sc.starting_bankroll,
                shares_per_trade=sc.shares_per_trade,
            )
        )
    return favorites
