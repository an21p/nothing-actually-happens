from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from src.storage.models import Market, Position
from src.live.notifier import (
    NullNotifier,
    TelegramNotifier,
    get_notifier,
)


def _market() -> Market:
    return Market(
        id="0xtest",
        question="Will X happen by April 30, 2026?",
        category="geopolitical",
        no_token_id="tok",
        created_at=datetime(2026, 4, 10, tzinfo=timezone.utc),
        end_date=datetime(2026, 4, 30, tzinfo=timezone.utc),
        source_url="https://polymarket.com/event/will-x-happen",
    )


def _position(**overrides) -> Position:
    base = dict(
        market_id="0xtest",
        strategy="snapshot_24__earliest_deadline",
        executor="paper",
        status="open",
        entry_price=0.80,
        entry_timestamp=datetime(2026, 4, 11, tzinfo=timezone.utc),
        size_shares=125.0,
        size_notional=100.0,
        sizing_rule="fixed_notional",
        sizing_params_json='{"notional": 100.0}',
    )
    base.update(overrides)
    return Position(**base)


def test_null_notifier_is_no_op():
    n = NullNotifier()
    n.on_entry(_position(), _market())
    n.on_resolution(_position(status="resolved", exit_price=1.0, realized_pnl=25.0), _market())


@patch("src.live.notifier.httpx.post")
def test_telegram_notifier_sends_entry_message(mock_post):
    mock_post.return_value = MagicMock(status_code=200)
    n = TelegramNotifier(bot_token="secret", chat_id="chat-123")

    n.on_entry(_position(), _market())

    args, kwargs = mock_post.call_args
    url = args[0]
    assert "api.telegram.org/botsecret/sendMessage" in url
    body = kwargs["json"]
    assert body["chat_id"] == "chat-123"
    assert "ENTRY" in body["text"]
    assert "Will X happen" in body["text"]
    assert "0.80" in body["text"]


@patch("src.live.notifier.httpx.post")
def test_telegram_notifier_sends_resolution_message(mock_post):
    mock_post.return_value = MagicMock(status_code=200)
    n = TelegramNotifier(bot_token="secret", chat_id="chat-123")

    pos = _position(
        status="resolved",
        exit_price=1.0,
        exit_timestamp=datetime(2026, 4, 30, tzinfo=timezone.utc),
        realized_pnl=25.0,
    )
    n.on_resolution(pos, _market())

    args, kwargs = mock_post.call_args
    text = kwargs["json"]["text"]
    assert "RESOLVED" in text
    assert "25.00" in text or "$25" in text


@patch("src.live.notifier.httpx.post")
def test_telegram_notifier_swallows_errors(mock_post):
    mock_post.side_effect = RuntimeError("network down")
    n = TelegramNotifier(bot_token="secret", chat_id="chat-123")
    n.on_entry(_position(), _market())  # must not raise


@patch("src.live.notifier.httpx.post")
def test_telegram_notifier_swallows_non_200(mock_post):
    mock_post.return_value = MagicMock(status_code=403)
    n = TelegramNotifier(bot_token="secret", chat_id="chat-123")
    n.on_entry(_position(), _market())  # must not raise


def test_get_notifier_returns_null_when_env_missing(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert isinstance(get_notifier(), NullNotifier)


def test_get_notifier_returns_telegram_when_env_set(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "c")
    n = get_notifier()
    assert isinstance(n, TelegramNotifier)
    assert n.bot_token == "t"
    assert n.chat_id == "c"
