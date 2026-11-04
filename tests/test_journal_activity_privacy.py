"""tests/test_journal_activity_privacy.py — journal ACTIVITY is private, including structured data
(owner ruling 2026-11-03; confirmation the same day: classify by source identity and field
sensitivity, fail closed for anything unclassified, and keep byte-for-byte invariance tests
including cross-endpoint inference checks).

Every journal fact in this file is SYNTHETIC. The Habitify ids are the real ids of the four habits
named "... Journal", already public in tests/fixtures/habitify/.

THE INFERENCE TEST (`tests/journal_activity_route_walk.py`). Three tables that differ ONLY in the
owner's private journal activity — none, every day, a few days (the journal partition, the two
journal habits on every Habitify row with the ingest's own roll-ups recomputed, a private in-app
note, the journal-derived partitions, the journal probe's health, and the presence record produced
by the real producer from those rows) — and every public GET route walked against each, with the
clock frozen at one instant. Every route's body must be byte-identical across the three, and so must
the whole set (a cross-endpoint inference needs at least one route to move).

NEGATIVE CONTROLS. (1) `--ungated`: the same walk with the activity policy publishing everything
must move the policy-governed routes (asserted below). (2) The same harness run against origin/main
e4889627e (recorded in the PR, not re-run here): 11 routes moved with the journal — /api/character,
/api/fulfillment_index, /api/habits, /api/journal_analysis, /api/mind_overview,
/api/observatory_week?domain=mind, /api/presence, /api/pulse, /api/snapshot, /api/status,
/api/survival — and the journal habits' names, a private note, the `notion` source id and the
`journal_presence` channel appeared on the wire.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))
sys.path.insert(0, str(ROOT / "scripts"))

from common import (
    activity_publication as AP,  # noqa: E402
    narrative_provenance as NP,  # noqa: E402
)

NOW = "2026-11-03T20:00:00+00:00"
VARIANTS = ("none", "daily", "gaps")
MORNING_ID = "99A94E6D-3D82-4BE9-85EF-8858CB4BA340"
EVENING_ID = "A862488C-8219-48EB-AD1F-90CBFDC37788"
FOOD_ID = "DBACD2CF-F839-42B2-A698-D214140EE370"
WHOOP_ID = "F5F5B8BB-62E8-4C74-9FD8-3C6E913F1DCD"
# Strings that must never reach the wire: the journal habits' names and ids, the synthetic private
# note, the journal source id and the fulfillment index's journal channel.
DIRECT_TOKENS = ("Morning Journal", "Evening Journal", MORNING_ID, EVENING_ID, "SYNTHETIC-PRIVATE-NOTE", "notion", "journal_presence")


def _walk(*args) -> dict:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "tests" / "journal_activity_route_walk.py"), "--now", NOW, *args],
        capture_output=True,
        text=True,
        timeout=300,
        cwd=str(ROOT),
    )
    assert proc.returncode == 0, proc.stderr[-3000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def walks() -> dict:
    return {v: _walk("--variant", v) for v in VARIANTS}


@pytest.fixture(scope="module")
def ungated() -> dict:
    return {v: _walk("--variant", v, "--ungated") for v in ("none", "daily")}


def _moved(runs: dict) -> list:
    base = runs["none"]["bodies"]
    return sorted(k for k in base if any(r["bodies"].get(k) != base[k] for r in runs.values()))


# ── the inference test ────────────────────────────────────────────────────────────────────


def test_the_walk_reaches_every_route(walks):
    for v, out in walks.items():
        assert out["routes"] >= 140 and out["answered"] >= out["routes"] - 3, (v, out["routes"], out["answered"])
        assert out["raised"] == {}, (v, out["raised"])
        assert out["unparsed_queries"] == 0, "a query the fake table could not read is a blind spot"


def test_no_public_route_moves_with_private_journal_activity(walks):
    assert _moved(walks) == [], "public routes whose body changes with journal activity alone"


def test_the_whole_public_surface_is_byte_identical_across_journal_variants(walks):
    """The cross-endpoint check: the SET of public responses, taken together, is one value."""

    def digest(out):
        return hashlib.sha256(json.dumps(out["bodies"], sort_keys=True).encode()).hexdigest()

    assert len({digest(walks[v]) for v in VARIANTS}) == 1
    assert set(walks["none"]["bodies"]) == set(walks["daily"]["bodies"]) == set(walks["gaps"]["bodies"])


def test_no_direct_journal_token_reaches_any_route(walks):
    for v, out in walks.items():
        for key, body in out["bodies"].items():
            hits = [t for t in DIRECT_TOKENS if t in body]
            assert not hits, (v, key, hits)


def test_the_walk_is_not_vacuous(walks):
    b = {k: json.loads(v)["body"] for k, v in walks["daily"]["bodies"].items()}
    habits = b["/api/habits"]
    assert len(habits["per_habit"]) == 5 and habits["history"] and habits["group_90d_avgs"]
    assert {h["name"] for h in habits["per_habit"]} >= {"Food Journal", "Whoop Journal"}  # public by the owner's word
    assert b["/api/habit_registry"]["count"] == 5
    presence = b["/api/presence"]
    assert presence["available"] is True and {c["id"] for c in presence["channels"]} == {"macrofactor", "withings", "habitify", "hevy"}
    fi = b["/api/fulfillment_index"]
    assert fi["method_version"] == 2 and any(d.get("state") == "ok" for d in fi["trend_7d"])
    assert set(fi["channels_adopted"]) == {"connection_tap", "interactions", "values_todoist"}
    status_ids = {c["id"] for g in b["/api/status"]["groups"] if g["id"] == "data_sources" for c in g["components"]}
    assert "whoop" in status_ids and "habitify" in status_ids and "notion" not in status_ids
    assert b["/api/status"]["health_check"]["passed"] == 2  # the two public probes, the journal's never counted
    assert "journal" not in b["/api/pulse"]["pulse"]["glyphs"]


def test_mutation_control_ungated_policy_moves_the_routes(ungated):
    moved = _moved(ungated)
    for route in ("/api/habits", "/api/presence", "/api/status", "/api/fulfillment_index", "/api/pulse", "/api/survival", "/api/character"):
        assert route in moved, (route, moved)


# ── the classification: sources ───────────────────────────────────────────────────────────


def test_the_journal_family_is_private_activity():
    for src in ("notion", "journal", "journal_analysis", "journal_quotes", "journal_presence", "flourishing", "mood_read"):
        assert AP.source_class(src) == AP.PRIVATE, src
        assert not AP.source_is_public(src)
    assert AP.is_private_activity_source("notion:enrichment")


def test_every_registry_source_engagement_channel_and_status_row_is_classified():
    """Fail closed — and a NEW source cannot land silently: it must be classified to be served."""
    from ingestion.source_registry import SOURCE_REGISTRY, engagement_channels

    unclassified = [s for s in SOURCE_REGISTRY if AP.source_class(s) is None]
    assert unclassified == [], f"classify these in narrative_provenance or activity_publication: {unclassified}"
    assert [c for c in engagement_channels() if AP.source_class(c) is None] == []
    tree = ast.parse((ROOT / "lambdas/web/site_api_status.py").read_text())
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "_DATA_SOURCES" for t in node.targets):
            ids = {elt.elts[0].value for elt in node.value.elts}
    assert ids and [s for s in ids if AP.source_class(s) is None] == []


def test_activity_only_sources_never_reclassify_a_narrative_family():
    for src, cls in AP.ACTIVITY_ONLY_SOURCES.items():
        assert NP.classify(src) is None, f"{src} is classified in narrative_provenance; do not shadow it"
        assert cls == AP.PUBLIC


def test_an_unclassified_source_is_not_public():
    assert AP.source_class("a_source_added_tomorrow") is None
    assert not AP.source_is_public("a_source_added_tomorrow")
    assert AP.public_mapping({"whoop": 1, "notion": 2, "a_source_added_tomorrow": 3}) == {"whoop": 1}


# ── the classification: habits, by identity ───────────────────────────────────────────────


def test_journal_habits_are_private_and_the_other_journals_public_by_id():
    assert not AP.habit_is_public("Morning Journal", {"habit_id": MORNING_ID})
    assert not AP.habit_is_public("Evening Journal", {"habit_id": EVENING_ID})
    assert not AP.habit_is_public("Renamed Anything", {"habit_id": MORNING_ID})  # identity, not wording
    assert AP.habit_is_public("Food Journal", {"habit_id": FOOD_ID})
    assert AP.habit_is_public("Whoop Journal", {"habit_id": WHOOP_ID})
    assert AP.habit_is_public("Whatever it is called now", {"habit_id": WHOOP_ID})


def test_an_unclassified_habit_is_not_published_until_classified():
    assert not AP.habit_is_public("A habit added tomorrow", {"habit_id": "NEW-ID"})
    assert not AP.habit_is_public("A habit added tomorrow")
    # the owner's registry field is the no-code classification path...
    assert AP.habit_is_public("A habit added tomorrow", {"habit_id": "NEW-ID"}, {"publication": "public"})
    assert not AP.habit_is_public("Food Journal", {"habit_id": FOOD_ID}, {"publication": "private"})
    # ...but it can never publish the journal.
    assert not AP.habit_is_public("Morning Journal", {"habit_id": MORNING_ID}, {"publication": "public"})


def test_the_public_habit_ids_carry_no_journal_id():
    assert not ({MORNING_ID, EVENING_ID} & AP.PUBLIC_HABIT_IDS)
    assert not (set(AP.HABIT_FAMILIES) & AP.PUBLIC_HABIT_IDS)


# ── the classification: fields ────────────────────────────────────────────────────────────


def _ingest_status_fields() -> set:
    """Every key `ingestion.habitify_lambda.transform` writes into a habit status."""
    src = (ROOT / "lambdas/ingestion/habitify_lambda.py").read_text()
    keys = set(re.findall(r'habit_statuses\[name\]\["(\w+)"\]', src))
    m = re.search(r"habit_statuses\[name\] = \{(.*?)\n        \}", src, re.S)
    assert m, "the status literal moved — update this guard"
    keys |= set(re.findall(r'"(\w+)":', m.group(1)))
    keys |= {"aliases"} if 'entry["aliases"]' in src else set()
    return keys


def test_every_field_the_ingest_writes_is_classified():
    written = _ingest_status_fields()
    assert {"status", "notes", "habit_id", "completed_at"} <= written  # the parser is reading the real literal
    assert sorted(written - set(AP.HABIT_STATUS_FIELDS)) == [], "classify the new field in HABIT_STATUS_FIELDS (unlisted = private)"


def test_free_text_and_timing_are_private_even_on_a_public_habit():
    st = {
        "status": "completed",
        "habit_id": FOOD_ID,
        "group": "Optimize",
        "notes": ["synthetic"],
        "notes_at": ["x"],
        "completed_at": "2026-11-02T14:00:00Z",
        "a_field_added_tomorrow": 1,
    }
    out = AP.public_habit_statuses({"Food Journal": st})
    assert out == {"Food Journal": {"status": "completed", "habit_id": FOOD_ID, "group": "Optimize"}}


def test_public_group_shares_ignore_private_habits():
    def st(hid, done):
        return {"status": "completed" if done else "failed", "habit_id": hid, "group": "Optimize"}

    base = {"Food Journal": st(FOOD_ID, True), "Whoop Journal": st(WHOOP_ID, False)}
    for journal_done in (True, False):
        statuses = dict(base, **{"Morning Journal": st(MORNING_ID, journal_done), "Evening Journal": st(EVENING_ID, journal_done)})
        assert AP.public_group_pcts(statuses, ["Optimize"]) == {"Optimize": 50}
    only_private = {"Morning Journal": dict(st(MORNING_ID, True), group="Mind")}
    assert AP.public_group_pcts(only_private, ["Mind"]) == {}  # a group left with no public habit is omitted


# ── presence: the producer's public projection ───────────────────────────────────────────


def test_public_presence_never_moves_with_journal_dates_or_journal_habit_completions():
    from content import engagement_core as E

    assert "notion" not in E.PUBLIC_CHANNELS and "macrofactor" in E.PUBLIC_CHANNELS
    base = {"macrofactor": ["2026-11-01"], "withings": ["2026-10-30"], "hevy": [], "habitify": ["2026-10-31"]}
    outs = []
    for journal in ([], ["2026-11-02", "2026-11-01", "2026-10-31"]):
        sig = E.compute_public_presence("2026-11-03", dict(base, notion=journal), experiment_start="2026-09-06")
        outs.append(json.dumps(sig, sort_keys=True, default=str))
    assert outs[0] == outs[1]
    row_journal_only = {
        "habit_statuses": {"Morning Journal": {"status": "completed", "habit_id": MORNING_ID}},
        "total_completed": Decimal("1"),
    }
    assert E.channel_counts_as_logged("habitify", row_journal_only) is True  # the private read counts it...
    assert E.public_counts_as_logged("habitify", row_journal_only) is False  # ...the public one never does


# ── the fulfillment index: method 2 ──────────────────────────────────────────────────────


def test_fulfillment_index_public_method_has_no_journal_input_and_the_private_method_is_unchanged():
    from health import fulfillment_index as fi

    assert fi.PRIVATE_CHANNELS == ("journal_presence",)
    assert "journal_presence" not in fi.PUBLIC_CHANNEL_NAMES and fi.PUBLIC_METHOD_VERSION == 2
    adopted = {n: True for n in fi.CHANNEL_NAMES}
    scores = {"connection_tap": 50, "interactions": 60, "values_todoist": 0}
    pub = [fi.compose_day("d", adopted, dict(scores, journal_presence=j), roster=fi.PUBLIC_CHANNELS) for j in (0, 100)]
    assert pub[0] == pub[1] and "journal_presence" not in pub[0]["channels"]
    assert pub[0]["coverage"] == 1.0 and pub[0]["score"] == 43.5
    # The owner's private read (method 1) is unchanged: the same four channels, the same arithmetic.
    full = fi.compose_day("d", adopted, dict(scores, journal_presence=100))
    assert full["score"] == 52.0 and full["channels"]["journal_presence"]["weight"] == 0.15
    assert "journal" not in fi.PUBLIC_DISCLOSURE.lower().replace("journal activity is private", "")
    assert [m["version"] for m in fi.PUBLIC_METHOD_HISTORY] == [1, 2]


# ── other serializers ────────────────────────────────────────────────────────────────────


def test_input_manifest_is_rejudged_over_public_sources():
    from common.input_manifest import public_manifest

    m = {
        "status": "partial",
        "complete": False,
        "degraded": ["notion"],
        "unobserved": [],
        "sources": {"whoop": {"status": "fresh"}, "notion": {"status": "stale"}},
    }
    pm = public_manifest(m)
    assert pm["status"] == "complete" and pm["complete"] is True and pm["degraded"] == [] and set(pm["sources"]) == {"whoop"}


def test_journal_derived_character_components_are_never_named():
    from health import character_privacy as cp

    assert not cp.component_is_publishable("journal_consistency")
    assert not cp.component_is_publishable("values_alignment")
    assert cp.component_is_publishable("vice_control")
    assert cp.event_driver_score("journal_consistency", {"score": 90}) is None


def test_pulse_json_carries_no_journal_or_journal_mood_glyph():
    from content import site_writer

    p = site_writer._compute_pulse(
        vitals={}, journey={}, training={}, journal_data={"entries": 3, "themes": ["x"]}, mood_data={"mood_avg": 4}
    )
    glyphs = p["pulse"]["glyphs"]
    assert "journal" not in glyphs and "mind" not in glyphs and p["pulse"]["signals_total"] == len(glyphs)


def test_the_homepage_portrait_carries_no_journal_figure():
    import publish_snapshot as ps

    assert "journal_analysis" not in ps.LIVE_ENDPOINTS

    class Ctx:
        as_of = "2026-11-03"
        fetched = {
            "mind_overview": {"mind": {"total_interactions_30d": 2, "journal_entries_30d": 9}},
            "journal_analysis": {"total_analyzed": 9},
        }

    block = ps._portrait_block(Ctx(), "2026-09-06")
    assert block["data"]["mind"] == {"state": "private", "text": ps.MIND_PRIVATE_TEXT}
    assert "9" not in json.dumps(block["data"]["mind"])
    src = (ROOT / "www/src/pages/index.astro").read_text()
    for gone in ("entries_total", "entries_30d", "the last on", "The journal went quiet"):
        assert gone not in src, gone


def test_activity_overrides_never_publish_a_journal_family():
    journal = {"notion", "journal", "journal_analysis", "journal_quotes", "journal_presence", "flourishing", "mood_read"}
    assert not (set(AP.ACTIVITY_OVERRIDES) & journal)
    assert set(AP.ACTIVITY_OVERRIDES) == {"genome"}, "every override is an owner-visible decision: name it in the PR"
