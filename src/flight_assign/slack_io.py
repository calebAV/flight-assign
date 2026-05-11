"""Slack I/O: scan a channel for the schedule, post assignments elsewhere."""

from __future__ import annotations

import logging
from typing import Callable, Iterable

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

DEFAULT_MAX_SCAN = 2000
PAGE_SIZE = 200

log = logging.getLogger(__name__)


class SlackClient:
    """Wraps slack_sdk."""

    def __init__(self, bot_token: str, channel_id: str):
        if not bot_token:
            raise ValueError("SlackClient requires a bot token")
        if not channel_id:
            raise ValueError("SlackClient requires a channel ID")
        self._client = WebClient(token=bot_token)
        self._channel_id = channel_id

    def find_message(
        self,
        predicate: Callable[[dict], bool],
        *,
        channel_id: str | None = None,
        max_scan: int = DEFAULT_MAX_SCAN,
    ) -> tuple[dict | None, int]:
        """Scan a channel newest-first, return (first match, n_scanned)."""
        target_channel = channel_id or self._channel_id
        cursor: str | None = None
        scanned = 0
        while scanned < max_scan:
            page_limit = min(PAGE_SIZE, max_scan - scanned)
            kwargs: dict = {"channel": target_channel, "limit": page_limit}
            if cursor:
                kwargs["cursor"] = cursor
            try:
                resp = self._client.conversations_history(**kwargs)
            except SlackApiError as exc:
                raise RuntimeError(
                    f"Slack history fetch failed for channel {target_channel}: "
                    f"{exc.response['error']}"
                ) from exc

            messages = resp.get("messages", []) or []
            for msg in messages:
                scanned += 1
                if predicate(msg):
                    return msg, scanned

            cursor = (resp.get("response_metadata") or {}).get("next_cursor")
            if not cursor or not messages:
                break

        return None, scanned

    def permalink(self, channel_id: str, ts: str) -> str | None:
        """Return a clickable Slack permalink for a (channel, ts) pair.
        Returns None on failure — caller should treat as soft failure."""
        try:
            resp = self._client.chat_getPermalink(channel=channel_id, message_ts=ts)
        except SlackApiError as exc:
            log.warning(
                "Could not get permalink for %s/%s: %s",
                channel_id, ts, exc.response.get("error"),
            )
            return None
        return resp.get("permalink")

    def post(self, text: str, *, blocks: Iterable[dict] | None = None) -> str:
        """Post a message to the default channel; return the ts."""
        try:
            resp = self._client.chat_postMessage(
                channel=self._channel_id,
                text=text,
                blocks=list(blocks) if blocks else None,
                unfurl_links=False,
                unfurl_media=False,
            )
        except SlackApiError as exc:
            raise RuntimeError(f"Slack post failed: {exc.response['error']}") from exc
        return resp.get("ts", "")
