"""Live bot configuration loaded from YAML + environment variables.

Structural settings (categories, per-strategy bankrolls) come from
`live_config.yaml`. Secrets (telegram tokens) still come from env.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class StrategyConfig:
    label: str
    starting_bankroll: float
    shares_per_trade: float


@dataclass(frozen=True)
class LiveConfig:
    categories: list[str]
    tolerance_hours: int
    executor: str
    strategies: dict[str, StrategyConfig]  # keyed by label
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None


def load_config(path: Path = Path("live_config.yaml")) -> LiveConfig:
    raw = yaml.safe_load(Path(path).read_text())
    strategies_raw = raw["strategies"] or {}
    strategies = {
        label: StrategyConfig(
            label=label,
            starting_bankroll=float(block["starting_bankroll"]),
            shares_per_trade=float(block["shares_per_trade"]),
        )
        for label, block in strategies_raw.items()
    }
    return LiveConfig(
        categories=list(raw["categories"]),
        tolerance_hours=int(raw["tolerance_hours"]),
        executor=str(raw["executor"]),
        strategies=strategies,
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN") or None,
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID") or None,
    )
