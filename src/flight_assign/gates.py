"""Gate filtering for ATL T and A-South (A1-A18).

The pier argument used to participate in filtering as a concourse-letter
fallback, but pier is now a numeric bag-staging ID (dptr_bag_pier_num).
The concourse is always derived from the gate string itself.
"""

from __future__ import annotations

import re
from typing import Iterable

from .aerovect import snapshot_gate

_A_SOUTH_MAX = 18
_GATE_RE = re.compile(r"^([AT])(\d+)([A-Z]?)$", re.IGNORECASE)


def is_target_gate(gate: str | None, pier: str | None = None) -> bool:
    """Return True if the gate is in T concourse or A-South (A1-A18).

    `pier` is accepted for backward compatibility but no longer used —
    it's a numeric staging ID now. Concourse is read from the gate
    string only.
    """
    g = (gate or "").strip().upper()
    if not g:
        return False
    m = _GATE_RE.match(g)
    if not m:
        return False
    letter, number, _suffix = m.group(1), int(m.group(2)), m.group(3)
    if letter == "T":
        return True
    if letter == "A":
        return 1 <= number <= _A_SOUTH_MAX
    return False


def filter_snapshots(snapshots: Iterable[dict]) -> list[dict]:
    """Keep snapshots whose gate is in T concourse or A-South."""
    return [s for s in snapshots if is_target_gate(snapshot_gate(s))]
