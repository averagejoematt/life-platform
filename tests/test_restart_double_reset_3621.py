"""tests/test_restart_double_reset_3621.py — #3621 box 2: the double-reset harness.

WHAT WAS UNPROVEN
─────────────────
`restart_intelligence_wipe` claims idempotency in its own docstring — "items already
tombstoned by ANY reset are skipped, so a prior archive's `cycle` stamp / generation
identity survives every later reset (#1202, ADR-077)" — and every generation-identity
attribute is written with `if_not_exists` PRECISELY so a later reset cannot overwrite it.
Nothing executed that claim. `is_already_tombstoned` was exercised on single dicts; the
thing actually at risk is the SECOND FULL PASS over a real archive, and the forensic RCA
said so plainly: "Nothing filed proves a double reset."

It matters because the failure is silent and permanent. #1202 is the specimen: a re-run
that re-tombstoned already-archived rows converged the whole archive onto the newest
cycle (a February pilot insight claiming `cycle=5`), destroying ADR-077's "navigable by
reset generation" guarantee with no error anywhere.

THE HARNESS
───────────
`FakeTable` implements the two DynamoDB operations the wipe uses — a paginated `query`
and an `update_item` that really evaluates `SET`, `if_not_exists(...)` and
ExpressionAttributeNames/Values — over 143 REAL rows captured read-only from the live
table (`tests/fixtures/restart_wipe_rows_2026-09-20.json`, projected to exactly the
attributes the wipe reads or writes; see that file's `_meta`). The wipe's own
`run_wipe()` drives it, twice, through `build_work()` — the same partition list the live
reset walks, not a re-derived one.

The assertion is the strong form: after run 2, EVERY provenance field of EVERY row is
byte-identical to what it was after run 1 — not merely "the counts look idempotent".

THE PAGINATION IS NOT DECORATION. `FakeTable` pages at 7 items with a real
`LastEvaluatedKey`, because the wipe's `while True:` loop is where a partition can be
half-walked, and a fake that returns everything in one page cannot fail that way.

MUTATION CONTROLS
─────────────────
Two, both in-test and both over the REAL module functions rather than a copy:
  * `test_mutation_control_dropping_if_not_exists_reds_the_contract` rebuilds the update
    expression with the `if_not_exists` wrappers stripped — the #1202 defect exactly —
    and asserts the same comparison FAILS. A harness that passes over the broken writer
    is proving nothing.
  * `test_mutation_control_a_blind_idempotency_check_reds_the_contract` replaces
    `is_already_tombstoned` with the pre-#1202 predicate (reason == the CURRENT genesis)
    and asserts the archive converges onto one cycle, which is the bug as it shipped.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "restart_wipe_rows_2026-09-20.json"

# The wipe self-manages sys.path (repo root + lambdas/ + deploy/) at import time.
_spec = importlib.util.spec_from_file_location("restart_intelligence_wipe", REPO_ROOT / "deploy" / "restart_intelligence_wipe.py")
wipe = importlib.util.module_from_spec(_spec)
sys.modules["restart_intelligence_wipe"] = wipe
_spec.loader.exec_module(wipe)

#: The attributes whose whole point is to record WHICH reset generation archived a row.
#: A second reset that changes any of these has destroyed the record it was meant to keep.
PROVENANCE_FIELDS = ("tombstone", "tombstoned_at", "tombstoned_reason", "cycle", "phase", "status", "status_before_tombstone", "hidden")

_SET_CLAUSE = re.compile(r"^\s*(?P<lhs>[#\w]+)\s*=\s*(?P<rhs>.+?)\s*$")
_IF_NOT_EXISTS = re.compile(r"^if_not_exists\(\s*(?P<attr>[#\w]+)\s*,\s*(?P<val>:[\w]+)\s*\)$")
#: The same shape, UNANCHORED — for the mutation controls, which strip the guard out of a
#: whole UpdateExpression rather than matching one clause.
_ANY_IF_NOT_EXISTS = re.compile(r"if_not_exists\(\s*[#\w]+\s*,\s*(:[\w]+)\s*\)")


def _unguarded(real_build_update):
    """`build_update` with every `if_not_exists(attr, :v)` collapsed to `:v` — the #1202
    defect, planted in the real function's own output."""

    def _wrapped(extra_attrs, now_iso, cycle, preserve_phase=False, item=None):
        expr, names, values = real_build_update(extra_attrs, now_iso, cycle, preserve_phase=preserve_phase, item=item)
        stripped = _ANY_IF_NOT_EXISTS.sub(lambda m: m.group(1), expr)
        assert stripped != expr, "the planted mutation changed nothing — the control would be vacuous"
        return stripped, names, values

    return _wrapped


class FakeTable:
    """An in-memory DynamoDB table that implements `query` (paginated) and `update_item`
    (real SET / if_not_exists evaluation). Deliberately NOT a general DDB emulator: it
    supports exactly the two expression shapes the wipe emits, and RAISES on anything
    else, so a future wipe change that outgrows it fails loudly instead of being
    silently mis-simulated."""

    PAGE = 7

    def __init__(self, rows):
        self.rows = {(r["pk"], r["sk"]): dict(r) for r in rows}
        self.update_calls = 0

    # ── reads ────────────────────────────────────────────────────────────────
    def _matching(self, pk, sk_prefix):
        return sorted((k for k in self.rows if k[0] == pk and k[1].startswith(sk_prefix)), key=lambda k: k[1])

    def query(self, **kwargs):
        kce = kwargs["KeyConditionExpression"]
        values = kwargs["ExpressionAttributeValues"]
        pk = values[":pk"]
        sk_prefix = values.get(":skp", "") if "begins_with" in kce else ""
        keys = self._matching(pk, sk_prefix)
        start = kwargs.get("ExclusiveStartKey")
        if start is not None:
            keys = [k for k in keys if k[1] > start["sk"]]
        page, rest = keys[: self.PAGE], keys[self.PAGE :]
        resp = {"Items": [copy.deepcopy(self.rows[k]) for k in page]}
        if rest:
            resp["LastEvaluatedKey"] = {"pk": page[-1][0], "sk": page[-1][1]}
        return resp

    # ── writes ───────────────────────────────────────────────────────────────
    def update_item(self, *, Key, UpdateExpression, ExpressionAttributeNames, ExpressionAttributeValues):
        self.update_calls += 1
        item = self.rows[(Key["pk"], Key["sk"])]
        body = UpdateExpression.strip()
        if not body.upper().startswith("SET "):
            raise AssertionError(f"FakeTable only models SET updates, got: {UpdateExpression!r}")
        for clause in _split_clauses(body[4:]):
            m = _SET_CLAUSE.match(clause)
            if not m:
                raise AssertionError(f"FakeTable cannot parse clause {clause!r}")
            attr = ExpressionAttributeNames.get(m.group("lhs"), m.group("lhs"))
            rhs = m.group("rhs")
            ine = _IF_NOT_EXISTS.match(rhs)
            if ine:
                guarded = ExpressionAttributeNames.get(ine.group("attr"), ine.group("attr"))
                if guarded in item:
                    continue  # the whole point: an existing value is never overwritten
                item[attr] = ExpressionAttributeValues[ine.group("val")]
            elif rhs.startswith(":"):
                item[attr] = ExpressionAttributeValues[rhs]
            else:
                raise AssertionError(f"FakeTable cannot evaluate RHS {rhs!r}")


def _split_clauses(text: str) -> list[str]:
    """Split a SET body on top-level commas (the commas inside if_not_exists(a, :b) are not)."""
    out, depth, buf = [], 0, ""
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(buf)
            buf = ""
        else:
            buf += ch
    if buf.strip():
        out.append(buf)
    return out


def _fixture_rows() -> list[dict]:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return payload["rows"]


def _provenance(table: FakeTable) -> dict:
    return {key: {f: row.get(f) for f in PROVENANCE_FIELDS} for key, row in table.rows.items()}


def _run_twice(rows=None, cycle_one=98, cycle_two=99):
    """Two full wipes over one table, with DIFFERENT cycles and DIFFERENT clocks — so a
    second write that lands is unmistakable rather than coincidentally identical."""
    table = FakeTable(rows if rows is not None else _fixture_rows())
    wipe.run_wipe(table, cycle=cycle_one, now_iso="2026-09-20T01:00:00+00:00", apply=True, work=wipe.build_work())
    after_first = _provenance(table)
    calls_first = table.update_calls
    wipe.run_wipe(table, cycle=cycle_two, now_iso="2026-09-21T02:00:00+00:00", apply=True, work=wipe.build_work())
    return table, after_first, _provenance(table), calls_first


# ─────────────────────────────────────────────────────────────────────────────
# the fixture is the wire, and it is not vacuous
# ─────────────────────────────────────────────────────────────────────────────


def test_the_fixture_is_a_real_capture_with_the_shapes_that_matter():
    """A harness over a corpus that exercises one code path proves one code path."""
    rows = _fixture_rows()
    assert len(rows) >= 100, f"only {len(rows)} rows — too thin to call this a double-reset corpus"
    assert len({r["pk"] for r in rows}) >= 8
    prior_reasons = {r.get("tombstoned_reason") for r in rows if r.get("tombstoned_reason")}
    assert len(prior_reasons) >= 5, f"the corpus must carry rows from SEVERAL prior resets, got {sorted(prior_reasons)}"
    assert {r.get("cycle") for r in rows if r.get("cycle") is not None} >= {1, 5}, "needs rows from more than one archived cycle"
    assert any(not r.get("tombstone") for r in rows), "needs untombstoned rows, or run 1 writes nothing"
    assert any(r.get("status") == "draft" for r in rows), "needs a chronicle draft (the #3598 status-void path)"
    assert any(r["pk"] == "NARRATIVE#arc" and r["sk"] == "STATE#current" for r in rows), "needs the #1950 phase-collision singleton"


def test_the_first_run_actually_writes():
    """The positive control for everything below: if run 1 tombstones nothing, 'run 2
    changed nothing' is true of a harness that does nothing at all."""
    table, _after_first, _after_second, calls_first = _run_twice()
    assert calls_first > 0, "run 1 performed ZERO updates — the idempotency assertion would be vacuous"


# ─────────────────────────────────────────────────────────────────────────────
# the contract
# ─────────────────────────────────────────────────────────────────────────────


def test_the_second_reset_mutates_zero_provenance_fields():
    """#3621 box 2, the acceptance clause verbatim: the second run mutates ZERO
    provenance fields."""
    _table, after_first, after_second, _calls = _run_twice()
    drifted = {k: (after_first[k], after_second[k]) for k in after_first if after_first[k] != after_second[k]}
    assert not drifted, f"the second reset mutated {len(drifted)} row(s): {list(drifted.items())[:3]}"


def test_the_second_reset_performs_no_writes_at_all():
    """Stronger than 'the values matched': an idempotent second pass should not even
    call update_item. A write that happens to be a no-op still burns WCU and still
    proves the skip predicate did not fire."""
    table, _f, _s, calls_first = _run_twice()
    assert table.update_calls == calls_first, f"run 2 issued {table.update_calls - calls_first} extra update_item call(s)"


def test_prior_generation_identity_survives_both_runs():
    """Every row that arrived already tombstoned keeps its ORIGINAL cycle, timestamp and
    reason — the #1202 guarantee, over the real archive."""
    rows = _fixture_rows()
    pre = {(r["pk"], r["sk"]): r for r in rows if r.get("tombstone")}
    assert len(pre) >= 50
    table, _f, _s, _c = _run_twice()
    for key, original in pre.items():
        now = table.rows[key]
        for field in ("cycle", "tombstoned_at", "tombstoned_reason"):
            assert now.get(field) == original.get(field), f"{key} {field}: {original.get(field)!r} -> {now.get(field)!r}"


def test_the_narrative_arc_phase_state_is_not_overwritten_by_either_run():
    """#1950: NARRATIVE#arc reuses `phase` for the narrative-arc STATE. The live
    STATE#current carries `setback`; neither reset may turn it into the taxonomy's
    'pilot'."""
    rows = _fixture_rows()
    arc = next(r for r in rows if r["pk"] == "NARRATIVE#arc" and r["sk"] == "STATE#current")
    assert arc["phase"] == "setback"
    table, _f, _s, _c = _run_twice()
    assert table.rows[("NARRATIVE#arc", "STATE#current")]["phase"] == "setback"


def test_cross_phase_coach_rows_are_never_tombstoned_by_either_run():
    """ADR-153: CHAT#/RELATIONSHIP# rows under a COACH#* pk are cross_phase — the
    texting relationship survives resets."""
    table, _f, _s, _c = _run_twice()
    for (pk, sk), row in table.rows.items():
        if pk.startswith("COACH#") and (sk.startswith("CHAT#") or sk.startswith("RELATIONSHIP#")):
            assert not row.get("tombstone"), f"{pk}/{sk} was tombstoned but is cross_phase"


def test_pagination_is_exercised_so_the_walk_is_really_a_walk():
    """If every partition fit in one page, the wipe's LastEvaluatedKey loop would be
    untested by this file and a half-walked partition would look identical to a clean one."""
    table = FakeTable(_fixture_rows())
    big = [pk for pk in {k[0] for k in table.rows} if len(table._matching(pk, "")) > FakeTable.PAGE]
    assert big, f"no partition exceeds the {FakeTable.PAGE}-row page size — pagination is not exercised"
    first = table.query(KeyConditionExpression="pk = :pk", ExpressionAttributeValues={":pk": big[0]})
    assert "LastEvaluatedKey" in first


# ─────────────────────────────────────────────────────────────────────────────
# mutation controls — remove the refusal, the contract must RED
# ─────────────────────────────────────────────────────────────────────────────


def test_mutation_control_dropping_if_not_exists_reds_the_contract(monkeypatch):
    """The #1202 defect, planted: strip the `if_not_exists` wrappers the generation
    identity depends on. The second reset then overwrites cycle/tombstoned_at/reason and
    this file's central assertion MUST fail. If it still passed, the harness would be
    proving the fixture, not the writer."""
    monkeypatch.setattr(wipe, "build_update", _unguarded(wipe.build_update))
    # ...and defeat the skip, exactly as a future refactor that "helpfully" re-tombstones would.
    monkeypatch.setattr(wipe, "is_already_tombstoned", lambda item: False)
    _table, after_first, after_second, _c = _run_twice()
    drifted = {k for k in after_first if after_first[k] != after_second[k]}
    assert drifted, "MUTATION CONTROL FAILED: the if_not_exists guards were removed and nothing changed"


def test_mutation_control_a_blind_idempotency_check_reds_the_contract(monkeypatch):
    """The pre-#1202 predicate: "already tombstoned" meant "tombstoned by THIS genesis".
    A row archived by an EARLIER reset then fails the check and is re-stamped, and with
    the `if_not_exists` guards also gone the whole archive converges onto the running
    cycle — a February pilot insight claiming cycle=5. That is the bug as it shipped, and
    `test_prior_generation_identity_survives_both_runs` above is the assertion that must
    RED under it. If this control passed, that test would be proving the fixture.

    NOTE the shape: the defect is visible on the FIRST pass, not the second. The blind
    predicate rewrites every prior reason to the CURRENT genesis, after which run 2 does
    skip — which is exactly why "run 2 changed nothing" is not on its own a proof of
    idempotency, and why this file compares against the captured originals too."""
    monkeypatch.setattr(wipe, "is_already_tombstoned", lambda item: item.get("tombstoned_reason") == wipe.TOMBSTONE_REASON)
    monkeypatch.setattr(wipe, "build_update", _unguarded(wipe.build_update))
    rows = _fixture_rows()
    pre = {(r["pk"], r["sk"]): r for r in rows if r.get("tombstone")}
    table, _after_first, _after_second, _c = _run_twice()
    clobbered = {k: (pre[k].get("cycle"), table.rows[k].get("cycle")) for k in pre if table.rows[k].get("cycle") != pre[k].get("cycle")}
    assert clobbered, "MUTATION CONTROL FAILED: the blind predicate + stripped guards preserved every prior cycle stamp"
    assert {new_cycle for _old, new_cycle in clobbered.values()} == {98}, (
        "expected the clobbered rows to carry the FIRST run's cycle (the blind predicate rewrites the reason on "
        f"pass 1, so pass 2 then skips them): {sorted(set(clobbered.values()))[:5]}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# the seam itself
# ─────────────────────────────────────────────────────────────────────────────


def test_run_wipe_is_read_only_without_apply():
    """A dry run must count and write NOTHING — the operator-facing promise of the
    default mode."""
    table = FakeTable(_fixture_rows())
    before = _provenance(table)
    counts, _samples, errors = wipe.run_wipe(table, cycle=98, now_iso="2026-09-20T01:00:00+00:00", apply=False)
    assert not errors
    assert sum(c["to_tombstone"] for c in counts.values()) > 0, "dry-run planned zero writes over a corpus with untombstoned rows"
    assert table.update_calls == 0
    assert _provenance(table) == before


def test_the_harness_drives_the_same_partition_list_the_reset_does():
    """`build_work()` is the live list. A harness with its own list proves idempotency
    for a wipe nobody runs."""
    work = wipe.build_work()
    labels = {label for _pk, label, _m, _e, _skp in work}
    assert len(work) == len(wipe.PARTITIONS) + len(wipe.COACH_PARTITIONS) + len(wipe.FULL_PK_PARTITIONS)
    assert {"insights", "chronicle", "protocols", "narrative_arc", "coach_thread"} <= labels


def test_fake_table_refuses_an_expression_shape_it_cannot_model():
    """The fake must fail loudly rather than silently mis-simulating a future wipe."""
    table = FakeTable(_fixture_rows())
    key = next(iter(table.rows))
    with pytest.raises(AssertionError):
        table.update_item(
            Key={"pk": key[0], "sk": key[1]},
            UpdateExpression="REMOVE tombstone",
            ExpressionAttributeNames={},
            ExpressionAttributeValues={},
        )
