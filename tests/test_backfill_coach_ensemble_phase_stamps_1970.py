"""tests/test_backfill_coach_ensemble_phase_stamps_1970.py — the #1970 operator tool.

deploy/backfill_coach_ensemble_phase_stamps.py is the reviewed, dry-run-by-default
repair for the two known live unstamped PREDICTION# rows (and any other stray
unstamped row on the same tagger-blind COACH#/ENSEMBLE# partitions). This file
proves it entirely offline against fakes — never against a real table — matching
the "no live AWS writes" constraint on the task that authored it.

#2119: `coach_narrative_orchestrator._cache_brief` was a second, previously-missed
writer to this same tagger-blind partition class (unstamped BRIEF# rows on
COACH#<coach_id> pks). It's now fixed at the source (write-time provenance), but
`test_query_unstamped_also_catches_a_brief_row_on_a_coach_partition` below proves
this operator script's `query_unstamped()` — which scans the WHOLE pk partition,
not a PREDICTION#-only sk prefix — already covers any BRIEF# rows written before
that fix landed, with no code change to this script required.
"""

from __future__ import annotations

import importlib.util
import sys
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "lambdas"))


def _load(module_name: str, rel_path: str):
    spec = importlib.util.spec_from_file_location(module_name, REPO_ROOT / rel_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


backfill = _load("backfill_coach_ensemble_phase_stamps", "deploy/backfill_coach_ensemble_phase_stamps.py")


def test_target_pks_covers_every_operational_coach_and_ensemble_singleton_but_not_influence_graph():
    from coach.persona_registry import OPERATIONAL_COACH_IDS

    pks = backfill.target_pks()
    for cid in OPERATIONAL_COACH_IDS:
        assert f"COACH#{cid}" in pks
    assert "COACH#computation" in pks
    for p in ("ENSEMBLE#digest", "ENSEMBLE#disagreements", "ENSEMBLE#dispute", "ENSEMBLE#docket"):
        assert p in pks
    # SYSTEM_STATE static config — never phase-stamped by design, must not be audited
    assert "ENSEMBLE#influence_graph" not in pks


class _FakeTable:
    def __init__(self, items_by_pk, page_size=10):
        self.items_by_pk = items_by_pk
        self.page_size = page_size
        self.updates = []

    def query(self, **kwargs):
        pk = kwargs["KeyConditionExpression"].get_expression()["values"][1]
        unstamped = [it for it in self.items_by_pk.get(pk, []) if "phase" not in it]
        start = (kwargs.get("ExclusiveStartKey") or {}).get("_offset", 0)
        page = unstamped[start : start + self.page_size]
        resp = {"Items": page}
        if start + self.page_size < len(unstamped):
            resp["LastEvaluatedKey"] = {"_offset": start + self.page_size}
        return resp

    def update_item(self, **kwargs):
        self.updates.append(kwargs)


def test_query_unstamped_filters_and_paginates():
    pk = "COACH#sleep_coach"
    items = [{"sk": "PREDICTION#a"}, {"sk": "PREDICTION#b", "phase": "experiment"}, {"sk": "PREDICTION#c"}]
    table = _FakeTable({pk: items}, page_size=1)
    found = backfill.query_unstamped(table, pk)
    assert {it["sk"] for it in found} == {"PREDICTION#a", "PREDICTION#c"}


def test_query_unstamped_also_catches_a_brief_row_on_a_coach_partition():
    """#2119: query_unstamped() queries the WHOLE pk partition (Key("pk").eq(pk)),
    not a PREDICTION#-only sk prefix — so a leftover unstamped BRIEF# row (the
    coach_narrative_orchestrator._cache_brief class, fixed at the source by
    #2119) on the SAME COACH#<coach_id> pk is already caught by this existing
    script, mixed in with PREDICTION#/other sk rows, with no code change here."""
    pk = "COACH#sleep_coach"
    items = [
        {"sk": "PREDICTION#a"},
        {"sk": "BRIEF#2026-08-01"},  # the #2119 class: unstamped, no PREDICTION# prefix
        {"sk": "BRIEF#2026-08-02", "phase": "experiment"},  # already stamped — must be skipped
        {"sk": "STANCE#latest", "phase": "experiment"},
    ]
    table = _FakeTable({pk: items})
    found = backfill.query_unstamped(table, pk)
    assert {it["sk"] for it in found} == {"PREDICTION#a", "BRIEF#2026-08-01"}


def test_apply_backfills_a_brief_row_end_to_end(monkeypatch):
    """#2119 AC2, non-vacuity: main(--apply) actually writes the stamp onto an
    unstamped BRIEF# row, exercised through the same path a real operator run
    would take — not just the query-level filter above."""
    pk = "COACH#sleep_coach"
    table = _FakeTable({pk: [{"sk": "BRIEF#2026-08-01"}, {"sk": "PREDICTION#already", "phase": "experiment", "cycle": 12}]})
    monkeypatch.setattr(backfill.boto3, "resource", lambda *a, **kw: type("R", (), {"Table": lambda self, n: table})())
    monkeypatch.setattr(backfill, "experiment_stamp", lambda: {"phase": "experiment", "cycle": 12})
    monkeypatch.setattr(sys, "argv", ["backfill_coach_ensemble_phase_stamps.py", "--apply"])

    rc = backfill.main()

    assert rc == 0
    assert len(table.updates) == 1
    upd = table.updates[0]
    assert upd["Key"] == {"pk": pk, "sk": "BRIEF#2026-08-01"}
    assert upd["ExpressionAttributeValues"][":phase"] == "experiment"


def test_update_kwargs_sets_phase_and_cycle_guarded_by_absence():
    kw = backfill._update_kwargs("COACH#sleep_coach", "PREDICTION#pred_x", {"phase": "experiment", "cycle": 12})
    assert kw["Key"] == {"pk": "COACH#sleep_coach", "sk": "PREDICTION#pred_x"}
    assert kw["ConditionExpression"] == "attribute_not_exists(#phase)"
    assert kw["ExpressionAttributeValues"][":phase"] == "experiment"
    assert kw["ExpressionAttributeValues"][":cycle"] == Decimal("12")
    assert isinstance(kw["ExpressionAttributeValues"][":cycle"], Decimal)  # Decimal before any DDB write


def test_update_kwargs_omits_cycle_when_stamp_has_none():
    kw = backfill._update_kwargs("COACH#sleep_coach", "PREDICTION#pred_x", {"phase": "experiment"})
    assert ":cycle" not in kw["ExpressionAttributeValues"]
    assert "#cycle" not in kw["ExpressionAttributeNames"]


def test_dry_run_finds_but_never_writes(monkeypatch, capsys):
    pk = "COACH#sleep_coach"
    table = _FakeTable({pk: [{"sk": "PREDICTION#pred_x"}]})
    monkeypatch.setattr(backfill.boto3, "resource", lambda *a, **kw: type("R", (), {"Table": lambda self, n: table})())
    monkeypatch.setattr(backfill, "experiment_stamp", lambda: {"phase": "experiment", "cycle": 12})
    monkeypatch.setattr(sys, "argv", ["backfill_coach_ensemble_phase_stamps.py"])

    rc = backfill.main()

    assert rc == 0
    assert table.updates == []  # dry-run: read-only, zero writes
    out = capsys.readouterr().out
    assert "DRY RUN" in out and "PREDICTION#pred_x" in out


def test_apply_writes_only_the_unstamped_rows(monkeypatch):
    stamped_pk = "COACH#sleep_coach"
    other_pk = "COACH#nutrition_coach"
    table = _FakeTable(
        {
            stamped_pk: [{"sk": "PREDICTION#already_stamped", "phase": "experiment", "cycle": 12}],
            other_pk: [{"sk": "PREDICTION#leaked_row"}],
        }
    )
    monkeypatch.setattr(backfill.boto3, "resource", lambda *a, **kw: type("R", (), {"Table": lambda self, n: table})())
    monkeypatch.setattr(backfill, "experiment_stamp", lambda: {"phase": "experiment", "cycle": 12})
    monkeypatch.setattr(sys, "argv", ["backfill_coach_ensemble_phase_stamps.py", "--apply"])

    rc = backfill.main()

    assert rc == 0
    assert len(table.updates) == 1
    upd = table.updates[0]
    assert upd["Key"] == {"pk": other_pk, "sk": "PREDICTION#leaked_row"}
    assert upd["ExpressionAttributeValues"][":phase"] == "experiment"


def test_refuses_to_run_without_a_phase_in_the_stamp(monkeypatch):
    """A gutted experiment_stamp() (e.g. constants import failure) must not run
    a silent no-op that looks like a clean pass."""
    table = _FakeTable({})
    monkeypatch.setattr(backfill.boto3, "resource", lambda *a, **kw: type("R", (), {"Table": lambda self, n: table})())
    monkeypatch.setattr(backfill, "experiment_stamp", lambda: {})
    monkeypatch.setattr(sys, "argv", ["backfill_coach_ensemble_phase_stamps.py"])

    rc = backfill.main()

    assert rc == 1
