"""Detect recent changes to a flight's gate / pier / time fields.

The AeroVect API tracks per-field update timestamps in `field_updated_at`.
If a tracked field was updated within the lookback window (a bit longer
than the cron interval, to forgive a skipped cycle), we flag the flight
in the Slack post so operators see the slip immediately.
"""

from __future__ import annotations

from typing import Iterable

MS_PER_MIN = 60_000

# Default: 15 min cron + 10 min buffer for a missed/late tick. Tunable
# via SLACK_CHANGE_LOOKBACK_MINUTES env var in main.py.
DEFAULT_LOOKBACK_MINUTES = 25

# Operationally meaningful changes the operator needs to see. Each value
# is the ordered list of API fields whose timestamps imply that kind of
# change. We check documented + actual names so the detector keeps
# working if AeroVect ever fixes the doc/data mismatch.
TRACKED_FIELDS: dict[str, tuple[str, ...]] = {
    "gate": ("dptr_gate", "gate"),
    "pier": ("dptr_bag_pier_num", "pier"),
    "time": ("est_out", "est_out_ms", "actual_out", "actual_out_ms",
             "sked_out", "sked_out_ms", "mission_time"),
}


def detect_changes(
    field_updated_at: dict,
    now_ms: int,
    *,
    lookback_minutes: int = DEFAULT_LOOKBACK_MINUTES,
) -> list[str]:
    """Return the ordered list of change categories (gate, pier, time)
    that were updated within the lookback window. Empty list if none."""
    if not field_updated_at:
        return []
    cutoff_ms = now_ms - lookback_minutes * MS_PER_MIN
    changes: list[str] = []
    for category, field_names in TRACKED_FIELDS.items():
        for fname in field_names:
            ts = field_updated_at.get(fname)
            if isinstance(ts, (int, float)) and ts >= cutoff_ms:
                changes.append(category)
                break  # one hit per category is enough
    return changes


def changes_summary(changes: Iterable[str]) -> str:
    """Render a parenthetical like '(gate, pier changed)' for the Slack
    post. Returns empty string when nothing changed."""
    items = list(changes)
    if not items:
        return ""
    return "(" + ", ".join(items) + " changed)"
