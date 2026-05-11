from datetime import datetime, timezone

from flight_assign.assign import Flight, assign_flights
from flight_assign.format import format_message
from flight_assign.roster import Operator

MIN = 60_000
HAULOUT_OFFSET = 55 * MIN


def _f(num, dep_ms, gate="A14", dest="GSP", time_type="E"):
    return Flight(
        flight_key=f"k-{num}",
        flt_num=num,
        airline="DL",
        dest=dest,
        gate=gate,
        pier=gate[0],
        departure_ms=dep_ms,
        time_type=time_type,
    )


def test_format_message_includes_flight_details():
    # Monday 2026-05-11 14:00 UTC = 10:00 ET
    now_utc = datetime(2026, 5, 11, 14, 0, tzinfo=timezone.utc)
    now_ms = int(now_utc.timestamp() * 1000)

    flights = [
        # haulout in 5 min (15:05 UTC = 11:05 ET), departure at 12:00 ET
        _f("1234", now_ms + 60 * MIN + HAULOUT_OFFSET, gate="A14", dest="GSP"),
    ]
    ops = [Operator("Andrew Christiansen", "Production")]
    res = assign_flights(flights, ops, now_ms=now_ms)
    msg = format_message(res, ops, now_utc=now_utc)

    assert "Andrew Christiansen" in msg
    assert "DL1234" in msg
    assert "→ GSP" in msg
    assert "A14" in msg
    assert "haulout" in msg
    # Header shows ET
    assert "ET" in msg


def test_format_message_no_operators():
    now_utc = datetime(2026, 5, 11, 14, 0, tzinfo=timezone.utc)
    res = assign_flights([], [], now_ms=int(now_utc.timestamp() * 1000))
    msg = format_message(res, [], now_utc=now_utc)
    assert "No operators currently on shift" in msg


def test_format_message_lists_unassigned():
    now_utc = datetime(2026, 5, 11, 14, 0, tzinfo=timezone.utc)
    now_ms = int(now_utc.timestamp() * 1000)
    # Two flights 5 min apart, single operator → second is unassigned
    flights = [
        _f("100", now_ms + 60 * MIN + HAULOUT_OFFSET),
        _f("101", now_ms + 65 * MIN + HAULOUT_OFFSET),
    ]
    ops = [Operator("Solo", "Production")]
    res = assign_flights(flights, ops, now_ms=now_ms)
    msg = format_message(res, ops, now_utc=now_utc)
    assert "Unassigned" in msg
    assert "DL101" in msg
