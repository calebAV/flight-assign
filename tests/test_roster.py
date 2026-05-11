from datetime import datetime, timezone

from flight_assign.roster import (
    Operator,
    current_shift_key,
    current_weekday_key,
    find_latest_schedule,
    operators_on_shift,
    parse_schedule_message,
)

SCHEDULE_JSON = """\
WEEKLY_SCHEDULE_JSON
```
{
  "weekOf": "2026-05-11",
  "days": {
    "monday": {
      "shift1": [{"name": "Andrew Christiansen", "role": "Production"},
                 {"name": "Heather Thompson", "role": "Reserve"}],
      "shift2": [{"name": "David Cobos", "role": "Production"}]
    },
    "tuesday": {"shift1": [], "shift2": []},
    "wednesday": {"shift1": [], "shift2": []},
    "thursday": {"shift1": [], "shift2": []},
    "friday": {"shift1": [], "shift2": []}
  }
}
```
_Excluded Training operators: Eashan Rao_
"""


def test_parse_schedule_message():
    sched = parse_schedule_message(SCHEDULE_JSON)
    assert sched is not None
    assert sched["weekOf"] == "2026-05-11"
    assert sched["days"]["monday"]["shift1"][0]["name"] == "Andrew Christiansen"


def test_parse_schedule_message_with_json_language_hint():
    msg = "WEEKLY_SCHEDULE_JSON\n```json\n{\"weekOf\":\"2026-05-11\",\"days\":{}}\n```"
    sched = parse_schedule_message(msg)
    assert sched == {"weekOf": "2026-05-11", "days": {}}


def test_parse_schedule_message_no_match():
    assert parse_schedule_message("just a regular message") is None
    assert parse_schedule_message("") is None


def test_find_latest_schedule_returns_first_valid():
    messages = [
        {"text": "🎉 lunch?"},
        {"text": "WEEKLY_SCHEDULE_JSON\n```\n{not valid json\n```"},
        {"text": SCHEDULE_JSON},
        {"text": "older message"},
    ]
    sched = find_latest_schedule(messages)
    assert sched is not None
    assert sched["weekOf"] == "2026-05-11"


def test_current_shift_key_shift1():
    # Monday 2026-05-11 10:00 ET → 14:00 UTC (EDT = UTC-4)
    t = datetime(2026, 5, 11, 14, 0, tzinfo=timezone.utc)
    assert current_shift_key(t) == "shift1"


def test_current_shift_key_shift2():
    # Monday 2026-05-11 16:00 ET → 20:00 UTC
    t = datetime(2026, 5, 11, 20, 0, tzinfo=timezone.utc)
    assert current_shift_key(t) == "shift2"


def test_current_shift_key_off_hours():
    # 03:00 ET → 07:00 UTC: before shift1
    t = datetime(2026, 5, 11, 7, 0, tzinfo=timezone.utc)
    assert current_shift_key(t) is None
    # 23:30 ET → 03:30 UTC next day: after shift2
    t = datetime(2026, 5, 12, 3, 30, tzinfo=timezone.utc)
    assert current_shift_key(t) is None


def test_current_shift_key_boundary():
    # Exactly 14:00 ET → shift2 (the new shift starts; old shift ends)
    t = datetime(2026, 5, 11, 18, 0, tzinfo=timezone.utc)
    assert current_shift_key(t) == "shift2"
    # Exactly 05:30 ET → shift1
    t = datetime(2026, 5, 11, 9, 30, tzinfo=timezone.utc)
    assert current_shift_key(t) == "shift1"


def test_current_weekday_key():
    # Monday 2026-05-11
    t = datetime(2026, 5, 11, 14, 0, tzinfo=timezone.utc)
    assert current_weekday_key(t) == "monday"
    # Late Sunday UTC could still be Sunday ET — check we use ET
    t = datetime(2026, 5, 11, 3, 0, tzinfo=timezone.utc)  # 23:00 ET Sunday
    assert current_weekday_key(t) == "sunday"


def test_operators_on_shift_picks_today_and_current_shift():
    sched = parse_schedule_message(SCHEDULE_JSON)
    # Monday 10:00 ET → shift1 on monday
    t = datetime(2026, 5, 11, 14, 0, tzinfo=timezone.utc)
    ops = operators_on_shift(sched, t)
    assert ops == [
        Operator(name="Andrew Christiansen", role="Production"),
        Operator(name="Heather Thompson", role="Reserve"),
    ]


def test_operators_on_shift_returns_empty_off_hours():
    sched = parse_schedule_message(SCHEDULE_JSON)
    # 03:00 ET → before shift1
    t = datetime(2026, 5, 11, 7, 0, tzinfo=timezone.utc)
    assert operators_on_shift(sched, t) == []


def test_operators_on_shift_shift2():
    sched = parse_schedule_message(SCHEDULE_JSON)
    # Monday 16:00 ET → shift2
    t = datetime(2026, 5, 11, 20, 0, tzinfo=timezone.utc)
    ops = operators_on_shift(sched, t)
    assert ops == [Operator(name="David Cobos", role="Production")]
