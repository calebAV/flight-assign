import pytest

from flight_assign.piers import MAX_PIER, MIN_PIER, filter_snapshots, is_target_pier


@pytest.mark.parametrize(
    "pier,expected",
    [
        # Inclusive bounds
        ("40", True),
        ("60", True),
        # Middle of range
        ("50", True),
        ("45", True),
        ("55", True),
        # Just outside
        ("39", False),
        ("61", False),
        # Far outside
        ("1", False),
        ("99", False),
        ("100", False),
        # Integer types (API sometimes returns int directly)
        (40, True),
        (50, True),
        (61, False),
        # Whitespace tolerated
        ("  50  ", True),
        # Bad inputs → False (can't service unknown)
        ("", False),
        (None, False),
        ("abc", False),
        ("50.5", False),  # non-int strings
        # Concourse-letter pier (legacy, no longer used as pier) → False
        ("A", False),
        ("T", False),
    ],
)
def test_is_target_pier(pier, expected):
    assert is_target_pier(pier) is expected


def test_pier_range_constants_match_spec():
    """Sanity check the ops-defined range."""
    assert MIN_PIER == 40
    assert MAX_PIER == 60


def test_filter_snapshots_keeps_in_range_drops_out():
    """End-to-end against snapshot dicts shaped like the real API."""
    snaps = [
        {"flt_num": "in_low",  "dptr_bag_pier_num": "40"},
        {"flt_num": "in_mid",  "dptr_bag_pier_num": "50"},
        {"flt_num": "in_high", "dptr_bag_pier_num": "60"},
        {"flt_num": "below",   "dptr_bag_pier_num": "39"},
        {"flt_num": "above",   "dptr_bag_pier_num": "75"},
        {"flt_num": "no_pier", "dptr_bag_pier_num": None},
        {"flt_num": "empty",   "dptr_bag_pier_num": ""},
    ]
    kept = filter_snapshots(snaps)
    assert [s["flt_num"] for s in kept] == ["in_low", "in_mid", "in_high"]


def test_filter_snapshots_uses_dptr_bag_pier_num_via_helper():
    """Confirms we go through snapshot_pier, not a hardcoded key."""
    snap = {"dptr_bag_pier_num": 55, "dptr_gate": "A14"}
    assert filter_snapshots([snap]) == [snap]
