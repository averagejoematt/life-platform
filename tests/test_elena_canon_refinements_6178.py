"""tests/test_elena_canon_refinements_6178.py — the owner's refinements to the unified Elena canon (#6178, owner ruling
2026-11-22 §7), each pinned where it can be tested deterministically.

  1. "compassionate without being soft" stays, verbatim.
  2. Hope only when the evidence warrants it: optimism is never a standing obligation.
  3. No invented career, employment history or first-hand interview — and a STAGED ENCOUNTER in a draft is a HARD
     source finding (``story_checks.staged_encounter_findings``), in the desk's post gate and in the publish audit,
     never a craft note. Proven against the shape that shipped and against lines that must not trip it.
  4. No journal text in an editorial prompt without explicit authorisation (``JOURNAL_IN_EDITORIAL_PROMPTS``).
  5. Only eligible, verified voice anchors: none from a chapter with a known unsupported passage, none modelling a
     forbidden or flagged device; ``verify_anchors`` fails an unreadable page or a line that is not verbatim.
  6. Coach quotations tied to approved original wording: the canon says so, and the quote gate refuses a coach line the
     platform does not hold while passing its exact words.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "lambdas"))

from content import autopublish_audit, elena_canon, story_checks, story_craft, story_writers  # noqa: E402

# The shape the published week-6 chapter carried (the editorial review's specimen), as a synthetic paragraph.
STAGED = "Marcus Webb, when I reached him this week, was blunt about it. 'It's a target he's not aiming at.' He paused."


def _all_text() -> str:
    return elena_canon.voice_block() + "\n" + elena_canon.host_block()


def test_the_version_is_bumped_past_the_unified_canon():
    major, minor, _patch = (int(x) for x in elena_canon.ELENA_CANON_VERSION.split("."))
    assert (major, minor) >= (1, 1), "a change to what she is must bump ELENA_CANON_VERSION"


# ── 1, 2: temperament ────────────────────────────────────────────────────────


def test_compassionate_without_being_soft_is_kept_verbatim():
    assert "compassionate without being soft" in elena_canon.TEMPERAMENT[0]
    assert "compassionate without being soft" in elena_canon.voice_block()


def test_hope_is_conditional_on_evidence_and_never_an_obligation():
    hope = [t for t in elena_canon.TEMPERAMENT if "hopeful" in t.lower()]
    assert len(hope) == 1, "one temperament line names hope"
    assert "evidence warrants" in hope[0] and "never a standing obligation" in hope[0]
    # and nothing anywhere makes optimism a duty
    assert not re.search(r"\b(always|stay|remain)\s+(optimistic|hopeful|positive|upbeat)\b", _all_text(), re.I)


# ── 3: no career, no first-hand interview, no staged encounter ───────────────


def test_the_canon_rules_out_a_career_employment_and_first_hand_interviews():
    d = elena_canon.DISCLOSURE
    assert "no career, employment history" in d and "interviewed no one" in d
    assert any("stage an encounter" in n and "first-hand interview never happened" in n for n in elena_canon.NEVER)


def test_a_staged_encounter_is_a_hard_source_finding():
    found = story_checks.staged_encounter_findings(STAGED)
    assert len(found) >= 2 and all(f.startswith("source:") for f in found), found
    # not a writer's note: the publish audit treats every one as blocking
    assert not any(autopublish_audit.is_style_finding(f) for f in found)
    for planted in (
        "I asked Park whether the score came first.",
        "Reeves told me the bounce was real.",
        "In our conversation she was clear about the floor.",
        "After I spoke with the coach, the picture changed.",
        "She laughed — the record had beaten her again.",
    ):
        assert story_checks.staged_encounter_findings(planted), planted


def test_reported_coach_reads_and_ordinary_verbs_do_not_trip_it():
    for clean in (
        "He paused the plan on Tuesday.",
        "Matthew paused his training block after the hike.",
        "Reeves asked whether the bounce felt like something Matthew did, or something his body did on its own.",
        "I am Elena Voss, written by a language model from Matthew's data.",
        "When I read the record, the gap is plain.",
        "Webb's read this week was that protein is a distribution problem.",
    ):
        assert story_checks.staged_encounter_findings(clean) == [], clean
    assert story_checks.staged_encounter_findings(elena_canon.voice_block()) == [], "the canon itself must pass its own rule"
    for a in elena_canon.VOICE_ANCHORS:
        assert story_checks.staged_encounter_findings(a["text"]) == [], a


def test_the_desks_post_gate_carries_the_staged_encounter_check():
    found = story_checks.all_findings(
        STAGED + "\n\n---\n*Week 6 of The Measured Life*",
        stop_reason="end_turn",
        allowed=set(),
        footer_pattern=story_writers.CHRONICLE_FOOTER,
    )
    assert any(f.startswith("source: a staged encounter") for f in found), found


def test_the_publish_audit_refuses_a_stored_draft_with_a_staged_encounter():
    row = {
        "content_markdown": STAGED,
        "date": "2026-11-17",
        "desk_findings_json": json.dumps({"post": [], "episode": []}),
        "desk_craft_json": "[]",
    }
    blocking = autopublish_audit.blocking_items(row)
    assert any(b.startswith("source: a staged encounter") for b in blocking), blocking
    assert not all(b.startswith("craft hold") for b in blocking), "an approval click alone would publish it"


# ── 4: no journal text without explicit authorisation ────────────────────────


def test_no_journal_text_enters_an_editorial_prompt_without_authorisation():
    assert elena_canon.JOURNAL_IN_EDITORIAL_PROMPTS is False, "flipping this is an owner act recorded in an ADR"
    assert any("journal" in n and "do not read it" in n for n in elena_canon.NEVER)
    # the writers' inputs are held journal-blind by their own test; it must keep existing
    assert (_REPO / "tests" / "test_chronicle_journal_invariance.py").exists()
    assert not re.search(r"access to (?:his|Matthew's) journal|journal (?:entries|text) (?:below|follow)", _all_text(), re.I)


# ── 5: only eligible, verified voice anchors ─────────────────────────────────


def test_every_anchor_is_eligible():
    bad = {a["text"]: elena_canon.anchor_eligibility(a) for a in elena_canon.VOICE_ANCHORS if elena_canon.anchor_eligibility(a)}
    assert bad == {}, bad
    assert not {a["source"] for a in elena_canon.VOICE_ANCHORS} & set(elena_canon.INELIGIBLE_CHAPTERS)
    assert "/story/week-09/" in elena_canon.INELIGIBLE_CHAPTERS, "the chapter with the unsupported interview stays out"


def test_the_eligibility_rule_refuses_what_1_0_0_carried():
    """Mutation control: the lines 1.0.0 used and 1.1.0 dropped are each refused, for the reason that dropped them."""
    dropped = [
        ({"text": "The direction is expected. The rate is the story.", "source": "/story/week-05/"}, "flagged"),
        (
            {
                "text": "Four consecutive wrong calls on the same mechanism is not noise. It is a model that does not match this subject.",
                "source": "/story/week-08/",
            },
            "pivot",
        ),
        ({"text": "The plan was followed; the full dose was not always taken.", "source": "/story/week-12/"}, "unsupported"),
        ({"text": "The scale will have its own answer, and it won't negotiate.", "source": "/story/week-04/"}, "flagged"),
    ]
    for anchor, why in dropped:
        reasons = " ".join(elena_canon.anchor_eligibility(anchor))
        assert why in reasons or (why == "unsupported" and "unsupported passage" in reasons), (anchor, reasons)


def test_verify_anchors_passes_only_verbatim_lines_on_readable_pages():
    page = (
        lambda src: "<p>" + " ".join(a["text"] for a in elena_canon.VOICE_ANCHORS if a["source"] == src).replace("'", "&#8217;") + "</p>"
    )  # noqa: E731
    assert elena_canon.verify_anchors(page) == []
    assert elena_canon.verify_anchors(lambda src: "<p>Something else entirely.</p>"), "a line not on its page must fail"

    def broken(src):
        raise OSError("offline")

    out = elena_canon.verify_anchors(broken)
    assert any("could not be read" in o for o in out), "an unreadable page is unverified, never a pass"


# ── 6: coach quotations tied to approved original wording ────────────────────


def test_a_coach_is_quoted_only_in_approved_original_wording():
    assert any("approved original wording" in e for e in elena_canon.EVIDENCE)
    held = "Protein is the lever this week and the floor is the floor"
    corpus = story_craft._norm(held)
    assert story_craft.quote_findings(f'Webb put it plainly: "{held}."', corpus) == []
    invented = 'Webb put it plainly: "The numbers never lie and the plan is perfect, every single day."'
    assert story_craft.quote_findings(invented, corpus), "a coach line the platform does not hold must be refused"
