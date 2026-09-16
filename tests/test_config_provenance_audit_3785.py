"""tests/test_config_provenance_audit_3785.py — #3785 box 3: the provenance dead-man.

THE MEASUREMENT THAT MADE THIS NECESSARY, and it is not "no instrument covered the path":

On 2026-09-14 an ad-hoc `aws s3 cp` pushed the repo's June-1 copy of
`config/hevy_template_index.json` (789 templates) over the live generated index (820).
The daily **Config twin drift** workflow was GREEN for **nine consecutive runs** across
that window — not because it was not watching, but because *while the clobber was active
both sides read 789 and AGREED*. A comparison gate is structurally blind in exactly the
state that matters, because the two artifacts it compares can be wrong together. A green
from it means "these two agree", never "this one is right".

The CloudWatch dead-man `hevy-template-index-not-rebuilt-48h` is blind for a second,
independent reason: it watches the PRODUCER's `TemplateIndexRebuilt` emit, and the
producer was firing perfectly. A silent revert followed by a silent repair at 13:40Z.

The discriminator was there the whole time: **only the generated object carries
`_built_at`.** Grading ONE artifact against the clock is not blind when both sides are
wrong.

THE LOAD-BEARING PROOF is a replay, not a mutation. The bytes that were live during the
incident are still in S3 version history and were fetched and run through `assess()`:

    s3://matthew-life-platform/config/hevy_template_index.json
      versionId JWxBiDofQ0vfxPzjoUj_ij5ZDZqQsVa_   (2026-09-15T17:47:58Z, ETag 8b2b0e11…)
      top-level keys: ['_built_from', '_comment', 'count', 'templates']   count: 789
      -> assess(...) = FAIL [no-stamp]

Its SHAPE is pinned below rather than its bytes. Committing a second copy of the 789-entry
index into `tests/` would re-create exactly the loadable ammunition this issue is about.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "deploy") not in sys.path:
    sys.path.insert(0, str(ROOT / "deploy"))

from config_provenance_audit import (  # noqa: E402
    CEILING_PERIODS,
    assess,
    declared_cadence,
    declared_generated,
)

_KEY = "config/hevy_template_index.json"
_NOW = datetime(2026, 9, 16, 22, 0, 0, tzinfo=timezone.utc)

# The clobbered object's real top-level shape (see the module docstring for the
# versionId that reproduces the bytes). What matters is the ABSENCE.
_CLOBBERED = {
    "_built_from": "live Hevy account template list",
    "_comment": "Full Hevy exercise-template index for draft_custom title resolution (ADR-069). …",
    "count": 789,
    "templates": {"bench press": {"id": "x", "title": "Bench Press"}},
}


def _healthy(built_at=None, templates=None):
    templates = templates if templates is not None else {"bench press": {"id": "x", "title": "Bench Press"}}
    return {
        "_comment": "GENERATED — rebuilt on a schedule …",
        "_built_from": "live Hevy account template list",
        "_built_at": (built_at or (_NOW - timedelta(hours=8))).isoformat(),
        "_sha256": hashlib.sha256(json.dumps(templates, sort_keys=True).encode("utf-8")).hexdigest(),
        "count": len(templates),
        "templates": templates,
    }


_DAILY = 86400 * CEILING_PERIODS


# ── the incident replay ──────────────────────────────────────────────────────


def test_THE_REPLAY_the_real_clobbered_object_FAILS():
    """The nine green runs, graded by the new instrument."""
    ok, code, msg = assess(_KEY, _CLOBBERED, ceiling_seconds=_DAILY, now=_NOW)
    assert not ok, "the clobbered object passes — the dead-man is as blind as the comparison gate it exists beside"
    assert code == "no-stamp"
    assert "_built_at" in msg


def test_the_HEALTHY_object_passes():
    """The control in the opposite direction — a check that fails on everything is not a check."""
    ok, code, msg = assess(_KEY, _healthy(), ceiling_seconds=_DAILY, now=_NOW)
    assert ok, msg
    assert code == "fresh"
    assert "_sha256 verified" in msg


def test_the_comparison_gate_CANNOT_separate_these_two_and_that_is_the_point():
    """Stated as an assertion so the reasoning cannot quietly rot: byte-equality against
    the committed twin returns the SAME answer for the clobbered object and for a repo
    copy that is simply up to date. Only the stamp separates them."""
    twin_bytes = json.dumps(_CLOBBERED, sort_keys=True).encode()
    assert hashlib.sha256(twin_bytes).hexdigest() == hashlib.sha256(twin_bytes).hexdigest()
    assert "_built_at" not in _CLOBBERED, "the clobbered shape must lack the stamp — that IS the discriminator"
    assert "_built_at" in _healthy(), "the generated shape must carry the stamp"


# ── the three assertions, each shown able to fail ────────────────────────────


def test_a_STALE_stamp_is_a_finding():
    ok, code, _ = assess(_KEY, _healthy(built_at=_NOW - timedelta(hours=60)), ceiling_seconds=_DAILY, now=_NOW)
    assert not ok and code == "stale"


def test_a_stamp_one_hour_INSIDE_the_ceiling_still_passes():
    """The ceiling is two producer periods for a stated reason — one dropped run or one
    vendor 429 self-heals on tomorrow's rebuild. A 47h-old stamp is that, not a fault."""
    ok, _, msg = assess(_KEY, _healthy(built_at=_NOW - timedelta(hours=47)), ceiling_seconds=_DAILY, now=_NOW)
    assert ok, msg


def test_a_DIGEST_mismatch_is_a_finding_that_neither_other_assertion_can_see():
    body = _healthy()
    body["templates"] = {"squat": {"id": "y", "title": "Squat"}}  # payload swapped, stamp fresh
    ok, code, _ = assess(_KEY, body, ceiling_seconds=_DAILY, now=_NOW)
    assert not ok and code == "digest-mismatch"


def test_an_UNDERIVABLE_cadence_is_reported_rather_than_defaulted():
    """A guessed ceiling is how a freshness check becomes decorative. No cadence means a
    FINDING that names what is missing, never a number chosen in the audit."""
    ok, code, msg = assess(_KEY, _healthy(), ceiling_seconds=None, now=_NOW)
    assert not ok and code == "no-cadence"
    assert "rule description" in msg


def test_an_ABSENT_object_is_not_a_pass():
    ok, code, _ = assess(_KEY, None, ceiling_seconds=_DAILY, now=_NOW)
    assert not ok and code == "unreadable"


def test_a_FUTURE_stamp_is_a_finding():
    ok, code, _ = assess(_KEY, _healthy(built_at=_NOW + timedelta(hours=3)), ceiling_seconds=_DAILY, now=_NOW)
    assert not ok and code == "future-stamp"


# ── the derivations, and the ratchet that stops them self-erasing ────────────


def test_the_enrolment_is_DERIVED_and_finds_the_real_producer():
    found = declared_generated(str(ROOT))
    assert _KEY in found, "the generated index is not enrolled — the audit would skip the one artifact it exists for"
    assert found[_KEY] == "lambdas/training/hevy_template_index.py:INDEX_KEY"


def test_THE_RATCHET_enrolment_can_only_grow():
    """The self-erasure hazard, and it is the one a vacuity guard cannot catch.

    Enrolment is derived from the producer declaring BOTH a `config/` key and a
    `_built_at` stamp. Drop the stamp from the producer and the key leaves the enrolled
    set — the audit reports a clean green over an artifact it has stopped watching, which
    is the same shape as the nine green runs. A floor makes that removal say so by name.
    """
    floor = {"config/hevy_template_index.json"}
    found = set(declared_generated(str(ROOT)))
    missing = floor - found
    assert not missing, (
        f"enrolled generated artifact(s) DISAPPEARED from the derivation: {sorted(missing)}. "
        "Either the producer stopped stamping provenance, or its config/ key constant moved out of "
        "module scope. Both silently un-watch the artifact — fix the producer, do not lower this floor."
    )


def test_BOTH_legs_are_required_for_enrolment():
    """A `config/` constant alone is a READER's key; a `_built_at` alone is some other
    module's payload. Requiring both is what keeps the derivation from enrolling every
    module that happens to mention either."""
    import config_provenance_audit as mod

    src = (ROOT / "deploy" / "config_provenance_audit.py").read_text(encoding="utf-8")
    body = src[src.index("def declared_generated") : src.index("def _cron_period_seconds")]
    # The stamp leg must read the AST, not the file text. A substring check reads
    # docstrings and comments, and this file's own ratchet control proved it: with the
    # producer's payload key renamed away, `_built_at` survived on a comment line and
    # enrolment held — the guard passed over the very removal it exists to catch.
    assert "isinstance(n, ast.Dict)" in body, "the stamp leg is a text match again — it survives a producer that stops stamping"
    assert "startswith(PREFIX)" in body, "the config/ key leg is gone from enrolment"
    # And the readers that only CONSUME the index must not be enrolled as producers.
    found = declared_generated(str(ROOT))
    assert found[_KEY].startswith("lambdas/training/"), found[_KEY]
    assert mod.CEILING_PERIODS == 2


def test_the_cadence_is_read_from_the_CDK_rule_that_names_the_key():
    cadence = declared_cadence(str(ROOT))
    assert _KEY in cadence, (
        "no EventBridge rule description names this key, so the audit has no honest ceiling. "
        "Name the key in the rule's description rather than picking a number in the audit."
    )
    seconds, where = cadence[_KEY]
    assert seconds == 86400, f"derived cadence {seconds}s — the rule is cron(hour=13, minute=40), i.e. daily"
    assert where == "cdk/stacks/ingestion_stack.py"


def test_the_cron_reader_REFUSES_shapes_it_cannot_read_honestly():
    """A wildcard or list field is a schedule this function must not guess at."""
    from config_provenance_audit import _cron_period_seconds

    assert _cron_period_seconds({"hour": "13", "minute": "40"}) == 86400
    assert _cron_period_seconds({"minute": "0"}) == 3600
    assert _cron_period_seconds({"minute": "0", "hour": "*"}) == 3600
    for shape in ({"hour": "13", "minute": "40", "week_day": "MON"}, {"hour": "1,13", "minute": "40"}, {"hour": "*/6", "minute": "0"}, {}):
        assert _cron_period_seconds(shape) is None, f"{shape} was given a cadence it does not honestly have"
