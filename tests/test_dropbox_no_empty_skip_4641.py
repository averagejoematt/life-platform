"""#4641: Dropbox's COST-03 "recently empty" skip is gone and must not silently return.

The skip had a 25-minute window under a 30-minute cron, so it never fired (6 of 672 polls found
files). Removing it is the honest fix: the 2-hour cadence is what saves calls, and a poll that
always reaches Dropbox always proves the credential. These tests pin the BEHAVIOUR, not a name:
a tracker that says "empty a second ago" must not stop the handler reaching list_folder.
"""

import os
from datetime import datetime, timezone
from unittest.mock import MagicMock

# The shape Dropbox /files/list_folder returns for a file entry (".tag" == "file").
NON_MACROFACTOR_FILE = {
    ".tag": "file",
    "name": "notes.txt",
    "path_lower": "/life-platform/notes.txt",
    "id": "id:AAAAAAAAAAAAAAAAAAAAAA",
    "size": 12,
    "content_hash": "0" * 64,
}


def _wire(monkeypatch, listing):
    os.environ.setdefault("S3_BUCKET", "test-bucket")
    dp = _dp()
    table = MagicMock()
    now = datetime.now(timezone.utc).isoformat()
    table.get_item.return_value = {"Item": {"last_empty_poll_at": now, "file_hashes": []}}
    calls = []
    monkeypatch.setattr(dp, "table", table)
    monkeypatch.setattr(dp, "_record_health", lambda **kw: None)
    monkeypatch.setattr(dp, "get_dropbox_secret", lambda: {"dropbox_app_key": "k", "dropbox_app_secret": "s", "dropbox_refresh_token": "r"})
    monkeypatch.setattr(dp, "refresh_access_token", lambda *a: "token")
    monkeypatch.setattr(dp, "list_folder", lambda tok: calls.append(tok) or listing)
    return table, calls


def _dp():
    from ingestion import dropbox_poll_lambda as dp

    return dp


def test_empty_listing_still_polls_and_writes_no_empty_marker(monkeypatch):
    table, calls = _wire(monkeypatch, [])
    resp = _dp().lambda_handler({}, None)
    assert calls == ["token"], "a tracker saying 'empty a second ago' must not skip the Dropbox call"
    assert resp["body"] == "No files found"
    for c in table.update_item.call_args_list:
        assert "last_empty_poll_at" not in str(c), "the dead empty-poll marker must not be written"


def test_non_macrofactor_listing_still_polls_and_writes_no_empty_marker(monkeypatch):
    table, calls = _wire(monkeypatch, [NON_MACROFACTOR_FILE])
    resp = _dp().lambda_handler({}, None)
    assert calls == ["token"]
    assert resp["body"] == "No MacroFactor CSVs found"
    for c in table.update_item.call_args_list:
        assert "last_empty_poll_at" not in str(c)
