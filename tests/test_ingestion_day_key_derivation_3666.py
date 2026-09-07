"""#3666 — every ingestion `DATE#` writer declares WHERE its day came from.

THE CLASS, NOT THE INSTANCE
---------------------------
#3666 opened as a habitify bug and was widened when a second, unrelated pipeline showed
the identical shape within the hour:

    habitify_lambda            given `created_date` (a UTC instant)  -> bucketed by UTC date,
                               filed under a PACIFIC `DATE#` key
    health_auto_export_lambda  given "2026-09-06 19:15:00 -0700"     -> re-derived the day in
                               UTC, so 980 mL of water logged at 19:15 PT on Sep 6 landed
                               on `DATE#2026-09-07`

Two codebases, one missing invariant: **a `DATE#` key must be derived from the datum's own
timestamp, in the frame the key claims to name.** Both instances were locally defensible
— habitify's site carried a written `utc-exempt(#2811)` reason, and HAE's carries a
signed-off audit (`docs/audits/TD-19_DATE_PARTITION_AUDIT.md`, TD-19 Phase 2) plus a
registry facet declaring the frame. Locally defensible and globally wrong is exactly the
shape a per-site exemption produces, so fixing two sites and stopping would have been the
same mistake at a different scale.

WHAT THIS GUARD DOES, AND WHAT IT HONESTLY CANNOT
-------------------------------------------------
It **derives** the set of ingestion modules that construct a `DATE#` sort key (an AST
scan for a write-position `"sk"` whose value contains the literal), and requires every one
of them to be registered below with (a) where the day comes from, (b) which calendar the
key names, and (c) a written reason. An unregistered writer reds; a registered writer that
disappears reds; a non-Pacific frame with no reason reds.

It does NOT claim to prove the semantics — no static scan can read "this variable holds
the reading's own timestamp". What it makes impossible is a THIRD instance landing
*silently*: a new `DATE#` writer cannot merge without someone writing down which frame it
uses and why, and the frames it declares are cross-checked against the live
`source_registry.day_key_frame` facet so the two records can never drift apart.

That is the same contract shape as tests/test_module_size_guard.py's BASELINE and
tests/test_utc_day_fleet_ratchet_2811.py's residue: a derived set, an explicit registry,
and a ratchet that only tightens.

Run:  python3 -m pytest tests/test_ingestion_day_key_derivation_3666.py -v
"""

import ast
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, os.path.join(str(ROOT), "lambdas"))

from ingestion.source_registry import day_key_frame_for  # noqa: E402

INGESTION = ROOT / "lambdas" / "ingestion"

# ── The vocabulary. Four honest origins for a `DATE#` day. ───────────────────────────
#   reading_timestamp — the datum's own instant, converted into the key's frame. THE
#                       default and the only one that survives an evening edit.
#   event_date        — the source hands over a calendar date directly (a CSV row's
#                       `Date`, a measurement session, a lab draw). Nothing to convert.
#   ingest_clock      — the day the platform observed something, not the day it happened.
#                       Legitimate only when the record IS about the ingest (an import
#                       receipt, an absence marker) and never for a behavioural datum.
#   inherited         — writes onto a key some other writer already derived.
ORIGINS = ("reading_timestamp", "event_date", "ingest_clock", "inherited")
FRAMES = ("pacific", "utc", "n/a")

# ── THE REGISTRY. Every module the AST scan finds must appear here. ──────────────────
# `source` ties the entry to source_registry's `day_key_frame` facet where one exists, so
# a module and the registry can never claim different calendars.
DAY_KEY_WRITERS = {
    "habitify_lambda.py": {
        "source": "habitify",
        "origin": "reading_timestamp",
        "frame": "pacific",
        "reason": (
            "#3666: the supplement bridge writes DATE#{date_str} where date_str is the Pacific day "
            "transform() attributed the completions to, via GET /logs/{habit_id}.created_date -> "
            "pacific_date_of. The vendor's /journal day-bucket is UTC and is deliberately NOT the key."
        ),
    },
    "ingestion_framework.py": {
        "source": None,  # the shared writer; the day arrives from each source's own fetch
        "origin": "inherited",
        "frame": "pacific",
        "reason": (
            "The SIMP-2 store and the #2643 absence marker both write the date the caller resolved. "
            "Gap detection anchors on pacific_now() (framework:416, the 2026-07-10 truth-audit fix), "
            "so a framework-derived day is Pacific; a source that hands it a different frame owns that."
        ),
    },
    "macrofactor_lambda.py": {
        "source": "macrofactor",
        "origin": "event_date",
        "frame": "pacific",
        "reason": (
            "The CSV row carries its own calendar date in the owner's local (Pacific) day — there is "
            "no instant to convert. #2394 pinned the parse so a locale-formatted date can never become "
            "sk='DATE#April 4, 2026' again."
        ),
    },
    "measurements_ingestion_lambda.py": {
        "source": "measurements",
        "origin": "event_date",
        "frame": "pacific",
        "reason": "The tape-measure session date is entered by the owner as a calendar day. No instant exists to re-frame.",
    },
    "food_delivery_lambda.py": {
        "source": "food_delivery",
        "origin": "event_date",
        "frame": "pacific",
        "reason": (
            "Per-transaction rows key on the statement's own transaction date (DATE#{d}#TXN#{id}). The "
            "one ingest_clock key in this module is the import RECEIPT (pacific_today()), which is a fact "
            "about the import and not about a behaviour — the sanctioned ingest_clock case."
        ),
    },
    "enrichment_lambda.py": {
        "source": "strava",
        "origin": "inherited",
        "frame": "pacific",
        "reason": "Updates an EXISTING strava DATE# record in place; it never derives a day, it re-opens one.",
    },
    "whoop_lambda.py": {
        "source": "whoop",
        "origin": "reading_timestamp",
        "frame": "utc",
        "reason": (
            "RESIDUAL, and not a writer: the sks built here are the RECONCILER's expected set "
            "(_utc_day(sleep['start'])), compared against stored keys to find gaps — the real writes go "
            "through ingestion_framework in the Pacific frame. So the reconciler's frame and the store's "
            "frame disagree for the evening PT hours. Same class as #3666, own blast radius, own issue; "
            "flagged here rather than fixed so it cannot be forgotten."
        ),
    },
    "health_auto_export_lambda.py": {
        "source": "apple_health",
        "origin": "reading_timestamp",
        "frame": "utc",
        "reason": (
            "THE OPEN EXEMPTION #3666 NAMES AND DOES NOT CLOSE. parse_date_str converts the reading's "
            "offset-aware timestamp to UTC before taking the day (TD-19 Phase 2, "
            "docs/audits/TD-19_DATE_PARTITION_AUDIT.md), so 33.14 fl_oz of water logged 2026-09-06 19:15 "
            "-0700 stored 980 mL on DATE#2026-09-07. This is a RULING, not a slip: source_registry "
            "declares day_key_frame='utc' and vitals_resolver (#3287), freshness_checker (#3257) and "
            "pacific_time.anchor_day_key all read that facet. Flipping it re-frames 2,508 already-stored "
            "rows with no backfill available, producing a silent mid-history discontinuity in the "
            "platform's densest partition (CGM, steps, BP, state of mind, workouts). It needs its own "
            "issue with a migration plan, not a one-line change riding a habitify fix."
        ),
    },
}


# ── DERIVING THE SET ─────────────────────────────────────────────────────────────────


def _has_date_key_literal(node) -> bool:
    return any(isinstance(n, ast.Constant) and isinstance(n.value, str) and "DATE#" in n.value for n in ast.walk(node))


def date_key_writers() -> set:
    """Ingestion modules that build a `DATE#` sort key in a WRITE position.

    Write position = a dict entry or subscript assignment whose key is ``"sk"``. That is
    what distinguishes a writer from the many modules that merely mention `DATE#` in a
    docstring or slice one off a stored key when reading.
    """
    found = set()
    for path in sorted(INGESTION.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values):
                    if isinstance(key, ast.Constant) and key.value == "sk" and _has_date_key_literal(value):
                        found.add(path.name)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Subscript) and isinstance(getattr(target, "slice", None), ast.Constant):
                        if target.slice.value == "sk" and _has_date_key_literal(node.value):
                            found.add(path.name)
    return found


# ── THE RATCHET ──────────────────────────────────────────────────────────────────────


def test_the_writer_set_is_derived_and_fully_registered():
    """A NEW `DATE#` writer cannot land without declaring its frame. This is the whole
    point — #3666's second instance was in a pipeline nobody thought to look at."""
    derived = date_key_writers()
    unregistered = sorted(derived - set(DAY_KEY_WRITERS))
    assert not unregistered, (
        "New ingestion module(s) construct a DATE# sort key with no declared day-key "
        "derivation (#3666). Add an entry naming where the day comes from, which calendar "
        "the key names, and why:\n  " + "\n  ".join(unregistered)
    )


def test_the_registry_has_no_stale_entries():
    """An entry for a module that no longer writes a key is dead weight, and worse, it
    licences a silent regrowth back to whatever it used to say."""
    derived = date_key_writers()
    stale = sorted(set(DAY_KEY_WRITERS) - derived)
    assert not stale, "DAY_KEY_WRITERS names modules that no longer write a DATE# key — prune them:\n  " + "\n  ".join(stale)


def test_every_entry_uses_the_declared_vocabulary():
    for name, entry in sorted(DAY_KEY_WRITERS.items()):
        assert entry["origin"] in ORIGINS, f"{name}: unknown origin {entry['origin']!r}"
        assert entry["frame"] in FRAMES, f"{name}: unknown frame {entry['frame']!r}"


def test_every_entry_carries_a_written_reason():
    """A registry of bare labels is decoration. The reason is the artifact."""
    for name, entry in sorted(DAY_KEY_WRITERS.items()):
        reason = entry.get("reason") or ""
        assert len(reason) >= 80, f"{name}: the day-key derivation needs a real written reason, got {reason!r}"


def test_a_non_pacific_frame_must_name_the_issue_that_ruled_on_it():
    """`DATE#` keys are Pacific days by platform default (#2811). A UTC one is a RULING,
    and a ruling with no issue number behind it is an exemption nobody can audit."""
    for name, entry in sorted(DAY_KEY_WRITERS.items()):
        if entry["frame"] == "pacific":
            continue
        assert "#" in entry["reason"] or "TD-" in entry["reason"], f"{name}: a {entry['frame']} frame must cite the ruling that chose it"


def test_the_declared_frames_agree_with_the_live_source_registry():
    """The two records of a source's calendar cannot be allowed to drift apart — that is
    precisely how habitify ended up filing a UTC bucket under a Pacific key."""
    disagreements = []
    for name, entry in sorted(DAY_KEY_WRITERS.items()):
        source = entry.get("source")
        if not source:
            continue
        facet = day_key_frame_for(source)
        if source == "whoop":
            # The reconciler's residual: the STORE is Pacific (framework) and the facet
            # agrees; only the expected-set computation is UTC. Pinned by its own test.
            continue
        if facet != entry["frame"]:
            disagreements.append(f"{name}: declares {entry['frame']!r}, source_registry.day_key_frame says {facet!r}")
    assert not disagreements, "\n".join(disagreements)


def test_the_only_utc_framed_writers_are_the_two_named_residuals():
    """The set, pinned. Closing either shrinks this — a THIRD member is a new defect."""
    utc = {name for name, entry in DAY_KEY_WRITERS.items() if entry["frame"] == "utc"}
    assert utc == {"health_auto_export_lambda.py", "whoop_lambda.py"}, (
        "The UTC-framed DATE# writer set changed. This ratchet only shrinks: closing "
        f"health_auto_export (TD-19 Phase 2 reversal + backfill) or whoop's reconciler removes a member. Got: {sorted(utc)}"
    )


def test_habitify_is_registered_as_reading_timestamp_in_the_pacific_frame():
    """The entry #3666 actually closes, pinned by name so a regression cannot quietly
    re-declare it. The BEHAVIOUR behind this entry is proven in
    tests/test_habitify_pacific_attribution_3666.py, not by this registry."""
    entry = DAY_KEY_WRITERS["habitify_lambda.py"]
    assert (entry["origin"], entry["frame"]) == ("reading_timestamp", "pacific")
    assert "created_date" in entry["reason"]
    src = (INGESTION / "habitify_lambda.py").read_text(encoding="utf-8")
    assert "pacific_date_of" in src, "habitify no longer derives its day from the reading's own timestamp"


def test_the_hae_exemption_still_describes_the_live_code():
    """An exemption whose reason has gone stale is worse than none — it asserts a shape
    the tree no longer has. If HAE stops converting to UTC, this entry must move."""
    src = (INGESTION / "health_auto_export_lambda.py").read_text(encoding="utf-8")
    assert "def parse_date_str" in src
    assert 'astimezone(timezone.utc).strftime("%Y-%m-%d")' in src, "HAE's day derivation changed — update or retire its #3666 exemption"
    assert day_key_frame_for("apple_health") == "utc"


def test_the_scan_would_see_a_planted_writer(tmp_path):
    """The instrument, tested. A guard that cannot fire is the #3666 class itself —
    #2811's fleet ratchet was blind to a whole call shape for two slices."""
    planted = INGESTION / "_planted_day_key_writer_3666.py"
    planted.write_text('X = {"pk": "USER#matthew#SOURCE#x", "sk": f"DATE#{d}"}\n', encoding="utf-8")
    try:
        assert "_planted_day_key_writer_3666.py" in date_key_writers()
    finally:
        planted.unlink()
    assert "_planted_day_key_writer_3666.py" not in date_key_writers()


def test_the_scan_ignores_a_mere_mention():
    """It must distinguish a WRITER from the many modules that name `DATE#` in prose or
    slice one off a stored key while reading — otherwise the registry fills with noise
    and stops being read."""
    planted = INGESTION / "_planted_day_key_reader_3666.py"
    planted.write_text('"""Reads sk DATE#YYYY-MM-DD."""\nd = sk.replace("DATE#", "")[:10]\n', encoding="utf-8")
    try:
        assert "_planted_day_key_reader_3666.py" not in date_key_writers()
    finally:
        planted.unlink()
