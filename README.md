# flight-assign

Posts Delta ATL haulout assignments to `#flight-assign` every 15 minutes.

## What it does

On each run (cron, every 15 min):

1. Pulls outbound Delta flights at ATL for the next 9 hours from the AeroVect Fleet API (`/nexus/snapshots`).
2. Filters to flights departing from **T concourse** or **A-South (A1–A18)**.
3. Reads the most recent `WEEKLY_SCHEDULE_JSON` message from a Slack channel (configurable) to know who's on shift.
4. Picks today's day-of-week and the current shift in Atlanta time:
   - `shift1` = 05:30–14:00 ET
   - `shift2` = 14:00–22:00 ET
   - Outside those windows the run is a no-op.
5. Computes `haulout_ms = departure_ms − 55 min` and skips any haulout that's already in the past.
6. Assigns each remaining flight to an operator using **round-robin by load** with a **minimum 12-minute gap** between consecutive haulouts for the same operator.
7. Posts a readable message to `#flight-assign`.

## Channel architecture

The schedule lives in the same channel where the bot posts every 15 min, which means the weekly schedule message gets buried under bot posts fast. Two options:

- **Single-channel mode** (simpler, the original setup): schedule and assignments both in `#flight-assign`. Bot paginates up to 2000 messages of history to find the schedule. Works fine for a week or two of activity.
- **Split-channel mode** (recommended for stability): schedule lives in a dedicated `#flight-assign-schedule` channel that only has schedule posts. Bot reads from there, posts assignments to `#flight-assign`. Never buried, easier to audit.

Switch between modes by setting (or unsetting) `SLACK_SCHEDULE_CHANNEL_ID`. See "Switching to split-channel mode" below.

## Repo layout

```
flight-assign/
├── .github/workflows/flight-assign.yml   # cron + workflow_dispatch
├── src/flight_assign/
│   ├── aerovect.py    # Auth0 + /nexus/snapshots client
│   ├── gates.py       # T + A1-A18 filter
│   ├── roster.py      # parse WEEKLY_SCHEDULE_JSON (tolerant), pick today's shift
│   ├── slack_io.py    # paginating history scan + post
│   ├── assign.py      # round-robin + 12-min spacing
│   ├── format.py      # Slack message body
│   └── main.py        # entry point
├── tests/             # 57 pytest tests
└── pyproject.toml
```

## Required GitHub Actions secrets

| Secret                       | Required? | What it is                                                          |
| ---------------------------- | --------- | ------------------------------------------------------------------- |
| `AEROVECT_CLIENT_ID`         | Yes       | Auth0 client ID with `read:delta-vehicles` scope.                   |
| `AEROVECT_CLIENT_SECRET`     | Yes       | Matching client secret.                                             |
| `SLACK_BOT_TOKEN`            | Yes       | `xoxb-…` bot token.                                                 |
| `SLACK_CHANNEL_ID`           | Yes       | Channel ID where assignments are POSTED (default `#flight-assign`). |
| `SLACK_SCHEDULE_CHANNEL_ID`  | Optional  | Channel ID where schedules are READ from. If unset, same as `SLACK_CHANNEL_ID`. |

Bot scopes needed: `channels:history`, `channels:read`, `chat:write`. The bot must be invited to both channels in split mode.

## Switching to split-channel mode

1. **Create the new channel** in Slack: `#flight-assign-schedule`. Public is fine.
2. **Invite the bot to both channels** (channel → Integrations → Add apps).
3. **Get the new channel ID:** in Slack, right-click the channel name → "View channel details" → scroll to the bottom for the ID (`C…`). Or use `slack_search_channels`.
4. **Add a GitHub secret** named `SLACK_SCHEDULE_CHANNEL_ID` with that ID.
5. **Point the schedule-converter skill at the new channel.** Edit the skill's `SKILL.md` (under your Cowork plugins folder) — change the hardcoded `C0AQEA7NR28` to your new channel ID.
6. **Re-post the schedule** to the new channel using the skill.
7. The next workflow run will read from the new channel and continue posting to `#flight-assign`.

To revert: unset `SLACK_SCHEDULE_CHANNEL_ID` in GitHub secrets and re-post the schedule to `#flight-assign`.

## Cron schedule

The workflow is triggered by `cron-job.org` hitting GitHub's `workflow_dispatch` API every 15 minutes during shift hours (05:30–22:00 ET, Mon–Fri). The workflow file also has a backup GitHub-native cron (`*/15 * * * *`) that fires every 15 min UTC; if you don't want the double-trigger, remove the `schedule:` block.

## Local development

```bash
pip install -e ".[dev]"
pytest               # run the 57-test suite
```

Dry run against your real account without posting:

```bash
export AEROVECT_CLIENT_ID=...
export AEROVECT_CLIENT_SECRET=...
export SLACK_BOT_TOKEN=...
export SLACK_CHANNEL_ID=C0AQEA7NR28
export SLACK_SCHEDULE_CHANNEL_ID=C...        # optional
export DRY_RUN=1
flight-assign
```

`DRY_RUN=1` prints the rendered message to stdout instead of posting.

## Tuning knobs

| Var                          | Default       | Purpose                                              |
| ---------------------------- | ------------- | ---------------------------------------------------- |
| `AIRPORT`                    | `ATL`         | ICAO/IATA code.                                      |
| `AIRLINE`                    | `DL`          | Airline filter.                                      |
| `HOURS_FORWARD`              | `9`           | API lookahead window.                                |
| `SLACK_HISTORY_MAX_SCAN`     | `2000`        | Max messages to paginate looking for the schedule.   |
| `DRY_RUN`                    | unset         | Print message instead of posting.                    |
| `LOG_LEVEL`                  | `INFO`        | Python logging level.                                |

Algorithm constants (in `assign.py`): `HAULOUT_LEAD_MINUTES=55`, `MIN_GAP_MINUTES=12`.

## Schedule parser

The parser is tolerant of formatting variations. It looks for the literal header `WEEKLY_SCHEDULE_JSON` (case-insensitive), then finds the next balanced `{…}` JSON object. Triple backticks, ```json fences, and surrounding chatter are all OK. The format produced by the schedule-converter skill works as-is.

If the parser finds the header but can't parse JSON after it, you'll see a warning log line with a preview of the offending text — useful when the format drifts.

## Behavior notes

- **Past haulouts are dropped.** If a flight departs in 30 min, its haulout was 25 min ago; we skip it.
- **Off-shift runs do nothing.** Outside 05:30–22:00 ET, no operators are eligible, so the post is skipped.
- **Schedule must be in the schedule channel.** If the bot can't find a `WEEKLY_SCHEDULE_JSON` message in the last 2000 messages, the run exits with code 2 and posts nothing.
- **Read-only API.** Assignments are not persisted — every cycle is a fresh allocation. Drops land every few minutes, so re-balancing on each run keeps things current.
