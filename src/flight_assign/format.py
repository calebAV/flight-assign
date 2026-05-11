"""Format an AssignmentResult into a Slack message body."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from .assign import Assignment, AssignmentResult, Flight
from .changes import changes_summary
from .roster import Operator

ATLANTA_TZ = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class ScheduleSource:
    """Provenance for the schedule used in a cycle."""
    week_of: str | None
    permalink: str | None
    expected_week: str | None


@dataclass(frozen=True)
class FeedHealth:
    """Diagnostic snapshot of the AeroVect feed for this cycle.

    `total` is the snapshot count from the API. `partial` is how many
    came back with a PARTIAL flight_key (Delta hasn't sent augmented
    columns yet). When partial == total, we can't filter by gate or
    airline because those fields don't exist.
    """
    total: int
    partial: int

    @property
    def all_partial(self) -> bool:
        return self.total > 0 and self.partial == self.total

    @property
    def partial_ratio(self) -> float:
        return self.partial / self.total if self.total else 0.0


def _fmt_time(epoch_ms: int) -> str:
    dt = datetime.fromtimestamp(epoch_ms / 1000.0, tz=timezone.utc).astimezone(ATLANTA_TZ)
    return dt.strftime("%H:%M")


def _time_type_tag(t: str) -> str:
    return {"A": "actual", "E": "est", "S": "sked"}.get(t, "sked")


def _flight_line(a: Assignment, changes: list[str] | None = None) -> str:
    f: Flight = a.flight
    bullet = "  • "
    suffix = ""
    if changes:
        bullet = "  • :warning: "
        suffix = f"  _{changes_summary(changes)}_"
    return (
        f"{bullet}{_fmt_time(f.haulout_ms)} haulout → "
        f"{_fmt_time(f.departure_ms)} dep ({_time_type_tag(f.time_type)})  "
        f"{f.airline}{f.flt_num} → {f.dest}  "
        f"pier {f.pier or '?'} / gate {f.gate or '?'}"
        f"{suffix}"
    )


def _source_line(src: ScheduleSource | None) -> str | None:
    if src is None:
        return None
    bits: list[str] = []
    if src.week_of:
        bits.append(f"weekOf={src.week_of}")
    if src.expected_week and src.week_of and src.week_of != src.expected_week:
        bits.append(f"⚠ expected {src.expected_week} — schedule may be stale")
    label = " · ".join(bits) if bits else "schedule"
    if src.permalink:
        return f"_Schedule: <{src.permalink}|{label}>_"
    return f"_Schedule: {label}_"


def _feed_health_line(health: FeedHealth | None) -> str | None:
    if health is None or health.total == 0:
        return None
    if health.all_partial:
        return (
            f":warning: *Data feed degraded* — none of the {health.total} "
            f"flights in window have a usable gate. No assignments possible. "
            f"Contact AeroVect support."
        )
    if health.partial_ratio >= 0.5:
        return (
            f":warning: {health.partial} of {health.total} flights have no "
            f"usable gate ({int(round(health.partial_ratio*100))}%) — "
            f"assignments limited."
        )
    return None


def format_message(
    result: AssignmentResult,
    operators_on_shift: list[Operator],
    *,
    now_utc: datetime | None = None,
    schedule_source: ScheduleSource | None = None,
    feed_health: FeedHealth | None = None,
    change_map: dict[str, list[str]] | None = None,
) -> str:
    """`change_map` is flight_key -> list of changed categories
    (e.g. {"k-1234": ["gate"]}). Lines for flights with non-empty
    entries get a :warning: prefix and a parenthetical."""
    """Build the Slack message body for this cycle."""
    now_utc = now_utc or datetime.now(timezone.utc)
    header_time = now_utc.astimezone(ATLANTA_TZ).strftime("%a %b %d, %H:%M ET")

    lines: list[str] = []
    lines.append(f"*Flight Assignments* — {header_time}")
    lines.append(
        f"Window: Delta ATL outbound, T concourse and A-South (A1–A18). "
        f"Haulout = departure − 55 min."
    )
    src = _source_line(schedule_source)
    if src:
        lines.append(src)
    health = _feed_health_line(feed_health)
    if health:
        lines.append(health)
    lines.append("")

    by_op = result.by_operator()
    if not operators_on_shift:
        lines.append("_No operators currently on shift — no assignments produced._")
        return "\n".join(lines)

    for op in operators_on_shift:
        assignments = by_op.get(op.name, [])
        role_tag = "" if op.role == "Production" else f"  _({op.role})_"
        if not assignments:
            lines.append(f"*{op.name}*{role_tag}")
            lines.append("  • _no flights this cycle_")
        else:
            lines.append(f"*{op.name}*{role_tag}  — {len(assignments)} flight"
                         f"{'s' if len(assignments) != 1 else ''}")
            for a in assignments:
                ch = (change_map or {}).get(a.flight.flight_key) or []
                lines.append(_flight_line(a, ch))
        lines.append("")

    if result.unassigned:
        lines.append("*Unassigned* (no operator within 12-min spacing rule)")
        for f in result.unassigned:
            lines.append(
                f"  • {_fmt_time(f.haulout_ms)} haulout → "
                f"{_fmt_time(f.departure_ms)} dep  "
                f"{f.airline}{f.flt_num} → {f.dest}  "
                f"pier {f.pier or '?'} / gate {f.gate or '?'}"
            )

    return "\n".join(lines).rstrip() + "\n"
