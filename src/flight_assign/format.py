"""Format an AssignmentResult into a Slack message body.

We emit a plain-text message so it remains greppable and copy/pasteable.
Times are rendered in Atlanta local time.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from .assign import Assignment, AssignmentResult, Flight
from .roster import Operator

ATLANTA_TZ = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class ScheduleSource:
    """Provenance for the schedule used in a cycle. Shown in the post header
    so operators can verify the bot is reading the right roster."""
    week_of: str | None
    permalink: str | None
    expected_week: str | None  # current Atlanta-local Monday for comparison


def _fmt_time(epoch_ms: int) -> str:
    dt = datetime.fromtimestamp(epoch_ms / 1000.0, tz=timezone.utc).astimezone(ATLANTA_TZ)
    return dt.strftime("%H:%M")


def _time_type_tag(t: str) -> str:
    return {"A": "actual", "E": "est", "S": "sked"}.get(t, "sked")


def _flight_line(a: Assignment) -> str:
    f: Flight = a.flight
    return (
        f"  • {_fmt_time(f.haulout_ms)} haulout → "
        f"{_fmt_time(f.departure_ms)} dep ({_time_type_tag(f.time_type)})  "
        f"{f.airline}{f.flt_num} → {f.dest}  "
        f"pier {f.pier or '?'} / gate {f.gate or '?'}"
    )


def _source_line(src: ScheduleSource | None) -> str | None:
    """Return a small italic note showing which schedule was used."""
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


def format_message(
    result: AssignmentResult,
    operators_on_shift: list[Operator],
    *,
    now_utc: datetime | None = None,
    schedule_source: ScheduleSource | None = None,
) -> str:
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
                lines.append(_flight_line(a))
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
