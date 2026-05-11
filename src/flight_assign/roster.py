"""Roster: read most recent WEEKLY_SCHEDULE_JSON from #flight-assign,
resolve who's on shift right now in Atlanta local time.

The schedule format is owned by the schedule-converter skill:
{
  "weekOf": "YYYY-MM-DD",
  "days": {
    "monday": {
      "shift1": [{"name": "...", "role": "Production"}, ...],
      "shift2": [...]
    }, ...
  }
}

Shift hours (Atlanta local / ET):
  shift1 = 05:30 -> 14:00
  shift2 = 14:00 -> 22:00
Outside those windows we return no operators (cron will skip posting).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, time, timezone
from typing import Iterable
from zoneinfo import ZoneInfo

ATLANTA_TZ = ZoneInfo("America/New_York")

SHIFT1_START = time(5, 30)
SHIFT1_END = time(14, 0)
SHIFT2_START = time(14, 0)
SHIFT2_END = time(22, 0)

_WEEKDAY_NAMES = [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
]

# Captures the JSON body inside a triple-backtick block following the
# "WEEKLY_SCHEDULE_JSON" header. Tolerates an optional ```json language hint.
_SCHEDULE_RE = re.compile(
    r"WEEKLY_SCHEDULE_JSON\s*```(?:json)?\s*(\{.*?\})\s*```",
    re.DOTALL,
)


@dataclass(frozen=True)
class Operator:
    name: str
    role: str  # "Production" or "Reserve"


def current_shift_key(now_utc: datetime | None = None) -> str | None:
    """Return 'shift1', 'shift2', or None based on Atlanta local time."""
    now_utc = now_utc or datetime.now(timezone.utc)
    local = now_utc.astimezone(ATLANTA_TZ).time()
    if SHIFT1_START <= local < SHIFT1_END:
        return "shift1"
    if SHIFT2_START <= local < SHIFT2_END:
        return "shift2"
    return None


def current_weekday_key(now_utc: datetime | None = None) -> str:
    """Lowercase weekday name in Atlanta local time."""
    now_utc = now_utc or datetime.now(timezone.utc)
    return _WEEKDAY_NAMES[now_utc.astimezone(ATLANTA_TZ).weekday()]


def parse_schedule_message(text: str) -> dict | None:
    """Extract the WEEKLY_SCHEDULE_JSON object from a Slack message body."""
    m = _SCHEDULE_RE.search(text or "")
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def find_latest_schedule(messages: Iterable[dict]) -> dict | None:
    """Given Slack messages (newest first), return the first parsed schedule.

    Each message is expected to be a dict with a 'text' field; that matches the
    shape `conversations.history` returns.
    """
    for msg in messages:
        text = msg.get("text") or ""
        sched = parse_schedule_message(text)
        if sched is not None:
            return sched
    return None


def operators_on_shift(
    schedule: dict,
    now_utc: datetime | None = None,
) -> list[Operator]:
    """Return the operators on shift right now, based on the schedule JSON."""
    shift_key = current_shift_key(now_utc)
    if shift_key is None:
        return []
    day_key = current_weekday_key(now_utc)
    day = (schedule.get("days") or {}).get(day_key) or {}
    raw = day.get(shift_key) or []
    out: list[Operator] = []
    for entry in raw:
        name = (entry or {}).get("name")
        role = (entry or {}).get("role", "Production")
        if not name:
            continue
        out.append(Operator(name=name, role=role))
    return out
