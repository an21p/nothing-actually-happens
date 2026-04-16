import json
from unittest.mock import MagicMock, patch

from src.live.open_markets import fetch_open_markets


def _raw(cid: str, question: str = "Test question?", category: str = "Geopolitics") -> dict:
    return {
        "id": "1",
        "conditionId": cid,
        "slug": f"slug-{cid}",
        "question": question,
        "outcomes": json.dumps(["Yes", "No"]),
        "outcomePrices": json.dumps(["0.25", "0.75"]),
        "clobTokenIds": json.dumps([f"yes-{cid}", f"no-{cid}"]),
        "active": True,
        "closed": False,
        "createdAt": "2026-04-10T00:00:00.000000Z",
        "endDate": "2026-04-30T00:00:00Z",
        "category": category,
        "negRisk": False,
    }


@patch("src.live.open_markets.time.sleep")
@patch("src.live.open_markets.httpx.Client")
def test_fetch_open_markets_sends_active_open_filters(mock_client_cls, _sleep):
    response = MagicMock()
    response.status_code = 200
    response.json.side_effect = [[_raw("m1")], []]
    response.raise_for_status = MagicMock()
    client = MagicMock()
    client.get.return_value = response
    mock_client_cls.return_value = client

    results = fetch_open_markets()

    assert len(results) == 1
    assert results[0]["id"] == "m1"
    assert results[0]["resolution"] is None

    params = client.get.call_args_list[0][1]["params"]
    assert params["closed"] == "false"
    assert params["active"] == "true"
    assert params["archived"] == "false"


@patch("src.live.open_markets.time.sleep")
@patch("src.live.open_markets.httpx.Client")
def test_fetch_open_markets_filters_by_category(mock_client_cls, _sleep):
    response = MagicMock()
    response.status_code = 200
    response.json.side_effect = [
        [
            _raw("geo1", question="Geo question?", category="Geopolitics"),
            _raw("cult1", question="Culture question?", category="Pop Culture"),
        ],
        [],
    ]
    response.raise_for_status = MagicMock()
    client = MagicMock()
    client.get.return_value = response
    mock_client_cls.return_value = client

    results = fetch_open_markets(categories=["geopolitical"])

    assert [m["id"] for m in results] == ["geo1"]


@patch("src.live.open_markets.time.sleep")
@patch("src.live.open_markets.httpx.Client")
def test_fetch_open_markets_respects_limit(mock_client_cls, _sleep):
    response = MagicMock()
    response.status_code = 200
    response.json.side_effect = [
        [_raw("m1"), _raw("m2"), _raw("m3")],
    ]
    response.raise_for_status = MagicMock()
    client = MagicMock()
    client.get.return_value = response
    mock_client_cls.return_value = client

    results = fetch_open_markets(limit=2)
    assert len(results) == 2
