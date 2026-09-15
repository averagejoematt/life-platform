"""tests/test_wrap_verify_doc_leg_3682.py — Phase 3 re-runs the derived doc leg AFTER
Phase 2 writes (#3682).

THE DEFECT. `scripts/wrap_gates.py`'s Phase 1 (`GATHER`) derives its doc leg from
`docs_ci_gate_commands()` and runs it BEFORE the wrap writes anything ("gather"). Phase 2
then writes tracked files several of those same gates read — `docs/INCIDENT_LOG.md` (e3),
`docs/alarm_citations.json` (e10), `docs/PROPORTIONALITY.md` (e12), `docs/**` pages (e),
`CLAUDE.md`/`handovers/HANDOVER_LATEST.md` (a) — and Phase 3 (`VERIFY`) never re-ran a
doc gate at all. A wrap could therefore pass its own battery over a derived block Phase 2
was about to stale, and the next push to `main` paid for it: PR #3680 red on
`incident_log_patterns.py --check` because the committed Patterns block said 204 dated /
169 post-June rows while the live table said 205/170 by the time the wrap pushed.

THE FIX, generically. `scripts/wrap_gates.py::VERIFY` now re-runs the exact same derived
doc leg (`derived_doc_gates()` — every `docs_ci_gate_commands()` entry minus the declared
`MUTATING_GATES`) AFTER Phase 2 has written. No script here special-cases
`incident_log_patterns.py`: a thirteenth Docs CI gate is inherited by Phase 3 with no
edit, the same property #3531 already gave Phase 1.

THE SET (5 members, enumerated in #3682's issue body by intersecting SKILL.md's Phase-2
writers with `docs_ci_gate_commands()`'s twelve gate inputs) plus a SIXTH: step (c)
regenerates `docs/OPERATING_KNOWLEDGE_LEDGER.md`'s committed snapshot, the identical
time-axis defect (Session AE, 2026-09-14, red-ed main on
`tests/test_operating_knowledge_ledger_2848.py`), but that check is a pytest test, not a
docs-ci.yml step, so `derived_doc_gates()` cannot reach it — it is hand-listed in `VERIFY`
instead, with a written reason, the same shape as `MUTATING_GATES`'s one declared
omission.

House style (#1189): every rule here is planted with a fixture that violates it — the
positive control below reproduces PR #3680's exact stale numbers and proves the gate
Phase 3 actually registered would have caught it.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / ".claude" / "skills" / "wrap" / "SKILL.md"


def _load(name: str, script: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / script)
    m = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(m)
    return m


wg = _load("_wg_3682", "wrap_gates.py")
ilp = _load("_ilp_3682", "incident_log_patterns.py")
rvg = wg.restart_verify_gates  # the module wrap_gates.py itself imported (deploy/)

_SKILL_TEXT = SKILL.read_text(encoding="utf-8")

# The Set: (step, the tracked file(s) it writes, the docs-ci.yml gate(s) — by their argv
# tail — that read/derive from it). Five members from the issue body's own table.
SET = [
    ("e3", "docs/INCIDENT_LOG.md", ["scripts/incident_log_patterns.py --check"]),
    ("e10", "docs/alarm_citations.json", ["scripts/check_doc_facts.py", "deploy/sync_doc_metadata.py --check"]),
    ("e12", "docs/PROPORTIONALITY.md", ["scripts/check_doc_facts.py", "scripts/check_doc_index.py --strict"]),
    (
        "e",
        "docs/** pages",
        [
            "scripts/check_doc_links.py",
            "scripts/check_doc_tombstones.py",
            "scripts/check_doc_index.py --strict",
            "scripts/generate_adr_index.py --check",
        ],
    ),
    ("a", "CLAUDE.md handovers/HANDOVER_LATEST.md", ["scripts/check_doc_facts.py", "deploy/sync_doc_metadata.py --check"]),
]

# The sixth member: a pytest test, not a docs-ci.yml gate — named explicitly rather than
# derived, and asserted separately below.
SIXTH_STEP, SIXTH_FILE, SIXTH_TEST = "c", "docs/OPERATING_KNOWLEDGE_LEDGER.md", "tests/test_operating_knowledge_ledger_2848.py"


# ── the Set is real: every named gate is a live docs-ci.yml command, not invented ───────


def test_set_gates_are_real_docs_ci_derived_commands():
    derived = {" ".join(c[1:]) for c in rvg.docs_ci_gate_commands()}
    for step, _file, gates in SET:
        for g in gates:
            assert g in derived, f"({step}): {g!r} is claimed as a docs-ci.yml gate but docs-ci.yml does not run it"


def test_set_writers_are_still_named_in_the_wrap_skill():
    """A Set member whose file SKILL.md no longer mentions would be a write nobody could
    even audit from the doc a session actually reads."""
    for step, file_desc, _gates in SET:
        first_path = file_desc.split()[0]
        needle = first_path.split("*")[0]  # "docs/** pages" -> "docs/"
        assert needle in _SKILL_TEXT, f"({step}): {needle!r} is not named in SKILL.md any more"


def test_sixth_member_file_is_named_in_the_wrap_skill():
    assert SIXTH_FILE in _SKILL_TEXT


# ── coverage: 5/5 (+ the sixth) reachable from Phase 3's VERIFY battery ─────────────────


def test_every_set_member_gate_is_covered_by_phase3_verify():
    """Acceptance box 2: 5/5 covered, no residual. #3682 achieves this by re-running the
    WHOLE derived doc leg in VERIFY (not a hand-picked subset), so this must hold for
    every member without per-member special-casing in wrap_gates.py."""
    verify_cmds = {" ".join(g.cmd[1:]) for g in wg.VERIFY}
    uncovered = [(step, file_desc, gates) for step, file_desc, gates in SET if not any(g in verify_cmds for g in gates)]
    assert not uncovered, f"Set member(s) with no owning gate in Phase 3 VERIFY, and no residual issue named: {uncovered}"


def test_sixth_member_the_operating_knowledge_ledger_is_covered_by_phase3_verify():
    """#2848/#3682: hand-listed (it is pytest, not a docs-ci.yml step) but still asserted
    as a real member of the Phase 3 battery, not just documented in step (c)'s prose."""
    verify_cmds = [" ".join(g.cmd) for g in wg.VERIFY]
    assert any(SIXTH_TEST in c for c in verify_cmds), "the operating-knowledge-ledger test must run in Phase 3 VERIFY"


def test_verify_reruns_the_whole_derived_doc_leg_generically_not_a_special_case():
    """The structural claim itself, asserted directly against the derivation rather than
    the Set table above (which could silently drift from source): every non-mutating
    docs-ci.yml gate Phase 1 runs must ALSO be in Phase 3's VERIFY — the identical list."""
    verify_cmds = {" ".join(g.cmd) for g in wg.VERIFY}
    checked = 0
    for cmd in rvg.docs_ci_gate_commands():
        if " ".join(cmd[1:]) in rvg.MUTATING_GATES:
            continue
        checked += 1
        assert " ".join(cmd) in verify_cmds, f"{' '.join(cmd)} runs in Phase 1 GATHER but is missing from Phase 3 VERIFY"
    assert checked >= 10, "too few non-mutating docs-ci.yml gates derived — the source list has gone blind"


def test_incident_log_patterns_is_not_hand_special_cased_in_wrap_gates_source():
    """The issue's own bar: the fix must be the generic re-run, never a hard-coded
    `incident_log_patterns` branch bolted on beside it."""
    import inspect

    src = inspect.getsource(wg)
    verify_section = src.split("VERIFY = [", 1)[1]
    # incident_log_patterns may appear ONLY via the shared `derived_doc_gates()` call —
    # never as its own literal Gate(...) entry inside the VERIFY list body.
    body_before_derived_call = verify_section.split("*derived_doc_gates()", 1)[0]
    assert "incident_log_patterns" not in body_before_derived_call, (
        "incident_log_patterns.py must not be hand-listed as its own VERIFY gate — "
        "it must be reached only through the generic derived-doc-leg re-run"
    )


def test_a_thirteenth_docs_ci_gate_is_inherited_by_verify_with_no_edit():
    """Negative control on the whole design, mirroring #3477/#3531's proof for Phase 1:
    add a gate to a scratch copy of the live workflow and confirm the SAME
    `derived_doc_gates()` call VERIFY makes would pick it up, with no code change here."""
    import tempfile

    live = (ROOT / ".github" / "workflows" / "docs-ci.yml").read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory() as td:
        scratch = Path(td) / "docs-ci.yml"
        scratch.write_text(
            live + "\n      - name: Thirteenth gate\n        if: always()\n        run: python3 scripts/nonexistent_gate_3682.py --check\n"
        )
        original = rvg.WORKFLOW
        try:
            rvg.WORKFLOW = scratch
            gates = wg.derived_doc_gates()
        finally:
            rvg.WORKFLOW = original
    assert any(g.cmd == ["python3", "scripts/nonexistent_gate_3682.py", "--check"] for g in gates)


# ── positive control: PR #3680's exact stale shape must fail the registered gate ────────


def test_positive_control_the_known_stale_incident_block_fails_the_registered_gate(tmp_path):
    """Acceptance box 2's positive control. PR #3680 red because the committed Patterns
    block said 204 dated / 169 post-June while the live table said 205/170. Reproduce that
    exact staleness and run the ACTUAL command object registered in `wg.VERIFY` — not a
    hand-typed re-invocation of the script — so this proves the wiring, not just the
    checker's own logic (already proven independently by
    `tests/test_incident_log_patterns_2840.py::test_check_reds_on_a_stale_block`)."""
    (gate,) = [g for g in wg.VERIFY if "incident_log_patterns.py" in " ".join(g.cmd)]
    assert gate.cmd == ["python3", "scripts/incident_log_patterns.py", "--check"]

    real_text = (ROOT / "docs" / "INCIDENT_LOG.md").read_text(encoding="utf-8")
    data = ilp.build()
    assert (data["total_rows"], data["post_june_rows"]) != (204, 169), "fixture must disagree with the live table"
    stale_data = {**data, "total_rows": 204, "post_june_rows": 169}
    stale_text = ilp.render_doc(real_text, stale_data)

    log = tmp_path / "INCIDENT_LOG.md"
    log.write_text(stale_text, encoding="utf-8")
    probe = (
        f"import sys; sys.path.insert(0, {str(ROOT / 'scripts')!r})\n"
        "import incident_log_patterns as m, pathlib\n"
        f"m.INCIDENT_LOG = pathlib.Path({str(log)!r})\n"
        f"sys.argv = ['x'] + {gate.cmd[2:]!r}\n"
        "raise SystemExit(m.main())"
    )
    out = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, timeout=60)
    assert out.returncode == 1, f"Phase 3's registered gate passed on PR #3680's known-stale numbers:\n{out.stdout}\n{out.stderr}"
    assert "STALE" in out.stderr
    live_total, live_post_june = str(data["total_rows"]), str(data["post_june_rows"])
    assert (
        live_total in out.stderr and live_post_june in out.stderr
    ), "the gate must name the live truth it disagrees with, not just say STALE"


# ── (e3): a row can never be stranded into an unrelated in-flight PR again ──────────────


def test_e3_names_apply_in_the_same_edit_and_the_phase4_git_add_list():
    """Acceptance box 3. PR #3680's second-order cost: the wrap's `git add docs/` note
    listed reasons for staging `docs/` that did not mention (e3), so an operator reading
    it literally could skip staging `docs/INCIDENT_LOG.md` after adding a row — stranding
    it into whatever unrelated branch's commit picked up the dirty file next. SKILL.md must
    name BOTH the same-edit `--apply` requirement AND the git-add list explicitly."""
    e3_start = _SKILL_TEXT.index("### (e3)")
    e4_start = _SKILL_TEXT.index("### (e4)")
    e3_section = _SKILL_TEXT[e3_start:e4_start]
    assert "incident_log_patterns.py --apply" in e3_section, "(e3) must require regenerating the derived block in the same edit"

    phase4_start = _SKILL_TEXT.index("## Phase 4")
    phase4_section = _SKILL_TEXT[phase4_start:]
    assert "docs/INCIDENT_LOG.md" in phase4_section, (
        "Phase 4's git add list/notes must name docs/INCIDENT_LOG.md explicitly — a bare "
        "`docs/` staging note that forgets (e3) is exactly how a row got stranded into an "
        "unrelated in-flight PR (#3682)"
    )
