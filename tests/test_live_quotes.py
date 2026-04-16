from unittest.mock import MagicMock, patch

from src.live.quotes import fetch_midpoint, fetch_midpoints_batch


@patch("src.live.quotes.httpx.Client")
def test_fetch_midpoint_returns_float(mock_client_cls):
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"mid": "0.545"}
    response.raise_for_status = MagicMock()
    client = MagicMock()
    client.get.return_value = response
    mock_client_cls.return_value.__enter__.return_value = client

    result = fetch_midpoint("token_abc")

    assert result == 0.545
    called_url, called_kwargs = client.get.call_args
    assert "midpoint" in called_url[0]
    assert called_kwargs["params"] == {"token_id": "token_abc"}


@patch("src.live.quotes.httpx.Client")
def test_fetch_midpoint_returns_none_on_404(mock_client_cls):
    response = MagicMock()
    response.status_code = 404
    response.raise_for_status = MagicMock()
    client = MagicMock()
    client.get.return_value = response
    mock_client_cls.return_value.__enter__.return_value = client

    assert fetch_midpoint("no_such_token") is None


@patch("src.live.quotes.httpx.Client")
def test_fetch_midpoints_batch_maps_responses(mock_client_cls):
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = [
        {"token_id": "aaa", "mid": "0.40"},
        {"token_id": "bbb", "mid": "0.80"},
    ]
    response.raise_for_status = MagicMock()
    client = MagicMock()
    client.post.return_value = response
    mock_client_cls.return_value.__enter__.return_value = client

    result = fetch_midpoints_batch(["aaa", "bbb"])

    assert result == {"aaa": 0.40, "bbb": 0.80}
    args, kwargs = client.post.call_args
    assert "midpoints" in args[0]
    assert kwargs["json"] == [{"token_id": "aaa"}, {"token_id": "bbb"}]


@patch("src.live.quotes.httpx.Client")
def test_fetch_midpoints_batch_empty_input_short_circuits(mock_client_cls):
    result = fetch_midpoints_batch([])
    assert result == {}
    mock_client_cls.assert_not_called()
