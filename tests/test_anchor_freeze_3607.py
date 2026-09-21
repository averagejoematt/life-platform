"""tests/test_anchor_freeze_3607.py — the sealed review anchors, with four planted must-fails.

WHY FOUR CONTROLS AND NOT ONE ASSERTION
────────────────────────────────────────
A freeze mechanism with no must-fail is exactly the class the 2026-09-05 forensic RCA is
about: a large majority of this platform's gates have never been shown able to fail, and a
gate nobody watched fail is a green light wired to nothing. So each half of #3607 is proved
by a planted failure AND its positive control — the control is what shows the red came from
the plant and not from the fixture being malformed:

  1. LOOSENING CONTROL   — a fixture with one clause weakened ('every' -> 'the sampled', an
     evidence requirement deleted, a placeholder turned back into prose) must red the
     tightening-only diff; the same fixture TIGHTENED must pass. And the owner-signed
     escape hatch must convert a red into a recorded decision — signed by anyone else, it
     stays red.
  2. STALE-LITERAL CONTROL — a fixture clause carrying the four literals that actually
     rotted in place ($85, cycle-6, a hand-typed page count, a lane budget in seconds) must
     red; the same clause written with placeholders must pass. This is the control that
     would have caught all four live stale literals.
  3. VACUOUS-PASS CONTROL — a clause whose evidence is deliberately absent must resolve
     UNOBSERVED, never MET, and must cap the lens below A. This is the property that
     distinguishes a bar from a shrug: six clauses on the 2026-09-05 baseline passed by
     silence, and none of them could have failed.
  4. HASH CONTROL — mutating ANCHORS.json without re-stamping the sibling must red, and
     `load_anchors()` must REFUSE (fail-closed, the prereg seal's posture), not warn.

The live half — the real committed artifact verifies, satisfies its schema, resolves every
placeholder it declares, and is wired into the review spine — runs against this tree.

Every mutation happens in a tmp_path copy of the two files. The real artifact is never
written by this suite, so no sibling test that sweeps the tree can see a half-mutated seal.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import shutil
import sys
from datetime import date

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if os.path.join(REPO, "scripts") not in sys.path:
    sys.path.insert(0, os.path.join(REPO, "scripts"))

_SPEC = importlib.util.spec_from_file_location("review_anchor_seal", os.path.join(REPO, "scripts", "review_anchor_seal.py"))
assert _SPEC and _SPEC.loader
ras = importlib.util.module_from_spec(_SPEC)
# Registered BEFORE exec: `@dataclass` resolves annotations through
# `sys.modules[cls.__module__]`, so a spec-loaded module carrying dataclasses fails at
# import time if it is not in sys.modules first.
sys.modules["review_anchor_seal"] = ras
_SPEC.loader.exec_module(ras)


# ── fixtures ──────────────────────────────────────────────────────────────────
def _clause(cid, text, evidence):
    return {"id": cid, "text": text, "evidence": evidence}


def _doc(clauses_a=None):
    """A minimal, schema-valid two-level artifact in the real file's shape."""
    a = clauses_a or [
        _clause(
            "demo.A.1",
            "Every live surface resolves inside the $${ceiling}/mo envelope.",
            "the governor's own value for the day of the run, quoted.",
        ),
        _clause("demo.A.2", "No page contradicts another page's account of the same week.", "the two surfaces quoted side by side."),
    ]
    return {
        "version": "1.0.0",
        "frozen_at": "2026-09-20",
        "frozen_by": "#3607 fixture",
        "loosenings": [],
        "records": [
            {
                "lens": "demo",
                "title": "Demo lens",
                "anchors": {
                    "A": a,
                    "C": [
                        _clause(
                            "demo.C.1",
                            "The surface renders but one monitoring path is silently dead.",
                            "the read that shows it produces nothing.",
                        )
                    ],
                    "F": [_clause("demo.F.1", "The surface is dishonest about what it knows.", "the served response, quoted.")],
                },
                "frozen_at": "2026-09-20",
                "frozen_by": "#3607 fixture",
                "supersedes_sha": None,
                "supersedes_note": "fixture",
                "derived_fields": sorted({p for c in a for p in ras.PLACEHOLDER_RE.findall(c["text"] + " " + c["evidence"])}),
                "proposed_extensions": [],
            }
        ],
    }


def _sealed_copy(tmp_path):
    """The REAL artifact + its seal, copied into a throwaway repo root."""
    root = tmp_path / "repo"
    (root / "docs" / "reviews" / "anchors").mkdir(parents=True)
    for rel in (ras.ANCHORS_REL, ras.SEAL_REL):
        shutil.copyfile(os.path.join(REPO, rel), root / rel)
    return str(root)


def _write(root, doc, reseal=True):
    path = os.path.join(root, ras.ANCHORS_REL)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    if reseal:
        ras.write_seal(root)
    return root


# ══════════════════════════════════════════════════════════════════════════════
# CONTROL 1 — LOOSENING. The ratchet must red on a weakened clause.
# ══════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize(
    "mutate,expect_kind",
    [
        (lambda c: c.update(text=c["text"].replace("Every", "The sampled")), "CLAUSE-WEAKENED"),
        (lambda c: c.update(evidence="quoted."), "EVIDENCE-RELAXED"),
        (lambda c: c.update(text="Every live surface resolves inside the monthly envelope."), "DERIVATION-DROPPED"),
    ],
    ids=["quantifier-weakened", "evidence-deleted", "placeholder-back-to-prose"],
)
def test_MUSTFAIL_a_weakened_clause_reds_the_tightening_only_diff(mutate, expect_kind):
    old = _doc()
    new = copy.deepcopy(old)
    mutate(new["records"][0]["anchors"]["A"][0])
    findings = ras.freeze_diff(old, new)
    assert findings, f"the {expect_kind} plant produced no finding — the ratchet is asleep"
    assert expect_kind in {f.kind for f in findings}, [f.line() for f in findings]


def test_MUSTFAIL_a_removed_clause_and_a_removed_lens_both_red():
    old = _doc()
    dropped = copy.deepcopy(old)
    dropped["records"][0]["anchors"]["A"].pop()
    assert "CLAUSE-REMOVED" in {f.kind for f in ras.freeze_diff(old, dropped)}
    gone = copy.deepcopy(old)
    gone["records"] = []
    assert "LENS-REMOVED" in {f.kind for f in ras.freeze_diff(old, gone)}


def test_POSITIVE_CONTROL_a_tightened_clause_passes_the_same_diff():
    """The control that proves the red above came from the plant: the same machinery, an
    edit that raises the bar, and no finding."""
    old = _doc()
    new = copy.deepcopy(old)
    clause = new["records"][0]["anchors"]["A"][0]
    clause["text"] += " Every exception must be named and dated before the run starts."
    clause["evidence"] += " Every exception is cited at file:line, never inferred."
    new["records"][0]["anchors"]["A"].append(
        _clause("demo.A.9", "No clause may be graded without a citation.", "the citation, quoted per clause.")
    )
    assert ras.freeze_diff(old, new) == [], [f.line() for f in ras.freeze_diff(old, new)]


def test_a_loosening_needs_an_OWNER_SIGNED_dated_line_and_nothing_else_will_do():
    old = _doc()
    new = copy.deepcopy(old)
    new["records"][0]["anchors"]["A"][0]["text"] = "The sampled live surfaces resolve inside the $${ceiling}/mo envelope."
    assert ras.unsigned_loosenings(old, new, REPO), "an unsigned weakening must red"

    owner = ras.owner_login(REPO)
    new["loosenings"] = [
        {"clauses": ["demo.A.1"], "why": "the full sweep is priced out of this cadence", "signed_by": owner, "signed_on": "2026-09-20"}
    ]
    assert ras.unsigned_loosenings(old, new, REPO) == [], "an owner-signed dated loosening is a recorded decision, not a red"

    for bad in (
        {"clauses": ["demo.A.1"], "why": "because", "signed_by": "some-agent", "signed_on": "2026-09-20"},
        {"clauses": ["demo.A.1"], "why": "because", "signed_by": owner, "signed_on": "whenever"},
        {"clauses": ["demo.A.1"], "why": "", "signed_by": owner, "signed_on": "2026-09-20"},
    ):
        new["loosenings"] = [bad]
        assert ras.unsigned_loosenings(old, new, REPO), f"a non-signature must not buy a loosening: {bad}"


def test_the_signed_loosening_appears_in_the_review_header(tmp_path):
    """A loosening the reader never sees is a loosening that happened in private."""
    owner = ras.owner_login(REPO)
    doc = _doc()
    doc["loosenings"] = [{"clauses": ["demo.A.1"], "why": "priced out of this cadence", "signed_by": owner, "signed_on": "2026-09-20"}]
    root = _write(str(tmp_path / "repo"), doc)
    os.makedirs(os.path.join(root, "deploy"), exist_ok=True)
    shutil.copyfile(os.path.join(REPO, "deploy", "github_posture.json"), os.path.join(root, "deploy", "github_posture.json"))
    block = ras.header_block(root, ctx={"ssm_client": _BrokenSSM()})
    assert "OWNER-SIGNED LOOSENINGS IN FORCE" in block and "demo.A.1" in block and owner in block


# ══════════════════════════════════════════════════════════════════════════════
# CONTROL 2 — STALE LITERAL. The four numbers that actually rotted in place.
# ══════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize(
    "text",
    [
        "all inside the solo-operator $85/mo envelope with no added standing machinery.",
        "Every live narrative surface tells one coherent cycle-6 story.",
        "the floor holds when MEASURED across the whole page registry (89 pages).",
        "the deploy-critical lane runs green offline in 90 seconds.",
    ],
    ids=["ceiling-85", "cycle-6", "89-pages", "lane-90s"],
)
def test_MUSTFAIL_a_bare_literal_inside_an_anchor_reds_the_freeze(text):
    assert ras.bare_literals(text), f"a hand-typed magnitude passed the derivation guard: {text!r}"
    doc = _doc([_clause("demo.A.1", text, "quoted at file:line, with every source named.")])
    assert any("bare literal" in p for p in ras.schema_problems(doc)), ras.schema_problems(doc)


def test_POSITIVE_CONTROL_the_same_clauses_with_placeholders_pass():
    """Each stale literal, rewritten as the placeholder that derives it — no findings."""
    clauses = [
        _clause("demo.A.1", "all inside the solo-operator $${ceiling}/mo envelope.", "the governor's own value for the day of the run."),
        _clause(
            "demo.A.2",
            "Every live narrative surface tells one coherent cycle-${cycle} story.",
            "the cycle read from its own source at run time.",
        ),
        _clause(
            "demo.A.3",
            "the floor holds when MEASURED across the whole registry (${page_count} pages).",
            "the measured size per node per page.",
        ),
        _clause(
            "demo.A.4",
            "the required lane runs green offline within ${lane_budget} seconds.",
            "the lane's own wall-clock emission beside the written figure.",
        ),
    ]
    for clause in clauses:
        assert ras.bare_literals(clause["text"]) == []
    assert ras.schema_problems(_doc(clauses)) == []


def test_reference_tokens_are_not_magnitudes_and_the_guard_knows_the_difference():
    """A guard that flags any digit is a guard nobody can satisfy. An ADR number, an issue
    reference, a success criterion, a status code and a service name all name a THING —
    none of them can go stale the way a threshold does."""
    for ok in (
        "the ADR-063/133 ceiling at the chokepoint",
        "reproduced on #3607 and extended by #3603",
        "target sizes meet WCAG 2.2 SC 2.5.8 as the hard floor",
        "sensitive prefixes return HTTP 403 or HTTP 404",
        "exactly the ADR-097-sanctioned GSI set, S3 origin, us-west-2",
    ):
        assert ras.bare_literals(ok) == [], ok
    for bad in ("within 72 hours of the probe", "at least 6 scored passages", "the 44px floor"):
        assert ras.bare_literals(bad), bad


def test_every_placeholder_in_the_registry_has_a_stated_source_and_resolves_or_says_why():
    resolutions = ras.resolve_all(ctx={"ssm_client": _BrokenSSM()})
    assert set(resolutions) == set(ras.RESOLVERS)
    for name, res in resolutions.items():
        assert ras.RESOLVERS[name][1], f"${{{name}}} has no stated derivation"
        if name == "cycle":
            assert not res.observed and "UNOBSERVED" in res.reason, "the SSM-backed placeholder must never guess offline"
        else:
            assert res.observed, f"${{{name}}} did not resolve offline: {res.reason}"
            assert res.source, f"${{{name}}} resolved with no cited source"


# ══════════════════════════════════════════════════════════════════════════════
# CONTROL 3 — VACUOUS PASS. Silence resolves UNOBSERVED and blocks an A.
# ══════════════════════════════════════════════════════════════════════════════
def test_MUSTFAIL_an_unsamplable_clause_is_UNOBSERVED_and_caps_the_lens_below_A():
    record = _doc()["records"][0]
    all_met = [ras.ClauseVerdict(c["id"], ras.MET, citation="live fetch 2026-09-20") for c in ras.clauses_for(record)]
    assert ras.lens_grade_ceiling(record, all_met).ceiling == "A"

    silent = list(all_met)
    silent[0] = ras.ClauseVerdict(silent[0].clause_id, ras.UNOBSERVED, reason="every series on this surface is an empty array today")
    grading = ras.lens_grade_ceiling(record, silent)
    assert grading.ceiling != "A", "a lens with an UNOBSERVED clause was graded A — silence read as a pass"
    assert grading.unobserved == [silent[0].clause_id]
    assert grading.problems == []


def test_a_MET_with_no_citation_is_rejected_outright():
    """The vacuous pass's other face: a grader may not assert MET into the void."""
    record = _doc()["records"][0]
    verdicts = [ras.ClauseVerdict(c["id"], ras.MET, citation="") for c in ras.clauses_for(record)]
    problems = ras.validate_verdicts(record, verdicts)
    assert problems and all("no citation" in p for p in problems)


def test_an_ungraded_clause_is_a_problem_not_a_pass():
    record = _doc()["records"][0]
    clauses = ras.clauses_for(record)
    verdicts = [ras.ClauseVerdict(c["id"], ras.MET, citation="cited") for c in clauses[:-1]]
    problems = ras.validate_verdicts(record, verdicts)
    assert any(clauses[-1]["id"] in p and "ungraded" in p for p in problems)


def test_a_FAILED_clause_caps_the_row_below_an_UNOBSERVED_one():
    record = _doc()["records"][0]
    verdicts = [ras.ClauseVerdict(c["id"], ras.MET, citation="cited") for c in ras.clauses_for(record)]
    verdicts[0] = ras.ClauseVerdict(verdicts[0].clause_id, ras.FAILED, citation="live response contradicts the clause")
    assert ras.lens_grade_ceiling(record, verdicts).ceiling == "B+"


def test_a_proposed_extension_does_not_bind_the_run_that_wrote_it():
    """The extension rule: two grades per lens, and the run has to be able to NAME the
    clause that moved the row."""
    doc = _doc()
    record = doc["records"][0]
    record["proposed_extensions"] = [
        {
            "id": "demo.A.p1",
            "anchor": "A",
            "text": "Every hook is sampled on every day the cycle has reached.",
            "evidence": "the matrix enumerated, cell by cell.",
            "proposed_by_run": "wf_demo_run",
            "proposed_on": "2026-09-20",
        }
    ]
    frozen_clauses = ras.clauses_for(record)
    assert "demo.A.p1" not in {c["id"] for c in frozen_clauses}, "a proposal leaked into the frozen set"

    frozen_verdicts = [ras.ClauseVerdict(c["id"], ras.MET, citation="cited") for c in frozen_clauses]
    frozen = ras.lens_grade_ceiling(record, frozen_verdicts)
    assert frozen.ceiling == "A"

    with_proposed = list(frozen_verdicts) + [
        ras.ClauseVerdict("demo.A.p1", ras.UNOBSERVED, reason="the cycle has not reached those days", proposed=True)
    ]
    advisory = ras.lens_grade_ceiling(record, with_proposed, include_proposed=True)
    assert advisory.ceiling == "A-" and advisory.problems == []
    assert ras.rows_moved_by(record, frozen, advisory) == ["demo.A.p1"]


def test_a_clause_whose_placeholder_is_unobservable_renders_as_UNOBSERVED_never_as_a_number():
    resolutions = ras.resolve_all(["cycle"], ctx={"ssm_client": _BrokenSSM()})
    rendered, unresolved = ras.render("one coherent cycle-${cycle} story", resolutions)
    assert unresolved == ["cycle"] and "UNOBSERVED" in rendered
    assert not any(ch.isdigit() for ch in rendered), "an unobservable placeholder produced a number — that is a guess"


# ══════════════════════════════════════════════════════════════════════════════
# CONTROL 4 — HASH. Fail-closed against an unsealed bar.
# ══════════════════════════════════════════════════════════════════════════════
def test_MUSTFAIL_mutating_the_artifact_without_resealing_reds_and_the_review_refuses(tmp_path):
    root = _sealed_copy(tmp_path)
    assert ras.verify_seal(root) == [], "the copied artifact should verify before the plant"
    before = ras.sha256_of(os.path.join(root, ras.ANCHORS_REL))

    data = ras.load_anchors_unchecked(root)
    data["records"][0]["anchors"]["A"][0]["text"] = "Anything at all."
    _write(root, data, reseal=False)
    after = ras.sha256_of(os.path.join(root, ras.ANCHORS_REL))
    assert before != after, "the plant did not change the bytes — a green here would mean nothing"

    problems = ras.verify_seal(root)
    assert problems and any("SEAL MISMATCH" in p for p in problems), problems
    with pytest.raises(ras.AnchorsUnsealed):
        ras.load_anchors(root)
    assert "SEAL DOES NOT VERIFY" in ras.header_block(root, ctx={"ssm_client": _BrokenSSM()})


def test_a_missing_seal_sibling_is_also_fail_closed(tmp_path):
    root = _sealed_copy(tmp_path)
    os.remove(os.path.join(root, ras.SEAL_REL))
    assert any("no seal sibling" in p for p in ras.verify_seal(root))
    with pytest.raises(ras.AnchorsUnsealed):
        ras.load_anchors(root)


def test_POSITIVE_CONTROL_a_deliberate_reseal_restores_the_verdict(tmp_path):
    root = _sealed_copy(tmp_path)
    data = ras.load_anchors_unchecked(root)
    data["records"][0]["anchors"]["A"][0]["text"] += " Every exception is named."
    _write(root, data, reseal=True)
    assert ras.verify_seal(root) == []


def test_the_seal_hashes_the_bytes_not_a_reserialization(tmp_path):
    """A seal computed over `json.dumps(json.load(f))` verifies a shape, not a file — a
    whitespace-only edit would pass it. This one must not."""
    root = _sealed_copy(tmp_path)
    path = os.path.join(root, ras.ANCHORS_REL)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write("\n")
    assert any("SEAL MISMATCH" in p for p in ras.verify_seal(root))


# ══════════════════════════════════════════════════════════════════════════════
# THE LIVE HALF — the real committed artifact
# ══════════════════════════════════════════════════════════════════════════════
def test_the_committed_artifact_verifies_against_its_sibling_and_satisfies_the_contract():
    assert ras.verify_seal(REPO) == [], ras.verify_seal(REPO)
    assert ras.schema_problems(ras.load_anchors(REPO)) == [], ras.schema_problems(ras.load_anchors_unchecked(REPO))


def test_the_artifact_covers_every_lens_the_newest_baseline_graded():
    """The SET, not the specimen: a lens that is graded but has no sealed anchor is graded
    against nothing, which is where all seventeen rows were before this file existed."""
    with open(os.path.join(REPO, "docs", "reviews", "fullreview_grades_2026-09-05.json"), encoding="utf-8") as fh:
        baseline = json.load(fh)
    graded = set(baseline["lenses"])
    sealed = {r["lens"] for r in ras.load_anchors(REPO)["records"]}
    assert graded - sealed == set(), f"graded lenses with no sealed anchor: {sorted(graded - sealed)}"


def test_every_committed_clause_carries_an_id_an_evidence_requirement_and_no_bare_literal():
    for record in ras.load_anchors(REPO)["records"]:
        for clause in ras.clauses_for(record, include_proposed=True):
            assert clause["id"].startswith(record["lens"] + ".")
            assert clause["evidence"].strip(), f"{clause['id']} has no evidence requirement"
            assert ras.bare_literals(clause["text"]) == [], clause["id"]


def test_the_first_seal_has_no_predecessor_and_says_so():
    for record in ras.load_anchors(REPO)["records"]:
        assert record["supersedes_sha"] is None and record["supersedes_note"], record["lens"]
        assert record["frozen_at"] and record["frozen_by"]


def test_the_review_spine_loads_the_artifact_and_prints_its_hash():
    """The dead-man. If the spine stops naming this module, the hash stops appearing in the
    report header and nobody can tell whether the bar moved or the platform did."""
    with open(os.path.join(REPO, ".claude", "skills", "review", "SKILL.md"), encoding="utf-8") as fh:
        spine = fh.read()
    assert "scripts/review_anchor_seal.py" in spine, "the review spine no longer loads the sealed anchors"
    assert ras.ANCHORS_REL in spine
    assert "--header" in spine and "sha256" in spine, "the spine must print the artifact's hash in the report header"


def test_the_cli_verify_exits_zero_on_the_committed_tree():
    assert ras.main(["--verify"]) == 0


def test_the_tightening_diff_against_the_committed_predecessor_is_clean():
    """Run the ratchet the way CI will: this tree's artifact against the artifact on main.
    Before the first seal lands there is no predecessor, and the diff says so rather than
    inventing one."""
    old = ras.anchors_at_ref("origin/main")
    if old is None:
        pytest.skip("no ANCHORS.json on origin/main yet — this is the first seal")
    assert ras.unsigned_loosenings(old, ras.load_anchors(REPO), REPO) == []


class _BrokenSSM:
    """An SSM client that cannot answer — the offline case, without touching the network."""

    def get_parameter(self, **_kwargs):
        raise RuntimeError("no credentials in this environment")


def test_the_cycle_resolver_never_guesses_and_never_raises():
    res = ras._resolve_cycle({"ssm_client": _BrokenSSM()})
    assert res.observed is False and res.value is None
    assert "never a guess" in res.reason


def test_the_ceiling_resolver_reuses_the_synth_time_parser_rather_than_a_second_one():
    """One derivation, two consumers: the AWS Budgets backstop and this anchor read the same
    number out of the governor source. A second parser is how two numbers start disagreeing."""
    spec = importlib.util.spec_from_file_location("_bc_for_test", os.path.join(REPO, "scripts", "budget_ceilings.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert ras._resolve_ceiling({}).value == mod.budget_amount_usd()


def test_the_cycle_day_resolver_tracks_the_genesis_constant():
    res = ras._resolve_cycle_day({"today": date.fromisoformat("2026-09-06")})
    assert res.observed and res.value == 1
