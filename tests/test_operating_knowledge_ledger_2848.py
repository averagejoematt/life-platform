"""tests/test_operating_knowledge_ledger_2848.py — the operating-knowledge ledger stays true (#2848).

`docs/OPERATING_KNOWLEDGE_LEDGER.md` is the maintained registry of where every rule in the
operator's private Claude-memory index lives in this repo (or why it deliberately does not).
Its predecessor — Appendix A of `docs/OPERATING_DISCIPLINE.md` — was a frozen table that was
current for one day, because the files it classified live outside git and nothing could
re-derive it. This ledger has the same blind spot and does not pretend otherwise; what it
adds is a committed SNAPSHOT of the memory index, so the ledger can at least be held
consistent with a denominator that is in git.

WHAT THIS FILE CHECKS (offline, no memory directory needed):
  - every file in the committed snapshot block has exactly one ledger row, and vice versa;
  - every row's `type` matches the file's own prefix;
  - every `homed-here` / `already-homed` / `superseded` row cites at least one repo path
    that git tracks — a ledger pointing at a page no clean checkout has is the machine-local
    class this whole issue exists to reduce;
  - every `narrative` / `off-repo` row states a reason;
  - the coverage counts in the doc equal the rows (a ledger claiming coverage it does not
    have is the failure mode the issue is about, reproduced inside the fix).

WHAT IT CANNOT CHECK, stated plainly: whether the live memory directory has grown past the
snapshot. That half is `scripts/check_operating_knowledge_ledger.py --live`, a /wrap step
(c) reflex run on the machine that has the directory. `test_live_findings_name_new_files`
proves that function against a synthetic directory so the reflex is not itself an
unverified instrument.

MUTATION PROOFS run the pure decision function against synthetic text with an injected
`tracked` predicate, so each arm is shown to red on the defect it owns without touching git.
"""

from __future__ import annotations

import importlib.util
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
_LEDGER = "docs/OPERATING_KNOWLEDGE_LEDGER.md"
_SCRIPT = REPO / "scripts" / "check_operating_knowledge_ledger.py"


def _load():
    spec = importlib.util.spec_from_file_location("check_operating_knowledge_ledger", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


okl = _load()


# ── the live document ─────────────────────────────────────────────────────────────────


def test_the_ledger_is_consistent_with_its_snapshot() -> None:
    text = (REPO / _LEDGER).read_text(encoding="utf-8")
    rows = okl.parse_rows(text)
    snap = okl.parse_snapshot(text)
    errors = okl.ledger_errors(text)
    print(f"[#2848] ledger: {len(rows)} rows · {len(snap)} snapshot files · {len(errors)} error(s)")
    assert len(snap) >= 300, f"only {len(snap)} snapshot files — the extractor has gone blind"
    assert len(rows) >= 300, f"only {len(rows)} rows parsed — the table shape changed"
    assert not errors, "the ledger disagrees with itself:\n  " + "\n  ".join(errors)


def test_every_rule_class_file_has_a_disposition() -> None:
    """The issue's own bar: a rule-class memory file either has a repo home or a named reason."""
    text = (REPO / _LEDGER).read_text(encoding="utf-8")
    rule_rows = [r for r in okl.parse_rows(text) if r[1] in okl.RULE_TYPES]
    assert len(rule_rows) >= 200, f"only {len(rule_rows)} rule-class rows"
    undisposed = [f for f, _, home, status in rule_rows if status not in okl.ALLOWED_STATUS["reference"]]
    assert not undisposed, undisposed
    homed = sum(1 for r in rule_rows if r[3] in okl.CITING_STATUSES)
    print(f"[#2848] rule-class rows: {len(rule_rows)} · with a repo citation: {homed}")
    assert homed / len(rule_rows) > 0.8, "fewer than 80% of rule-class rows cite a repo home"


def test_the_pages_the_ledger_routes_to_route_back() -> None:
    """A registry nobody is pointed at is a registry nobody maintains."""
    for page in (
        "docs/OPERATING_DISCIPLINE.md",
        "docs/CONTINUITY.md",
        "docs/README.md",
        "docs/ONBOARDING.md",
        ".claude/skills/wrap/SKILL.md",
    ):
        assert "OPERATING_KNOWLEDGE_LEDGER.md" in (REPO / page).read_text(encoding="utf-8"), f"{page} does not point at the ledger"


def test_the_script_offline_mode_agrees_with_this_test() -> None:
    """The CLI and the test call the same function; the CLI must not drift into a second copy."""
    assert okl.main([]) == 0


# ── mutation proofs (synthetic, no repo dependency) ───────────────────────────────────

_GOOD = """
<!-- LEDGER-COVERAGE:START -->
**Files in the memory index snapshot: 4** — feedback 1 · reference 2 · security 0 · project 1 · user 0 · index 0

**Rule-class files (feedback + reference + security): 3** — homed-here 1 · already-homed 1 · superseded 0 · narrative 1 · off-repo 0

**Program/session files (project): 1** — already-homed 0 · superseded 0 · narrative 1 · off-repo 0 · index 0
<!-- LEDGER-COVERAGE:END -->

<!-- LEDGER-SNAPSHOT:START -->
```
feedback_alpha.md
reference_beta.md
reference_gamma.md
project_delta.md
```
<!-- LEDGER-SNAPSHOT:END -->

| memory file | type | home | status |
|---|---|---|---|
| `feedback_alpha.md` | feedback | `docs/CONVENTIONS.md` §7 | homed-here |
| `reference_beta.md` | reference | `docs/OPERATING_DISCIPLINE.md` §1.2 | already-homed |
| `reference_gamma.md` | reference | — narrative: a one-off measurement about a metric | narrative |
| `project_delta.md` | project | — narrative: a session record; the handover is the repo copy | narrative |
"""

_ALL_TRACKED = lambda p: True  # noqa: E731 - a predicate, injected


def test_a_consistent_ledger_has_no_errors() -> None:
    assert okl.ledger_errors(_GOOD, tracked=_ALL_TRACKED) == []


def test_a_snapshot_file_without_a_row_reds() -> None:
    dropped = _GOOD.replace("| `reference_gamma.md` | reference | — narrative: a one-off measurement about a metric | narrative |\n", "")
    errors = okl.ledger_errors(dropped, tracked=_ALL_TRACKED)
    assert any("snapshot file has no ledger row: reference_gamma.md" in e for e in errors), errors


def test_a_row_outside_the_snapshot_reds() -> None:
    extra = _GOOD + "| `reference_omega.md` | reference | `docs/CONVENTIONS.md` §7 | homed-here |\n"
    errors = okl.ledger_errors(extra, tracked=_ALL_TRACKED)
    assert any("ledger row not in snapshot: reference_omega.md" in e for e in errors), errors


def test_a_homed_row_citing_an_untracked_path_reds() -> None:
    errors = okl.ledger_errors(_GOOD, tracked=lambda p: p != "docs/CONVENTIONS.md")
    assert any("cited path is not tracked by git: docs/CONVENTIONS.md" in e for e in errors), errors


def test_a_homed_row_with_no_citation_reds() -> None:
    bare = _GOOD.replace("| `docs/CONVENTIONS.md` §7 | homed-here |", "| somewhere in the docs | homed-here |")
    errors = okl.ledger_errors(bare, tracked=_ALL_TRACKED)
    assert any("cites no repo path" in e for e in errors), errors


def test_a_narrative_row_without_a_reason_reds() -> None:
    mute = _GOOD.replace("— narrative: a one-off measurement about a metric", "—")
    errors = okl.ledger_errors(mute, tracked=_ALL_TRACKED)
    assert any("needs a stated reason" in e for e in errors), errors


def test_a_wrong_type_or_status_reds() -> None:
    wrong_type = _GOOD.replace("| `reference_beta.md` | reference |", "| `reference_beta.md` | feedback |")
    assert any("filename says 'reference'" in e for e in okl.ledger_errors(wrong_type, tracked=_ALL_TRACKED))
    wrong_status = _GOOD.replace(
        "| `project_delta.md` | project | — narrative: a session record; the handover is the repo copy | narrative |",
        "| `project_delta.md` | project | — narrative: a session record; the handover is the repo copy | user |",
    )
    assert any("status 'user' not allowed for type 'project'" in e for e in okl.ledger_errors(wrong_status, tracked=_ALL_TRACKED))


def test_a_miscounted_coverage_line_reds() -> None:
    miscount = _GOOD.replace("homed-here 1 · already-homed 1", "homed-here 2 · already-homed 1")
    errors = okl.ledger_errors(miscount, tracked=_ALL_TRACKED)
    assert any("says homed-here 2, rows say 1" in e for e in errors), errors
    wrong_total = _GOOD.replace("snapshot: 4**", "snapshot: 5**")
    errors = okl.ledger_errors(wrong_total, tracked=_ALL_TRACKED)
    assert any("declares 5 files, block lists 4" in e for e in errors), errors


def test_a_missing_snapshot_block_reds() -> None:
    assert okl.ledger_errors("| `a.md` | index | x | index |", tracked=_ALL_TRACKED) == [
        "no LEDGER-SNAPSHOT block — the ledger states no denominator"
    ]


def test_live_findings_name_new_files(tmp_path: pathlib.Path) -> None:
    """The /wrap reflex: a memory file with no row is named; a row whose file is gone is named."""
    for name in ("feedback_alpha.md", "reference_beta.md", "reference_gamma.md", "reference_new_lesson.md"):
        (tmp_path / name).write_text("---\nname: x\n---\n", encoding="utf-8")
    unledgered, gone = okl.live_findings(tmp_path, _GOOD)
    assert unledgered == ["reference_new_lesson.md"]
    assert gone == ["project_delta.md"]


def test_type_of_is_the_filename_prefix() -> None:
    assert okl.type_of("feedback_x.md") == "feedback"
    assert okl.type_of("reference_x.md") == "reference"
    assert okl.type_of("security_x.md") == "security"
    assert okl.type_of("project_x.md") == "project"
    assert okl.type_of("user_x.md") == "user"
    assert okl.type_of("MEMORY.md") == "index"
    assert okl.type_of("INDEX_review_discipline.md") == "index"


@pytest.mark.parametrize(
    "cell,expected",
    [
        ("`docs/CONVENTIONS.md` §7 + `scripts/foo.py`", ["docs/CONVENTIONS.md", "scripts/foo.py"]),
        ("`origin/main` and `type:epic` and `--live`", []),
        ("`CLAUDE.md` § Authorship", ["CLAUDE.md"]),
    ],
)
def test_repo_paths_in_a_home_cell(cell: str, expected: list[str]) -> None:
    assert okl.repo_paths_in(cell) == expected
