"""Live bot configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class LiveConfig:
    categories: list[str]
    sizing_rule: str
    sizing_notional: float
    sizing_shares: float
    kelly_win_rate: float
    kelly_fraction: float
    bankroll_start: float
    max_open_positions: int
    executor: str
    max_age_hours: int
    tolerance_hours: int
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None


def _csv(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def load_config() -> LiveConfig:
    categories_raw = os.getenv("LIVE_CATEGORIES")
    categories = (
        _csv(categories_raw)
        if categories_raw
        else ["geopolitical", "political", "culture"]
    )

    return LiveConfig(
        categories=categories,
        sizing_rule=os.getenv("LIVE_SIZING_RULE", "fixed_notional"),
        sizing_notional=float(os.getenv("LIVE_SIZING_NOTIONAL", "100")),
        sizing_shares=float(os.getenv("LIVE_SIZING_SHARES", "100")),
        kelly_win_rate=float(os.getenv("LIVE_SIZING_KELLY_WIN_RATE", "0.75")),
        kelly_fraction=float(os.getenv("LIVE_SIZING_KELLY_FRACTION", "0.25")),
        bankroll_start=float(os.getenv("LIVE_BANKROLL_START", "10000")),
        max_open_positions=int(os.getenv("LIVE_MAX_OPEN_POSITIONS", "50")),
        executor=os.getenv("LIVE_EXECUTOR", "paper"),
        max_age_hours=int(os.getenv("LIVE_MAX_AGE_HOURS", "24")),
        tolerance_hours=int(os.getenv("LIVE_TOLERANCE_HOURS", "12")),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN") or None,
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID") or None,
    )
