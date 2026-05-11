"""Assignment engine: round-robin by load with a 12-minute spacing constraint.

Rules:
- haulout_ms = mission_time_ms - 55 minutes
- Flights whose haulout has already passed are skipped (treated as already
  handled by a previous post; per product decision).
- For each remaining flight, in haulout order, find operators whose last
  haulout was at least MIN_GAP_MINUTES earlier. Among eligible, pick the
  one with the fewest assignments so far. Ties: longest-waiting operator.
- If no operator is eligible, the flight is recorded as unassigned (the
  message formatter will surface this).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from .roster import Operator

HAULOUT_LEAD_MINUTES = 55
MIN_GAP_MINUTES = 12

MS_PER_MIN = 60_000


@dataclass(frozen=True)
class Flight:
    flight_key: str
    flt_num: str
    airline: str
    dest: str
    gate: str
    pier: str
    departure_ms: int  # mission_time_ms
    time_type: str  # "A", "E", or "S"

    @property
    def haulout_ms(self) -> int:
        return self.departure_ms - HAULOUT_LEAD_MINUTES * MS_PER_MIN


@dataclass
class Assignment:
    flight: Flight
    operator: Operator | None  # None when no eligible operator


@dataclass
class AssignmentResult:
    assigned: list[Assignment] = field(default_factory=list)
    unassigned: list[Flight] = field(default_factory=list)

    def by_operator(self) -> dict[str, list[Assignment]]:
        out: dict[str, list[Assignment]] = {}
        for a in self.assigned:
            if a.operator is None:
                continue
            out.setdefault(a.operator.name, []).append(a)
        for ops in out.values():
            ops.sort(key=lambda a: a.flight.haulout_ms)
        return out


def snapshot_to_flight(snap: dict) -> Flight | None:
    """Build a Flight from a /nexus/snapshots row. Returns None if unusable.

    Uses the snapshot_gate/snapshot_pier/snapshot_airline helpers so we
    pick up the actual field names the API returns (dptr_gate etc.) and
    fall back to "DL" for airline since the endpoint is Delta-only.
    """
    from .aerovect import snapshot_airline, snapshot_gate, snapshot_pier

    departure_ms = snap.get("mission_time")
    if not isinstance(departure_ms, int):
        return None
    return Flight(
        flight_key=snap.get("flight_key") or "",
        flt_num=str(snap.get("flt_num") or ""),
        airline=snapshot_airline(snap, default="DL"),
        dest=str(snap.get("leg_dest_ap_cde") or ""),
        gate=snapshot_gate(snap),
        pier=snapshot_pier(snap),
        departure_ms=int(departure_ms),
        time_type=str(snap.get("time_type") or "S"),
    )


def assign_flights(
    flights: Iterable[Flight],
    operators: Iterable[Operator],
    now_ms: int,
    *,
    min_gap_minutes: int = MIN_GAP_MINUTES,
) -> AssignmentResult:
    """Assign flights to operators.

    Args:
        flights: candidate flights (already filtered to target gates).
        operators: on-shift operators.
        now_ms: epoch ms representing "now"; past haulouts are skipped.
        min_gap_minutes: minimum minutes between consecutive haulouts for the
            same operator.

    Returns AssignmentResult.
    """
    operators = list(operators)
    result = AssignmentResult()
    if not operators:
        # Nothing to assign against; treat every future flight as unassigned.
        for f in sorted(flights, key=lambda x: x.haulout_ms):
            if f.haulout_ms >= now_ms:
                result.unassigned.append(f)
        return result

    # Track last-haulout-ms per operator and assignment count.
    last_haulout: dict[str, int] = {op.name: -10**15 for op in operators}
    load: dict[str, int] = {op.name: 0 for op in operators}

    future_flights = [f for f in flights if f.haulout_ms >= now_ms]
    future_flights.sort(key=lambda f: (f.haulout_ms, f.flt_num))

    min_gap_ms = min_gap_minutes * MS_PER_MIN

    for flight in future_flights:
        eligible: list[Operator] = [
            op
            for op in operators
            if flight.haulout_ms - last_haulout[op.name] >= min_gap_ms
        ]
        if not eligible:
            result.unassigned.append(flight)
            continue

        # Round-robin by load: fewest assignments wins.
        # Tiebreak: longest-waiting (smallest last_haulout).
        # Final tiebreak: name, for deterministic output.
        eligible.sort(
            key=lambda op: (load[op.name], last_haulout[op.name], op.name)
        )
        chosen = eligible[0]
        result.assigned.append(Assignment(flight=flight, operator=chosen))
        last_haulout[chosen.name] = flight.haulout_ms
        load[chosen.name] += 1

    return result
