from flight_assign.assign import (
    HAULOUT_LEAD_MINUTES,
    MIN_GAP_MINUTES,
    Flight,
    assign_flights,
)
from flight_assign.roster import Operator

MIN = 60_000  # ms per minute
HAULOUT_OFFSET_MS = HAULOUT_LEAD_MINUTES * MIN


def _flight(num: str, dep_ms: int, gate: str = "A5", dest: str = "GSP") -> Flight:
    return Flight(
        flight_key=f"k-{num}",
        flt_num=num,
        airline="DL",
        dest=dest,
        gate=gate,
        pier=gate[0],
        departure_ms=dep_ms,
        time_type="E",
    )


def _op(name: str, role: str = "Production") -> Operator:
    return Operator(name=name, role=role)


def test_skips_past_haulouts():
    now = 10_000_000_000  # ms
    # Departure 30 min from now → haulout was 25 min ago → skip
    past = _flight("100", now + 30 * MIN)
    # Departure 60 min from now → haulout in 5 min → keep
    future = _flight("101", now + 60 * MIN)
    ops = [_op("A"), _op("B")]
    res = assign_flights([past, future], ops, now_ms=now)
    assert len(res.assigned) == 1
    assert res.assigned[0].flight.flt_num == "101"
    assert res.unassigned == []


def test_enforces_12_minute_gap_per_operator():
    """Two flights with haulouts 10 min apart cannot share an operator."""
    now = 10_000_000_000
    # haulout1 at now+60, haulout2 at now+70 (10 min later — too close)
    f1 = _flight("200", now + 60 * MIN + HAULOUT_OFFSET_MS)
    f2 = _flight("201", now + 70 * MIN + HAULOUT_OFFSET_MS)
    # Only one operator → second flight must be unassigned
    res = assign_flights([f1, f2], [_op("Solo")], now_ms=now)
    assert len(res.assigned) == 1
    assert res.assigned[0].operator.name == "Solo"
    assert res.assigned[0].flight.flt_num == "200"
    assert len(res.unassigned) == 1
    assert res.unassigned[0].flt_num == "201"


def test_12_min_gap_exactly_eligible():
    """12 min gap is OK (>= threshold)."""
    now = 10_000_000_000
    f1 = _flight("300", now + 60 * MIN + HAULOUT_OFFSET_MS)
    f2 = _flight("301", now + (60 + MIN_GAP_MINUTES) * MIN + HAULOUT_OFFSET_MS)
    res = assign_flights([f1, f2], [_op("Solo")], now_ms=now)
    assert len(res.assigned) == 2
    assert all(a.operator.name == "Solo" for a in res.assigned)


def test_round_robin_balances_load():
    """Three operators, three back-to-back flights → each operator gets one."""
    now = 10_000_000_000
    flights = [
        _flight("A", now + (60 + 0) * MIN + HAULOUT_OFFSET_MS),
        _flight("B", now + (60 + 4) * MIN + HAULOUT_OFFSET_MS),
        _flight("C", now + (60 + 8) * MIN + HAULOUT_OFFSET_MS),
    ]
    ops = [_op("Op1"), _op("Op2"), _op("Op3")]
    res = assign_flights(flights, ops, now_ms=now)
    # All assigned, one per operator
    by_op = res.by_operator()
    assert sorted(by_op.keys()) == ["Op1", "Op2", "Op3"]
    assert all(len(v) == 1 for v in by_op.values())


def test_unassigned_when_no_operators():
    now = 10_000_000_000
    flights = [_flight("Z", now + 60 * MIN + HAULOUT_OFFSET_MS)]
    res = assign_flights(flights, [], now_ms=now)
    assert res.assigned == []
    assert len(res.unassigned) == 1


def test_round_robin_with_dense_schedule():
    """5 flights every 5 minutes, 2 operators. Each can take a flight only
    every 12 min minimum. Expected: alternating operators with some unassigned
    because of the gap constraint."""
    now = 10_000_000_000
    flights = [
        _flight(str(i), now + (60 + 5 * i) * MIN + HAULOUT_OFFSET_MS)
        for i in range(5)
    ]
    res = assign_flights(flights, [_op("A"), _op("B")], now_ms=now)
    # Flight 0 -> A (load 0), Flight 1 -> B (load 0), Flight 2 -> A only if
    # 10 min since A's last haulout >= 12 → NO. Flight 2 -> B? 5 min since B → NO.
    # So flight 2 is unassigned. Flight 3: A's last haulout was 15 min ago → eligible.
    # Flight 4: A took flight 3, only 5 min ago → ineligible. B's last was 20 min ago → eligible.
    by_op = res.by_operator()
    assert by_op["A"][0].flight.flt_num == "0"
    assert by_op["B"][0].flight.flt_num == "1"
    # Verify the gap constraint holds within each operator's stream
    for assignments in by_op.values():
        haulouts = [a.flight.haulout_ms for a in assignments]
        for prev, nxt in zip(haulouts, haulouts[1:]):
            assert nxt - prev >= MIN_GAP_MINUTES * MIN


def test_deterministic_with_identical_haulouts():
    """Two flights with the same haulout time → both go to different ops,
    output is deterministic across runs."""
    now = 10_000_000_000
    h = now + 60 * MIN + HAULOUT_OFFSET_MS
    f_alpha = _flight("100", h)
    f_bravo = _flight("200", h)
    ops = [_op("Op1"), _op("Op2")]
    res1 = assign_flights([f_alpha, f_bravo], ops, now_ms=now)
    res2 = assign_flights([f_bravo, f_alpha], ops, now_ms=now)
    assert [a.operator.name for a in res1.assigned] == [
        a.operator.name for a in res2.assigned
    ]
