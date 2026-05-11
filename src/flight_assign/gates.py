"""Gate filtering for ATL T and A-South (A1-A18).

The AeroVect snapshot exposes `gate` (e.g. "A14", "T7", "B23") and `pier`
(e.g. "A", "T", "B"). We trust `gate` as the source of truth since some
drops have a missing pier; pier is used as a fallback only.
"""

from __future__ import annotations

import re
from typing import Iterable

# A-South is A1..A18. A19+ is A-North and out of scope.
_A_SOUTH_MAX = 18

# Match an A or T gate prefix followed by digits and an optional letter suffix
# (e.g. "A14", "T7", "T11", "A2B" — rare but seen for split gates).
_GATE_RE = re.compile(r"^([AT])(\d+)([A-Z]?)$", re.IGNORECASE)


def is_target_gate(gate: str | None, pier: str | None = None) -> bool:
    """Return True if the gate is in T concourse or A-South (A1-A18)."""
    g = (gate or "").strip().upper()
    p = (pier or "").strip().upper()

    if g:
        m = _GATE_RE.match(g)
        if m:
            letter, number, _suffix = m.group(1), int(m.group(2)), m.group(3)
            if letter == "T":
                return True
            if letter == "A":
                return 1 <= number <= _A_SOUTH_MAX
            return False
        # Gate string is non-empty but malformed; refuse rather than guess.
        return False

    # No gate string. Fall back to pier — T pier counts entirely, but with no
    # gate number we can't safely include A pier (would risk A-North flights).
    return p == "T"


def filter_snapshots(snapshots: Iterable[dict]) -> list[dict]:
    """Keep snapshots whose gate is in T concourse or A-South."""
    return [s for s in snapshots if is_target_gate(s.get("gate"), s.get("pier"))]
