"""Tests for the paginating Slack history scan."""

from unittest.mock import MagicMock

from flight_assign.slack_io import SlackClient


def _make_client_with_pages(pages: list[dict]) -> SlackClient:
    """Build a SlackClient whose underlying WebClient returns these pages
    in order from conversations_history(...).
    """
    cli = SlackClient(bot_token="xoxb-test", channel_id="C-test")
    mock_wc = MagicMock()
    mock_wc.conversations_history.side_effect = pages
    cli._client = mock_wc
    return cli


def test_find_message_matches_first_page():
    pages = [
        {
            "messages": [
                {"text": "a"},
                {"text": "MATCH"},
                {"text": "b"},
            ],
            "response_metadata": {"next_cursor": "cur1"},
        }
    ]
    cli = _make_client_with_pages(pages)
    msg, scanned = cli.find_message(lambda m: m["text"] == "MATCH")
    assert msg["text"] == "MATCH"
    assert scanned == 2  # 'a' then 'MATCH'


def test_find_message_paginates_until_match():
    """Match is on the 3rd page — must call conversations_history 3 times."""
    pages = [
        {"messages": [{"text": "p1m1"}, {"text": "p1m2"}],
         "response_metadata": {"next_cursor": "cur1"}},
        {"messages": [{"text": "p2m1"}, {"text": "p2m2"}],
         "response_metadata": {"next_cursor": "cur2"}},
        {"messages": [{"text": "p3m1"}, {"text": "MATCH"}, {"text": "p3m3"}],
         "response_metadata": {"next_cursor": "cur3"}},
    ]
    cli = _make_client_with_pages(pages)
    msg, scanned = cli.find_message(lambda m: m["text"] == "MATCH")
    assert msg["text"] == "MATCH"
    # Scanned: 2 + 2 + 2 (p3m1, MATCH stops the scan)
    assert scanned == 6
    assert cli._client.conversations_history.call_count == 3


def test_find_message_returns_none_when_nothing_matches():
    """Scan multiple pages, no match → return (None, scanned)."""
    pages = [
        {"messages": [{"text": f"m{i}"} for i in range(3)],
         "response_metadata": {"next_cursor": "cur1"}},
        {"messages": [{"text": f"m{i}"} for i in range(3, 6)],
         "response_metadata": {"next_cursor": ""}},
    ]
    cli = _make_client_with_pages(pages)
    msg, scanned = cli.find_message(lambda m: m["text"] == "NEVER")
    assert msg is None
    assert scanned == 6


def test_find_message_respects_max_scan():
    """If max_scan is small, stop early even when more pages exist."""
    pages = [
        {"messages": [{"text": f"m{i}"} for i in range(50)],
         "response_metadata": {"next_cursor": "cur1"}},
    ]
    cli = _make_client_with_pages(pages)
    msg, scanned = cli.find_message(lambda m: m["text"] == "NEVER", max_scan=10)
    assert msg is None
    # We stop after exhausting the page we got back, but the request was
    # limited to 10 messages — so scanned should be <= the page size we asked for.
    assert scanned <= 50
    # And we shouldn't have made a 2nd request
    assert cli._client.conversations_history.call_count == 1


def test_find_message_uses_channel_override():
    """When find_message is called with channel_id=X, the API call uses X."""
    pages = [
        {"messages": [{"text": "MATCH"}],
         "response_metadata": {"next_cursor": ""}}
    ]
    cli = _make_client_with_pages(pages)
    msg, _ = cli.find_message(
        lambda m: m["text"] == "MATCH",
        channel_id="C-OTHER",
    )
    assert msg is not None
    # Verify the channel argument that was passed
    call_kwargs = cli._client.conversations_history.call_args_list[0].kwargs
    assert call_kwargs["channel"] == "C-OTHER"


def test_find_message_defaults_to_constructor_channel():
    pages = [
        {"messages": [{"text": "MATCH"}],
         "response_metadata": {"next_cursor": ""}}
    ]
    cli = _make_client_with_pages(pages)  # channel="C-test"
    cli.find_message(lambda m: m["text"] == "MATCH")
    call_kwargs = cli._client.conversations_history.call_args_list[0].kwargs
    assert call_kwargs["channel"] == "C-test"
