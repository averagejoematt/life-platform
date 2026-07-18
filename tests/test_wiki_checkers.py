"""tests/test_wiki_checkers.py — the wiki drift machinery gates a clean repo.

Integration smokes mirroring test_sync_doc_metadata_check.py's repo-HEAD test: each
checker must exit 0 against the current tree. If one reds here, the wiki contract
(docs/CONVENTIONS.md §8) was violated by the change that broke it — fix the docs (or
the rule), don't skip the test.
"""

import ast
import importlib.util
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _run(script, *args):
    return subprocess.run([sys.executable, str(ROOT / script), *args], capture_output=True, text=True)


def _load(script):
    spec = importlib.util.spec_from_file_location("_mod", ROOT / script)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_doc_links_resolve():
    r = _run("scripts/check_doc_links.py")
    assert r.returncode == 0, r.stdout + r.stderr


def test_no_live_tombstone_references():
    r = _run("scripts/check_doc_tombstones.py")
    assert r.returncode == 0, r.stdout + r.stderr


def test_wiki_index_coverage_and_headers():
    r = _run("scripts/check_doc_index.py")
    assert r.returncode == 0, r.stdout + r.stderr


def test_adr_index_current():
    r = _run("scripts/generate_adr_index.py", "--check")
    assert r.returncode == 0, r.stdout + r.stderr


def test_adr_index_parses_h3_records_and_folds_amendments():
    """#1321: h3-headed records (the ADR-046..057 class) are real records; a
    `### ADR-NNN Amendment (...)` heading folds into its parent record — never a
    distinct index row (it would duplicate the parent's number)."""
    gen = _load("scripts/generate_adr_index.py")
    doc = (
        "## ADR-001 — First\n**Status:** Active\n**Date:** 2026-01-01\nbody\n"
        "### ADR-002 — H3 record\n**Status:** Active\n**Date:** 2026-01-02\nbody\n"
        "### ADR-002 Amendment (2026-01-03): a tweak\namendment body\n"
        "## ADR-003: Third\n**Status:** Accepted\n**Date:** 2026-01-04\nbody\n"
    )
    recs = gen._records(doc)
    assert [r["num"] for r in recs] == ["001", "002", "003"]
    assert recs[1]["title"] == "H3 record"
    # the amendment stays inside the parent's body: the parent keeps its own date,
    # and no fourth row appears.
    assert recs[1]["date"] == "2026-01-02"


def test_adr_index_record_parse_agrees_with_permissive_scan():
    """#1321 regression guard: on the live corpus the record parse must see every
    distinct ADR number a permissive any-level heading scan finds (the pre-fix
    `##`-only parse missed the 12 h3-headed records ADR-046..057 while --check
    certified the index current)."""
    gen = _load("scripts/generate_adr_index.py")
    src = (ROOT / "docs" / "DECISIONS.md").read_text(encoding="utf-8")
    nums = [r["num"] for r in gen._records(src)]
    for n in range(46, 58):
        assert f"{n:03d}" in nums, f"ADR-{n:03d} (h3-headed) missing from the parsed records (#1321)"
    assert len(nums) == len(set(nums)), "duplicate ADR record rows"
    assert set(nums) == set(gen._ANY_ADR_HEADING_RE.findall(src)), "record parse disagrees with the permissive heading scan (#1321)"


def test_doc_facts_clean():
    r = _run("scripts/check_doc_facts.py")
    assert r.returncode == 0, r.stdout + r.stderr


def test_doc_facts_gate_is_not_vacuous():
    """The scanner must actually flag a stale value — a gate that passes on anything
    is worse than none (the lesson from the shared-layer scan that matched nothing)."""
    facts = _load("scripts/check_doc_facts.py")
    # exact fact: any deviation is drift; the true value is not.
    assert facts._off(127, 64, 0.0, approx=False) is True
    assert facts._off(64, 64, 0.0, approx=False) is False
    # soft fact honors the ~approx marker (allows an honest "~3,600" vs 3,644)…
    assert facts._off(3600, 3644, 0.18, approx=True) is False
    # …but still catches the 2.9x-stale class (1,217 vs 3,644).
    assert facts._off(1217, 3644, 0.18, approx=True) is True
    # the "python3 tests/" glue class must NOT match a test-count pattern.
    joined = [p for _, pats, _ in facts.FACT_SPECS for p in pats if "tests?" in p]
    assert joined, "expected test_count patterns to exist"
    assert not any(re.search(p, "run python3 tests/visual_qa.py now") for p in joined)
    # a real "N MCP tools" claim IS caught.
    tool_pats = [p for key, pats, _ in facts.FACT_SPECS if key == "tool_count" for p in pats]
    assert any(re.search(p, "the server exposes 143 MCP tools") for p in tool_pats)


def test_experiment_anchor_ground_truth_is_discovered():
    """#1235: genesis + cycle resolve from the real source (constants.py / CYCLE_GENESES),
    not a stale literal — proves the fact the anchor gate polices is live."""
    facts = _load("scripts/check_doc_facts.py")
    truth = facts._ground_truth()
    constants = (ROOT / "lambdas" / "constants.py").read_text(encoding="utf-8")
    m = re.search(r'EXPERIMENT_START_DATE\s*=\s*"(\d{4}-\d{2}-\d{2})"', constants)
    assert m, "EXPERIMENT_START_DATE literal not found in lambdas/constants.py"
    assert truth["experiment_genesis"] == m.group(1)
    assert isinstance(truth["experiment_cycle"], int) and truth["experiment_cycle"] >= 6


def test_experiment_anchor_gate_is_not_vacuous():
    """#1235 (per the #1189 vacuous-scan lesson): the anchor scan must FLAG a stale
    'currently <genesis>, cycle N' claim, PASS the true value, and EXEMPT the phrasings
    that legitimately name other dates/cycles (history, synthetic drill records)."""
    facts = _load("scripts/check_doc_facts.py")
    d = Path(tempfile.mkdtemp())

    # the EXACT #1235 defect shape (a full reset stale) — must be caught, both facts.
    bad = d / "stale.md"
    bad.write_text("anchored `constants.py` (currently **2026-07-12**, cycle 5 — a future genesis)\n")
    hits = facts._anchor_hits([bad], "2026-07-13", 6)
    assert hits, "anchor scan is VACUOUS — it did not flag the planted stale genesis/cycle"
    joined = "\n".join(hits)
    assert "2026-07-12" in joined and "claims 5" in joined

    # the current (true) anchor — must pass.
    good = d / "ok.md"
    good.write_text("anchored (currently **2026-07-13**, cycle 6 — a future genesis)\n")
    assert facts._anchor_hits([good], "2026-07-13", 6) == []

    # a HISTORICAL-framed line naming an old cycle/genesis — must NOT be flagged.
    hist = d / "hist.md"
    hist.write_text("the tombstoned cycle-5 brief was leaked; earlier genesis was 2026-07-12\n")
    assert facts._anchor_hits([hist], "2026-07-13", 6) == []

    # a synthetic drill record (bare 'genesis <date>', not the 'currently' anchor) — exempt.
    drill = d / "drill.md"
    drill.write_text("Drill record 2026-07-12 (genesis day, synthetic genesis 2026-08-02): dry-run\n")
    assert facts._anchor_hits([drill], "2026-07-13", 6) == []


def test_experiment_anchor_clean_on_current_tree():
    """After the fix, no live doc states a stale experiment genesis/cycle as current."""
    facts = _load("scripts/check_doc_facts.py")
    truth = facts._ground_truth()
    hits = facts._anchor_hits(facts._scan_files(), truth["experiment_genesis"], truth["experiment_cycle"])
    assert hits == [], "stale experiment anchor still in a live doc:\n" + "\n".join(hits)


def test_cdk_cron_map_discovers_from_source():
    """#1205: the cron gate's ground truth is LIVE-discovered from cdk/stacks/*.py, not a
    pinned literal — re-derive two schedules (one per stack file) straight from source and
    assert the map agrees, proving the fact the gate polices tracks the CDK."""
    facts = _load("scripts/check_doc_facts.py")
    cmap = facts._cdk_cron_map()
    assert cmap, "CDK cron map is empty — discovery broke"
    compute = (ROOT / "cdk" / "stacks" / "compute_stack.py").read_text(encoding="utf-8")
    m = re.search(r'function_name="character-sheet-compute".*?schedule="(cron\([^"]*\))"', compute, re.S)
    assert m, "could not locate character-sheet-compute schedule in compute_stack.py"
    assert cmap.get("character-sheet-compute") == m.group(1)
    email = (ROOT / "cdk" / "stacks" / "email_stack.py").read_text(encoding="utf-8")
    mb = re.search(r'function_name="daily-brief".*?schedule="(cron\([^"]*\))"', email, re.S)
    assert mb, "could not locate daily-brief schedule in email_stack.py"
    assert cmap.get("daily-brief") == mb.group(1)


def test_cron_gate_is_not_vacuous():
    """#1205 (per the #1189 vacuous-scan lesson): the cron scan must FLAG a doc cron that
    disagrees with the CDK, PASS the matching value, and EXEMPT the shapes that legitimately
    differ (history, hyphen-suffixed rule names, ambiguous multi-cron lines)."""
    facts = _load("scripts/check_doc_facts.py")
    d = Path(tempfile.mkdtemp())
    cdk = {"character-sheet-compute": "cron(30 16 * * ? *)", "wednesday-chronicle": "cron(0 15 ? * WED *)"}

    # the EXACT #1205 defect: a stale cron quoted next to the function name — must be caught.
    bad = d / "stale.md"
    bad.write_text("| Character Sheet Compute | `character-sheet-compute` | `cron(35 17 * * ? *)` | 10:35 AM |\n")
    hits = facts._cron_hits([bad], cdk)
    assert hits, "cron scan is VACUOUS — it did not flag the planted stale cron"
    assert "character-sheet-compute" in hits[0] and "cron(30 16 * * ? *)" in hits[0]

    # the correct (current) cron — must pass.
    good = d / "ok.md"
    good.write_text("| Character Sheet Compute | `character-sheet-compute` | `cron(30 16 * * ? *)` | 09:30 AM |\n")
    assert facts._cron_hits([good], cdk) == []

    # hyphen-aware: `wednesday-chronicle` must NOT match inside `wednesday-chronicle-schedule`,
    # so a line naming only the suffixed rule form is skipped (no false positive).
    suffixed = d / "suffixed.md"
    suffixed.write_text("`wednesday-chronicle-schedule` ENABLED (`cron(59 59 ? * WED *)`)\n")
    assert facts._cron_hits([suffixed], cdk) == []

    # a HISTORICAL-framed line stating an old cron — must NOT be flagged.
    hist = d / "hist.md"
    hist.write_text("`character-sheet-compute` was `cron(35 17 * * ? *)` before Phase 3.1\n")
    assert facts._cron_hits([hist], cdk) == []

    # an ambiguous line with two crons — skipped (the table shape is one cron per row).
    ambig = d / "ambig.md"
    ambig.write_text("`character-sheet-compute` `cron(35 17 * * ? *)` and `cron(30 16 * * ? *)`\n")
    assert facts._cron_hits([ambig], cdk) == []


def test_cron_gate_clean_on_current_tree():
    """After the fix, no live doc quotes a cron that disagrees with the CDK schedule."""
    facts = _load("scripts/check_doc_facts.py")
    hits = facts._cron_hits(facts._scan_files(), facts._cdk_cron_map())
    assert hits == [], "a live doc quotes a cron that disagrees with the CDK schedule:\n" + "\n".join(hits)


def test_og_source_count_ground_truth_is_the_registry():
    """#1260: the reader-facing card count resolves from lambdas/source_registry.py's
    SOURCE_REGISTRY (AST-counted), not a hand-maintained literal — proves the fact the og
    scan polices is live and self-correcting."""
    facts = _load("scripts/check_doc_facts.py")
    truth = facts._registry_source_count()
    src = (ROOT / "lambdas" / "source_registry.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    counted = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "SOURCE_REGISTRY" and isinstance(node.value, ast.Dict):
                    counted = len(node.value.keys)
    assert counted is not None and counted >= 1
    assert truth == counted, f"registry discoverer ({truth}) disagrees with an independent AST count ({counted})"


def test_og_source_count_gate_is_not_vacuous():
    """#1260 (per the #1189 vacuous-scan lesson): the og scan must FLAG the exact pre-fix
    '25 data sources' literal, PASS the fixed f-string form (no numeric literal), and EXEMPT
    the shapes that legitimately differ (full-line comments, history)."""
    facts = _load("scripts/check_doc_facts.py")
    truth = facts._registry_source_count()
    d = Path(tempfile.mkdtemp())

    # the EXACT #1260 defect: a hardcoded stale count in a reader-facing draw.text — caught.
    bad = d / "og_image_lambda.py"
    bad.write_text('    draw.text((48, 180), "One man. 25 data sources. Total transparency.", fill=MUTED)\n')
    hits = facts._og_source_hits([bad], truth)
    assert hits, "og-source scan is VACUOUS — it did not flag the planted stale '25 data sources'"
    assert "claims 25 data sources" in hits[0] and f"truth is {truth}" in hits[0]

    # the fixed card: an f-string interpolates the count, so no numeric literal is present — clean.
    good = d / "og_good.py"
    good.write_text('    draw.text((48, 180), f"One man. {n_sources} data sources. Total transparency.")\n')
    assert facts._og_source_hits([good], truth) == []

    # a value that happens to EQUAL the registry truth — not a drift, so not flagged.
    okval = d / "og_okval.py"
    okval.write_text(f'    draw.text((0, 0), "One man. {truth} data sources.")\n')
    assert facts._og_source_hits([okval], truth) == []

    # a full-line comment / HISTORICAL-framed line naming the old count — exempt.
    hist = d / "og_hist.py"
    hist.write_text('# the card used to say "25 data sources" — was 25, now derived from the registry\n')
    assert facts._og_source_hits([hist], truth) == []


def test_og_source_count_clean_on_current_tree():
    """After the fix, no og_*.py card hardcodes a data-source count that disagrees with the
    registry (the evidence pointer no longer reproduces)."""
    facts = _load("scripts/check_doc_facts.py")
    truth = facts._registry_source_count()
    hits = facts._og_source_hits(facts._scan_og_files(), truth)
    assert hits == [], "an og card still hardcodes a stale data-source count:\n" + "\n".join(hits)
