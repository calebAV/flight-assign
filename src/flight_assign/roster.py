"""Roster: read most recent WEEKLY_SCHEDULE_JSON from a Slack channel,
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
import logging
import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta as _td, timezone
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

# Marker required at the top of a schedule message.
_HEADER_RE = re.compile(r"WEEKLY_SCHEDULE_JSON", re.IGNORECASE)

# Slack and macOS auto-curlify straight quotes in some clients. Normalize
# them to straight quotes before handing to json.loads.
_SMART_QUOTE_MAP = str.maketrans({
    "“": '"',  # left double curly  "
    "”": '"',  # right double curly "
    "„": '"',  # double low-9       „
    "‟": '"',  # double high-reversed
    "‘": "'",  # left single curly  '
    "’": "'",  # right single curly '
    "‚": "'",  # single low-9
    "‛": "'",  # single high-reversed
    "«": '"',  # left guillemet  «
    "»": '"',  # right guillemet »
})

log = logging.getLogger(__name__)


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


def current_week_monday(now_utc: datetime | None = None) -> str:
    """Return YYYY-MM-DD for the Monday of the current Atlanta-local week.

    Kept around as a utility even though the schedule resolver no longer
    filters by it — useful for logging which week is "expected."
    """
    now_utc = now_utc or datetime.now(timezone.utc)
    local = now_utc.astimezone(ATLANTA_TZ).date()
    monday = local - _td(days=local.weekday())
    return monday.strftime("%Y-%m-%d")


def _first_balanced_json_object(text: str, start: int) -> dict | None:
    """Walk `text` starting at index `start`, find the next `{...}` with
    balanced braces (respecting JSON strings), return the parsed object.
    Returns None on no match or parse failure.
    """
    open_idx = text.find("{", start)
    if open_idx == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    i = open_idx
    while i < len(text):
        c = text[i]
        if escape:
            escape = False
        elif c == "\\" and in_string:
            escape = True
        elif c == '"':
            in_string = not in_string
        elif not in_string:
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[open_idx : i + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        return None
        i += 1
    return None


def _is_schedule_shape(obj) -> bool:
    """Validate that a parsed object looks like a schedule.

    A real schedule has `weekOf` (string) and `days` (object). Without this
    check, the tolerant parser would happily match any JSON object that
    happens to follow a 'WEEKLY_SCHEDULE_JSON' mention in chat.
    """
    return (
        isinstance(obj, dict)
        and isinstance(obj.get("weekOf"), str)
        and isinstance(obj.get("days"), dict)
    )


def parse_schedule_message(text: str) -> dict | None:
    """Extract WEEKLY_SCHEDULE_JSON from a Slack message body.

    Tolerant of formatting (with or without triple backticks, json fence,
    Unicode smart quotes). Requires the parsed object to look like a real
    schedule (weekOf + days) — random JSON in chatter does not match.
    """
    if not text:
        return None
    header = _HEADER_RE.search(text)
    if not header:
        return None
    # Normalize curly quotes before parsing.
    body = text[header.end():].translate(_SMART_QUOTE_MAP)
    obj = _first_balanced_json_object(body, 0)
    if obj is None:
        log.warning(
            "Found WEEKLY_SCHEDULE_JSON header but could not parse a JSON "
            "object after it. Message preview: %r",
            text[: min(200, len(text))],
        )
        return None
    if not _is_schedule_shape(obj):
        log.warning(
            "Parsed JSON after WEEKLY_SCHEDULE_JSON header but it's not a "
            "valid schedule shape (need weekOf + days). Keys: %r",
            sorted(obj.keys()) if isinstance(obj, dict) else type(obj).__name__,
        )
        return None
    return obj


def find_latest_schedule(messages: Iterable[dict]) -> dict | None:
    """Given Slack messages (newest first), return the first parsed schedule."""
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
