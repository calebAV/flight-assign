"""Slack I/O: read recent #flight-assign history, send assignment messages."""

from __future__ import annotations

from typing import Iterable

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

# Default history scan: 50 messages is plenty — the schedule is usually
# the most recent JSON-looking message, posted weekly.
DEFAULT_HISTORY_LIMIT = 50


class SlackClient:
    """Thin wrapper around slack_sdk for the two calls we need."""

    def __init__(self, bot_token: str, channel_id: str):
        if not bot_token:
            raise ValueError("SlackClient requires a bot token")
        if not channel_id:
            raise ValueError("SlackClient requires a channel ID")
        self._client = WebClient(token=bot_token)
        self._channel_id = channel_id

    def recent_messages(self, limit: int = DEFAULT_HISTORY_LIMIT) -> list[dict]:
        """Return up to `limit` recent messages, newest first."""
        try:
            resp = self._client.conversations_history(
                channel=self._channel_id,
                limit=limit,
            )
        except SlackApiError as exc:
            raise RuntimeError(f"Slack history fetch failed: {exc.response['error']}") from exc
        return list(resp.get("messages", []))

    def post(self, text: str, *, blocks: Iterable[dict] | None = None) -> str:
        """Post a message; return the ts of the posted message."""
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
