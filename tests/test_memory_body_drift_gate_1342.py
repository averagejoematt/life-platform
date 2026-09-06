"""tests/test_memory_body_drift_gate_1342.py — the /wrap memory-body-drift gate (#1342).

Replays the SDLC-review finding: a `MEMORY.md` INDEX line can be corrected while the
topic-file BODY it points at keeps issuing a stale directive — `project_launch_dates.md`
said "always use 2026-04-01. Never use 2026-02-22" through at least three genesis
re-anchors after its index line was hedged, and `reference_site_api_layer_manual_attach.md`
named the RETIRED `operational_stack.py` as the site-api infra owner eleven days after #793
moved that ownership to `serve_stack.py`. `check_doc_facts.py` can't see the memory dir (it
is outside git) — this is the wrap-time equivalent for memory-body content.

The memory dir itself is NOT part of this repo, so these tests plant fixture text
reproducing the two pre-fix defects VERBATIM (copied from the actual pre-#1342 file
content) rather than reading the real out-of-repo files, per the check_doc_facts.py
"vacuous scan" house style (#1189): plant bad + good + historical fixtures, prove the rule
bites on the bad one and stays quiet on the others.
"""

import importlib.util
from pathlib import Path

from skill_paths import require_skill as _skill  # the ONE skill registry (no hard-coded .claude paths)

ROOT = Path(__file__).resolve().parent.parent
WRAP = _skill("wrap")
SCRIPT = ROOT / "scripts" / "check_memory_body_facts.py"


def _load():
    spec = importlib.util.spec_from_file_location("_membody_1342", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# ── the gate is wired into the /wrap skill ──────────────────────────────────────
def test_wrap_skill_has_memory_body_drift_gate():
    wrap = WRAP.read_text(encoding="utf-8")
    assert "check_memory_body_facts.py" in wrap, "#1342: the /wrap step (c) grep is missing"
    assert "Body-follows-index rule" in wrap, "#1342: the index-correction-obligates-body-rewrite rule is missing"


def test_script_module_loads_and_exposes_testable_functions():
    chk = _load()
    assert hasattr(chk, "_body_hits")
    assert hasattr(chk, "GENESIS_DIRECTIVE")
    assert hasattr(chk, "STALE_STACK_CLAIMS")


# ── ground truth resolves from the live source (not a hand literal) ─────────────
def test_ground_truth_genesis_matches_constants_py():
    import re

    chk = _load()
    genesis = chk._ground_truth_genesis()
    constants = (ROOT / "lambdas" / "common" / "constants.py").read_text(encoding="utf-8")
    m = re.search(r'EXPERIMENT_START_DATE\s*=\s*"(\d{4}-\d{2}-\d{2})"', constants)
    assert m, "EXPERIMENT_START_DATE literal not found in lambdas/constants.py"
    assert genesis == m.group(1)


# ── the scan is non-vacuous: it fires on the EXACT pre-#1342 defect text ────────
def test_gate_fires_on_the_exact_pre_fix_launch_dates_defect(tmp_path):
    """Verbatim excerpt of project_launch_dates.md's body BEFORE the #1342 fix."""
    chk = _load()
    bad = tmp_path / "project_launch_dates.md"
    bad.write_text(
        "Two dates in the system — only April 1 matters for journey logic:\n\n"
        "- **2026-02-22**: When the platform was built and data collection began.\n"
        "- **2026-04-01**: Official Day 1 of the public experiment. ALL journey_start_date\n"
        "  references should use this date.\n\n"
        '**How to apply:** When adding any new feature that computes "days on journey", '
        '"Week N", or progress from a start date, always use 2026-04-01. Never use '
        "2026-02-22 for user-facing calculations.\n"
    )
    hits = chk._body_hits([bad], "2026-07-19")
    assert hits, "memory-body scan is VACUOUS — it did not flag the exact pre-#1342 'always use 2026-04-01' directive"
    assert any("2026-04-01" in h for h in hits)


def test_gate_fires_on_the_exact_pre_fix_stack_ownership_defect(tmp_path):
    """Verbatim excerpt of reference_site_api_layer_manual_attach.md's body BEFORE the fix."""
    chk = _load()
    bad = tmp_path / "reference_site_api_layer_manual_attach.md"
    bad.write_text(
        "**Current truth (2026-07-07):**\n"
        "- **CDK (cdk/stacks/operational_stack.py) owns the infrastructure** — function "
        "definition, IAM role, env vars, alarms. An Operational stack deploy is safe: it "
        "ships the same package layout as the script.\n"
    )
    hits = chk._body_hits([bad], "2026-07-19")
    assert hits, "memory-body scan is VACUOUS — it did not flag the exact pre-#1342 operational_stack.py ownership claim"
    assert any("serve_stack" in h for h in hits)


def test_gate_passes_the_fixed_launch_dates_body(tmp_path):
    chk = _load()
    good = tmp_path / "project_launch_dates.md"
    good.write_text(
        "The experiment genesis is NOT a fixed date — it is EXPERIMENT_START_DATE in "
        "lambdas/constants.py, re-anchored on every restart. Always read it live, never "
        "hardcode it.\n"
    )
    assert chk._body_hits([good], "2026-07-19") == []


def test_gate_exempts_historically_framed_claims():
    """A line explicitly narrating the OLD claim as retired/obsolete/superseded must not
    re-trip the gate — the corrected file necessarily quotes its own former defect."""
    chk = _load()
    import tempfile

    d = Path(tempfile.mkdtemp())
    hist = d / "hist.md"
    hist.write_text(
        '**Retired claim (superseded by #793, do NOT act on):** "operational_stack.py owns '
        'the infrastructure" was true only 2026-07-07 → 2026-07-08.\n'
    )
    assert chk._body_hits([hist], "2026-07-19") == []


# ── the two known bodies are actually fixed on disk (outside the repo) ──────────
def _memory_dir():
    """DERIVED from the script, never spelled twice.

    This used to hard-code the `-Users-matthewwalker-Documents-Claude-life-platform`
    project key alongside the script's own copy. Claude Code derives that key from the
    checkout's absolute path, so moving the repo (2026-08-30, ~/Documents/Claude → ~/dev)
    re-keys the memory dir — and a second spelling means the repoint can land on the
    script while this test keeps asserting against the old, now-unwritten directory. The
    failure is silent in the worst way: `mem_dir.exists()` goes False and the test
    returns green having verified nothing.
    """
    return _load().DEFAULT_MEMORY_DIR


def test_known_drifted_bodies_are_fixed_if_present():
    """Best-effort: if this machine has the memory dir (it's not part of the repo and CI
    won't have it), assert the two named files no longer trip the gate."""
    mem_dir = _memory_dir()
    if not mem_dir.exists():
        return  # nothing to verify on this machine/CI — the wrap.md gate + fixture tests above are the enforceable part
    chk = _load()
    genesis = chk._ground_truth_genesis()
    targets = [mem_dir / "project_launch_dates.md", mem_dir / "reference_site_api_layer_manual_attach.md"]
    targets = [t for t in targets if t.exists()]
    if not targets:
        return
    hits = chk._body_hits(targets, genesis)
    assert hits == [], "#1342: a known-drifted memory body still trips the gate:\n" + "\n".join(hits)


def test_check_memory_body_facts_cli_runs_clean_or_skips():
    """The script itself must exit 0 — either 'clean' (memory dir present + no drift) or a
    graceful skip (memory dir absent, e.g. CI)."""
    import subprocess
    import sys

    r = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True)
    assert r.returncode == 0, (
        "the memory dir ON THIS MACHINE carries stale facts — this is the gate working, not a\n"
        "broken test. CI has no memory dir and skips. Fix the flagged lines in\n"
        "~/.claude/projects/-Users-matthewwalker-dev-life-platform/memory/ (a `genesis <date>`\n"
        "or `cycle <N> LIVE` token on a line marked LIVE/CURRENT must equal the live\n"
        "constants; if the line is a record of a past cycle, frame it as history — 'was',\n"
        "'superseded'), then re-run.\n\n" + r.stdout + r.stderr
    )


# ── #3539: the STATE tokens (`genesis <date>`, `cycle <N> LIVE`) ──────────────────────
#
# The #1342 rules above match exactly one phrasing, "always use <date>". The memory
# surface does not write its genesis that way any more — it writes STATE, and on
# 2026-09-05 the index said "cycle 16 LIVE, genesis 2026-09-04" against an
# EXPERIMENT_START_DATE of 2026-09-05 while a topic file still said "CURRENT: cycle 13
# LIVE, genesis 2026-08-10", three cycles stale. Neither line was reachable by any rule
# in this gate, and `_scan_memory_files` excluded MEMORY.md outright on the stated
# grounds that the index was "already-guarded" — nothing guarded it.


def _plant(tmp_path, name, body):
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return p


def test_state_rule_fires_on_the_real_2026_09_05_lines(tmp_path):
    """The lines are VERBATIM from the memory surface on the day #3539 was filed — a
    synthetic control alone would not tell you the rule reaches the real corpus."""
    chk = _load()
    planted = [
        _plant(
            tmp_path,
            "MEMORY.md",
            "- [Monday reset](project_monday_reset.md) — **cycle 16 LIVE, genesis 2026-09-04** (future-genesis eve reset 09-03)\n",
        ),
        _plant(
            tmp_path,
            "project_monday_reset.md",
            'description: "Experiment reset tooling (ADR-077) — CURRENT: cycle 13 LIVE, genesis 2026-08-10 (first truth-gated FUTURE genesis)"\n',
        ),
    ]
    hits = chk._state_hits(planted, "2026-09-05", "16")
    joined = "\n".join(hits)
    assert "MEMORY.md:1" in joined and "2026-09-04" in joined, hits
    assert "project_monday_reset.md:1" in joined and "2026-08-10" in joined, hits
    assert "cycle 13" in joined, hits

    # ...and the corrected forms must pass, or the gate forbids its own fix.
    fixed = [
        _plant(tmp_path, "MEMORY.md", "- [Monday reset](project_monday_reset.md) — **cycle 16 LIVE, genesis 2026-09-05**\n"),
        _plant(tmp_path, "project_monday_reset.md", 'description: "reset tooling — CURRENT: cycle 16 LIVE, genesis 2026-09-05"\n'),
    ]
    assert chk._state_hits(fixed, "2026-09-05", "16") == []


def test_state_rule_leaves_the_diary_alone(tmp_path):
    """These files are half ledger and half DIARY. A record of a PAST cycle is true and
    must never red — sweeping every `genesis <date>` token returned 17 hits on the live
    dir, 12 of them history. The currentness marker is the discriminator."""
    chk = _load()
    history = _plant(
        tmp_path,
        "project_session_o.md",
        "Cycle-5 reset executed early with a live pre-start countdown (genesis 2026-07-12) after the stall audits\n"
        "the cycle-15 reset with future genesis 2026-09-01 and the official launch\n"
        "runbook in **#2465** (genesis 2026-08-09, keep-chronicle DATE#2026-08-02)\n"
        "Cycle 15 (genesis 2026-09-01) → **cycle 16, genesis 2026-09-04**, run as a future/eve reset\n",
    )
    assert chk._state_hits([history], "2026-09-05", "16") == []

    # An explicitly historical framing is exempt even WITH a currentness marker.
    retired = _plant(
        tmp_path, "project_old.md", "This was CURRENT: cycle 13 LIVE, genesis 2026-08-10 — superseded by the cycle-16 re-anchor\n"
    )
    assert chk._state_hits([retired], "2026-09-05", "16") == []


def test_the_index_itself_is_in_scope_now(tmp_path):
    """`_scan_memory_files` used to exclude MEMORY.md. It is the first file a session
    reads, and nothing guarded it."""
    chk = _load()
    _plant(tmp_path, "MEMORY.md", "index\n")
    _plant(tmp_path, "project_topic.md", "body\n")
    names = {p.name for p in chk._scan_memory_files(tmp_path)}
    assert names == {"MEMORY.md", "project_topic.md"}


def test_the_cycle_ground_truth_is_derived_not_typed():
    """The needle comes from check_doc_facts._ground_truth() — the SAME discoverer the
    genesis rule uses — so this gate can never hold its own copy of the cycle number.

    Proved by swapping the discoverer's answer: if the gate typed the cycle anywhere, the
    swap would not move it. (#3539's whole point is that a fact restated in a second
    place is a fact with no owner.)"""
    chk = _load()
    assert chk._ground_truth_cycle().isdigit(), "cycle ground truth unresolved"

    chk._TRUTH_CACHE.clear()
    chk._TRUTH_CACHE.update({"experiment_genesis": "2099-12-31", "experiment_cycle": 99})
    try:
        assert chk._ground_truth_cycle() == "99"
        assert chk._ground_truth_genesis() == "2099-12-31"
    finally:
        chk._TRUTH_CACHE.clear()
