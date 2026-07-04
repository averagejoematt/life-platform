"""#406 — the cockpit's sync strip: real ingestion write times, honest states.

Pins: /api/last_sync reads ingested_at / webhook_ingested_at stamps (never the
day-granular DATE key), covers only the passive pipes, reports a missing stamp
as null instead of inventing one, and the front-end's glow is gated on the
earned-fresh window with truthful stale text.
"""

import json
import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

from web import site_api_data as sad  # noqa: E402

COCKPIT_JS = open(os.path.join(_REPO, "site/assets/js/cockpit.js")).read()
COCKPIT_CSS = open(os.path.join(_REPO, "site/assets/css/cockpit.css")).read()


def _with_fake_table(monkeypatch, per_source_items):
    class _T:
        def query(self, **kwargs):
            expr = kwargs.get("KeyConditionExpression")
            # boto3 conditions carry the pk value in the expression tree.
            pk = expr._values[0]._values[1] if hasattr(expr, "_values") else ""
            for sid, items in per_source_items.items():
                if pk.endswith(f"SOURCE#{sid}"):
                    return {"Items": items}
            return {"Items": []}

    monkeypatch.setattr(sad, "table", _T())


def test_last_sync_reads_real_write_stamps(monkeypatch):
    _with_fake_table(
        monkeypatch,
        {
            "whoop": [{"ingested_at": "2026-07-04T05:00:00+00:00"}, {"ingested_at": "2026-07-04T04:00:00+00:00"}],
            "eightsleep": [{"ingested_at": "2026-07-03T20:11:00+00:00"}],
            "apple_health": [{"webhook_ingested_at": "2026-07-04T05:30:00+00:00"}],
        },
    )
    body = json.loads(sad.handle_last_sync()["body"])
    by_id = {s["id"]: s for s in body["sources"]}
    assert by_id["whoop"]["last_write"] == "2026-07-04T05:00:00+00:00"  # the max, not the first
    assert by_id["apple_health"]["last_write"] == "2026-07-04T05:30:00+00:00"
    assert body["freshest"]["id"] == "apple_health"
    assert body["server_now"]  # the client's skew anchor


def test_missing_stamp_is_null_never_invented(monkeypatch):
    _with_fake_table(monkeypatch, {"whoop": [{"date": "2026-07-04"}]})  # no write stamps at all
    body = json.loads(sad.handle_last_sync()["body"])
    by_id = {s["id"]: s for s in body["sources"]}
    assert by_id["whoop"]["last_write"] is None
    assert by_id["eightsleep"]["last_write"] is None
    assert body["freshest"] is None


def test_only_passive_pipes_are_in_the_strip():
    """Behavioral sources (weigh-ins, lifts, food logs) must not appear — an
    'ago' there would read as a nag, and their motion is Matthew's, not the
    machine's."""
    assert set(sad._SYNC_SOURCES) == {"whoop", "eightsleep", "apple_health"}


def test_frontend_ticks_and_earns_the_glow():
    assert "setInterval(renderSyncLine, 30_000)" in COCKPIT_JS  # the ago ticks client-side
    assert "SYNC_FRESH_MIN" in COCKPIT_JS and "is-fresh" in COCKPIT_JS
    assert "d.server_now ? Date.parse(d.server_now) - Date.now()" in COCKPIT_JS  # skew-corrected, not naive
    # Stale states render truthfully (h/d formats exist, nothing hides them).
    assert "`${h}h ago`" in COCKPIT_JS and "d ago" in COCKPIT_JS
    # The pulse animation is gated on the fresh class only — no decorative glow.
    assert ".sync-dot.is-fresh" in COCKPIT_CSS
    assert COCKPIT_CSS.count("syncPulse") == 2  # defined once, applied once (on is-fresh)
