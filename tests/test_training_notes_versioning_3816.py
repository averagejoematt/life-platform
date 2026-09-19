"""tests/test_training_notes_versioning_3816.py — a re-extraction cannot silently rewrite
the note layer's past (#3816).

THE INCIDENT
  `write_workout_notes` did a plain `put_item` at `DATE#<date>#WORKOUT#<id>`, and BOTH
  re-runners (the on-ingest hook + windowed re-run in `hevy_backfill_lambda`, and
  `deploy/backfill_training_notes.py --apply`) called it over historical dates. The
  2026-09-07 cycling note was reported in #3699 as `degraded: true, extracted_by:
  deterministic, progression`; by 2026-09-14 it read `degraded: false, extracted_by:
  hybrid, progression + logging_quirk`. The record is CORRECT now, and nothing on it
  says it spent a week telling the coach something else. `extracted_at` moved — which is
  indistinguishable from a first extraction that simply happened late.

  This layer is a TRAJECTORY the coach reads as an arc, so a re-derivation changes the
  PAST SHAPE of that arc. Attest, never backfill.

WHAT THIS PINS
  1. idempotence — an unchanged re-extraction writes NOTHING AT ALL (the windowed re-run
     fires on every hevy-backfill invoke; a "harmless" re-put churns `extracted_at`,
     which is the only tell a re-derivation ever left);
  2. the positive control — a re-extraction whose signals DIFFER archives the prior
     verbatim, keeps it readable BY KEY, and stamps `supersedes` on the new head;
  3. the reader containment — the archived rows fall outside the key ranges BOTH live
     readers of this partition use, by key shape and not by a filter each has to
     remember;
  4. the negative controls — a first write is not a version; a read failure never
     licenses a clean-lineage claim.
"""

from __future__ import annotations

import os
import sys
from decimal import Decimal

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from training import training_notes as tn  # noqa: E402

# The live specimen's own note text (2026-09-07 cycling, workout e5c2f877…).
CYCLING = "Low effort level 10 for whole thing"
EXS = [{"template_id": "D8F7F851", "name": "Cycling", "notes": CYCLING}]
DATE = "2026-09-07"
WUID = "hevy:e5c2f877"
HEAD_SK = f"DATE#{DATE}#WORKOUT#e5c2f877"
PK = tn.notes_pk("D8F7F851")


class ConditionalCheckFailedException(Exception):
    """boto3 mints this class dynamically off the error code; the module matches on the
    NAME, so the fake has to carry the same name for the write-once path to be real."""


def _as_ddb(value):
    """What boto3's resource layer ACTUALLY hands back: DynamoDB has one number type, so
    every int and float comes back a `Decimal`. A fake table that returns the ints it was
    given is not the wire, and the whole point of this test file is a comparison that
    survives the round-trip — the first version of it did not (`9` vs `Decimal('9')`)."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: _as_ddb(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_as_ddb(v) for v in value]
    return value


class FakeTable:
    """Enough DynamoDB to exercise the read-compare-archive-write path."""

    def __init__(self):
        self.items: dict[tuple[str, str], dict] = {}
        self.puts: list[dict] = []
        self.fail_get = False
        self.fail_put_sk_prefix: str | None = None

    def put_item(self, Item, ConditionExpression=None):
        if self.fail_put_sk_prefix and str(Item["sk"]).startswith(self.fail_put_sk_prefix):
            raise RuntimeError("simulated put failure")
        key = (Item["pk"], Item["sk"])
        if ConditionExpression is not None and key in self.items:
            # The one condition this module uses is attribute_not_exists(sk).
            raise ConditionalCheckFailedException("the conditional request failed")
        self.items[key] = _as_ddb(Item)
        self.puts.append(Item)

    def get_item(self, Key):
        if self.fail_get:
            raise RuntimeError("simulated get failure")
        it = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": it} if it is not None else {}


def _llm(signals):
    """An llm_fn returning a fixed signal list — the model tail, deterministically."""

    def _fn(_note, _taxonomy):
        return list(signals)

    return _fn


LOGGING_QUIRK = [{"class": "logging_quirk", "summary": "counted steps, not yards", "confidence": 0.7}]


# ── 1. Idempotence: an unchanged re-extraction writes nothing at all ──────────
def test_unchanged_reextraction_writes_nothing():
    t = FakeTable()
    r1 = tn.write_workout_notes(t, DATE, WUID, EXS, llm_fn=None)
    assert r1["wrote"] == 1 and r1["versioned"] == 0 and r1["skipped"] == 0
    first_put_count = len(t.puts)

    r2 = tn.write_workout_notes(t, DATE, WUID, EXS, llm_fn=None, now_iso="2099-01-01T00:00:00Z")
    assert r2["wrote"] == 0, "an unchanged re-extraction wrote a row"
    assert r2["skipped"] == 1
    assert len(t.puts) == first_put_count, "an unchanged re-extraction touched the table"
    assert len(t.items) == 1
    # And the `extracted_at` churn — the only tell a re-derivation ever left — is gone.
    assert t.items[(PK, HEAD_SK)]["extracted_at"] != "2099-01-01T00:00:00Z"


def test_two_identical_runs_produce_one_row():
    t = FakeTable()
    tn.write_workout_notes(t, DATE, WUID, EXS, llm_fn=None)
    tn.write_workout_notes(t, DATE, WUID, EXS, llm_fn=None)
    assert len(t.items) == 1
    assert list(t.items)[0] == (PK, HEAD_SK)


def test_decimal_roundtrip_is_not_a_change():
    """A confidence read back from DynamoDB is a Decimal. If the compare didn't
    normalise it, EVERY re-run would look like a changed extraction and version."""
    t = FakeTable()
    tn.write_workout_notes(t, DATE, WUID, EXS, llm_fn=_llm(LOGGING_QUIRK))
    stored = t.items[(PK, HEAD_SK)]
    assert any(isinstance(s.get("confidence"), Decimal) for s in stored["signals"]), "fixture no longer exercises Decimal"
    r2 = tn.write_workout_notes(t, DATE, WUID, EXS, llm_fn=_llm(LOGGING_QUIRK))
    assert r2["skipped"] == 1 and r2["wrote"] == 0


def test_an_int_read_back_as_decimal_is_not_a_change():
    """THE false positive this comparator was born with. DynamoDB has one number type:
    a deterministic `{"level": 9}` comes back as `Decimal('9')`, and the fresh extraction
    that produced it holds the int `9`. Compared through `json.dumps(default=float)` that
    is `9.0` vs `9` — so EVERY stored record read as changed, and the versioning writer
    would have minted a new version on every hevy-backfill invoke, forever. Measured live
    on 2026-09-19: 13 of 42 stored records reported as changed for exactly this reason.
    """
    fresh = {"note_hash": "h", "signals": [{"class": "progression", "confidence": 0.9, "value": {"level": 9}}]}
    stored = {"note_hash": "h", "signals": [{"class": "progression", "confidence": Decimal("0.9"), "value": {"level": Decimal("9")}}]}
    assert not tn.extraction_changed(stored, fresh)
    # ...and the guard still sees a REAL numeric change (it is not just equal-to-everything).
    assert tn.extraction_changed(
        stored, {"note_hash": "h", "signals": [{"class": "progression", "confidence": 0.9, "value": {"level": 10}}]}
    )


def test_a_live_stored_record_round_trips_unchanged():
    """End to end through the writer: seed, read the row back the way DynamoDB would
    (Decimal-ised by `floats_to_decimal`), and re-run. Zero writes."""
    t = FakeTable()
    tn.write_workout_notes(t, DATE, WUID, EXS, llm_fn=None)
    stored = t.items[(PK, HEAD_SK)]
    assert isinstance(stored["signals"][0]["value"]["level"], Decimal), "fixture no longer exercises the Decimal path"
    assert not tn.extraction_changed(stored, tn.build_note_item(DATE, WUID, EXS[0], tn.extract_signals(CYCLING)))


# ── 1b. The read-only change predicate ────────────────────────────────────────
def test_certain_change_reason_is_silent_on_an_unchanged_record():
    t = FakeTable()
    tn.write_workout_notes(t, DATE, WUID, EXS, llm_fn=_llm(LOGGING_QUIRK))
    stored = t.items[(PK, HEAD_SK)]
    assert tn.certain_change_reason(stored, CYCLING) is None


def test_certain_change_reason_names_the_three_forced_cases():
    t = FakeTable()
    tn.write_workout_notes(t, DATE, WUID, EXS, llm_fn=None)
    stored = dict(t.items[(PK, HEAD_SK)])
    assert "note text changed" in tn.certain_change_reason(stored, CYCLING + " and more")
    assert "algo_version" in tn.certain_change_reason(dict(stored, algo_version="note-extractor@0.9.0"), CYCLING)
    # The model tail can ADD a class; it can never remove one the regex produced, so a
    # stored record missing a deterministic class is a forced change.
    stripped = dict(stored, signals=[s for s in stored["signals"] if s["class"] != "progression"])
    assert "progression" in tn.certain_change_reason(stripped, CYCLING)


# ── 2. Positive control: a CHANGED re-extraction versions ─────────────────────
def _seed_then_change(t):
    """Seed the deterministic-only extraction (the specimen's week-one state), then
    re-run with the model tail available (its post-#3768 state)."""
    tn.write_workout_notes(t, DATE, WUID, EXS, llm_fn=None, now_iso="2026-09-07T18:00:00Z")
    before = dict(t.items[(PK, HEAD_SK)])
    res = tn.write_workout_notes(t, DATE, WUID, EXS, llm_fn=_llm(LOGGING_QUIRK), now_iso="2026-09-14T14:21:25Z")
    return before, res


def test_changed_reextraction_versions_and_the_prior_is_still_readable_by_key():
    t = FakeTable()
    before, res = _seed_then_change(t)
    assert res["versioned"] == 1 and res["wrote"] == 1 and res["skipped"] == 0

    head = t.items[(PK, HEAD_SK)]
    assert head["extracted_by"] == "hybrid"
    assert any(s["class"] == "logging_quirk" for s in head["signals"])

    # The prior is readable BY KEY — not "still in the table somewhere".
    prior_sk = head["supersedes"]["sk"]
    got = t.get_item(Key={"pk": PK, "sk": prior_sk})["Item"]
    assert got["extracted_by"] == before["extracted_by"] == "deterministic"
    assert got["signals"] == before["signals"], "the archived prior is not the verbatim prior"
    assert got["extracted_at"] == "2026-09-07T18:00:00Z"
    assert got["record_kind"] == tn.RECORD_KIND_PRIOR
    assert got["superseded_head_sk"] == HEAD_SK


def test_head_carries_supersedes_naming_the_prior():
    t = FakeTable()
    before, _ = _seed_then_change(t)
    head = t.items[(PK, HEAD_SK)]
    sup = head.get("supersedes")
    assert sup, "the new head does not say it replaced anything"
    assert sup["extracted_at"] == "2026-09-07T18:00:00Z"
    assert sup["algo_version"] == before["algo_version"]
    assert sup["note_hash"] == before["note_hash"]
    # The stamp is a POINTER: it names the archive key, so a reader can fetch the prior.
    assert t.get_item(Key={"pk": PK, "sk": sup["sk"]}).get("Item") is not None
    # And the head remembers when this layer FIRST spoke about this workout+exercise —
    # the fact `extracted_at` destroys when it moves.
    assert head["version"] == 2
    assert head["first_extracted_at"] == "2026-09-07T18:00:00Z"
    assert head["extracted_at"] == "2026-09-14T14:21:25Z"


def test_a_third_extraction_keeps_both_priors():
    t = FakeTable()
    _seed_then_change(t)
    other = [{"class": "limiter", "summary": "legs", "confidence": 0.5}]
    tn.write_workout_notes(t, DATE, WUID, EXS, llm_fn=_llm(other), now_iso="2026-09-20T00:00:00Z")
    archived = sorted(sk for (_pk, sk) in t.items if sk.startswith(tn.ARCHIVE_PREFIX))
    assert len(archived) == 2, f"a version was lost: {archived}"
    assert t.items[(PK, HEAD_SK)]["version"] == 3


# ── 2b. The archive is bounded by DISTINCT extractions, not by passes ─────────
# Measured live on 2026-09-19 with `--report-overwrites`: of 42 stored note records, the
# only two a re-run would version today are `2026-06-23 Treadmill` and `2026-09-10
# Treadmill` — and both are there because that workout logs the SAME exercise template
# TWICE with two different notes. They collide on one head key by construction, so every
# pass writes A over B and then B over A. A timestamped archive key would mint two NEW
# rows per pass, forever, in a measured partition. (The collision itself is a separate,
# pre-existing conservation defect — named as residual in the PR, not fixed here.)
COLLIDING = [
    {"template_id": "D8F7F851", "name": "Treadmill", "notes": "Level 9 - 5.6 miles"},
    {"template_id": "D8F7F851", "name": "Treadmill", "notes": "Level 4 - 1.2 miles"},
]


def test_a_flapping_head_does_not_mint_an_archive_row_per_pass():
    t = FakeTable()
    for i in range(6):
        tn.write_workout_notes(t, DATE, WUID, COLLIDING, llm_fn=None, now_iso=f"2026-09-{7 + i:02d}T00:00:00Z")
    archived = sorted(sk for (_pk, sk) in t.items if sk.startswith(tn.ARCHIVE_PREFIX))
    assert len(archived) == 2, f"6 passes minted {len(archived)} archive rows — the archive is unbounded: {archived}"


def test_an_already_archived_extraction_keeps_its_first_timestamps():
    """Write-once: re-archiving the same extraction must not move `archived_at` or
    overwrite the copy with a later pass's view of it."""
    t = FakeTable()
    tn.write_workout_notes(t, DATE, WUID, COLLIDING, llm_fn=None, now_iso="2026-09-07T00:00:00Z")
    first = {sk: dict(it) for (_pk, sk), it in t.items.items() if sk.startswith(tn.ARCHIVE_PREFIX)}
    assert first
    tn.write_workout_notes(t, DATE, WUID, COLLIDING, llm_fn=None, now_iso="2026-09-30T00:00:00Z")
    for sk, was in first.items():
        now = t.items[(PK, sk)]
        assert now["archived_at"] == was["archived_at"]
        assert now["extracted_at"] == was["extracted_at"]


# ── 3. Reader containment: archived rows are outside every live reader's range ─
def test_archive_key_sorts_outside_the_two_reader_ranges():
    """`tool_get_exercise_notes` queries sk >= DATE#<start>; `training_notes_health`
    queries begins_with(DATE#<d>#WORKOUT#). The archive prefix must fall outside BOTH
    by key shape — not by a filter each reader has to remember to apply."""
    prior_sk = tn.prior_extraction_sk(HEAD_SK, {"note_hash": "h", "signals": []})
    assert prior_sk < "DATE#1970-01-01", "an archived row leaks into sk >= DATE#<start>"
    assert not prior_sk.startswith(f"DATE#{DATE}#WORKOUT#"), "an archived row leaks into the health check's begins_with"
    # ...and it does NOT collide with the correction overlay the reader special-cases.
    assert not prior_sk.endswith("#CORRECTION")


def test_the_mcp_reader_range_sees_only_the_head():
    """Simulate the live reader's key condition over the partition after a version."""
    t = FakeTable()
    _seed_then_change(t)
    start = "2026-01-01"
    visible = [sk for (pk, sk) in t.items if pk == PK and sk >= f"DATE#{start}"]
    assert visible == [HEAD_SK], f"the reader would see a duplicate row: {visible}"


def test_the_health_check_range_sees_only_the_head():
    t = FakeTable()
    _seed_then_change(t)
    visible = [sk for (pk, sk) in t.items if pk == PK and sk.startswith(f"DATE#{DATE}#WORKOUT#")]
    assert visible == [HEAD_SK], f"the health check would double-count: {visible}"


# ── 4. Negative controls ──────────────────────────────────────────────────────
def test_a_first_write_is_not_a_version():
    """A guard that fires on everything is not a guard: the first extraction of a note
    has no prior, claims no `supersedes`, and archives nothing."""
    t = FakeTable()
    res = tn.write_workout_notes(t, DATE, WUID, EXS, llm_fn=None)
    head = t.items[(PK, HEAD_SK)]
    assert res["versioned"] == 0
    assert "supersedes" not in head
    assert head["version"] == 1 and head["first_extracted_at"] == head["extracted_at"]
    assert not [sk for (_pk, sk) in t.items if sk.startswith(tn.ARCHIVE_PREFIX)]


def test_an_unreadable_prior_never_claims_a_clean_lineage():
    """Fail-soft (this runs inside ingestion) but never fail SILENT. If the head could
    not be read, the record written says so instead of implying a first extraction."""
    t = FakeTable()
    tn.write_workout_notes(t, DATE, WUID, EXS, llm_fn=None)
    t.fail_get = True
    res = tn.write_workout_notes(t, DATE, WUID, EXS, llm_fn=_llm(LOGGING_QUIRK))
    assert res["prior_unverified"] == 1 and res["wrote"] == 1
    head = t.items[(PK, HEAD_SK)]
    assert head["prior_unverified"] is True
    assert "supersedes" not in head, "a head that could not read its prior must not claim one"
    assert "version" not in head, "an unverified write must not mint a version number"


def test_a_failed_archive_is_stamped_on_the_record():
    t = FakeTable()
    tn.write_workout_notes(t, DATE, WUID, EXS, llm_fn=None, now_iso="2026-09-07T18:00:00Z")
    t.fail_put_sk_prefix = tn.ARCHIVE_PREFIX
    res = tn.write_workout_notes(t, DATE, WUID, EXS, llm_fn=_llm(LOGGING_QUIRK))
    assert res["archive_failed"] == 1
    assert t.items[(PK, HEAD_SK)]["prior_archive_failed"] is True


def test_extraction_changed_ignores_extracted_at_only():
    a = {"note_hash": "h", "signals": [], "extracted_at": "2026-01-01T00:00:00Z", "algo_version": tn.ALGO_VERSION}
    b = dict(a, extracted_at="2026-09-01T00:00:00Z")
    assert not tn.extraction_changed(a, b)
    assert tn.extraction_changed(a, dict(a, degraded=True))
    assert tn.extraction_changed(a, dict(a, note_hash="other"))


def test_the_raw_partition_is_still_never_written():
    """Invariant 1 survives the new write path: archive rows are in the DERIVED
    partition too, never the raw Hevy one."""
    t = FakeTable()
    _seed_then_change(t)
    for pk, _sk in t.items:
        assert f"#SOURCE#{tn.NOTES_SOURCE}#EXERCISE#" in pk
        assert pk != tn.raw_pk()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
