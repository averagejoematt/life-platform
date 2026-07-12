"""#406/#1101 — the cockpit's sync strip: real ingestion write times, honest states.

Pins: /api/last_sync covers EVERY registry source (#1101 — active board sources +
paused, registry-driven so a new source appears automatically), reads real
ingested_at / webhook_ingested_at stamps when a pipe stamps its writes, falls back
to the day-granular DATE key with precision "day" (never implied minutes), reports
a never-written source honestly (last_seen null), and computes per-source status
against each source's OWN registry-derived threshold (e.g. Todoist's cadence-derived
72h — #471/#589), never a global constant. The front-end renders ALL sources (no
last_write filter), has no "← freshest" marker, and its glow is gated per source
via motion.js's shared wireFreshness() primitive (data-fresh-ts/-window).
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

from fakes import FakeDdbTable  # noqa: E402
from source_registry import public_board_sources, public_paused_sources, stale_hours_overrides  # noqa: E402
from web import site_api_data as sad  # noqa: E402

COCKPIT_JS = open(os.path.join(_REPO, "site/assets/js/cockpit.js")).read()
COCKPIT_CSS = open(os.path.join(_REPO, "site/assets/css/cockpit.css")).read()


def _with_fake_table(monkeypatch, per_source_items):
    def _query_hook(_table, **kwargs):
        expr = kwargs.get("KeyConditionExpression")
        # boto3 conditions carry the pk value in the expression tree.
        pk = expr._values[0]._values[1] if hasattr(expr, "_values") else ""
        for sid, items in per_source_items.items():
            if pk.endswith(f"SOURCE#{sid}"):
                return {"Items": items}
        return {"Items": []}

    monkeypatch.setattr(sad, "table", FakeDdbTable(query_hook=_query_hook))


def _body(monkeypatch, per_source_items):
    _with_fake_table(monkeypatch, per_source_items)
    return json.loads(sad.handle_last_sync()["body"])


def test_every_registry_source_rendered(monkeypatch):
    """#1101 AC: registry-driven — the payload covers EVERY registry source (active
    + paused), so the sync line renders them all and a new source appears
    automatically. The front-end applies no filter (pinned below)."""
    body = _body(monkeypatch, {})
    ids = [s["id"] for s in body["sources"]]
    expected = set(public_board_sources()) | set(public_paused_sources())
    assert set(ids) == expected
    assert len(ids) == len(expected)  # no dupes, count matches the registry


def test_last_sync_reads_real_write_stamps(monkeypatch):
    now = datetime.now(timezone.utc)
    body = _body(
        monkeypatch,
        {
            "whoop": [
                {"sk": "DATE#" + now.strftime("%Y-%m-%d"), "ingested_at": (now - timedelta(hours=1)).isoformat()},
                {"sk": "DATE#" + now.strftime("%Y-%m-%d"), "ingested_at": (now - timedelta(hours=2)).isoformat()},
            ],
            "apple_health": [{"sk": "DATE#" + now.strftime("%Y-%m-%d"), "webhook_ingested_at": (now - timedelta(minutes=30)).isoformat()}],
        },
    )
    by_id = {s["id"]: s for s in body["sources"]}
    assert by_id["whoop"]["last_write"] == (now - timedelta(hours=1)).isoformat()  # the max, not the first
    assert by_id["whoop"]["precision"] == "instant"
    assert by_id["whoop"]["status"] == "fresh"
    assert by_id["apple_health"]["last_write"] == (now - timedelta(minutes=30)).isoformat()
    assert body["server_now"]  # the client's skew anchor
    # #589: each active source carries its OWN registry-derived window — never a flat
    # guess — so the front-end pulse primitive can be driven honestly per source.
    assert all(isinstance(s["stale_hours"], (int, float)) for s in body["sources"] if s["status"] != "paused")


def test_missing_stamp_falls_back_to_day_granularity_never_invents(monkeypatch):
    """A source with DATE# records but no write stamps reports the day-granular
    DATE key as precision "day" (the /api/source_freshness basis) — last_write
    stays null, an instant is never invented."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    body = _body(monkeypatch, {"whoop": [{"sk": f"DATE#{today}"}]})
    by_id = {s["id"]: s for s in body["sources"]}
    assert by_id["whoop"]["last_write"] is None
    assert by_id["whoop"]["precision"] == "day"
    assert by_id["whoop"]["last_seen"].startswith(today)
    assert by_id["whoop"]["status"] == "fresh"  # today's record is inside whoop's window
    # Never written at all: nothing is faked.
    assert by_id["eightsleep"]["last_write"] is None
    assert by_id["eightsleep"]["last_seen"] is None
    assert by_id["eightsleep"]["status"] == "stale"


def test_status_uses_each_sources_own_registry_threshold(monkeypatch):
    """#1101 AC: staleness uses the per-source registry window, not a global
    constant — a 60h-old write is fresh for Todoist (72h cadence-derived, #471)
    but stale for Whoop (48h default)."""
    overrides = stale_hours_overrides(public_board_sources())
    assert overrides.get("todoist") == 72  # the registry premise this test rides on
    ts = (datetime.now(timezone.utc) - timedelta(hours=60)).isoformat()
    body = _body(monkeypatch, {"todoist": [{"sk": "DATE#x", "ingested_at": ts}], "whoop": [{"sk": "DATE#x", "ingested_at": ts}]})
    by_id = {s["id"]: s for s in body["sources"]}
    assert by_id["todoist"]["stale_hours"] == 72
    assert by_id["todoist"]["status"] == "fresh"
    assert by_id["whoop"]["status"] == "stale"


def test_behavioral_lapse_and_paused_states(monkeypatch):
    """A behavioral source's staleness is a logging lapse (behavioral-stale, never
    a broken-pipe claim) and a paused source says "paused" — same semantics as
    /api/source_freshness."""
    ts = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    body = _body(monkeypatch, {"withings": [{"sk": "DATE#x", "ingested_at": ts}]})
    by_id = {s["id"]: s for s in body["sources"]}
    assert by_id["withings"]["status"] == "behavioral-stale"  # 30d > 168h window, behavioral
    assert by_id["macrofactor"]["status"] == "behavioral-stale"  # never written, behavioral
    assert by_id["garmin"]["status"] == "paused"
    assert by_id["garmin"]["last_seen"] is None


def test_frontend_renders_all_sources_no_freshest_marker():
    """#1101: the front-end renders every source the API returns — no truthy-
    last_write filter — and the "← freshest" marker is gone (CSS rule too)."""
    assert ".filter((s) => s.last_write)" not in COCKPIT_JS
    assert "← freshest" not in COCKPIT_JS and "_sync.freshest" not in COCKPIT_JS
    assert "sync-freshest" not in COCKPIT_JS and "sync-freshest" not in COCKPIT_CSS
    # Honest non-writer states exist: paused + em-dash for never-written.
    assert '"paused"' in COCKPIT_JS and '"—"' in COCKPIT_JS
    # Day-granular sources get day-level wording, never implied minutes.
    assert "_dayAgoText" in COCKPIT_JS and '"today"' in COCKPIT_JS


def test_frontend_ticks_and_earns_the_glow():
    assert "setInterval(renderSyncLine, 30_000)" in COCKPIT_JS  # the ago ticks client-side
    # #589: the glow is the shared data-fresh-ts/-window primitive (motion.js's
    # wireFreshness()), not a flat client-side minute guess — each source earns its
    # own glow from ITS OWN registry-derived window.
    assert "data-fresh-ts=" in COCKPIT_JS and "data-fresh-window=" in COCKPIT_JS
    assert "s.stale_hours" in COCKPIT_JS
    assert "SYNC_FRESH_MIN" not in COCKPIT_JS and "is-fresh" not in COCKPIT_JS
    assert "d.server_now ? Date.parse(d.server_now) - Date.now()" in COCKPIT_JS  # skew-corrected, not naive
    # Stale states render truthfully (h/d formats exist, nothing hides them).
    assert "`${h}h ago`" in COCKPIT_JS and "d ago" in COCKPIT_JS
    # The old bespoke pulse mechanism is retired in favor of the shared .fr-dot primitive.
    assert ".sync-dot.is-fresh" not in COCKPIT_CSS and "syncPulse" not in COCKPIT_CSS
    assert "fr-dot" in COCKPIT_JS
