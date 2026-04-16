from src.live.config import LiveConfig, load_config


def test_load_config_defaults(monkeypatch):
    for key in [
        "LIVE_CATEGORIES",
        "LIVE_SIZING_RULE",
        "LIVE_SIZING_NOTIONAL",
        "LIVE_SIZING_SHARES",
        "LIVE_SIZING_KELLY_WIN_RATE",
        "LIVE_SIZING_KELLY_FRACTION",
        "LIVE_BANKROLL_START",
        "LIVE_MAX_OPEN_POSITIONS",
        "LIVE_EXECUTOR",
    ]:
        monkeypatch.delenv(key, raising=False)
    cfg = load_config()
    assert isinstance(cfg, LiveConfig)
    assert cfg.categories == ["geopolitical", "political", "culture"]
    assert cfg.sizing_rule == "fixed_notional"
    assert cfg.sizing_notional == 100.0
    assert cfg.bankroll_start == 10_000.0
    assert cfg.max_open_positions == 50
    assert cfg.executor == "paper"
    assert cfg.max_age_hours == 24
    assert cfg.tolerance_hours == 12


def test_load_config_from_env(monkeypatch):
    monkeypatch.setenv("LIVE_CATEGORIES", "political")
    monkeypatch.setenv("LIVE_SIZING_RULE", "kelly")
    monkeypatch.setenv("LIVE_SIZING_KELLY_WIN_RATE", "0.82")
    monkeypatch.setenv("LIVE_SIZING_KELLY_FRACTION", "0.10")
    monkeypatch.setenv("LIVE_BANKROLL_START", "5000")
    monkeypatch.setenv("LIVE_MAX_OPEN_POSITIONS", "10")
    monkeypatch.setenv("LIVE_EXECUTOR", "paper")

    cfg = load_config()
    assert cfg.categories == ["political"]
    assert cfg.sizing_rule == "kelly"
    assert cfg.kelly_win_rate == 0.82
    assert cfg.kelly_fraction == 0.10
    assert cfg.bankroll_start == 5000.0
    assert cfg.max_open_positions == 10
