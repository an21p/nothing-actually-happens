from pathlib import Path

import pytest

from src.live.config import LiveConfig, StrategyConfig, load_config


def _write_config(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "live_config.yaml"
    path.write_text(text)
    return path


def test_load_config_full_shape(tmp_path, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    path = _write_config(
        tmp_path,
        """
categories: [geopolitical]
tolerance_hours: 12
executor: paper
strategies:
  snapshot_24__earliest_created:
    starting_bankroll: 1000.0
    shares_per_trade: 10.0
  threshold_0.3__earliest_created:
    starting_bankroll: 500.0
    shares_per_trade: 5.0
""",
    )
    cfg = load_config(path)
    assert isinstance(cfg, LiveConfig)
    assert cfg.categories == ["geopolitical"]
    assert cfg.tolerance_hours == 12
    assert cfg.executor == "paper"
    assert set(cfg.strategies.keys()) == {
        "snapshot_24__earliest_created",
        "threshold_0.3__earliest_created",
    }
    snap = cfg.strategies["snapshot_24__earliest_created"]
    assert isinstance(snap, StrategyConfig)
    assert snap.label == "snapshot_24__earliest_created"
    assert snap.starting_bankroll == 1000.0
    assert snap.shares_per_trade == 10.0
    thr = cfg.strategies["threshold_0.3__earliest_created"]
    assert thr.starting_bankroll == 500.0
    assert thr.shares_per_trade == 5.0
    assert cfg.telegram_bot_token is None
    assert cfg.telegram_chat_id is None


def test_load_config_pulls_telegram_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "abc123")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "999")
    path = _write_config(
        tmp_path,
        """
categories: [geopolitical]
tolerance_hours: 12
executor: paper
strategies: {}
""",
    )
    cfg = load_config(path)
    assert cfg.telegram_bot_token == "abc123"
    assert cfg.telegram_chat_id == "999"


def test_load_config_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "does_not_exist.yaml")


def test_load_config_rejects_missing_required_keys(tmp_path):
    path = _write_config(tmp_path, "categories: [geopolitical]\n")
    with pytest.raises(KeyError):
        load_config(path)
