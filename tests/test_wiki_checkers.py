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
from datetime import date
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


def test_mcp_manual_zip_tombstones_fire_on_the_prefix_recipe():
    """#1322 non-vacuity (per the #1189 vacuous-scan lesson): the rules added for the
    retired manual MCP zip must FIRE on the exact pre-fix deploy/README.md and
    OPERATIONAL_RUNBOOK.md lines (the recipe staged no lambdas/ tree — a zip built from
    it boot-breaks life-platform-mcp with "No module named 'reading'"), must NOT be
    swallowed by the retirement-line exemption, and must stay quiet on the replacement
    guidance."""
    ts = _load("scripts/check_doc_tombstones.py")
    rules = ts._rules()
    prefix_lines = [
        # deploy/README.md:99 (pre-fix)
        "# ⚠️  NEVER use deploy_lambda.sh for MCP — it strips the mcp/ directory (ADR-031)",
        # deploy/README.md:113 (pre-fix)
        "zip -j $ZIP mcp_server.py mcp_bridge.py",
        # deploy/README.md:108 (pre-fix)
        "**`deploy_lambda.sh` hard-rejects `life-platform-mcp`.** The MCP Lambda is a multi-module package",
        # deploy/OPERATIONAL_RUNBOOK.md:123 (pre-fix)
        "For the MCP Lambda (`life-platform-mcp`), `deploy_lambda.sh` will refuse — it requires the full `mcp/` package.",
    ]
    for line in prefix_lines:
        assert not ts.RETIREMENT_LINE_RE.search(line), f"pre-fix line would be exempted, gate is vacuous: {line}"
        assert any(rx.search(line) for rx, _ in rules), f"no tombstone rule fires on the retired recipe line: {line}"
    # the replacement guidance (the live MCP path) must not trip any live rule.
    good = "MCP Lambda → `bash deploy/deploy_lambda.sh life-platform-mcp mcp_server.py` builds the mcp-shaped full bundle (--mcp)"
    assert not ts.RETIREMENT_LINE_RE.search(good)
    hits = [rx.pattern for rx, _ in rules if rx.search(good)]
    assert not hits, f"replacement guidance trips tombstone rule(s): {hits}"


def test_deploy_docs_scanned_for_tombstones():
    """#1322: the tombstone scanner's live surface includes every top-level deploy/*.md
    (not just README), so the retired recipe can't silently return via the runbook."""
    ts = _load("scripts/check_doc_tombstones.py")
    scanned = {str(p.relative_to(ROOT)) for p in ts._scan_files(include_exempt=False)}
    assert "deploy/README.md" in scanned
    assert "deploy/OPERATIONAL_RUNBOOK.md" in scanned
    # dated/deprecated records stay exempt (history may mention history)…
    assert "deploy/MANIFEST.md" not in scanned
    assert "deploy/V2_ROLLBACK.md" not in scanned
    # …but are still reachable with --all.
    assert "deploy/MANIFEST.md" in {str(p.relative_to(ROOT)) for p in ts._scan_files(include_exempt=True)}


def test_makefile_scanned_for_tombstones():
    """#1323: the Makefile is a second entry-point system (`make <target>`) that can
    route an operator onto a retired script exactly like a stale doc line can — it
    must be on the tombstone scanner's live surface so the build_layer.sh rule (added
    for #781) actually fires on it, instead of the candidate list silently excluding
    it forever."""
    ts = _load("scripts/check_doc_tombstones.py")
    scanned = {str(p.relative_to(ROOT)) for p in ts._scan_files(include_exempt=False)}
    assert "Makefile" in scanned


def test_makefile_tombstone_rule_fires_on_the_prefix_layer_target():
    """Non-vacuity (per the #1189 vacuous-scan lesson): the build_layer.sh rule must
    FIRE on the exact pre-#1323 Makefile line (`layer:` target shelling out to the
    deleted deploy/build_layer.sh), and NOT be swallowed by the retirement-line
    exemption."""
    ts = _load("scripts/check_doc_tombstones.py")
    rules = ts._rules()
    prefix_line = "\tbash deploy/build_layer.sh"
    assert not ts.RETIREMENT_LINE_RE.search(prefix_line), f"pre-fix line would be exempted, gate is vacuous: {prefix_line}"
    assert any(rx.search(prefix_line) for rx, _ in rules), "no tombstone rule fires on the retired build_layer.sh line"
    # the replacement guidance (the live fleet-deploy path) must not trip any live rule.
    good = "\tbash deploy/deploy_fleet.sh"
    hits = [rx.pattern for rx, _ in rules if rx.search(good)]
    assert not hits, f"replacement guidance trips tombstone rule(s): {hits}"


def test_deploy_docs_freshness_ceiling_is_not_vacuous():
    """#1322: check_deploy_docs must FLAG a headerless deploy doc (the exact pre-fix
    deploy/README.md shape) and a canonical doc unverified past the hard ceiling (the
    '14 months stale' class), PASS a freshly verified page, and leave non-canonical
    (superseded/archive) pages freshness-exempt."""
    idx = _load("scripts/check_doc_index.py")
    d = Path(tempfile.mkdtemp())
    # the pre-fix README shape: a "Last updated" line but no status header.
    (d / "README.md").write_text("# Deploy Scripts\n\n> Last updated: 2026-05-24 (v8.1.0)\n", encoding="utf-8")
    # the 14-months-unverified class the issue names.
    (d / "OLD.md").write_text("> **Status:** canonical · **Verified:** 2025-05-18\n\nold\n", encoding="utf-8")
    (d / "FRESH.md").write_text("> **Status:** canonical · **Verified:** 2026-07-18\n\nfresh\n", encoding="utf-8")
    (d / "MANIFEST.md").write_text("> **Status:** superseded · dead\n\ndead\n", encoding="utf-8")
    (d / "NOVERIFY.md").write_text("> **Status:** canonical\n\nno date\n", encoding="utf-8")
    problems, stale = idx.check_deploy_docs(deploy_dir=d, today=date(2026, 7, 18))
    joined = "\n".join(problems)
    assert any("README.md" in p and "missing status header" in p for p in problems), joined
    assert any("OLD.md" in p and "unverified" in p for p in problems), joined
    assert any("NOVERIFY.md" in p and "Verified" in p for p in problems), joined
    assert not any("FRESH.md" in p or "MANIFEST.md" in p for p in problems), joined
    # OLD.md also lands on the advisory stale report.
    assert any(rel == "deploy/OLD.md" for _, rel, _ in stale), stale


def test_live_deploy_docs_pass_the_deploy_gate():
    """After the #1322 fix, the real deploy/*.md surface is header-stamped and fresh."""
    idx = _load("scripts/check_doc_index.py")
    problems, _ = idx.check_deploy_docs()
    assert problems == [], "\n".join(problems)


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


def test_adr_index_flags_unmarked_supersession():
    """#1343 regression guard: a record whose Status is bare 'Active' while a LATER
    record's own body names it with supersedes/amends/retires, and the target carries
    no marker back, must be flagged. Proven RED on a synthetic fixture shaped exactly
    like the pre-fix ADR-013/ADR-027 (retired by ADR-131, still reading 'Active', no
    back-reference) — this is the non-vacuity proof: the guard must actually fire, not
    just exist."""
    gen = _load("scripts/generate_adr_index.py")
    doc = (
        "## ADR-013 — Shared Lambda Layer for Common Modules\n\n"
        "**Status:** Active  \n**Date:** 2026-03-05\nbody with no marker\n\n"
        "## ADR-131: One code-distribution channel\n\n"
        "**Status:** Accepted  \n**Date:** 2026-07-06\n"
        "This decision retires ADR-013 and bundles everything into one channel.\n"
    )
    flags = gen._find_unmarked_supersessions(doc)
    assert len(flags) == 1, flags
    assert "ADR-013" in flags[0] and "ADR-131" in flags[0], flags


def test_adr_index_does_not_flag_a_marked_supersession():
    """The GREEN counterpart: once the target record's own Status field (or body) carries
    a marker, the same citing text no longer flags — this is the fix #1343 applies to the
    real ADR-013/ADR-027/ADR-005 records, proven here on a minimal fixture."""
    gen = _load("scripts/generate_adr_index.py")
    doc = (
        "## ADR-013 — Shared Lambda Layer for Common Modules\n\n"
        "**Status:** Superseded by ADR-131  \n**Date:** 2026-03-05\nbody\n\n"
        "## ADR-131: One code-distribution channel\n\n"
        "**Status:** Accepted  \n**Date:** 2026-07-06\n"
        "This decision retires ADR-013 and bundles everything into one channel.\n"
    )
    assert gen._find_unmarked_supersessions(doc) == []


def test_adr_index_does_not_flag_an_amendment_with_a_body_marker():
    """A record that stays Active but gains an 'Amended by' body note (ADR-005's
    real-world shape after ADR-097) must not be flagged — amending is not retiring, and
    the Status legitimately stays Active."""
    gen = _load("scripts/generate_adr_index.py")
    doc = (
        "## ADR-005 — No GSI on DynamoDB Table\n\n"
        "**Status:** Active  \n**Date:** 2026-02-25\nbody\n\n"
        "**Amended by:** ADR-097 — adds two GSIs for one domain.\n\n"
        "## ADR-097: Two GSIs for the reading domain\n\n"
        "**Status:** Accepted  \n**Date:** 2026-06-29\n"
        "This amends ADR-005 for one domain only.\n"
    )
    assert gen._find_unmarked_supersessions(doc) == []


def test_adr_index_live_tree_has_no_unmarked_supersessions():
    """Non-vacuity in the other direction: the live docs/DECISIONS.md — after the
    #1343 sweep marked ADR-013/ADR-027/ADR-005 — must pass the guard with zero flags."""
    gen = _load("scripts/generate_adr_index.py")
    src = (ROOT / "docs" / "DECISIONS.md").read_text(encoding="utf-8")
    flags = gen._find_unmarked_supersessions(src)
    assert flags == [], flags


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
