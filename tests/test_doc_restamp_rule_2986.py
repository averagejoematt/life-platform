"""#2986 (folded #2838) — THE GENERIC RE-STAMP RULE, as a standing guard.

  A sync/apply run may only advance a freshness date on content it actually
  regenerated or verified.

WHY A GENERIC RULE AND NOT A SEVENTH INSTANCE
  The platform has implemented this rule three times, once per literal, each time after
  an incident:
    • `scripts/doc_facts_ops.py` CHECK D3 — the secret_count `live-verified` stamp reds
      after 90d, written because the doc-sync was re-stamping "Last updated" over a count
      nobody had checked since 2026-07-10 ("manufactured freshness", its own words);
    • `deploy/sync_doc_secret_inventory.py` — the same fact's explicit refresh command;
    • `docs/MCP_TOOL_CATALOG.md` — a body a month stale ("## All 72 Tools") under a header
      the reconcile bot re-stamped daily ("Total tools: 76"), the observation that seeded
      this epic.
  Three literals, one rule, and no standing statement of it — so instance four (the
  `ESSAY_ORG_CHART_OF_ONE.md` / `CAREER_ARTIFACT_SUBMISSION_KIT.md` pair, #3162) was found
  the same way the first three were: by a human reading prose.

WHAT "GUARD THE SET" MEANS HERE
  The guarded surface is DERIVED from `sync_doc_metadata.RULES` — every replacement
  template containing the `{date}` placeholder. Nothing in this file, and nothing in
  `deploy/doc_restamp_guard.py`, enumerates the nine stamped rules that exist today. A
  tenth joins the guard by being written; `test_every_stamped_rule_is_recognised_as_such`
  reds loudly if a new template's date change is not classifiable, which is the only way
  a new stamped literal could slip past the hold.

THE TWO DIRECTIONS, MUTATION-PROVED
  (a) re-stamp WITHOUT regeneration -> the stamp is HELD and the run says so;
  (b) regenerate (either signal) THEN re-stamp -> the stamp advances.
  Both run through the real `sync_doc_metadata.process_doc`, over a real git tree, with a
  real `RULES`-shaped table. Direction (a) is additionally proved on the LIVE repo surface
  (`docs/SLOs.md`) so the hermetic fixture can never drift away from the wire.

A HELD STAMP IS NOT A RED. `--check` has ignored date-only differences since #2649, so
holding cannot fail CI; it only stops the machine manufacturing freshness. The dedicated
assertion for that is `test_a_hold_is_never_counted_as_drift`.
"""

from __future__ import annotations

import os
import re
import subprocess  # nosec B404 — fixed argv git, test fixture only
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "deploy"))
os.environ.setdefault("AWS_REGION", "us-west-2")

import doc_restamp_guard as guard  # noqa: E402
import sync_doc_metadata as sync  # noqa: E402

_STAMP_DOC = "docs/SLOs.md"  # the live surface used for the on-repo proof: one rule, date-only


# ══════════════════════════════════════════════════════════════════════════════
# THE SET — derived from the sync tool's own rule table, never enumerated here
# ══════════════════════════════════════════════════════════════════════════════


def test_the_stamped_surface_is_derived_and_non_empty():
    """If this ever returns nothing, the guard below is vacuously green — the #2703 shape."""
    stamped = guard.stamped_rules(sync.RULES)
    assert stamped, "no rule in sync_doc_metadata.RULES stamps a date — the guard would be testing nothing"
    assert all(guard.STAMP_PLACEHOLDER in template for _, _, template in stamped)
    assert len(stamped) < len(sync.RULES), "every rule looks like a stamp — the placeholder test is too loose"


def test_a_new_stamped_rule_enrols_by_existing():
    """Enrolment is by construction: a doc nobody listed anywhere is picked up anyway."""
    invented = list(sync.RULES) + [("docs/NOT_A_REAL_DOC.md", r"Checked: \d{4}-\d{2}-\d{2}", "Checked: {date}")]
    assert "docs/NOT_A_REAL_DOC.md" in guard.stamped_docs(invented)
    assert "docs/NOT_A_REAL_DOC.md" not in guard.stamped_docs(sync.RULES)


@pytest.mark.parametrize("doc,pattern,template", guard.stamped_rules(sync.RULES), ids=lambda v: str(v)[:40])
def test_every_stamped_rule_is_recognised_as_such(doc, pattern, template):
    """THE SET GUARD. For each stamped rule, a difference of ONLY the date must be
    classified as date-only — that classification is what routes it into the hold.

    A new template whose date moves in a way `differs_only_by_date_stamp` cannot see
    would silently keep the old always-re-stamp behaviour. This reds instead.
    """
    today = sync.apply_facts(template)
    assert re.search(r"\d{4}-\d{2}-\d{2}", today), f"{doc}: rendered stamp template carries no date: {today!r}"
    yesterday = re.sub(r"\b(\d{4}-\d{2}-)(\d{2})\b", lambda m: m.group(1) + "01", today)
    assert yesterday != today
    assert guard.differs_only_by_date_stamp(yesterday, today), f"{doc}: a date-only change is not recognised — it would bypass the hold"


def test_the_date_masker_is_not_a_blanket_line_ignore():
    """#2649's contract, re-asserted at its new shared home: masking is per-change, because
    docs/ARCHITECTURE.md carries the date and the Lambda count on the SAME line."""
    assert guard.differs_only_by_date_stamp("Last updated: 2026-08-14 (v8.6.0)", "Last updated: 2026-08-15 (v8.6.0)")
    assert not guard.differs_only_by_date_stamp(
        "Last updated: 2026-08-14 (v8.6.0 — 104 Lambdas)",
        "Last updated: 2026-08-15 (v8.6.0 — 999 Lambdas)",
    )
    assert not guard.differs_only_by_date_stamp("76 tools", "88 tools")
    assert (
        sync._differs_only_by_date_stamp is guard.differs_only_by_date_stamp
    ), "the #2649 re-export must stay the same function, not a fork"


def test_the_rule_itself():
    """Either verification signal licenses the stamp; neither does not."""
    assert guard.may_restamp(rederived_in_run=True, regenerated=False)
    assert guard.may_restamp(rederived_in_run=False, regenerated=True)
    assert guard.may_restamp(rederived_in_run=True, regenerated=True)
    assert not guard.may_restamp(rederived_in_run=False, regenerated=False)


# ══════════════════════════════════════════════════════════════════════════════
# MUTATION PROOFS — the real process_doc over a real git tree
# ══════════════════════════════════════════════════════════════════════════════


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)  # nosec B603 B607


@pytest.fixture
def tree(tmp_path, monkeypatch):
    """A committed one-doc git tree wired into the REAL sync module (ROOT + RULES + facts).

    Everything under test is the shipping code path; only the corpus is synthetic, so the
    proofs cannot mutate the repo and cannot be perturbed by another agent's working tree.
    """
    doc = tmp_path / "docs" / "THING.md"
    doc.parent.mkdir(parents=True)
    doc.write_text("Last updated: 2026-08-01 (v1.0.0)\n\nWidgets: 7\n", encoding="utf-8")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "t")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "seed")

    rules = [
        ("docs/THING.md", r"Last updated: \d{4}-\d{2}-\d{2} \([^\)]+\)", "Last updated: {date} ({version})"),
        ("docs/THING.md", r"Widgets: \d+", "Widgets: {widget_count}"),
    ]
    monkeypatch.setattr(sync, "ROOT", tmp_path)
    monkeypatch.setattr(sync, "RULES", rules)
    monkeypatch.setitem(sync.PLATFORM_FACTS, "date", "2026-08-26")
    monkeypatch.setitem(sync.PLATFORM_FACTS, "version", "v1.0.0")
    sync.PLATFORM_FACTS["widget_count"] = 7
    yield doc
    sync.PLATFORM_FACTS.pop("widget_count", None)


def _stamp(doc: Path) -> str:
    return re.search(r"Last updated: (\d{4}-\d{2}-\d{2})", doc.read_text(encoding="utf-8")).group(1)


def test_a_restamp_without_regeneration_is_held(tree):
    """DIRECTION (a) — the defect. Nothing was re-derived, nothing was regenerated, so the
    date must NOT move, and the run must say why rather than doing it silently."""
    changes = sync.process_doc("docs/THING.md", dry_run=False)
    assert _stamp(tree) == "2026-08-01", "the sync advanced a freshness date on content it never touched (#2986)"
    assert any(c.startswith(guard.HOLD_PREFIX) for c in changes), f"the hold was silent: {changes!r}"
    assert not any(c.startswith("  ~") for c in changes), "a held stamp must not be reported as drift"


def test_b1_a_literal_this_run_rederived_licenses_the_stamp(tree):
    """DIRECTION (b), signal 1 — the sync itself rewrote a non-date literal in this doc,
    so the stamp travels with content the run demonstrably re-derived."""
    tree.write_text(tree.read_text(encoding="utf-8").replace("Widgets: 7", "Widgets: 999"), encoding="utf-8")
    changes = sync.process_doc("docs/THING.md", dry_run=False)
    assert "Widgets: 7" in tree.read_text(encoding="utf-8")
    assert _stamp(tree) == "2026-08-26", "a legitimate regenerate+re-stamp was blocked — the guard is too strict"
    assert not any(c.startswith(guard.HOLD_PREFIX) for c in changes)


def test_b2_a_body_regenerated_by_another_writer_licenses_the_stamp(tree):
    """DIRECTION (b), signal 2 — a generator (or a human) rewrote the body in this working
    tree before the sync ran. This is `generate_mcp_tool_catalog.py` -> sync, done honestly:
    the catalog's stamp SHOULD move on the day its body is regenerated."""
    tree.write_text(tree.read_text(encoding="utf-8") + "\nA newly generated section.\n", encoding="utf-8")
    changes = sync.process_doc("docs/THING.md", dry_run=False)
    assert _stamp(tree) == "2026-08-26", "a regenerated body did not license its own stamp"
    assert not any(c.startswith(guard.HOLD_PREFIX) for c in changes)


def test_staling_the_stamp_is_not_itself_regeneration(tree):
    """The laundering path. Rolling the date back IS a byte change against HEAD, so a naive
    `text != HEAD` regeneration test would re-stamp it — the bug, wearing a diff as a
    disguise. Every comparison masks dates first, so this must still hold."""
    tree.write_text(tree.read_text(encoding="utf-8").replace("2026-08-01", "2026-07-04"), encoding="utf-8")
    assert not guard.regenerated_by_another_writer(tree.parent.parent, "docs/THING.md", tree.read_text(encoding="utf-8"))
    sync.process_doc("docs/THING.md", dry_run=False)
    assert _stamp(tree) == "2026-07-04", "a date-only edit was mistaken for regenerated content"


def test_a_hold_is_never_counted_as_drift(tree):
    """A hold happens on every un-regenerated doc at every UTC rollover. If main() counted
    it, --check would go red daily on the calendar — precisely the #2649 noise the hold
    exists to end. The prefix is the contract between the two."""
    changes = sync.process_doc("docs/THING.md", dry_run=False)
    note = next(c for c in changes if c.startswith(guard.HOLD_PREFIX))
    assert not note.startswith("  ~") and not note.startswith("  ! ")
    assert "docs/THING.md" in note and "#2986" in note


def test_a_brand_new_doc_may_stamp_itself(tree):
    """Content that does not exist in HEAD is, by definition, freshly written."""
    fresh = tree.parent / "NEW.md"
    fresh.write_text("Last updated: 2026-08-01 (v1.0.0)\n", encoding="utf-8")
    assert guard.head_text(tree.parent.parent, "docs/NEW.md") == ""
    assert guard.regenerated_by_another_writer(tree.parent.parent, "docs/NEW.md", fresh.read_text(encoding="utf-8"))


def test_fail_closed_when_git_cannot_answer(tmp_path):
    """No repo, no evidence, no stamp. A stamp that stays honest-but-old is a smaller lie
    than one advanced without evidence, and this epic exists because the platform kept
    choosing the larger one."""
    (tmp_path / "loose.md").write_text("Last updated: 2026-08-01\n", encoding="utf-8")
    assert guard.head_text(tmp_path, "loose.md") is None
    assert not guard.regenerated_by_another_writer(tmp_path, "loose.md", "Last updated: 2026-08-01\n")


# ══════════════════════════════════════════════════════════════════════════════
# THE LIVE SURFACE — the hermetic fixture above must not drift away from the wire
# ══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def live_doc(monkeypatch):
    """A real stamped doc with its date rolled back, restored byte-for-byte on exit.

    `PLATFORM_FACTS` is pinned to the doc's OWN non-date values instead of running the
    ~8s auto-discovery: the subject here is the stamp path over the live `RULES` entry and
    the live git tree, and pinning guarantees the date is the only thing in play. The
    guard below fails loudly (rather than silently testing nothing) if the rule ever grows
    a placeholder this pinning does not cover.
    """
    if subprocess.run(["git", "diff", "--quiet", "HEAD", "--", _STAMP_DOC], cwd=str(_REPO)).returncode:  # nosec B603 B607
        pytest.skip(f"{_STAMP_DOC} is dirty in this working tree — the HEAD signal is not measurable")
    path = _REPO / _STAMP_DOC
    original = path.read_text(encoding="utf-8")
    stamped = [r for r in guard.stamped_rules(sync.RULES) if r[0] == _STAMP_DOC]
    assert len(stamped) == 1, f"{_STAMP_DOC} no longer has exactly one stamped rule — repoint _STAMP_DOC"

    live_line = re.search(stamped[0][1], original)
    assert live_line, f"{_STAMP_DOC}'s stamped rule matches nothing — repoint _STAMP_DOC"
    version = re.search(r"\((v[\d.]+)\)", live_line.group(0))
    assert version, f"cannot read {_STAMP_DOC}'s version from {live_line.group(0)!r} — repoint _STAMP_DOC"
    monkeypatch.setitem(sync.PLATFORM_FACTS, "version", version.group(1))
    monkeypatch.setitem(sync.PLATFORM_FACTS, "date", "2026-08-26")
    assert guard.differs_only_by_date_stamp(
        live_line.group(0), sync.apply_facts(stamped[0][2])
    ), f"pinned facts do not reproduce {_STAMP_DOC}'s stamp line — the rule grew a placeholder; repoint or extend"

    path.write_text(
        re.sub(stamped[0][1], lambda m: m.group(0).replace(_stamp_of(m.group(0)), "2026-01-02"), original, count=1), encoding="utf-8"
    )
    yield path
    path.write_text(original, encoding="utf-8")


def _stamp_of(text: str) -> str:
    return re.search(r"\d{4}-\d{2}-\d{2}", text).group(0)


def test_the_hold_is_live_on_the_real_repo_surface(live_doc):
    """DIRECTION (a) against the shipping RULES, the shipping ROOT and the real git tree."""
    changes = sync.process_doc(_STAMP_DOC, dry_run=False)
    assert _stamp(live_doc) == "2026-01-02", "the live sync re-stamped a doc it never regenerated (#2986)"
    assert any(c.startswith(guard.HOLD_PREFIX) for c in changes), f"the live hold was silent: {changes!r}"


def test_a_regenerated_body_is_live_licensed_on_the_real_repo_surface(live_doc):
    """DIRECTION (b) on the same live surface: regenerate the body, and the stamp moves.
    Without this, direction (a) alone could be passing because the stamp path is dead."""
    live_doc.write_text(live_doc.read_text(encoding="utf-8") + "\n<!-- regenerated -->\n", encoding="utf-8")
    changes = sync.process_doc(_STAMP_DOC, dry_run=False)
    assert _stamp(live_doc) == "2026-08-26", "a regenerated live doc was denied its own stamp"
    assert not any(c.startswith(guard.HOLD_PREFIX) for c in changes)
