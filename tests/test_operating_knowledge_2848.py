"""tests/test_operating_knowledge_2848.py — #2848: the migrated operating knowledge stays true.

#2848 moved the durable half of the operator's private review-discipline memory into
`docs/OPERATING_DISCIPLINE.md`, and named the artifacts a memoryless session needs in
`docs/ONBOARDING.md`'s "Cold Start" section. Both are prose, and prose rots in two
specific ways this file catches:

1. **A cited artifact stops existing** (renamed, deleted, or never tracked in the first
   place). A reading order that points at a path no clean checkout has is worse than no
   reading order — it is the machine-local class: the citation resolves on the machine
   that wrote it and nowhere else. So the assertion is *tracked in git*, not
   `os.path.exists` — those two answers differ for exactly the files that matter.

2. **The audit's own arithmetic drifts.** Appendix A classifies 154 memory entries into
   five classes. A count in the summary table that disagrees with the entries actually
   listed is a ledger claiming coverage it does not have — the failure mode the whole
   issue is about, reproduced inside the artifact that fixes it. So the declared total,
   the per-class counts, and the enumerated slugs must all agree, and no slug may appear
   twice or in two classes.

WHAT THIS CANNOT SEE, stated per `docs/OPERATING_DISCIPLINE.md` §1: it checks that a
citation *resolves*, never that the cited page still *says* what the sentence claims (the
`a_citation_string_is_not_an_owner` class). And it cannot check the memory corpus at all
— those files live outside git on one machine, which is the condition #2848 exists to
reduce. Appendix A is therefore a frozen dated record and this file only holds it
internally consistent.

NON-VACUITY: an empty extraction is the silent-pass shape here — rename the Cold Start
heading and a naive version of this check would examine zero citations and report clean.
Both extractors therefore assert a floor on what they found, and every assertion prints
its denominator.

MUTATION PROOF: `test_a_bad_citation_reds` and `test_a_miscounted_class_reds` run the two
decision functions against synthetic text with no repo dependency, and show each goes red
on the defect it owns. `test_the_real_docs_pass_the_same_functions` is the positive
control on the live documents.
"""

from __future__ import annotations

import pathlib
import re
import subprocess

REPO = pathlib.Path(__file__).resolve().parent.parent

_DISCIPLINE = "docs/OPERATING_DISCIPLINE.md"
_ONBOARDING = "docs/ONBOARDING.md"
_COLD_START_HEADING = "## Cold Start — operating with no session memory"

# A backticked token is treated as a repo-path citation only when its first segment is a
# real top-level entry of this repo, or it is one of the root files. Deliberately narrow:
# `origin/main`, `us-west-2` and `type:epic` are backticked all over these pages and are
# not paths. Widening this set is how the check would start reporting false reds.
_TOP_LEVEL = frozenset(
    {
        ".claude",
        ".github",
        "backup",
        "cdk",
        "config",
        "deploy",
        "docs",
        "handovers",
        "ingest",
        "lambdas",
        "mcp",
        "model",
        "scripts",
        "seeds",
        "setup",
        "site",
        "tests",
    }
)
_ROOT_FILES = frozenset({"CLAUDE.md", "CONTRIBUTING.md", "README.md", "Makefile", "LICENSE"})

_BACKTICKED = re.compile(r"`([^`\n]+)`")
_PATH_SHAPED = re.compile(r"^[A-Za-z0-9._][A-Za-z0-9._/-]*$")

# Appendix A's two shapes: the summary row and the per-class enumeration.
_CLASS_ROW = re.compile(r"^\|\s*`(\w+)`\s*\|\s*(\d+)\s*\|", re.MULTILINE)
_CLASS_LIST = re.compile(r"^\*\*`(\w+)` \((\d+)\):\*\*\s*(.+)$", re.MULTILINE)
_DECLARED_TOTAL = re.compile(r"\*\*Corpus audited:\s*(\d+)\s+entries\*\*")


def extract_path_citations(text: str) -> list[str]:
    """Every backticked token in ``text`` that names a path in this repo."""
    found = []
    for token in _BACKTICKED.findall(text):
        token = token.strip()
        if not _PATH_SHAPED.match(token):
            continue
        head = token.split("/", 1)[0]
        if head in _TOP_LEVEL and "/" in token:
            found.append(token)
        elif token in _ROOT_FILES:
            found.append(token)
    return sorted(set(found))


def _tracked(path: str) -> bool:
    """True when ``path`` is a file or directory git knows about.

    Tracked-at-HEAD is the primary answer; the index is consulted as well so a path added
    in the very commit under test still resolves when the suite runs pre-merge.
    """
    try:
        at_head = subprocess.run(["git", "ls-tree", "HEAD", "--", path], cwd=REPO, capture_output=True, text=True, timeout=30)
        staged = subprocess.run(["git", "status", "--porcelain", "--", path], cwd=REPO, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):  # pragma: no cover - environment
        return True  # no git available: refuse to invent a failure
    if at_head.returncode == 0 and at_head.stdout.strip():
        return True
    # A path added in the commit under test is not at HEAD yet but is in the index; an
    # untracked file reports `??` and must NOT count as resolved.
    return staged.returncode == 0 and any(line and not line.startswith("??") for line in staged.stdout.splitlines())


def unresolved_citations(text: str) -> list[str]:
    """The cited paths git does not know about. Empty list == every citation resolves."""
    return [p for p in extract_path_citations(text) if not _tracked(p)]


def audit_ledger_errors(text: str) -> list[str]:
    """Arithmetic + uniqueness errors in the Appendix A classification ledger."""
    errors: list[str] = []
    declared = _DECLARED_TOTAL.search(text)
    if not declared:
        return ["no '**Corpus audited: N entries**' line — the ledger states no denominator"]
    total = int(declared.group(1))

    rows = {name: int(n) for name, n in _CLASS_ROW.findall(text)}
    lists = {name: (int(n), body) for name, n, body in _CLASS_LIST.findall(text)}

    if set(rows) != set(lists):
        errors.append(f"summary classes {sorted(rows)} != enumerated classes {sorted(lists)}")
        return errors

    seen: dict[str, str] = {}
    for name, (claimed, body) in sorted(lists.items()):
        slugs = [s.strip(" `") for s in body.split(",") if s.strip()]
        if len(slugs) != claimed:
            errors.append(f"class '{name}' claims {claimed} entries, enumerates {len(slugs)}")
        if rows[name] != claimed:
            errors.append(f"class '{name}': summary row says {rows[name]}, enumeration says {claimed}")
        for slug in slugs:
            if slug in seen:
                errors.append(f"entry '{slug}' classified twice: '{seen[slug]}' and '{name}'")
            seen[slug] = name

    if sum(rows.values()) != total:
        errors.append(f"class counts sum to {sum(rows.values())}, corpus declared as {total}")
    if len(seen) != total:
        errors.append(f"{len(seen)} distinct entries enumerated, corpus declared as {total}")
    return errors


def cold_start_section(text: str) -> str:
    """The Cold Start block of ONBOARDING — empty string when the heading is gone."""
    if _COLD_START_HEADING not in text:
        return ""
    after = text.split(_COLD_START_HEADING, 1)[1]
    return after.split("\n## ", 1)[0]


# ── the live documents ────────────────────────────────────────────────────────────────


def test_operating_discipline_citations_all_resolve() -> None:
    text = (REPO / _DISCIPLINE).read_text(encoding="utf-8")
    cited = extract_path_citations(text)
    print(f"[#2848] {_DISCIPLINE}: {len(cited)} repo-path citations checked")
    assert len(cited) >= 10, f"only {len(cited)} citations found — the extractor has gone blind"
    bad = [p for p in cited if not _tracked(p)]
    assert not bad, f"{_DISCIPLINE} cites paths git does not know: {bad}"


def test_cold_start_section_exists_and_its_artifacts_are_tracked() -> None:
    text = (REPO / _ONBOARDING).read_text(encoding="utf-8")
    section = cold_start_section(text)
    assert section, f"{_ONBOARDING} has lost its '{_COLD_START_HEADING}' section (#2848 acceptance box 3)"
    cited = extract_path_citations(section)
    print(f"[#2848] {_ONBOARDING} Cold Start: {len(cited)} repo artifacts named")
    assert len(cited) >= 10, f"the cold-start reading order names only {len(cited)} artifacts"
    bad = [p for p in cited if not _tracked(p)]
    assert not bad, f"the cold-start reading order names paths git does not know: {bad}"


def test_the_audit_ledger_is_internally_consistent() -> None:
    text = (REPO / _DISCIPLINE).read_text(encoding="utf-8")
    errors = audit_ledger_errors(text)
    total = _DECLARED_TOTAL.search(text)
    print(f"[#2848] Appendix A: {total.group(1) if total else '?'} entries declared, {len(errors)} ledger errors")
    assert not errors, "Appendix A classification ledger disagrees with itself:\n  " + "\n  ".join(errors)


def test_the_two_pages_point_at_each_other() -> None:
    """The routing claim both pages make must be real, or a reader lands nowhere."""
    discipline = (REPO / _DISCIPLINE).read_text(encoding="utf-8")
    onboarding = (REPO / _ONBOARDING).read_text(encoding="utf-8")
    assert "docs/CONVENTIONS.md" in discipline, "OPERATING_DISCIPLINE must route deploy/CI rules to CONVENTIONS"
    assert "docs/CHARTER.md" in discipline, "OPERATING_DISCIPLINE must route architecture rules to the charter"
    assert _DISCIPLINE in onboarding, "the cold-start reading order must name OPERATING_DISCIPLINE"


# ── mutation proofs (synthetic, no repo dependency) ───────────────────────────────────

_GOOD_LEDGER = """
**Corpus audited: 4 entries**

| Class | n | What it means |
|---|---|---|
| `homed` | 3 | already in the repo |
| `new` | 1 | migrated here |

**`homed` (3):** `alpha`, `beta`, `gamma`

**`new` (1):** `delta`
"""


def test_a_bad_citation_reds() -> None:
    good = "read `docs/CONVENTIONS.md` then `scripts/backlog_next.py`"
    assert unresolved_citations(good) == [], "positive control: real citations must resolve"
    bad = good + " and `docs/THIS_PAGE_DOES_NOT_EXIST_2848.md`"
    assert unresolved_citations(bad) == ["docs/THIS_PAGE_DOES_NOT_EXIST_2848.md"]


def test_the_extractor_ignores_non_paths() -> None:
    """`origin/main` and friends are backticked constantly and are not citations."""
    assert extract_path_citations("`origin/main` `us-west-2` `type:epic` `git add -A`") == []


def test_a_miscounted_class_reds() -> None:
    assert audit_ledger_errors(_GOOD_LEDGER) == [], "positive control: a consistent ledger has no errors"
    miscounted = _GOOD_LEDGER.replace("| `homed` | 3 |", "| `homed` | 4 |")
    errors = audit_ledger_errors(miscounted)
    assert any("summary row says 4" in e for e in errors), errors
    dropped = _GOOD_LEDGER.replace("**`homed` (3):** `alpha`, `beta`, `gamma`", "**`homed` (3):** `alpha`, `beta`")
    assert any("enumerates 2" in e for e in audit_ledger_errors(dropped))
    duplicated = _GOOD_LEDGER.replace("**`new` (1):** `delta`", "**`new` (1):** `alpha`")
    assert any("classified twice" in e for e in audit_ledger_errors(duplicated))


def test_a_missing_cold_start_section_reds() -> None:
    assert cold_start_section("## Something Else\nbody\n") == ""
    assert cold_start_section(f"{_COLD_START_HEADING}\nbody\n\n## Next\n").strip() == "body"


def test_the_real_docs_pass_the_same_functions() -> None:
    """Positive control: the two decision functions stay quiet on the healthy case."""
    text = (REPO / _DISCIPLINE).read_text(encoding="utf-8")
    assert audit_ledger_errors(text) == []
    assert unresolved_citations(text) == []


# ── #3264: production authority — the cold-read gap that risked a destructive act ──────
#
# #2848's residual gap 1 was the only one where a successor acting reasonably on repo
# evidence alone could take a destructive production action (approve a stale lease and
# ship a tree older than what is live) or strand the pipeline (leave one waiting). The
# rule lived exclusively in the operator's off-repo memory.
#
# This gate is deliberately STRUCTURAL where it can be: it anchors on tracked repo paths
# and on cross-page pointers, not on prose phrasing. Phrase-matched rules are a
# known-failed family here (#2959/#3003/#3199) — every field instance of one has failed.
# The two textual arms below are load-bearing CONCEPTS, not phrasings, and each is
# mutation-proved to actually red.

_AUTHORITY_HEADING = "## 5. Production authority — who may deploy, and what a waiting gate is"
_LEASE_SCRIPTS = ("deploy/approve_deployment.sh", "deploy/reject_deployment.sh")


def authority_section(text: str) -> str:
    """The production-authority section — empty string when the heading is gone."""
    if _AUTHORITY_HEADING not in text:
        return ""
    return text.split(_AUTHORITY_HEADING, 1)[1].split("\n## ", 1)[0]


def deploy_authority_errors(discipline: str, conventions: str, onboarding: str) -> list[str]:
    """Pure decision function — takes its documents as arguments, never reads the repo,
    so the RULE can be mutation-proven independently of today's prose."""
    errors: list[str] = []
    section = authority_section(discipline)
    if not section:
        return [f"{_DISCIPLINE} has lost its production-authority section (#3264)"]

    # Structural: both disposal paths must be named. Naming only `approve` is the exact
    # failure mode — rejection is the MORE common correct outcome for a stale lease.
    for script in _LEASE_SCRIPTS:
        if script not in section:
            errors.append(f"the authority section never names {script} — a lease has two dispositions, not one")

    # Concept, not phrasing: a gated run is a lease on a SHA. Without this a reader
    # treats approval as a queue ticket, which is how a tree older than live gets shipped.
    if "lease" not in section.lower() or "sha" not in section.lower():
        errors.append("the authority section does not state that a gated run is a lease on a specific sha")

    # Concept, not phrasing: the default when no grant exists.
    if "standing grant" not in section.lower():
        errors.append("the authority section does not define what a standing grant is")

    # Structural cross-page pointers — a rule nobody is routed to is a rule nobody reads.
    if "OPERATING_DISCIPLINE.md" not in conventions:
        errors.append("docs/CONVENTIONS.md does not route deploy AUTHORITY to the discipline page")
    if _COLD_START_HEADING in onboarding:
        cold = cold_start_section(onboarding)
        if "OPERATING_DISCIPLINE" not in cold:
            errors.append("the cold-start reading order does not name the page that carries deploy authority")
    return errors


def test_deploy_authority_is_documented() -> None:
    """The live documents satisfy #3264's contract."""
    errors = deploy_authority_errors(
        (REPO / _DISCIPLINE).read_text(encoding="utf-8"),
        (REPO / "docs/CONVENTIONS.md").read_text(encoding="utf-8"),
        (REPO / _ONBOARDING).read_text(encoding="utf-8"),
    )
    print(f"[#3264] production-authority contract: {len(errors)} error(s)")
    assert not errors, "deploy authority is not documented to contract:\n  " + "\n  ".join(errors)


def test_the_authority_sections_scripts_are_real() -> None:
    """The disposal procedure must name scripts that EXIST — a runbook pointing at a
    script git does not know is worse than no runbook."""
    for script in _LEASE_SCRIPTS:
        assert _tracked(script), f"{script} is named as the disposal procedure but git does not track it"


def test_a_missing_authority_section_reds() -> None:
    """Mutation proof: delete the section and the gate must fail."""
    live = (REPO / _DISCIPLINE).read_text(encoding="utf-8")
    conv = (REPO / "docs/CONVENTIONS.md").read_text(encoding="utf-8")
    onb = (REPO / _ONBOARDING).read_text(encoding="utf-8")
    assert deploy_authority_errors(live, conv, onb) == []  # positive control
    gutted = live.replace(_AUTHORITY_HEADING, "## 5. Something Else")
    assert any("lost its production-authority section" in e for e in deploy_authority_errors(gutted, conv, onb))


def test_dropping_the_reject_path_reds() -> None:
    """Mutation proof for the arm that matters most: a section that names only
    `approve_deployment.sh` teaches a reader that approving is the way to clear a lease.
    Rejecting a superseded lease is the more common correct disposition."""
    live = (REPO / _DISCIPLINE).read_text(encoding="utf-8")
    conv = (REPO / "docs/CONVENTIONS.md").read_text(encoding="utf-8")
    onb = (REPO / _ONBOARDING).read_text(encoding="utf-8")
    approve_only = live.replace("deploy/reject_deployment.sh", "deploy/approve_deployment.sh")
    errors = deploy_authority_errors(approve_only, conv, onb)
    assert any("reject_deployment.sh" in e for e in errors), errors


def test_losing_the_lease_semantics_reds() -> None:
    """Mutation proof: strip the lease/sha concept and the gate must fail. This is the
    arm that guards against shipping a tree older than what is live."""
    live = (REPO / _DISCIPLINE).read_text(encoding="utf-8")
    conv = (REPO / "docs/CONVENTIONS.md").read_text(encoding="utf-8")
    onb = (REPO / _ONBOARDING).read_text(encoding="utf-8")
    section = authority_section(live)
    flattened = live.replace(section, section.replace("lease", "item").replace("LEASE", "ITEM"))
    assert any("lease on a specific sha" in e for e in deploy_authority_errors(flattened, conv, onb))


def test_an_unrouted_authority_page_reds() -> None:
    """Mutation proof: a rule nobody is routed to is a rule nobody reads."""
    live = (REPO / _DISCIPLINE).read_text(encoding="utf-8")
    onb = (REPO / _ONBOARDING).read_text(encoding="utf-8")
    errors = deploy_authority_errors(live, "no pointer here", onb)
    assert any("does not route deploy AUTHORITY" in e for e in errors), errors
