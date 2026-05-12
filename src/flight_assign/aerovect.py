"""AeroVect Fleet API client.

Mints an Auth0 token (cached for the run) and fetches outbound snapshots.
Doc reference: https://api.fleet.aerovect.com  (see README).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import requests

AUTH0_URL = "https://aerovect.us.auth0.com/oauth/token"
API_AUDIENCE = "https://fleet.aerovect.com/"
API_BASE = "https://api.fleet.aerovect.com"
TOKEN_GRACE_SECONDS = 60  # re-mint a minute before nominal expiry


@dataclass
class _CachedToken:
    access_token: str
    expires_at_epoch: float


class AeroVectClient:
    """Thin client for /nexus/snapshots. Caches the JWT in-memory."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        *,
        session: requests.Session | None = None,
        timeout: float = 15.0,
    ):
        if not client_id or not client_secret:
            raise ValueError("AeroVectClient requires client_id and client_secret")
        self._client_id = client_id
        self._client_secret = client_secret
        self._session = session or requests.Session()
        self._timeout = timeout
        self._token: _CachedToken | None = None

    def _mint_token(self) -> _CachedToken:
        resp = self._session.post(
            AUTH0_URL,
            json={
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "audience": API_AUDIENCE,
                "grant_type": "client_credentials",
            },
            timeout=self._timeout,
        )
        resp.raise_for_status()
        body = resp.json()
        access_token = body["access_token"]
        expires_in = int(body.get("expires_in", 36000))
        return _CachedToken(
            access_token=access_token,
            expires_at_epoch=time.time() + expires_in - TOKEN_GRACE_SECONDS,
        )

    def _bearer(self) -> str:
        if self._token is None or time.time() >= self._token.expires_at_epoch:
            self._token = self._mint_token()
        return f"Bearer {self._token.access_token}"

    def get_snapshots(
        self,
        airport: str,
        *,
        hours_back: int = 0,
        hours_forward: int = 9,
    ) -> list[dict[str, Any]]:
        """Return the `snapshots` array from GET /nexus/snapshots."""
        if not (0 <= hours_back <= 48):
            raise ValueError("hours_back must be 0..48")
        if not (0 <= hours_forward <= 48):
            raise ValueError("hours_forward must be 0..48")

        resp = self._session.get(
            f"{API_BASE}/nexus/snapshots",
            params={
                "airport": airport,
                "hours_back": hours_back,
                "hours_forward": hours_forward,
            },
            headers={"Authorization": self._bearer()},
            timeout=self._timeout,
        )
        resp.raise_for_status()
        return resp.json().get("snapshots", [])

    def get_flights(self, airport: str) -> dict[str, list[dict]]:
        """Return the full /flights response: {"inbound": [...], "outbound": [...]}.

        This endpoint returns the live tracked-flight list for the airport —
        approximately the next ~4 hours of upcoming departures with all the
        operational columns (dptr_gate, dptr_bag_pier_num, al_cde, mission_time,
        etc.) populated. No time-window parameters; the API decides scope.
        """
        resp = self._session.get(
            f"{API_BASE}/flights",
            params={"airport": airport},
            headers={"Authorization": self._bearer()},
            timeout=self._timeout,
        )
        resp.raise_for_status()
        body = resp.json()
        # Always return a dict with both arrays present so callers can rely on shape.
        return {
            "inbound": list(body.get("inbound") or []),
            "outbound": list(body.get("outbound") or []),
        }


def snapshot_airline(snap: dict, *, default: str = "") -> str:
    """Recover the airline code from a snapshot, even when airline_cde is null.

    Strategy:
      1. Use airline_cde if it's a non-empty string.
      2. Else parse it out of flight_key, which has the shape
         "YYYY-MM-DD#AL#FLTNUM#ORIG#DEST" per the API docs. The 2nd `#`-
         separated component is the airline code.
      3. flight_keys that start with "PARTIAL" don't have the airline
         in the expected slot — return empty string and let the caller
         decide (typically: skip the flight).

    Returns the uppercased airline code, or "" if unrecoverable.
    """
    # /nexus/snapshots calls this `airline_cde`; /flights calls it `al_cde`.
    for key in ("airline_cde", "al_cde"):
        code = (snap.get(key) or "")
        if isinstance(code, str):
            code = code.strip().upper()
            if code:
                return code

    fk = (snap.get("flight_key") or "").strip()
    if not fk or fk.startswith("PARTIAL"):
        return default

    parts = fk.split("#")
    # Expected shape: parts[0]=date, parts[1]=airline, parts[2]=fltnum, ...
    if len(parts) >= 2 and parts[1]:
        return parts[1].upper()
    return default


def snapshot_gate(snap: dict) -> str:
    """Return the gate string from a snapshot, with field-name fallbacks.

    The API doc says the field is `gate`, but the actual production data
    uses `dptr_gate`. Try documented first, fall back to observed.
    """
    return str(snap.get("gate") or snap.get("dptr_gate") or "").strip().upper()


def snapshot_pier(snap: dict) -> str:
    """Return the bag/cart staging pier number from a snapshot.

    The API doc described `pier` as the concourse letter, but ops needs
    the numeric pier (where bag tugs stage), which the production data
    exposes as `dptr_bag_pier_num`. The concourse letter is already
    conveyed by the gate string (e.g. "A14" / "T05"), so the slack post
    isn't losing information by switching pier to numeric.

    Preference order:
      1. dptr_bag_pier_num (the actual operator-facing pier number)
      2. pier (kept as a legacy fallback; not seen in production yet)
    """
    pier_num = str(snap.get("dptr_bag_pier_num") or "").strip()
    if pier_num:
        return pier_num
    return str(snap.get("pier") or "").strip().upper()
