"""tests/test_obligation_carriers_3597.py — a waiver, deferral or residue ledger carries a
condition, an expiry and a carrier, and the calendar probes it (#3597, epic #3592).

One file per acceptance box of the issue, each with its red AND its green:

  1. the alarm-citation gate, end to end through `main()` — a synthetic alarm that
     transitioned AFTER its citation's `added` date exits 1; the same entry re-cited on the
     episode day with the live cause exits 0 (the checks themselves landed with #3501);
  2. the obligation vocabulary on the governed surfaces — `revisit when traffic grows` with
     no `#N` reds, with `#1234` is homed, `revisit 2026-11-01` with no calendar probe reds —
     plus the Load-bearing demote field and its calendar probe, and the closure contract's
     `unhomed-residual` armed BLOCK on the real #2643 close (PR #2877's `Fast-follow`);
  3. an a11y serious entry with no `issue` reds (the rule lives in tests/a11y_audit.py,
     #3548 — pinned here against the file the issue names);
  4. the residue registry — every entry carries a carrier + expiry, an entry without one
     reds, a ledger that is not registered reds, and the ledgers pinned today shrink only;
  5. the rejected rent (`NewInteriorGapCount`) is absent from the shipped tree.

Nothing here reads the calendar date against a live expiry: expiry is a fact about TODAY
and belongs to the scheduled `operating_calendar.py --due` sweep, never to a unit test
that would red an innocent PR on the day an entry lapses (#2975).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"


def _load(name: str, path: Path):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


oc = _load("_obligation_carriers_3597", SCRIPTS / "obligation_carriers.py")
cal = _load("_operating_calendar_for_3597", SCRIPTS / "operating_calendar.py")
cc = _load("closure_contract_3597", SCRIPTS / "closure_contract.py")
sweep = _load("closure_sweep_3597", SCRIPTS / "closure_sweep.py")
cac = _load("_check_alarm_citations_3597", SCRIPTS / "check_alarm_citations.py")
residue = _load("_obligation_residue_3597", ROOT / "tests" / "obligation_residue_3597.py")

ADR = "docs/DECISIONS.md"


# ═══════════════════════════════════════════════════════════════════════════════════════
# 1. the alarm-citation gate — a citation older than the episode fails, a fresh one passes
# ═══════════════════════════════════════════════════════════════════════════════════════


def _run_citation_gate(monkeypatch, citation: dict, live_cause: list) -> int:
    now = datetime.now(timezone.utc)
    transitioned = (now - timedelta(days=2)).replace(microsecond=0)
    alarm = {
        "name": "qa-smoke-failures",
        "updated": transitioned.isoformat(),
        "transitioned": transitioned.isoformat(),
        "by_construction": False,
    }
    monkeypatch.setattr(cac, "fetch_alarms", lambda: ([alarm], None))
    monkeypatch.setattr(cac, "load_citations", lambda: {"qa-smoke-failures": citation})
    monkeypatch.setattr(cac, "load_alarm_audience", lambda: {})
    monkeypatch.setattr(cac, "fetch_alarm_history", lambda *a, **k: ([], None))
    monkeypatch.setattr(cac, "fetch_all_alarm_names", lambda *a, **k: ({"qa-smoke-failures"}, None))
    monkeypatch.setattr(cac, "fetch_issue_states", lambda refs: ({str(r): "OPEN" for r in refs}, None))
    monkeypatch.setattr(cac, "fetch_qa_smoke_causes", lambda *a, **k: ({"qa-smoke-failures": live_cause}, None))
    monkeypatch.setattr(sys, "argv", ["check_alarm_citations.py"])
    return cac.main(), transitioned.date()


def test_a_synthetic_alarm_that_transitioned_after_its_citation_fails_the_gate(monkeypatch, capsys):
    stale = {"citation": "#3598 — CURED and PROVEN LIVE", "added": "2020-01-01", "cause": "reader_truth:frozen_artifacts"}
    rc, _day = _run_citation_gate(monkeypatch, stale, ["reader_truth:frozen_artifacts"])
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "qa-smoke-failures" in out


def test_a_cause_the_citation_does_not_explain_fails_the_gate_even_when_dated_today(monkeypatch, capsys):
    today = datetime.now(timezone.utc).date().isoformat()
    wrong = {"citation": "#3598", "added": today, "cause": "cross_surface:weight"}
    rc, _day = _run_citation_gate(monkeypatch, wrong, ["reader_truth:frozen_artifacts"])
    assert rc == 1, capsys.readouterr().out


def test_the_same_entry_with_cause_and_date_matching_the_episode_passes(monkeypatch, capsys):
    now = datetime.now(timezone.utc)
    episode_day = (now - timedelta(days=2)).date().isoformat()
    fresh = {"citation": "#3598", "added": episode_day, "cause": "reader_truth:frozen_artifacts"}
    rc, _day = _run_citation_gate(monkeypatch, fresh, ["reader_truth:frozen_artifacts"])
    assert rc == 0, capsys.readouterr().out


# ═══════════════════════════════════════════════════════════════════════════════════════
# 2a. the obligation vocabulary — structural home, never a phrase list of excuses
# ═══════════════════════════════════════════════════════════════════════════════════════


def test_revisit_when_traffic_grows_with_no_carrier_is_red():
    adr = "### ADR-999 — keep the monolith\n\nWe keep one Lambda. Revisit when traffic grows.\n"
    out = oc.unhomed_obligations(ADR, adr, dated={})
    assert len(out) == 1 and "Revisit when traffic grows" in out[0][1]


def test_the_same_obligation_with_a_carrier_issue_is_green():
    adr = "### ADR-999 — keep the monolith\n\nWe keep one Lambda. Revisit when traffic grows (#1234).\n"
    assert oc.unhomed_obligations(ADR, adr, dated={}) == []


def test_a_not_work_tag_is_a_home_too():
    adr = "We keep one Lambda. Revisit when traffic grows — not-work — the quarterly re-read owns it.\n"
    assert oc.unhomed_obligations(ADR, adr, dated={}) == []


def test_a_dated_obligation_with_no_calendar_probe_is_red():
    row = "| MCP server | Load-bearing | $ | revisit 2026-11-01 |\n"
    out = oc.unhomed_obligations("docs/PROPORTIONALITY.md", row, dated={})
    assert len(out) == 1 and "no calendar probe" in out[0][2]


def test_the_same_date_registered_for_the_calendar_probe_is_green():
    row = "| MCP server | Load-bearing | $ | revisit 2026-11-01 |\n"
    dated = {("docs/PROPORTIONALITY.md", "2026-11-01"): {"declared": "2026-09-23", "what": "re-measure the tool count"}}
    assert oc.unhomed_obligations("docs/PROPORTIONALITY.md", row, dated=dated) == []
    assert oc.dated_obligation_findings(dated) == []


def test_a_registered_date_past_ninety_days_is_not_a_home():
    dated = {("docs/PROPORTIONALITY.md", "2031-01-01"): {"declared": "2026-09-23", "what": "someday"}}
    assert any("90 days" in p for p in oc.dated_obligation_findings(dated))


def test_narrative_later_and_past_tense_revisited_are_not_obligations():
    """The #2959 lesson: the cue nominates, it never decides — and it must not nominate prose."""
    assert not oc.names_obligation("Later that week the reset ran; step 4 of the wrap caught it.")
    assert not oc.names_obligation("The ceiling was revisited on 2026-08-28 and raised.")
    assert not oc.names_obligation("No revisit is needed: the trigger is retired.")
    assert oc.names_obligation("The rest is deferred to a later session.")
    assert oc.names_obligation("Owner decides whether to keep it.")
    assert oc.names_obligation("Fast-follow: whoop and habitify.")


def test_a_heartbeat_exemption_is_a_governed_surface_read_by_ast():
    src = (
        'EXEMPT = "exempt"\n'
        "COVERAGE = {\n"
        '    "a-fn": (EXEMPT, "2026-09-01", "silent absence is fine; revisit once it has a send history"),\n'
        '    "b-fn": (EXEMPT, "2026-09-01", "silent absence is fine; revisit once it has a send history (#1382)"),\n'
        '    "c-fn": ("alarm", "c-fn-heartbeat"),\n'
        "}\n"
    )
    rel = "tests/test_heartbeat_completeness.py"
    assert rel in oc.OBLIGATION_SURFACES
    blocks = oc.surface_blocks(rel, src)
    assert [b.split(":")[0] for b in blocks] == ["a-fn", "b-fn"]
    assert [k for k, _e, _r in oc.unhomed_obligations(rel, src, dated={})] == [oc.obligation_key(rel, blocks[0])]


def test_every_unhomed_obligation_on_a_governed_surface_is_pinned():
    live = {k: excerpt for k, excerpt, _r in oc.live_unhomed_obligations()}
    new = sorted(set(live) - set(residue.OBLIGATION_RESIDUE))
    assert not new, (
        "an obligation on a governed surface has no home — give it a carrier `#N`, a `not-work —` tag, "
        "or a date registered in obligation_carriers.DATED_OBLIGATIONS (<= 90d). Never pin a new one:\n"
        + "\n".join(f"  {k}: {live[k]}" for k in new)
    )


def test_the_obligation_residue_only_shrinks():
    live = {k for k, _e, _r in oc.live_unhomed_obligations()}
    stale = sorted(set(residue.OBLIGATION_RESIDUE) - live)
    assert not stale, "these pinned obligations gained a home (or left) — delete their rows:\n" + "\n".join(stale)
    assert len(residue.OBLIGATION_RESIDUE) <= 44, "seeded at 44 on 2026-09-23; the ceiling only comes down"


def test_the_live_dated_obligation_registry_is_well_formed():
    assert oc.dated_obligation_findings() == []


# ═══════════════════════════════════════════════════════════════════════════════════════
# 2b. every Load-bearing proportionality row carries a demote field; the calendar probes it
# ═══════════════════════════════════════════════════════════════════════════════════════

_HEADER = "| Subsystem | Posture | Rent | Earns its keep by / demote trigger |\n|---|---|---|---|\n"


def test_a_load_bearing_row_with_neither_field_is_red_and_either_field_is_green():
    doc = (
        _HEADER
        + "| Bare row | Load-bearing | $0 | **Demote trigger:** free text only |\n"
        + "| Dated row | Load-bearing · ratchet | $0 | demote_by: 2026-12-01 |\n"
        + "| Conditioned row | **Load-bearing** | $0 | **demote_when:** zero fires in 90d (#4122) |\n"
        + "| Portfolio row | Portfolio | $0 | nothing required |\n"
    )
    assert [s for _k, s in oc.rows_missing_demote_field(doc)] == ["Bare row"]


def test_a_row_past_its_demote_by_reds_the_calendar_probe_and_a_future_one_passes():
    doc = _HEADER + "| Old gate | Load-bearing | $0 | demote_by: 2026-10-01 |\n| New gate | Load-bearing | $0 | demote_by: 2026-12-01 |\n"
    lapsed = oc.expired_carriers(date(2026, 11, 1), registry={}, dated={}, proportionality_text=doc)
    assert len(lapsed) == 1 and "Old gate" in lapsed[0]
    assert oc.expired_carriers(date(2026, 10, 1), registry={}, dated={}, proportionality_text=doc) == [], "the date itself is still live"
    bad = _HEADER + "| Typo | Load-bearing | $0 | demote_by: 2026-02-30 |\n"
    assert "UNPARSEABLE" in oc.expired_carriers(date(2026, 1, 1), registry={}, dated={}, proportionality_text=bad)[0]


def test_the_operating_calendar_dead_man_exits_5_on_a_lapsed_carrier(monkeypatch, capsys):
    monkeypatch.setattr(cal, "due_report", lambda today: ("report", [], []))
    monkeypatch.setattr(cal, "carry_forward_report", lambda today: (["carry ok"], []))
    monkeypatch.setattr(oc, "expired_carriers", lambda today: ["proportionality row 'Old gate' — demote_by 2026-10-01 has passed"])
    assert cal.main(["--due", "--today", "2026-11-01"]) == cal.EXIT_EXPIRED_CARRIER == 5
    assert "Old gate" in capsys.readouterr().out
    monkeypatch.setattr(oc, "expired_carriers", lambda today: [])
    assert cal.main(["--due", "--today", "2026-11-01"]) == cal.EXIT_CLEAN


def test_the_workflow_names_exit_5_in_its_own_case_arm():
    wf = (ROOT / ".github" / "workflows" / "operating-calendar.yml").read_text(encoding="utf-8")
    assert "5) echo" in wf and "EXIT_EXPIRED_CARRIER" in wf


def test_every_load_bearing_row_without_a_demote_field_is_pinned_and_the_pin_only_shrinks():
    text = (ROOT / oc.PROPORTIONALITY).read_text(encoding="utf-8")
    missing = dict(oc.rows_missing_demote_field(text))
    new = sorted(set(missing) - set(residue.DEMOTE_FIELD_RESIDUE))
    assert not new, "a Load-bearing row lands with no `demote_by:` / `demote_when:` — give it one:\n" + "\n".join(
        f"  {k}: {missing[k]}" for k in new
    )
    stale = sorted(set(residue.DEMOTE_FIELD_RESIDUE) - set(missing))
    assert not stale, "these rows gained a demote field (or left) — delete their pins:\n" + "\n".join(stale)
    assert len(residue.DEMOTE_FIELD_RESIDUE) <= 81, "seeded at 81 on 2026-09-23; the ceiling only comes down"


# ═══════════════════════════════════════════════════════════════════════════════════════
# 2c. the closure contract: `unhomed-residual` is BLOCK, and the #2643 close is its specimen
# ═══════════════════════════════════════════════════════════════════════════════════════


def test_the_real_2643_close_fast_follow_is_a_blocking_unhomed_residual():
    raw = json.loads((ROOT / "tests" / "fixtures" / "closure_contract" / "issue_2643_fast_follow_3597.json").read_text(encoding="utf-8"))
    issue = sweep.parse_issue(raw["issues"][0])
    findings = [f for f in sweep.evaluate_issue(issue) if f.code == "unhomed-residual"]
    assert any("Fast-follow, not done here" in f.detail for f in findings), findings
    assert cc.arming_for("unhomed-residual", "warn") == "block"
    code, lines = sweep.render({"findings": findings, "dispositioned": [], "scanned": 1}, "fixture", "warn")
    assert code == 1 and "blocking=unhomed-residual" in lines[-1]


def test_the_same_fast_follow_with_a_carrier_is_homed():
    body = "**Fast-follow, not done here:** whoop and habitify opt in under #3504.\n"
    assert cc.unhomed_residuals(body) == []
    assert cc.unhomed_residuals("**Fast-follow, not done here:** whoop and habitify.\n")


def test_the_residual_leg_ignores_working_notes_posted_before_the_close():
    closed = "2026-08-18T15:37:18Z"
    node = {
        "number": 1,
        "closedAt": closed,
        "stateReason": "COMPLETED",
        "author": {"login": "someone"},
        "labels": {"nodes": []},
        "comments": {
            "nodes": [
                {"author": {"login": "someone"}, "createdAt": "2026-08-10T00:00:00Z", "body": "Deferred to a later session, maybe."},
                {
                    "author": {"login": "someone"},
                    "createdAt": "2026-08-18T15:36:00Z",
                    "body": "**Shipped:** x\n**Outcome:** realized — done.",
                },
            ]
        },
    }
    assert [f for f in sweep.evaluate_issue(sweep.parse_issue(node)) if f.code == "unhomed-residual"] == []


# ═══════════════════════════════════════════════════════════════════════════════════════
# 3. an a11y serious entry with no `issue` reds (tests/a11y_audit.py, #3548)
# ═══════════════════════════════════════════════════════════════════════════════════════


def test_a_serious_axe_entry_with_no_issue_is_red_and_with_one_is_green():
    a11y = _load("_a11y_audit_3597", ROOT / "tests" / "a11y_audit.py")
    row = {"id": "svg-img-alt", "impact": "serious", "help": "svg needs a name", "nodes": 1}
    missing = {"pages": {"/method/build/": [dict(row)]}}
    assert a11y.untriaged_serious_entries(missing), "a serious row with no `issue` must red"
    owned = {"pages": {"/method/build/": [dict(row, issue="#3548")]}}
    assert a11y.untriaged_serious_entries(owned) == []


# ═══════════════════════════════════════════════════════════════════════════════════════
# 4. the residue registry — carrier + condition + expiry + consumer, derived not listed
# ═══════════════════════════════════════════════════════════════════════════════════════


def test_the_live_residue_registry_meets_its_contract():
    assert oc.registry_findings() == []


def test_the_registry_names_the_four_ledgers_the_issue_lists():
    keys = set(oc.RESIDUE_LEDGERS)
    for must in (
        "tests/conformance_residue.py::CONFORMANCE_RESIDUE",
        "tests/pair_seam_residue.py::PAIR_SEAM_RESIDUE",
        "tests/mypy_clean_set.py::DIRTY",
        "tests/a11y_baseline.json",
    ):
        assert must in keys, must


def test_an_entry_without_an_expiry_is_red():
    reg = {k: dict(v) for k, v in oc.RESIDUE_LEDGERS.items()}
    reg["tests/pair_seam_residue.py::PAIR_SEAM_RESIDUE"].pop("expires")
    problems = oc.registry_findings(registry=reg)
    assert any("PAIR_SEAM_RESIDUE" in p and "expires" in p for p in problems), problems


def test_an_entry_past_ninety_days_or_without_an_issue_carrier_is_red():
    reg = {k: dict(v) for k, v in oc.RESIDUE_LEDGERS.items()}
    reg["tests/conformance_residue.py::CONFORMANCE_RESIDUE"].update(expires="2031-01-01")
    reg["tests/mypy_clean_set.py::DIRTY"].update(carrier="someday")
    problems = oc.registry_findings(registry=reg)
    assert any("CONFORMANCE_RESIDUE" in p and "90 days" in p for p in problems)
    assert any("DIRTY" in p and "not an issue" in p for p in problems)


def test_a_new_python_ledger_not_in_the_registry_is_red(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "shiny_new_residue.py").write_text("SHINY_RESIDUE = {'a': '2026-09-23'}\n", encoding="utf-8")
    (tmp_path / "tests" / "not_a_ledger.py").write_text("def f():\n    LOCAL_RESIDUE = 1\n", encoding="utf-8")
    assert oc.discover_residue_ledgers(tmp_path) == ["tests/shiny_new_residue.py::SHINY_RESIDUE"]
    problems = oc.registry_findings(registry={}, root=tmp_path)
    assert any("SHINY_RESIDUE" in p and "NOT in RESIDUE_LEDGERS" in p for p in problems), problems


def test_a_new_data_file_ledger_not_in_the_registry_is_red(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "contrast_baseline.json").write_text("{}", encoding="utf-8")
    assert oc.discover_residue_ledgers(tmp_path) == ["tests/contrast_baseline.json"]
    assert any("contrast_baseline.json" in p for p in oc.registry_findings(registry={}, root=tmp_path))


def test_a_phantom_registration_is_red():
    reg = dict(oc.RESIDUE_LEDGERS)
    reg["tests/nowhere.py::GHOST_RESIDUE"] = dict(oc.RESIDUE_LEDGERS["tests/pair_seam_residue.py::PAIR_SEAM_RESIDUE"])
    assert any("GHOST_RESIDUE" in p and "phantom" in p for p in oc.registry_findings(registry=reg))


def test_the_probe_names_a_lapsed_ledger_and_is_silent_before_it():
    reg = {"tests/x.py::X_RESIDUE": {"carrier": "#1", "expires": "2026-10-01"}}
    assert oc.expired_carriers(date(2026, 10, 1), registry=reg, dated={}, proportionality_text="") == []
    assert oc.expired_carriers(date(2026, 10, 2), registry=reg, dated={}, proportionality_text="")[0].startswith(
        "residue ledger tests/x.py"
    )


# ═══════════════════════════════════════════════════════════════════════════════════════
# 5. the rent the RCA rejected stays rejected
# ═══════════════════════════════════════════════════════════════════════════════════════


def test_new_interior_gap_count_was_not_added():
    """REJECTED in the forensic RCA's rent register: #3504's absence marker over every
    framework DAILY_SOURCE removes the condition instead of instrumenting it (asserted by
    tests/test_source_enumeration_drift.py)."""
    for sub in ("lambdas", "cdk", "mcp"):
        for path in (ROOT / sub).rglob("*.py"):
            if "cdk.out" in path.parts or "node_modules" in path.parts:
                continue
            assert "NewInteriorGapCount" not in path.read_text(encoding="utf-8", errors="ignore"), path
