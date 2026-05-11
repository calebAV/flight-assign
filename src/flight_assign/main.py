"""Entry point. Reads env, pulls flights, reads roster, assigns, posts.

Required environment variables:
  AEROVECT_CLIENT_ID
  AEROVECT_CLIENT_SECRET
  SLACK_BOT_TOKEN
  SLACK_CHANNEL_ID            Channel to POST assignments to
                              (default: C0AQEA7NR28 = #flight-assign).
  SLACK_SCHEDULE_CHANNEL_ID   Channel to READ schedules from. Optional.
                              If unset, defaults to SLACK_CHANNEL_ID.
  AIRPORT                     (default: ATL)
  AIRLINE                     (default: DL)
  HOURS_FORWARD               (default: 9)
  SLACK_HISTORY_MAX_SCAN      (default: 2000)
  DRY_RUN                     ("1"/"true" to skip the Slack post)
"""

from __future__ import annotations

import logging
import os
import sys
import time

from .aerovect import AeroVectClient
from .assign import assign_flights, snapshot_to_flight
from .format import format_message
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
    val = os.environ.get(name, default)
    if required and not val:
        raise SystemExit(f"Missing required env var: {name}")
    return val or ""


def _truthy(v: str) -> bool:
    return v.strip().lower() in {"1", "true", "yes", "on"}


def _resolve_schedule(slack: SlackClient, channel_id: str, max_scan: int) -> dict | None:
    """Find the newest valid WEEKLY_SCHEDULE_JSON in the channel.

    Always picks the latest valid schedule, so mid-week re-posts win.
    The parser already validates shape (weekOf + days), so random JSON
    in chatter cannot impersonate a schedule.
    """
    def is_schedule(msg: dict) -> bool:
        return parse_schedule_message(msg.get("text") or "") is not None

    matched, scanned = slack.find_message(
        is_schedule, channel_id=channel_id, max_scan=max_scan
    )
    if matched is None:
        log.error(
            "no WEEKLY_SCHEDULE_JSON found in channel %s after scanning %d "
            "messages. Re-post the schedule via the schedule-converter skill.",
            channel_id, scanned,
        )
        return None

    sched = parse_schedule_message(matched["text"])
    expected_week = current_week_monday()
    actual_week = sched.get("weekOf") if sched else None
    if actual_week == expected_week:
        log.info(
            "using schedule weekOf=%s (current week) — found after scanning "
            "%d messages",
            actual_week, scanned,
        )
    else:
        log.warning(
            "using newest schedule weekOf=%s, but current week is %s. "
            "Re-post the schedule if this is stale.",
            actual_week, expected_week,
        )
    return sched


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
    airline = _env("AIRLINE", default="DL").upper()
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
    log.info("fetched %d snapshots from /nexus/snapshots", len(snapshots))

    snapshots = [s for s in snapshots if (s.get("airline_cde") or "").upper() == airline]
    log.info("after airline filter (%s): %d snapshots", airline, len(snapshots))
    snapshots = filter_snapshots(snapshots)
    log.info("after gate filter (T + A1-A18): %d snapshots", len(snapshots))

    flights = [f for f in (snapshot_to_flight(s) for s in snapshots) if f is not None]

    # 2) Read roster — always pick the newest valid schedule.
    slack = SlackClient(slack_token, post_channel)
    schedule = _resolve_schedule(slack, schedule_channel, max_scan)
    if schedule is None:
        return 2

    operators = operators_on_shift(schedule)
    log.info("on-shift operators: %d", len(operators))

    # 3) Assign.
    now_ms = int(time.time() * 1000)
    result = assign_flights(flights, operators, now_ms=now_ms)
    log.info(
        "assigned=%d, unassigned=%d",
        len(result.assigned),
        len(result.unassigned),
    )

    # 4) Post.
    body = format_message(result, operators)
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
