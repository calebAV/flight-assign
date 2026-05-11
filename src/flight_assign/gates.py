"""Gate filtering for ATL T and A-South (A1-A18)."""

from __future__ import annotations

import re
from typing import Iterable

from .aerovect import snapshot_gate, snapshot_pier

_A_SOUTH_MAX = 18
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
        return False

    return p == "T"


def filter_snapshots(snapshots: Iterable[dict]) -> list[dict]:
    """Keep snapshots whose gate is in T concourse or A-South.

    Uses snapshot_gate()/snapshot_pier() so we handle the documented
    `gate`/`pier` field names AND the actual production field names
    (`dptr_gate`, etc.).
    """
    return [
        s for s in snapshots
        if is_target_gate(snapshot_gate(s), snapshot_pier(s))
    ]
