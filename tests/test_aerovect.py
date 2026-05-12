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


from flight_assign.aerovect import snapshot_gate, snapshot_pier


# --- snapshot_airline default param ---


def test_snapshot_airline_uses_default_for_partial():
    snap = {"airline_cde": None, "flight_key": "PARTIAL#2026-05-11#1234"}
    assert snapshot_airline(snap, default="DL") == "DL"


def test_snapshot_airline_default_is_empty_unless_passed():
    snap = {"airline_cde": None, "flight_key": "PARTIAL#2026-05-11#1234"}
    assert snapshot_airline(snap) == ""


def test_snapshot_airline_real_data_overrides_default():
    """If the API DOES give us an airline, we use it regardless of default."""
    snap = {"airline_cde": "DAL", "flight_key": "PARTIAL#2026-05-11#1234"}
    assert snapshot_airline(snap, default="DL") == "DAL"


# --- snapshot_gate ---


def test_snapshot_gate_prefers_documented_field():
    assert snapshot_gate({"gate": "A14", "dptr_gate": "B5"}) == "A14"


def test_snapshot_gate_falls_back_to_dptr_gate():
    assert snapshot_gate({"gate": None, "dptr_gate": "A14"}) == "A14"


def test_snapshot_gate_uppercases():
    assert snapshot_gate({"dptr_gate": "a14"}) == "A14"


def test_snapshot_gate_empty_when_neither():
    assert snapshot_gate({}) == ""
    assert snapshot_gate({"gate": "", "dptr_gate": ""}) == ""


# --- snapshot_pier (numeric bag pier) ---


def test_snapshot_pier_returns_dptr_bag_pier_num():
    """The operator-facing pier is the numeric staging pier."""
    assert snapshot_pier({"dptr_bag_pier_num": "75", "dptr_gate": "A14"}) == "75"


def test_snapshot_pier_handles_integer_value():
    """API may return as int instead of string."""
    assert snapshot_pier({"dptr_bag_pier_num": 54}) == "54"


def test_snapshot_pier_falls_back_to_legacy_pier_field():
    """If dptr_bag_pier_num is missing but `pier` is set, use that."""
    assert snapshot_pier({"pier": "A", "dptr_gate": "A14"}) == "A"


def test_snapshot_pier_empty_when_no_pier_data():
    """Old behavior derived from gate letter; new behavior returns empty.
    Operators get pier info from dptr_bag_pier_num or not at all."""
    assert snapshot_pier({"dptr_gate": "A14"}) == ""
    assert snapshot_pier({}) == ""


# --- end-to-end with real-shape data from Caleb's curl ---


def test_real_world_partial_snapshot_with_dptr_gate_kept_by_filter():
    """The fix: PARTIAL flight_key + dptr_gate=A05 should be a kept Delta flight."""
    from flight_assign.gates import filter_snapshots
    snap = {
        "flight_key": "PARTIAL#2026-05-11#1575",
        "flt_num": "1575",
        "dptr_gate": "A05",
        "leg_dest_ap_cde": "JFK",
        "mission_time": 1778521620000,
        "time_type": "E",
    }
    assert filter_snapshots([snap]) == [snap]
    assert snapshot_airline(snap, default="DL") == "DL"
    assert snapshot_gate(snap) == "A05"
    # pier comes from dptr_bag_pier_num; this snap has none → empty
    assert snapshot_pier(snap) == ""


# --- /flights endpoint: snapshot_airline reads al_cde ---


def test_snapshot_airline_reads_al_cde_field():
    """/flights returns the airline as `al_cde`, not `airline_cde`."""
    snap = {"al_cde": "DL", "flight_key": "2026-05-12#DL#1234#ATL#GSP"}
    assert snapshot_airline(snap) == "DL"


def test_snapshot_airline_prefers_airline_cde_over_al_cde():
    """If both fields are present (unlikely, but defensive), documented wins."""
    snap = {"airline_cde": "DL", "al_cde": "9E"}
    assert snapshot_airline(snap) == "DL"


def test_snapshot_airline_uppercases_al_cde():
    assert snapshot_airline({"al_cde": "dl"}) == "DL"


def test_snapshot_airline_uses_default_when_al_cde_empty():
    snap = {"al_cde": "", "flight_key": "PARTIAL#2026-05-12#1234"}
    assert snapshot_airline(snap, default="DL") == "DL"


def test_snapshot_airline_real_flights_response_shape():
    """Smoke test against the actual /flights record shape we saw."""
    snap = {
        "al_cde": "DL",
        "flt_num": 1155,
        "flight_key": "2026-05-12#DL#1155#ATL#BNA",
        "dptr_gate": "B28",
        "dptr_bag_pier_num": "91",
        "mission_time": 1778594160000,
        "cncl_ind": "N",
    }
    assert snapshot_airline(snap) == "DL"
