"""Entry point. Reads env, pulls flights, reads roster, assigns, posts.

Required environment variables:
  AEROVECT_CLIENT_ID
  AEROVECT_CLIENT_SECRET
  SLACK_BOT_TOKEN
  SLACK_CHANNEL_ID         (default: C0AQEA7NR28 = #flight-assign)
  AIRPORT                  (default: ATL)
  AIRLINE                  (default: DL)
  HOURS_FORWARD            (default: 9)
  DRY_RUN                  ("1" or "true" to skip the Slack post)
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
from .roster import find_latest_schedule, operators_on_shift
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


def run() -> int:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )

    client_id = _env("AEROVECT_CLIENT_ID", required=True)
    client_secret = _env("AEROVECT_CLIENT_SECRET", required=True)
    slack_token = _env("SLACK_BOT_TOKEN", required=True)
    channel_id = _env("SLACK_CHANNEL_ID", default=DEFAULT_CHANNEL_ID)
    airport = _env("AIRPORT", default="ATL").upper()
    airline = _env("AIRLINE", default="DL").upper()
    hours_forward = int(_env("HOURS_FORWARD", default="9"))
    dry_run = _truthy(_env("DRY_RUN", default=""))

    # 1) Pull flights.
    av = AeroVectClient(client_id, client_secret)
    snapshots = av.get_snapshots(airport, hours_back=0, hours_forward=hours_forward)
    log.info("fetched %d snapshots from /nexus/snapshots", len(snapshots))

    # Filter: airline + target gates.
    snapshots = [s for s in snapshots if (s.get("airline_cde") or "").upper() == airline]
    snapshots = filter_snapshots(snapshots)
    log.info("after airline+gate filter: %d snapshots", len(snapshots))

    flights = [f for f in (snapshot_to_flight(s) for s in snapshots) if f is not None]

    # 2) Read roster.
    slack = SlackClient(slack_token, channel_id)
    messages = slack.recent_messages(limit=80)
    schedule = find_latest_schedule(messages)
    if schedule is None:
        log.error("no WEEKLY_SCHEDULE_JSON found in recent channel history")
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
    log.info("posted ts=%s to channel=%s", ts, channel_id)
    return 0


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
