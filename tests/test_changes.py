"""Tests for the change-detection module."""

from flight_assign.changes import (
    DEFAULT_LOOKBACK_MINUTES,
    changes_summary,
    detect_changes,
)

MIN_MS = 60_000
NOW = 10_000_000_000


def test_detects_recent_gate_change():
    fua = {"dptr_gate": NOW - 5 * MIN_MS}  # 5 min ago
    assert detect_changes(fua, NOW) == ["gate"]


def test_does_not_flag_old_change():
    fua = {"dptr_gate": NOW - 60 * MIN_MS}  # 1 hour ago, beyond lookback
    assert detect_changes(fua, NOW) == []


def test_detects_pier_change():
    fua = {"dptr_bag_pier_num": NOW - 3 * MIN_MS}
    assert detect_changes(fua, NOW) == ["pier"]


def test_detects_time_change_via_est_out():
    fua = {"est_out": NOW - 2 * MIN_MS}
    assert detect_changes(fua, NOW) == ["time"]


def test_detects_time_change_via_actual_out():
    fua = {"actual_out": NOW - 1 * MIN_MS}
    assert detect_changes(fua, NOW) == ["time"]


def test_detects_multiple_changes_in_consistent_order():
    fua = {
        "dptr_gate": NOW - 1 * MIN_MS,
        "dptr_bag_pier_num": NOW - 2 * MIN_MS,
        "est_out": NOW - 3 * MIN_MS,
    }
    # Order matches TRACKED_FIELDS dict: gate, pier, time
    assert detect_changes(fua, NOW) == ["gate", "pier", "time"]


def test_handles_documented_alternative_field_names():
    """API doc names should also trigger (gate, pier) per the doc."""
    fua = {"gate": NOW - 1 * MIN_MS, "pier": NOW - 2 * MIN_MS}
    assert detect_changes(fua, NOW) == ["gate", "pier"]


def test_lookback_at_exact_boundary_is_inclusive():
    """A field updated EXACTLY `lookback_minutes` ago is still flagged."""
    fua = {"dptr_gate": NOW - DEFAULT_LOOKBACK_MINUTES * MIN_MS}
    assert detect_changes(fua, NOW) == ["gate"]


def test_custom_lookback_minutes_narrows_window():
    fua = {"dptr_gate": NOW - 20 * MIN_MS}
    assert detect_changes(fua, NOW, lookback_minutes=10) == []
    assert detect_changes(fua, NOW, lookback_minutes=25) == ["gate"]


def test_empty_or_missing_field_updated_at():
    assert detect_changes({}, NOW) == []
    assert detect_changes(None, NOW) == []


def test_non_numeric_timestamps_ignored():
    fua = {"dptr_gate": "yesterday", "dptr_bag_pier_num": None}
    assert detect_changes(fua, NOW) == []


def test_changes_summary_renders_humanly():
    assert changes_summary([]) == ""
    assert changes_summary(["gate"]) == "(gate changed)"
    assert changes_summary(["gate", "pier"]) == "(gate, pier changed)"
    assert changes_summary(["gate", "pier", "time"]) == "(gate, pier, time changed)"
