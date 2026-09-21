"""tests/test_training_notes_occurrence_key_3918.py — one note record per exercise-SESSION.

THE DEFECT
  The training-notes head key was `DATE#<d>#WORKOUT#<id>` inside the per-template
  partition — one key per (workout, TEMPLATE). A workout that logs the same template
  twice with two different notes therefore had both notes land on ONE key. Live
  specimens, measured 2026-09-19: 2026-06-23 and 2026-09-10, both Treadmill. #3816/#3899
  stopped the second write DESTROYING the first (it archives + versions instead), but the
  two notes were still not separately addressable and every pass re-versioned them
  against each other.

  The reason it stayed invisible for months is in `training_notes_health`: it queried the
  note partition with `Limit=1` and counted ONE record per noted exercise, so the
  collision read back as "2 noted sessions, 2 records found, 0 missing" off a single
  stored row.

WHAT THIS PINS
  1. the key — `DATE#<d>#WORKOUT#<id>#<occurrence>`, occurrence counted over ALL
     appearances of the template so a note added to the first block never re-keys the
     second;
  2. read-compat — a legacy row (no suffix) IS occurrence 0: an unchanged re-extraction
     over history still writes nothing, and a migrated record is never listed twice;
  3. the readers — `tool_get_exercise_notes` returns `occurrence` and yields two entries
     for the colliding workout; `training_notes_health` counts ALL occurrences and
     reports `occurrence_mismatches`, the measurement the collision was hiding inside;
  4. the mutation control — with the occurrence suffix removed, 1 and 3 BOTH go red.

The fixture is the Hevy WIRE shape as the ingest writes it to DynamoDB (pk/sk/exercises
with sets), not a hand-shaped stub: tests/fixtures/training_notes_3918/.
"""

from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import sys
from decimal import Decimal

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "lambdas"))

# mcp.config reads these at import time (same shape as tests/test_mcp_list_available_tools.py).
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("TABLE_NAME", "test-table")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from training import training_notes as tn  # noqa: E402

FIXTURE = REPO / "tests" / "fixtures" / "training_notes_3918" / "hevy_workout_duplicate_template_2026-09-10.json"
TEMPLATE = "D8F7F851"  # Treadmill
PK = tn.notes_pk(TEMPLATE)
NOTE_A = "Level 9 - 5.6 miles"
NOTE_B = "Level 4 - 1.2 miles"


def workout(date: str | None = None) -> dict:
    """The live wire row, optionally re-dated (the health window is a Pacific day range)."""
    w = json.loads(FIXTURE.read_text())[0]
    if date:
        wid = tn.workout_id_of_raw_row(w)
        w = dict(w, date=date, sk=f"DATE#{date}#WORKOUT#{wid}")
    return w


def wid_of(w: dict) -> str:
    return tn.workout_id_of_raw_row(w)


# ── a fake table that is the WIRE, not a dict ────────────────────────────────
class ConditionalCheckFailedException(Exception):
    """boto3 mints this class dynamically off the error code; the module matches on the
    NAME, so the fake has to carry the same name for the write-once path to be real."""


def _as_ddb(value):
    """DynamoDB has ONE number type: everything comes back a Decimal."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: _as_ddb(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_as_ddb(v) for v in value]
    return value


def _matches(cond, item) -> bool:
    """Evaluate a real boto3 Key condition against a stored item.

    The readers under test build their key conditions with `boto3.dynamodb.conditions`,
    so the fake evaluates THOSE objects rather than re-stating the predicate — a test
    that re-implements `begins_with` cannot catch a reader that queries the wrong range.
    """
    if cond is None:
        return True
    e = cond.get_expression()
    op, values = e["operator"], e["values"]
    if op in ("AND", "OR"):
        results = [_matches(v, item) for v in values]
        return all(results) if op == "AND" else any(results)
    attr = getattr(values[0], "name", None)
    got = item.get(attr, "")
    if op == "=":
        return got == values[1]
    if op == "begins_with":
        return str(got).startswith(values[1])
    if op == "BETWEEN":
        return values[1] <= got <= values[2]
    if op == ">=":
        return got >= values[1]
    raise NotImplementedError(f"the fake table does not implement {op!r}")


class FakeTable:
    def __init__(self, items=None):
        self.items: dict = {}
        self.deleted: list = []
        self.puts: list = []
        for it in items or []:  # seeded rows are the table's PRIOR state, not writes
            self.items[(it["pk"], it["sk"])] = _as_ddb(dict(it))

    def put_item(self, Item, ConditionExpression=None):
        key = (Item["pk"], Item["sk"])
        if ConditionExpression is not None and key in self.items:
            raise ConditionalCheckFailedException("the conditional request failed")
        self.items[key] = _as_ddb(dict(Item))
        self.puts.append(dict(Item))

    def get_item(self, Key):
        it = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": it} if it is not None else {}

    def delete_item(self, Key):
        self.items.pop((Key["pk"], Key["sk"]), None)
        self.deleted.append((Key["pk"], Key["sk"]))

    def query(self, KeyConditionExpression=None, Limit=None, **_kw):
        rows = [dict(v) for v in self.items.values() if _matches(KeyConditionExpression, v)]
        rows.sort(key=lambda r: str(r.get("sk")))
        return {"Items": rows[: int(Limit)] if Limit else rows}

    def head_sks(self, pk=PK):
        return sorted(sk for (p, sk) in self.items if p == pk and not sk.startswith(tn.ARCHIVE_PREFIX))

    def archive_sks(self, pk=PK):
        return sorted(sk for (p, sk) in self.items if p == pk and sk.startswith(tn.ARCHIVE_PREFIX))


# ══════════════════════════════════════════════════════════════════════════════
# 0. The fixture is the specimen
# ══════════════════════════════════════════════════════════════════════════════
def test_fixture_is_the_wire_shape_with_one_template_logged_twice():
    w = workout()
    assert w["pk"] == "USER#matthew#SOURCE#hevy" and w["sk"].startswith("DATE#2026-09-10#WORKOUT#")
    assert w["workout_uid"] == f"hevy:{wid_of(w)}", "the fixture lost the uid the writer keys from"
    tids = [e["template_id"] for e in w["exercises"]]
    assert tids.count(TEMPLATE) == 2, "the fixture no longer logs one template twice — it cannot reproduce the collision"
    noted = [e["notes"] for e in w["exercises"] if (e.get("notes") or "").strip()]
    assert noted == [NOTE_A, NOTE_B], "the two noted blocks are the specimen; they must differ"
    assert all("sets" in e for e in w["exercises"]), "the wire row carries sets; a stub would not"


# ══════════════════════════════════════════════════════════════════════════════
# 1. The key
# ══════════════════════════════════════════════════════════════════════════════
def assert_two_distinct_records(items):
    """The property under test, as a callable — the mutation control re-runs it."""
    assert len(items) == 2, f"expected one record per noted block, got {len(items)}"
    sks = [it["sk"] for it in items]
    assert len(set(sks)) == 2, f"the two noted blocks collide on one key: {sks}"
    assert sorted(it["note_raw"] for it in items) == sorted([NOTE_A, NOTE_B])
    assert [tn.occurrence_from_sk(sk) for sk in sorted(sks)] == [0, 1]


def test_the_two_notes_get_their_own_head_keys():
    w = workout()
    items = tn.build_workout_note_items(w["date"], w["workout_uid"], w["exercises"], llm_fn=None)
    assert_two_distinct_records(items)
    wid = wid_of(w)
    assert {it["sk"] for it in items} == {
        f"DATE#2026-09-10#WORKOUT#{wid}#0",
        f"DATE#2026-09-10#WORKOUT#{wid}#1",
    }
    assert [it["occurrence"] for it in sorted(items, key=lambda i: i["sk"])] == [0, 1]


def test_occurrence_counts_every_appearance_not_only_the_noted_ones():
    """Counting only NOTED blocks would re-key an existing record the day a note is added
    to the block before it. The unnoted first Treadmill still consumes index 0."""
    exs = [
        {"template_id": TEMPLATE, "name": "Treadmill", "notes": ""},
        {"template_id": TEMPLATE, "name": "Treadmill", "notes": NOTE_B},
    ]
    items = tn.build_workout_note_items("2026-09-10", "hevy:abc", exs, llm_fn=None)
    assert len(items) == 1
    assert items[0]["sk"].endswith("#1"), f"the noted second block was keyed as occurrence 0: {items[0]['sk']}"
    assert tn.occurrence_indices(exs) == [0, 1]


def test_occurrence_from_sk_reads_the_old_scheme_as_zero_and_never_reads_an_archive_key():
    assert tn.occurrence_from_sk("DATE#2026-09-10#WORKOUT#abc") == 0
    assert tn.is_legacy_head_sk("DATE#2026-09-10#WORKOUT#abc")
    assert tn.occurrence_from_sk("DATE#2026-09-10#WORKOUT#abc#1") == 1
    assert not tn.is_legacy_head_sk("DATE#2026-09-10#WORKOUT#abc#1")
    # a correction overlay names the record it corrects
    assert tn.occurrence_from_sk("DATE#2026-09-10#WORKOUT#abc#1#CORRECTION") == 1
    # an archive key ends in a content digest that CAN be all digits — position, not suffix
    assert tn.occurrence_from_sk(f"{tn.ARCHIVE_PREFIX}DATE#2026-09-10#WORKOUT#abc#1#0123456789012345") == 0
    assert tn.head_sk_base("DATE#2026-09-10#WORKOUT#abc#1") == "DATE#2026-09-10#WORKOUT#abc"
    assert tn.head_sk_base("DATE#2026-09-10#WORKOUT#abc") == "DATE#2026-09-10#WORKOUT#abc"


def test_the_writer_stores_both_notes_and_versions_nothing():
    """The collision is GONE at the source: two rows, no archive, nothing superseded."""
    w = workout()
    t = FakeTable()
    res = tn.write_workout_notes(t, w["date"], w["workout_uid"], w["exercises"], llm_fn=None)
    assert res["wrote"] == 2 and res["versioned"] == 0 and res["skipped"] == 0
    assert len(t.head_sks()) == 2 and t.archive_sks() == []
    # ...and a second pass is still a no-op (the #3816 property survives the re-key)
    res2 = tn.write_workout_notes(t, w["date"], w["workout_uid"], w["exercises"], llm_fn=None)
    assert res2["wrote"] == 0 and res2["skipped"] == 2
    assert len(t.head_sks()) == 2 and t.archive_sks() == []


def test_repeated_passes_no_longer_flap_the_head(monkeypatch):
    """Under the old key this workout minted an archive row per DISTINCT extraction and
    rewrote the head on every single pass. Six passes now write two rows, once."""
    w = workout()
    t = FakeTable()
    for _ in range(6):
        tn.write_workout_notes(t, w["date"], w["workout_uid"], w["exercises"], llm_fn=None)
    assert len(t.puts) == 2, f"a pass rewrote the head: {len(t.puts)} puts for 2 records"
    assert t.archive_sks() == []


# ══════════════════════════════════════════════════════════════════════════════
# 2. Read-compat with the old scheme (no rewrite)
# ══════════════════════════════════════════════════════════════════════════════
def _seed_legacy(t, w, note=NOTE_A, now_iso="2026-09-11T03:00:00Z"):
    """One row at the PRE-#3918 key, exactly as the live partition holds it."""
    ex = {"template_id": TEMPLATE, "name": "Treadmill", "notes": note}
    item = tn.build_note_item(w["date"], w["workout_uid"], ex, tn.extract_signals(note, date=w["date"]), now_iso=now_iso)
    item["sk"] = tn.legacy_head_sk(w["date"], wid_of(w))
    item.pop("occurrence", None)
    item["version"] = 1
    item["first_extracted_at"] = now_iso
    t.put_item(Item=item)
    return item


def test_an_unchanged_reextraction_over_a_legacy_row_writes_nothing():
    """The dominant path. If the writer did not look at the legacy key it would mint a
    DUPLICATE row at the occurrence key on the next windowed re-run — over history, for
    every record in the partition."""
    w = workout()
    t = FakeTable()
    _seed_legacy(t, w)
    res = tn.write_workout_notes(
        t, w["date"], w["workout_uid"], [{"template_id": TEMPLATE, "name": "Treadmill", "notes": NOTE_A}], llm_fn=None
    )
    assert res["wrote"] == 0 and res["skipped"] == 1
    assert t.head_sks() == [tn.legacy_head_sk(w["date"], wid_of(w))], "a duplicate row was minted for an unchanged note"


def test_a_changed_reextraction_rekeys_the_legacy_row_and_keeps_the_prior():
    w = workout()
    t = FakeTable()
    legacy_sk = _seed_legacy(t, w)["sk"]
    changed = [{"class": "logging_quirk", "summary": "counted steps", "confidence": 0.7}]
    res = tn.write_workout_notes(
        t,
        w["date"],
        w["workout_uid"],
        [{"template_id": TEMPLATE, "name": "Treadmill", "notes": NOTE_A}],
        llm_fn=lambda _n, _t: changed,
        now_iso="2026-09-20T00:00:00Z",
    )
    assert res["versioned"] == 1 and res["legacy_rekeyed"] == 1 and res["legacy_delete_failed"] == 0
    head_sk = tn.head_sk(w["date"], wid_of(w), 0)
    assert t.head_sks() == [head_sk], "the stale legacy row was left behind as a duplicate"
    head = t.items[(PK, head_sk)]
    assert head["migrated_from_sk"] == legacy_sk
    assert head["first_extracted_at"] == "2026-09-11T03:00:00Z", "the re-key lost when this layer first spoke"
    # the prior is still readable BY KEY (archived from its legacy key, before the delete)
    assert t.get_item(Key={"pk": PK, "sk": head["supersedes"]["sk"]}).get("Item") is not None
    assert (PK, legacy_sk) in t.deleted


def test_a_legacy_row_and_a_new_row_read_as_ONE_record():
    """Belt and braces: if the legacy delete ever fails, the readers de-duplicate."""
    w = workout()
    rows = [
        {"sk": tn.legacy_head_sk(w["date"], wid_of(w)), "note_raw": NOTE_A},
        {"sk": tn.head_sk(w["date"], wid_of(w), 0), "note_raw": NOTE_A},
        {"sk": tn.head_sk(w["date"], wid_of(w), 1), "note_raw": NOTE_B},
    ]
    found = tn.dedupe_head_rows(rows)
    assert sorted(found) == [0, 1]
    assert found[0]["sk"].endswith("#0"), "the legacy row won over the migrated one"


def test_dedupe_ignores_corrections_and_archived_priors():
    base = "DATE#2026-09-10#WORKOUT#abc"
    rows = [
        {"sk": f"{base}#0"},
        {"sk": f"{base}#0#CORRECTION"},
        {"sk": f"{tn.ARCHIVE_PREFIX}{base}#0#deadbeefdeadbeef", "record_kind": tn.RECORD_KIND_PRIOR},
    ]
    assert list(tn.dedupe_head_rows(rows)) == [0]


# ══════════════════════════════════════════════════════════════════════════════
# 3. The readers
# ══════════════════════════════════════════════════════════════════════════════
def _read_tool(monkeypatch, table, health=None):
    import mcp.tools_training_notes as ttn

    monkeypatch.setattr(ttn, "table", table)
    monkeypatch.setattr(
        "training.training_notes.training_notes_health",
        lambda *_a, **_k: health or {"checked": True, "extractor_dark": False, "noted_exercise_sessions": 2, "records_found": 2},
    )
    return ttn.tool_get_exercise_notes({"template_id": TEMPLATE, "lookback_days": 365})


def test_get_exercise_notes_returns_both_blocks_each_with_its_occurrence(monkeypatch):
    w = workout()
    t = FakeTable()
    tn.write_workout_notes(t, w["date"], w["workout_uid"], w["exercises"], llm_fn=None)
    out = _read_tool(monkeypatch, t)
    assert out["sessions_with_notes"] == 2, "the reader still collapses the two blocks into one"
    assert [e["occurrence"] for e in out["timeline"]] == [0, 1]
    assert [e["note_raw"] for e in out["timeline"]] == [NOTE_A, NOTE_B]
    assert len({e["workout_uid"] for e in out["timeline"]}) == 1, "both entries are the same workout"


def test_get_exercise_notes_lists_a_pending_migration_once(monkeypatch):
    """A legacy row plus its migrated twin is ONE session, not two."""
    w = workout()
    t = FakeTable()
    _seed_legacy(t, w)
    tn.write_workout_notes(t, w["date"], w["workout_uid"], [{"template_id": TEMPLATE, "name": "Treadmill", "notes": NOTE_A}], llm_fn=None)
    # force the pending state: both rows present at once
    item = dict(t.items[(PK, tn.legacy_head_sk(w["date"], wid_of(w)))])
    new = dict(item, sk=tn.head_sk(w["date"], wid_of(w), 0), occurrence=0)
    t.put_item(Item=new)
    out = _read_tool(monkeypatch, t)
    assert out["sessions_with_notes"] == 1, f"the pending migration was listed twice: {out['timeline']}"
    assert out["timeline"][0]["occurrence"] == 0


def _health(table):
    return tn.training_notes_health(table, lookback_days=14)


def assert_health_sees_both_occurrences(table):
    """The property under test, as a callable — the mutation control re-runs it."""
    h = _health(table)
    assert h["checked"] is True
    assert h["noted_exercise_sessions"] == 2
    assert h["records_found"] == 2, f"the health check found {h['records_found']} record(s) for 2 noted blocks"
    assert h["missing_records"] == 0
    assert h["occurrence_mismatches"] == 0, h["occurrence_mismatch_detail"]


def test_health_counts_both_occurrences():
    today = tn.pacific_today()
    w = workout(today)
    t = FakeTable([w])
    tn.write_workout_notes(t, w["date"], w["workout_uid"], w["exercises"], llm_fn=None)
    assert_health_sees_both_occurrences(t)


def test_health_reports_the_collision_the_old_measurement_was_hiding():
    """THE measurement. With only the pre-#3918 single row stored, the old check reported
    2 noted / 2 found / 0 missing — it asked `Limit=1` twice and counted the same row
    each time. The same table now reports one record, one miss, one mismatch."""
    today = tn.pacific_today()
    w = workout(today)
    t = FakeTable([w])
    _seed_legacy(t, w)
    h = _health(t)
    assert h["noted_exercise_sessions"] == 2
    assert h["records_found"] == 1
    assert h["missing_records"] == 1
    assert h["occurrence_mismatches"] == 1
    detail = h["occurrence_mismatch_detail"][0]
    assert detail["noted"] == 2 and detail["records"] == 1 and detail["template_id"] == TEMPLATE
    assert "fewer note records than noted occurrences" in h["note"]


def test_health_does_not_cry_mismatch_over_an_ordinary_legacy_row():
    """NEGATIVE CONTROL. A guard that fires on every legacy row is not a guard: one noted
    block with one stored row is the old scheme matching itself, whatever index the block
    sat at in the exercise list."""
    today = tn.pacific_today()
    w = workout(today)
    w = dict(w, exercises=[dict(w["exercises"][1]), dict(w["exercises"][2])])  # unnoted row, then the noted block
    t = FakeTable([w])
    ex = w["exercises"][1]
    item = tn.build_note_item(w["date"], w["workout_uid"], ex, tn.extract_signals(ex["notes"]), occurrence=1)
    item["sk"] = tn.legacy_head_sk(w["date"], wid_of(w))
    item.pop("occurrence", None)
    t.put_item(Item=item)
    h = _health(t)
    assert h["noted_exercise_sessions"] == 1 and h["records_found"] == 1
    assert h["missing_records"] == 0 and h["occurrence_mismatches"] == 0


# ══════════════════════════════════════════════════════════════════════════════
# 4. The mutation control — remove the suffix, BOTH go red
# ══════════════════════════════════════════════════════════════════════════════
def test_mutation_control_removing_the_occurrence_suffix_reds_both_properties(monkeypatch):
    """If `head_sk` drops the occurrence, the key is the pre-#3918 key again. Both the
    conservation property (1) and the health measurement (3) must FAIL — a test that
    still passes against the old key shape is not testing the fix."""
    monkeypatch.setattr(tn, "head_sk", lambda date, workout_id, occurrence=0: f"DATE#{date}#WORKOUT#{workout_id}")

    w = workout()
    items = tn.build_workout_note_items(w["date"], w["workout_uid"], w["exercises"], llm_fn=None)
    with pytest.raises(AssertionError):
        assert_two_distinct_records(items)

    today = tn.pacific_today()
    wt = workout(today)
    t = FakeTable([wt])
    tn.write_workout_notes(t, wt["date"], wt["workout_uid"], wt["exercises"], llm_fn=None)
    with pytest.raises(AssertionError):
        assert_health_sees_both_occurrences(t)


# ══════════════════════════════════════════════════════════════════════════════
# 5. The backfill script's two read-only modes
# ══════════════════════════════════════════════════════════════════════════════
def _backfill_module():
    spec = importlib.util.spec_from_file_location("_bf3918", os.path.join(str(REPO), "deploy", "backfill_training_notes.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_migrate_plan_splits_a_collision_into_two_distinct_notes():
    """Box 3, dry-run: the displaced note lives in the #3816 ARCHIVE, and the plan
    promotes it to its own occurrence key. Nothing is written, no model is called."""
    bf = _backfill_module()
    w = workout()
    t = FakeTable([w])
    # Reproduce the live pre-fix state: one legacy head + the archived prior it displaced.
    legacy = _seed_legacy(t, w, note=NOTE_B, now_iso="2026-09-11T03:00:00Z")
    prior = dict(legacy)
    prior["note_raw"] = NOTE_A
    prior["note_hash"] = tn.note_hash(NOTE_A)
    prior["sk"] = tn.prior_extraction_sk(legacy["sk"], prior)
    prior["record_kind"] = tn.RECORD_KIND_PRIOR
    prior["superseded_head_sk"] = legacy["sk"]
    t.put_item(Item=prior)

    before_puts, before_deletes = len(t.puts), len(t.deleted)
    plans = bf.migrate_collisions(t, dates=(w["date"],), apply=False)
    assert len(plans) == 1
    p = plans[0]
    assert p["template_id"] == TEMPLATE and p["noted_occurrences"] == [0, 1]
    assert p["distinct_notes"] == 2, p
    assert sorted(p["end_state"]) == [tn.head_sk(w["date"], wid_of(w), 0), tn.head_sk(w["date"], wid_of(w), 1)]
    assert p["deletes"] == [legacy["sk"]]
    assert (len(t.puts), len(t.deleted)) == (before_puts, before_deletes), "a dry run wrote to the table"


def test_migrate_apply_leaves_two_reachable_notes():
    bf = _backfill_module()
    w = workout()
    t = FakeTable([w])
    legacy = _seed_legacy(t, w, note=NOTE_B)
    prior = dict(legacy, note_raw=NOTE_A, note_hash=tn.note_hash(NOTE_A), record_kind=tn.RECORD_KIND_PRIOR)
    prior["sk"] = tn.prior_extraction_sk(legacy["sk"], prior)
    t.put_item(Item=prior)

    bf.migrate_collisions(t, dates=(w["date"],), apply=True)
    heads = t.head_sks()
    assert heads == [tn.head_sk(w["date"], wid_of(w), 0), tn.head_sk(w["date"], wid_of(w), 1)]
    notes = {str(t.items[(PK, sk)]["note_raw"]) for sk in heads}
    assert notes == {NOTE_A, NOTE_B}, f"the two notes are not both reachable: {notes}"
    assert (PK, legacy["sk"]) in t.deleted
    assert t.archive_sks(), "the archived prior was consumed rather than left in place"


def test_migrate_refuses_to_claim_success_when_a_note_has_no_stored_extraction():
    """NEGATIVE CONTROL: with the archived prior absent there is nothing to re-key the
    second note from, and re-extracting it is model spend — so the run FAILS loudly
    instead of reporting a resolved collision."""
    bf = _backfill_module()
    w = workout()
    t = FakeTable([w])
    _seed_legacy(t, w, note=NOTE_B)
    with pytest.raises(AssertionError, match="does NOT yield"):
        bf.migrate_collisions(t, dates=(w["date"],), apply=False)


def test_value_census_counts_and_characterises_the_unextracted(capsys):
    bf = _backfill_module()
    w = workout()
    t = FakeTable([w])
    c = bf.value_census(t, since="2000-01-01")
    assert c["noted_exercise_sessions_total"] == 2
    assert c["unextracted"] == 2, "a workout with no note records at all reported some as extracted"
    assert c["by_year"] == {"2026": 2}
    assert c["top_exercises"][0] == ("Treadmill", 2)
    assert c["note_length"]["max"] == len(NOTE_A)
    assert len(c["samples"]) == 2
    assert t.puts == [] and t.deleted == [], "the census wrote to the table"
    bf.print_value_census(c)
    out = capsys.readouterr().out
    assert "READ-ONLY" in out and "Treadmill" in out and "no model was called" in out


def test_value_census_does_not_count_an_already_extracted_session():
    """NEGATIVE CONTROL — the census must shrink when the records exist."""
    bf = _backfill_module()
    w = workout()
    t = FakeTable([w])
    tn.write_workout_notes(t, w["date"], w["workout_uid"], w["exercises"], llm_fn=None)
    c = bf.value_census(t, since="2000-01-01")
    assert c["unextracted"] == 0 and c["by_year"] == {} and c["samples"] == []


def test_value_census_keyword_classes_are_word_bounded():
    bf = _backfill_module()
    hits = bf.keyword_hits(["barbell rows felt heavy", "left knee twinge on the last rep", "form cue: slow tempo"])
    assert hits["equipment"]["keywords"].get("bar") is None, "'bar' scored inside 'barbell'"
    assert hits["progression"]["sessions"] == 1 and hits["progression"]["keywords"]["heavy"] == 1
    assert hits["pain"]["sessions"] == 1 and hits["pain"]["keywords"]["knee"] == 1
    assert hits["form"]["sessions"] == 1 and hits["form"]["keywords"]["tempo"] == 1


def test_the_backfill_docstring_carries_the_measured_population():
    """The docstring said "trivial at current scale (~1 session)" while 532 noted
    exercise-sessions had no record — the stale number is what made the backfill look
    like a no-op worth skipping."""
    bf = _backfill_module()
    assert bf.MEASURED_UNEXTRACTED == 532
    assert "532" in (bf.__doc__ or ""), "the module docstring no longer names the measured population"
    assert "Trivial at current scale" not in (bf.__doc__ or "")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))


# ══════════════════════════════════════════════════════════════════════════════
# 6. --only-note: ONE exercise-session, bounded spend ("run the one", 2026-09-20 ruling)
# ══════════════════════════════════════════════════════════════════════════════
def test_only_note_narrows_to_one_block_and_keeps_its_occurrence():
    """The fixture logs the Treadmill twice. Naming occurrence 1 must leave exactly one
    NOTED block, at occurrence 1 — the other blocks keep their positions with blank
    notes, so the head key the writer mints is unchanged."""
    bf = _backfill_module()
    w = workout()
    narrowed = bf.only_note_workouts([w], (w["date"], TEMPLATE, 1))
    assert len(narrowed) == 1
    exs = narrowed[0]["exercises"]
    assert len(exs) == len(w["exercises"]), "a block was dropped — the occurrence index would shift"
    noted = [(tn.normalize_exercise_key(e)[0], o) for e, o in zip(exs, tn.occurrence_indices(exs)) if (e.get("notes") or "").strip()]
    assert noted == [(TEMPLATE, 1)], noted
    items = tn.build_workout_note_items(w["date"], w["workout_uid"], exs)
    assert [it["sk"] for it in items] == [tn.head_sk(w["date"], wid_of(w), 1)]
    assert items[0]["note_raw"] == NOTE_B
    # The source row is untouched (the narrowing is a copy).
    assert (w["exercises"][0].get("notes") or "").strip(), "the caller's workout row was mutated"


def test_only_note_finds_nothing_for_a_target_that_is_not_noted():
    """NEGATIVE CONTROL: a wrong date, template or occurrence yields [] — the driver
    refuses to run rather than backfilling an empty selection or the wrong session."""
    bf = _backfill_module()
    w = workout()
    assert bf.only_note_workouts([w], ("1999-01-01", TEMPLATE, 0)) == []
    assert bf.only_note_workouts([w], (w["date"], "00000000", 0)) == []
    assert bf.only_note_workouts([w], (w["date"], TEMPLATE, 7)) == []


def test_only_note_spec_parses_and_refuses_junk():
    bf = _backfill_module()
    assert bf.parse_only_note("2026-06-23/243710de/0") == ("2026-06-23", "243710DE", 0)
    for junk in ("2026-06-23", "243710DE/0", "2026-06-23/243710DE", "yesterday/243710DE/0", ""):
        with pytest.raises(ValueError):
            bf.parse_only_note(junk)


def test_bounded_cap_is_the_live_count_plus_exactly_n():
    """The September cap is reached; the run's cap is live+N, never a blanket lift."""
    bf = _backfill_module()
    from training import training_notes_llm as tl

    t = FakeTable([{"pk": tl._USAGE_PK, "sk": f"MONTH#{tl._month()}", "calls": 300}])
    assert bf.bounded_cap(t, 1) == 301
    assert bf.bounded_cap(t, 0) == 300
    assert bf.bounded_cap(FakeTable(), 1) == 1


def test_migrate_plan_is_keyed_by_template_so_another_blocks_occurrence_0_cannot_shadow_the_collision():
    """Found live (2026-09-10, session AP): the Rowing and Elliptical blocks of the same
    workout are ALSO occurrence 0 of their own templates. A plan keyed by occurrence alone
    let the last noted block overwrite the Treadmill's occurrence-0 note, so the real
    archived prior was reported "no stored extraction carries this note text" and the
    migration refused a collision it could resolve."""
    bf = _backfill_module()
    w = workout()
    # Give the other template's block (index 1, occurrence 0 of ITS template) a note of its own.
    w["exercises"][1] = dict(w["exercises"][1], notes="Shadow note on the cable row")
    t = FakeTable([w])
    legacy = _seed_legacy(t, w, note=NOTE_B, now_iso="2026-09-11T03:00:00Z")
    prior = dict(legacy, note_raw=NOTE_A, note_hash=tn.note_hash(NOTE_A), record_kind=tn.RECORD_KIND_PRIOR)
    prior["sk"] = tn.prior_extraction_sk(legacy["sk"], prior)
    prior["superseded_head_sk"] = legacy["sk"]
    t.put_item(Item=prior)

    plans = bf.migrate_collisions(t, dates=(w["date"],), apply=False)
    (p,) = [p for p in plans if p["template_id"] == TEMPLATE]
    assert p["unavailable"] == [], f"the other block's note shadowed occurrence 0: {p['unavailable']}"
    assert p["distinct_notes"] == 2 and sorted(p["end_state"]) == [tn.head_sk(w["date"], wid_of(w), 0), tn.head_sk(w["date"], wid_of(w), 1)]
    by_sk = {str(it["sk"]): str(it["note_raw"]) for it in p["puts"]}
    assert by_sk.get(tn.head_sk(w["date"], wid_of(w), 0)) == NOTE_A, f"occurrence 0 must be promoted from ITS archived prior: {by_sk}"
