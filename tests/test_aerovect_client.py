"""Tests for AeroVectClient.get_flights() with a mocked WebClient."""

from unittest.mock import MagicMock

from flight_assign.aerovect import AeroVectClient


def _make_client(response_body: dict):
    """Build an AeroVectClient whose underlying session.get returns
    `response_body` from .json(). Bypasses the real Auth0 call."""
    cli = AeroVectClient("cid", "csecret")
    cli._token = MagicMock(access_token="fake", expires_at_epoch=1e20)
    mock_resp = MagicMock()
    mock_resp.json.return_value = response_body
    mock_resp.raise_for_status.return_value = None
    cli._session = MagicMock()
    cli._session.get.return_value = mock_resp
    return cli


def test_get_flights_returns_inbound_and_outbound_arrays():
    cli = _make_client({
        "inbound": [{"flt_num": 100}],
        "outbound": [{"flt_num": 200}, {"flt_num": 201}],
    })
    body = cli.get_flights("ATL")
    assert isinstance(body, dict)
    assert [f["flt_num"] for f in body["outbound"]] == [200, 201]
    assert [f["flt_num"] for f in body["inbound"]] == [100]


def test_get_flights_handles_missing_keys_gracefully():
    """If the API returns just {}, we still return shaped lists."""
    cli = _make_client({})
    body = cli.get_flights("ATL")
    assert body == {"inbound": [], "outbound": []}


def test_get_flights_handles_null_arrays():
    cli = _make_client({"inbound": None, "outbound": None})
    body = cli.get_flights("ATL")
    assert body == {"inbound": [], "outbound": []}


def test_get_flights_passes_airport_param():
    cli = _make_client({"inbound": [], "outbound": []})
    cli.get_flights("ATL")
    call = cli._session.get.call_args
    assert call.kwargs["params"]["airport"] == "ATL"


def test_get_flights_includes_bearer_token():
    """We send the token even though /flights may accept anonymous calls —
    if AeroVect tightens auth, we're already covered."""
    cli = _make_client({"inbound": [], "outbound": []})
    cli.get_flights("ATL")
    headers = cli._session.get.call_args.kwargs["headers"]
    assert headers["Authorization"].startswith("Bearer ")
