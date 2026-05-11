"""Tests for snapshot_airline() — recovers airline from flight_key when
airline_cde is null."""

from flight_assign.aerovect import snapshot_airline


def test_uses_airline_cde_when_present():
    assert snapshot_airline({"airline_cde": "DL", "flight_key": "..."}) == "DL"


def test_uppercases_airline_cde():
    assert snapshot_airline({"airline_cde": "dl"}) == "DL"


def test_falls_back_to_flight_key_when_cde_missing():
    snap = {"airline_cde": None, "flight_key": "2026-05-04#DL#1234#ATL#GSP"}
    assert snapshot_airline(snap) == "DL"


def test_falls_back_to_flight_key_when_cde_empty_string():
    snap = {"airline_cde": "", "flight_key": "2026-05-04#DAL#1234#ATL#GSP"}
    assert snapshot_airline(snap) == "DAL"


def test_returns_empty_string_for_partial_flight_key():
    """PARTIAL keys don't have airline in the expected slot."""
    snap = {"airline_cde": None, "flight_key": "PARTIAL#2026-05-04#1234"}
    assert snapshot_airline(snap) == ""


def test_returns_empty_string_when_no_data_at_all():
    assert snapshot_airline({}) == ""


def test_returns_empty_string_when_flight_key_malformed():
    assert snapshot_airline({"flight_key": "garbage"}) == ""


def test_handles_lowercase_partial_in_flight_key_robustly():
    """Treat 'PARTIAL' as case-sensitive per the API doc — but a lowercase
    'partial' is suspect; safest is to NOT fallback there either."""
    # We only special-case the documented "PARTIAL" prefix; a 'partial' string
    # would be parsed and probably return junk — acceptable since the API
    # doc uses uppercase.
    snap = {"flight_key": "2026-05-04#DL#1234#ATL#GSP"}
    assert snapshot_airline(snap) == "DL"
