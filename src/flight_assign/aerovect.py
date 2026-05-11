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

    # ---- auth -------------------------------------------------------------

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
        # Auth0 returns expires_in seconds; tokens are 10h per docs.
        expires_in = int(body.get("expires_in", 36000))
        return _CachedToken(
            access_token=access_token,
            expires_at_epoch=time.time() + expires_in - TOKEN_GRACE_SECONDS,
        )

    def _bearer(self) -> str:
        if self._token is None or time.time() >= self._token.expires_at_epoch:
            self._token = self._mint_token()
        return f"Bearer {self._token.access_token}"

    # ---- endpoints --------------------------------------------------------

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
