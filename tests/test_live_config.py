from src.live.config import LiveConfig, load_config


def test_load_config_defaults(monkeypatch):
    for key in [
        "LIVE_CATEGORIES",
        "LIVE_SIZING_RULE",
        "LIVE_SIZING_NOTIONAL",
        "LIVE_SIZING_SHARES",
        "LIVE_BANKROLL_START",
        "LIVE_MAX_OPEN_POSITIONS",
        "LIVE_EXECUTOR",
    ]:
        monkeypatch.delenv(key, raising=False)
    cfg = load_config()
    assert isinstance(cfg, LiveConfig)
    assert cfg.categories == ["geopolitical", "political", "culture"]
    assert cfg.sizing_rule == "fixed_shares"
    assert cfg.sizing_shares == 10.0
    assert cfg.sizing_notional == 10.0
    assert cfg.bankroll_start == 10_000.0
    assert cfg.max_open_positions == 50
    assert cfg.executor == "paper"
    assert cfg.max_age_hours == 24
    assert cfg.tolerance_hours == 12


def test_load_config_from_env(monkeypatch):
    monkeypatch.setenv("LIVE_CATEGORIES", "political")
    monkeypatch.setenv("LIVE_SIZING_RULE", "fixed_shares")
    monkeypatch.setenv("LIVE_SIZING_SHARES", "250")
    monkeypatch.setenv("LIVE_BANKROLL_START", "5000")
    monkeypatch.setenv("LIVE_MAX_OPEN_POSITIONS", "10")
    monkeypatch.setenv("LIVE_EXECUTOR", "paper")

    cfg = load_config()
    assert cfg.categories == ["political"]
    assert cfg.sizing_rule == "fixed_shares"
    assert cfg.sizing_shares == 250.0
    assert cfg.bankroll_start == 5000.0
    assert cfg.max_open_positions == 10
