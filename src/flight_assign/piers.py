"""Pier range filtering.

We only service piers 40-60 (inclusive). Flights at piers outside that
range — or flights with no usable pier number — are excluded.

The pier value comes from snapshot_pier() (which prefers
`dptr_bag_pier_num` over the legacy `pier` field).
"""

from __future__ import annotations

from typing import Iterable

from .aerovect import snapshot_pier

# Configurable range. Inclusive on both ends. Edit here if ops expands the
# serviced area; the rest of the code reads from these constants.
MIN_PIER = 40
MAX_PIER = 60


def is_target_pier(pier: str | int | None) -> bool:
    """Return True if `pier` parses as an int inside [MIN_PIER, MAX_PIER]."""
    if pier is None:
        return False
    try:
        n = int(str(pier).strip())
    except (TypeError, ValueError):
        return False
    return MIN_PIER <= n <= MAX_PIER


def filter_snapshots(snapshots: Iterable[dict]) -> list[dict]:
    """Keep snapshots whose pier is in [MIN_PIER, MAX_PIER]."""
    return [s for s in snapshots if is_target_pier(snapshot_pier(s))]
