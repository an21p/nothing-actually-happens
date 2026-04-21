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
