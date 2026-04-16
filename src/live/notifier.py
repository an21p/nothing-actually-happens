"""Live-event notifications (entry + resolution).

Pluggable so the runner doesn't care whether Telegram is configured.
Factory inspects env vars and returns either a TelegramNotifier or the
no-op NullNotifier if credentials are absent.
"""

from __future__ import annotations

import logging
import os
from typing import Protocol

import httpx

from src.storage.models import Market, Position

logger = logging.getLogger(__name__)


class Notifier(Protocol):
    def on_entry(self, position: Position, market: Market) -> None: ...
    def on_resolution(self, position: Position, market: Market) -> None: ...


class NullNotifier:
    def on_entry(self, position: Position, market: Market) -> None:
        return None

    def on_resolution(self, position: Position, market: Market) -> None:
        return None


def _format_entry(position: Position, market: Market) -> str:
    link = market.source_url or ""
    return (
        "ENTRY opened\n"
        f"{market.question}\n"
        f"Category: {market.category}\n"
        f"Entry: {position.entry_price:.2f}  Size: {position.size_shares:.2f} shares "
        f"(${position.size_notional:.2f})\n"
        f"Rule: {position.sizing_rule}\n"
        f"{link}"
    )


def _format_resolution(position: Position, market: Market) -> str:
    pnl = position.realized_pnl if position.realized_pnl is not None else 0.0
    exit_price = position.exit_price if position.exit_price is not None else 0.0
    return (
        "RESOLVED\n"
        f"{market.question}\n"
        f"Exit: {exit_price:.2f}  Realized P&L: ${pnl:.2f}\n"
        f"Entry: {position.entry_price:.2f}  Size: {position.size_shares:.2f} shares"
    )


class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str) -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id

    def _send(self, text: str) -> None:
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        try:
            response = httpx.post(
                url, json={"chat_id": self.chat_id, "text": text}, timeout=10.0
            )
            if response.status_code != 200:
                logger.warning(
                    "Telegram sendMessage returned %s: %s",
                    response.status_code,
                    getattr(response, "text", ""),
                )
        except Exception as exc:  # noqa: BLE001 — intentional swallow
            logger.warning("Telegram sendMessage failed: %s", exc)

    def on_entry(self, position: Position, market: Market) -> None:
        self._send(_format_entry(position, market))

    def on_resolution(self, position: Position, market: Market) -> None:
        self._send(_format_resolution(position, market))


def get_notifier() -> Notifier:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if token and chat_id:
        return TelegramNotifier(bot_token=token, chat_id=chat_id)
    return NullNotifier()
