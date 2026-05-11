"""Entry point. Reads env, pulls flights, reads roster, assigns, posts.

Required environment variables:
  AEROVECT_CLIENT_ID
  AEROVECT_CLIENT_SECRET
  SLACK_BOT_TOKEN
  SLACK_CHANNEL_ID            Channel to POST assignments to
                              (default: C0AQEA7NR28 = #flight-assign).
  SLACK_SCHEDULE_CHANNEL_ID   Channel to READ schedules from. Optional.
                              Falls back to SLACK_CHANNEL_ID when empty/unset.
  AIRPORT                     (default: ATL)
  AIRLINE                     Comma-separated airline codes to keep,
                              case-insensitive. Default: "DL,DAL"
                              (covers both Delta's IATA and ICAO codes).
  HOURS_FORWARD               (default: 9)
  SLACK_HISTORY_MAX_SCAN      (default: 2000)
  DRY_RUN                     ("1"/"true" to skip the Slack post)
"""

from __future__ import annotations

import logging
import os
import sys
import time
from collections import Counter

from .aerovect import AeroVectClient, snapshot_airline
from .assign import assign_flights, snapshot_to_flight
from .format import FeedHealth, ScheduleSource, format_message
from .gates import filter_snapshots
from .roster import (
    current_week_monday,
    operators_on_shift,
    parse_schedule_message,
)
from .slack_io import SlackClient

DEFAULT_CHANNEL_ID = "C0AQEA7NR28"  # #flight-assign

log = logging.getLogger("flight_assign")


def _env(name: str, default: str | None = None, *, required: bool = False) -> str:
    """Read env var. Treats empty string the same as unset."""
    val = os.environ.get(name)
    if not val:
        val = default
    if required and not val:
        raise SystemExit(f"Missing required env var: {name}")
    return val or ""


def _truthy(v: str) -> bool:
    return v.strip().lower() in {"1", "true", "yes", "on"}


def _parse_airline_list(raw: str) -> list[str]:
    return [a.strip().upper() for a in raw.split(",") if a.strip()]


def _resolve_schedule(
    slack: SlackClient, channel_id: str, max_scan: int
) -> tuple[dict | None, ScheduleSource | None]:
    def is_schedule(msg: dict) -> bool:
        return parse_schedule_message(msg.get("text") or "") is not None

    matched, scanned = slack.find_message(
        is_schedule, channel_id=channel_id, max_scan=max_scan
    )
    expected_week = current_week_monday()

    if matched is None:
        log.error(
            "no WEEKLY_SCHEDULE_JSON found in channel %s after scanning %d "
            "messages.", channel_id, scanned,
        )
        return None, None

    sched = parse_schedule_message(matched["text"])
    actual_week = sched.get("weekOf") if sched else None
    ts = matched.get("ts") or ""
    permalink = slack.permalink(channel_id, ts) if ts else None

    log.info(
        "using schedule weekOf=%s (expected %s), ts=%s, permalink=%s, "
        "found after scanning %d messages",
        actual_week, expected_week, ts, permalink, scanned,
    )
    if actual_week != expected_week:
        log.warning(
            "schedule weekOf %s does not match current week %s.",
            actual_week, expected_week,
        )

    return sched, ScheduleSource(
        week_of=actual_week,
        permalink=permalink,
        expected_week=expected_week,
    )


def run() -> int:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )

    client_id = _env("AEROVECT_CLIENT_ID", required=True)
    client_secret = _env("AEROVECT_CLIENT_SECRET", required=True)
    slack_token = _env("SLACK_BOT_TOKEN", required=True)
    post_channel = _env("SLACK_CHANNEL_ID", default=DEFAULT_CHANNEL_ID)
    schedule_channel = _env("SLACK_SCHEDULE_CHANNEL_ID", default=post_channel)
    airport = _env("AIRPORT", default="ATL").upper()
    airlines = _parse_airline_list(_env("AIRLINE", default="DL,DAL"))
    hours_forward = int(_env("HOURS_FORWARD", default="9"))
    max_scan = int(_env("SLACK_HISTORY_MAX_SCAN", default="2000"))
    dry_run = _truthy(_env("DRY_RUN", default=""))

    if schedule_channel != post_channel:
        log.info(
            "channels: read schedule from %s, post assignments to %s",
            schedule_channel, post_channel,
        )
    else:
        log.info("channels: single-channel mode (%s)", post_channel)

    # 1) Pull flights.
    av = AeroVectClient(client_id, client_secret)
    snapshots = av.get_snapshots(airport, hours_back=0, hours_forward=hours_forward)
    total_snapshots = len(snapshots)
    log.info("fetched %d snapshots from /nexus/snapshots", total_snapshots)

    if snapshots:
        log.info(
            "sample flight_keys (first 3): %s",
            [s.get("flight_key") for s in snapshots[:3]],
        )

    # Count snapshots with NO usable gate (after applying dptr_gate fallback).
    # That's the true "data degraded" signal — PARTIAL keys alone are fine
    # when dptr_gate is populated.
    from .aerovect import snapshot_gate
    no_gate_count = sum(1 for s in snapshots if not snapshot_gate(s))
    feed_health = FeedHealth(total=total_snapshots, partial=no_gate_count)
    if no_gate_count:
        log.warning(
            "%d of %d snapshots have no usable gate (neither `gate` nor "
            "`dptr_gate` is populated). Those flights cannot be assigned.",
            no_gate_count, total_snapshots,
        )

    # Airline distribution (PARTIAL keys will show up as "?")
    code_counts = Counter(snapshot_airline(s, default="DL") or "?" for s in snapshots)
    log.info("airline code distribution (with flight_key fallback): %s",
             dict(code_counts))

    snapshots = [s for s in snapshots if snapshot_airline(s, default="DL") in airlines]
    log.info(
        "after airline filter (%s): %d snapshots",
        "/".join(airlines), len(snapshots),
    )

    snapshots = filter_snapshots(snapshots)
    log.info("after gate filter (T + A1-A18): %d snapshots", len(snapshots))

    flights = [f for f in (snapshot_to_flight(s) for s in snapshots) if f is not None]

    # 2) Read roster.
    slack = SlackClient(slack_token, post_channel)
    schedule, source = _resolve_schedule(slack, schedule_channel, max_scan)
    if schedule is None:
        return 2

    operators = operators_on_shift(schedule)
    log.info(
        "on-shift operators: %d (%s)",
        len(operators), ", ".join(o.name for o in operators),
    )

    # 3) Assign.
    now_ms = int(time.time() * 1000)
    result = assign_flights(flights, operators, now_ms=now_ms)
    log.info(
        "assigned=%d, unassigned=%d",
        len(result.assigned),
        len(result.unassigned),
    )

    # 4) Post.
    body = format_message(result, operators, schedule_source=source, feed_health=feed_health)
    if dry_run:
        print(body)
        return 0
    if not operators:
        log.info("no operators on shift, skipping post")
        return 0

    ts = slack.post(body)
    log.info("posted ts=%s to channel=%s", ts, post_channel)
    return 0


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
