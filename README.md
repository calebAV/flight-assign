# flight-assign

Posts Delta ATL haulout assignments to `#flight-assign` every 15 minutes.

## What it does

On each run (cron, every 15 min):

1. Pulls outbound Delta flights at ATL for the next 9 hours from the AeroVect Fleet API (`/nexus/snapshots`).
2. Filters to flights departing from **T concourse** or **A-South (A1–A18)**.
3. Reads the most recent `WEEKLY_SCHEDULE_JSON` message in `#flight-assign` (Slack channel `C0AQEA7NR28`) to know who is on shift.
4. Picks today's day-of-week and the current shift in Atlanta time:
   - `shift1` = 05:30–14:00 ET
   - `shift2` = 14:00–22:00 ET
   - Outside those windows the run is a no-op.
5. Computes `haulout_ms = departure_ms − 55 min` and skips any haulout that's already in the past.
6. Assigns each remaining flight to an operator using **round-robin by load** with a **minimum 12-minute gap** between consecutive haulouts for the same operator. Flights that can't be assigned under the gap rule are flagged "Unassigned".
7. Posts a readable message to `#flight-assign`.

## Repo layout

```
flight-assign/
├── .github/workflows/flight-assign.yml   # cron every 15 min
├── src/flight_assign/
│   ├── aerovect.py    # Auth0 + /nexus/snapshots client
│   ├── gates.py       # T + A1-A18 filter
│   ├── roster.py      # parse WEEKLY_SCHEDULE_JSON, pick today's shift
│   ├── slack_io.py    # slack history read + post
│   ├── assign.py      # round-robin + 12-min spacing
│   ├── format.py      # Slack message body
│   └── main.py        # entry point
├── tests/             # pytest (46 tests, all green)
└── pyproject.toml
```

## Required GitHub Actions secrets

Set these under **Settings → Secrets and variables → Actions**:

| Secret                    | What it is                                                    |
| ------------------------- | ------------------------------------------------------------- |
| `AEROVECT_CLIENT_ID`      | Auth0 client ID with `read:delta-vehicles` scope.             |
| `AEROVECT_CLIENT_SECRET`  | Matching client secret.                                       |
| `SLACK_BOT_TOKEN`         | `xoxb-…` bot token. Bot must be invited to `#flight-assign`.  |
| `SLACK_CHANNEL_ID`        | `C0AQEA7NR28` (the #flight-assign channel ID).                |

The bot needs these Slack scopes: `channels:history`, `channels:read`, `chat:write`.

## Cron schedule

GitHub Actions runs the workflow on `*/15 * * * *` (every 15 min, UTC). The program filters itself to ATL shift hours (05:30–22:00 ET), so the ~32 daily runs outside those hours exit cleanly without posting.

> Note: GitHub Actions cron is best-effort and can lag by a few minutes during peak load. If you need precise on-the-quarter-hour delivery, run the same code on a dedicated runner with a real cron daemon.

## Local development

```bash
pip install -e ".[dev]"
pytest               # run the test suite
```

To dry-run against your real account without posting to Slack:

```bash
export AEROVECT_CLIENT_ID=...
export AEROVECT_CLIENT_SECRET=...
export SLACK_BOT_TOKEN=...
export SLACK_CHANNEL_ID=C0AQEA7NR28
export DRY_RUN=1
flight-assign
```

`DRY_RUN=1` prints the rendered message to stdout instead of posting.

## Tuning knobs

Environment variables (also surfaced in the workflow YAML):

| Var             | Default | Purpose                                      |
| --------------- | ------- | -------------------------------------------- |
| `AIRPORT`       | `ATL`   | ICAO/IATA code for `/nexus/snapshots`.       |
| `AIRLINE`       | `DL`    | Airline code filter applied client-side.     |
| `HOURS_FORWARD` | `9`     | API lookahead window.                        |
| `DRY_RUN`       | unset   | If `1`/`true`, print message instead of posting. |
| `LOG_LEVEL`     | `INFO`  | Python logging level.                        |

Algorithm constants (in `assign.py`):

- `HAULOUT_LEAD_MINUTES = 55` — how far before departure the haulout happens.
- `MIN_GAP_MINUTES = 12` — minimum spacing between haulouts for the same operator.

## Behavior notes / gotchas

- **Past haulouts are dropped.** If a flight departs in 30 min, its haulout was 25 min ago; we skip it (the operator handled it from a previous post).
- **Off-shift runs do nothing.** Outside 05:30–22:00 ET, no operators are eligible, so the post is skipped.
- **Schedule must be in the channel.** If the bot can't find a `WEEKLY_SCHEDULE_JSON` message in the last 80 messages, the run exits with code 2 and posts nothing. Use the `schedule-converter` skill in Cowork to regenerate it.
- **Read-only API.** Assignments are not persisted anywhere — every cycle is a fresh allocation. That's intentional: drops land every few minutes, so re-balancing on each run keeps things current.
- **Round-robin tie-break.** When two operators are tied on load, the one whose last haulout was longer ago wins; if neither has flown yet, alphabetical-by-name (deterministic).

## When to revisit the design

- If operators need to **acknowledge** assignments → add a Slack interactive component and a store.
- If you need **inbound** flights → the API currently returns empty for inbound; ask AeroVect.
- If the bot is **double-posting** during peak load → set `concurrency.cancel-in-progress: true` in the workflow (currently `false` so a slow run isn't killed mid-post).
