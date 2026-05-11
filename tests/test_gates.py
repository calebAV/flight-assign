import pytest

from flight_assign.gates import filter_snapshots, is_target_gate


@pytest.mark.parametrize(
    "gate,pier,expected",
    [
        # T concourse — all included
        ("T1", "T", True),
        ("T7", "T", True),
        ("T16", "T", True),
        # A-South boundary
        ("A1", "A", True),
        ("A14", "A", True),
        ("A18", "A", True),
        # A-North — excluded
        ("A19", "A", False),
        ("A22", "A", False),
        ("A30", "A", False),
        # Other concourses — excluded
        ("B14", "B", False),
        ("C5", "C", False),
        ("D10", "D", False),
        ("E1", "E", False),
        ("F3", "F", False),
        # Lowercase tolerated
        ("a5", "a", True),
        ("t9", "t", True),
        # Split gates like A2B (rare but valid)
        ("A2B", "A", True),
        # Malformed gate strings → reject
        ("", "A", False),
        ("???", "A", False),
        ("A", "A", False),
        # No gate → always reject (pier is no longer a concourse letter)
        (None, "T", False),
        (None, "A", False),
        ("", "", False),
    ],
)
def test_is_target_gate(gate, pier, expected):
    assert is_target_gate(gate, pier) is expected


def test_filter_snapshots_drops_non_target():
    snaps = [
        {"gate": "A14", "pier": "A", "flt_num": "1"},
        {"gate": "A19", "pier": "A", "flt_num": "2"},
        {"gate": "T7", "pier": "T", "flt_num": "3"},
        {"gate": "B14", "pier": "B", "flt_num": "4"},
    ]
    kept = filter_snapshots(snaps)
    nums = [s["flt_num"] for s in kept]
    assert nums == ["1", "3"]
