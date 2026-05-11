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
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta as _td, timezone
from typing import Iterable, Iterator
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
_WEEKDAY_SET = set(_WEEKDAY_NAMES)

_HEADER_RE = re.compile(r"WEEKLY_SCHEDULE_JSON", re.IGNORECASE)

# Slack/macOS auto-curlify quotes in some clients. Normalize to straight
# before json.loads, including the case where ONLY ONE side got curlified
# (left curly + straight right, or vice versa).
_SMART_QUOTE_MAP = str.maketrans({
    "“": '"', "”": '"', "„": '"', "‟": '"',
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "«": '"', "»": '"',
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
    now_utc = now_utc or datetime.now(timezone.utc)
    return _WEEKDAY_NAMES[now_utc.astimezone(ATLANTA_TZ).weekday()]


def current_week_monday(now_utc: datetime | None = None) -> str:
    now_utc = now_utc or datetime.now(timezone.utc)
    local = now_utc.astimezone(ATLANTA_TZ).date()
    monday = local - _td(days=local.weekday())
    return monday.strftime("%Y-%m-%d")


def _iter_balanced_json_objects(text: str) -> Iterator[dict]:
    """Yield every parseable balanced JSON object in `text` (top-level only).

    Walks left to right. When a `{` is found, advances until the matching `}`
    (respecting quoted strings), parses the slice, and yields the result if
    parsing succeeds. Then continues scanning after the close brace.
    """
    pos = 0
    n = len(text)
    while pos < n:
        start = text.find("{", pos)
        if start == -1:
            return
        depth = 0
        in_string = False
        escape = False
        i = start
        end = -1
        while i < n:
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
                        end = i + 1
                        break
            i += 1
        if end == -1:
            return
        try:
            obj = json.loads(text[start:end])
        except json.JSONDecodeError:
            pos = start + 1  # advance just past this `{` and retry
            continue
        if isinstance(obj, dict):
            yield obj
        pos = end


def _is_schedule_shape(obj) -> bool:
    """Validate that a parsed object actually looks like a schedule.

    Requires weekOf:str, days:dict, and `days` containing at least one
    weekday key (monday..sunday). This is specific enough that random JSON
    in channel chatter won't false-positive.
    """
    if not isinstance(obj, dict):
        return False
    if not isinstance(obj.get("weekOf"), str):
        return False
    days = obj.get("days")
    if not isinstance(days, dict):
        return False
    return any(d in _WEEKDAY_SET for d in days)


def parse_schedule_message(text: str) -> dict | None:
    """Extract a schedule from a Slack message body.

    Strategy:
      1. Normalize Unicode smart quotes -> straight quotes.
      2. If a `WEEKLY_SCHEDULE_JSON` header is present, search after it
         (preferred — the explicit marker tells us it IS a schedule).
      3. Otherwise, scan the whole message for any JSON object that
         matches the schedule shape (weekOf + days + weekday keys).
      4. Return the first shape-matching object, or None.
    """
    if not text:
        return None
    normalized = text.translate(_SMART_QUOTE_MAP)

    header = _HEADER_RE.search(normalized)
    search_text = normalized[header.end():] if header else normalized

    for obj in _iter_balanced_json_objects(search_text):
        if _is_schedule_shape(obj):
            return obj

    if header:
        log.warning(
            "Found WEEKLY_SCHEDULE_JSON header but no valid schedule-shape "
            "JSON after it. Preview: %r",
            text[: min(200, len(text))],
        )
    return None


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
