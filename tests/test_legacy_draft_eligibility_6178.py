"""tests/test_legacy_draft_eligibility_6178.py — a fallback (legacy-writer) draft becomes ELIGIBLE for the owner's
approval only when it passes exactly the checks a Story Desk draft passes; it is never published by anything but his
click (#6178, owner ruling 2026-11-22 §7 "Legacy writer").

What is pinned:
  * the switch (``CHRONICLE_LEGACY_ELIGIBLE``) defaults OFF, and off is the #6155 behaviour: always held;
  * on, the legacy door runs the SAME functions as the desk's ``_Gates.post`` (proven equal on a draft), plus the
    season-title check;
  * a legacy draft failing any ONE of the source, privacy, quote, factual or editorial checks is NOT approvable;
  * one passing all is approvable — and still unpublished: the approval refusal is empty, nothing publishes it, the
    stale sweep still only holds, and the Panel's legacy writer still waits for the owner;
  * a check that cannot run holds the draft and names which.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "lambdas"))
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from content import autopublish_audit, story_pipeline  # noqa: E402

DATE = "2026-11-17"
HELD = "Protein is the lever this week and the floor is the floor"


class _G:
    """The desk's gate object, built by hand: the dossier figures it grounds against and the quote corpus it holds."""

    def __init__(self):
        self.n = 11
        self.dossier = {"week": 11}
        self.allowed = {"290", "288.5", "3.8"}
        self.nye = []
        self.previous = {10: "Week 10 said the scale read 292.6."}
        self.context = {}
        self.corpus = story_pipeline.story_craft._norm(HELD)
        self.owner_lines = []
        self.weight_known = True

    craft_post = story_pipeline._Gates.craft_post
    post = story_pipeline._Gates.post


def _md(body: str, title: str = "Below 290") -> str:
    return f'"{title}"\n\n[Weight: 288.5 lbs | Week Grade: avg 60 | T0 Streak: 3 days]\n\n{body}\n\n---\n*Week 11 of The Measured Life*'


CLEAN = (
    "The scale crossed below 290 this week, at 288.5, and the week closed 3.8 pounds down. "
    f'Webb\'s note held its line: "{HELD}." The rest of the record is quiet, and this installment leaves it that way.'
)

# One draft per check family, each failing exactly that family.
FAILING = {
    "source (a staged encounter)": CLEAN + " When I reached Webb this week, he was blunt.",
    "privacy (an off-record specific)": CLEAN + " His girlfriend noticed the change first.",
    "quote (a coach line the platform does not hold)": CLEAN + ' Reeves said, "The numbers never lie and the plan is perfect."',
    "factual (an ungrounded figure)": CLEAN + " He walked 417 minutes across the week.",
}


def _no_fact(*a, **k):
    return []


def _audit(md, *, fact=_no_fact, eligible=True, ledger=None):
    g = _G()
    if not eligible:
        return [story_pipeline.LEGACY_NOTE] + story_pipeline.legacy_findings(g, md, ledger or {"titles": []})
    return [autopublish_audit.LEGACY_CHECKED_NOTE] + story_pipeline.legacy_gate_findings(g, md, ledger or {"titles": []}, fact_check=fact)


def _row(findings):
    """The draft row attach_legacy_audit writes, as the approve path reads it."""
    from emails import chronicle_store

    writes = []

    class T:
        def update_item(self, **k):
            writes.append(k)

    chronicle_store.attach_legacy_audit(DATE, findings, _g={"table": T(), "USER_ID": "matthew", "logger": None})
    v = writes[0]["ExpressionAttributeValues"]
    return {
        "status": "draft",
        "date": DATE,
        "title": "Below 290",
        "stats_line": "",
        "content_markdown": CLEAN,
        "desk_findings_json": v[":f"],
        "desk_craft_json": v[":c"],
        "publish_hold": v[":h"],
    }


def _approval_refusal(row):
    from emails import chronicle_approve_lambda as approve

    return approve.approval_refusal(row)


# ── the switch ───────────────────────────────────────────────────────────────


def test_the_switch_defaults_off_and_takes_only_explicit_values():
    assert story_pipeline.legacy_eligibility_on({}) is False
    for v in ("", "off", "0", "false", "yes", "enabled"):
        assert story_pipeline.legacy_eligibility_on({story_pipeline.LEGACY_ELIGIBLE_ENV: v}) is False, v
    for v in ("on", "1", "true", " ON "):
        assert story_pipeline.legacy_eligibility_on({story_pipeline.LEGACY_ELIGIBLE_ENV: v}) is True, v


def test_switch_off_a_clean_legacy_draft_is_still_held():
    row = _row(_audit(_md(CLEAN), eligible=False))
    assert row["publish_hold"] == story_pipeline.LEGACY_HOLD
    assert any(story_pipeline.LEGACY_NOTE in r for r in _approval_refusal(row))


# ── the same functions ───────────────────────────────────────────────────────


def test_the_legacy_door_runs_exactly_the_desks_post_gate(monkeypatch):
    seen = []
    fact = lambda text, dossier, context=None: seen.append(text) or ["fact: 'x' — planted → fix"]  # noqa: E731
    monkeypatch.setattr(story_pipeline.story_writers, "fact_check", fact)
    g = _G()
    md = _md(FAILING["factual (an ungrounded figure)"])
    _title, gmd, _body = story_pipeline._legacy_text(md)
    desk = g.post(gmd, None)  # what the desk's _Gates.post finds on the same text
    legacy = story_pipeline.legacy_gate_findings(g, md, {"titles": []})
    assert sorted(legacy) == sorted(desk), "the legacy door must run the desk's gate, not a look-alike"
    assert seen and "[Weight:" not in seen[0], "the legacy machine header is a data field, not prose"


# ── one failing check: not approvable ────────────────────────────────────────


def test_a_legacy_draft_failing_any_one_check_is_not_approvable():
    approvable = []
    for which, body in sorted(FAILING.items()):
        row = _row(_audit(_md(body)))
        row["content_markdown"] = body
        if not _approval_refusal(row):
            approvable.append(which)
    assert approvable == [], f"the approve click would publish a draft failing: {approvable}"


def test_a_failing_fact_read_or_a_repeated_title_is_not_approvable():
    planted = lambda *a, **k: ["fact: 'crossed below 290' — the dossier shows 291.2 → correct it"]  # noqa: E731
    assert _approval_refusal(_row(_audit(_md(CLEAN), fact=planted)))
    assert _approval_refusal(_row(_audit(_md(CLEAN), ledger={"titles": [{"week": 9, "title": "Below 290"}]})))


def test_a_check_that_cannot_run_holds_the_draft_and_names_it():
    def down(*a, **k):
        raise TimeoutError("bedrock unavailable")

    findings = _audit(_md(CLEAN), fact=down)
    assert any("the fact read could not run" in f for f in findings), findings
    assert _approval_refusal(_row(findings))


# ── all passing: approvable, unpublished ─────────────────────────────────────


def test_a_legacy_draft_passing_every_check_is_approvable_but_unpublished():
    findings = _audit(_md(CLEAN))
    assert findings[0] == autopublish_audit.LEGACY_CHECKED_NOTE
    row = _row(findings)
    assert row["status"] == "draft" and row["publish_hold"] == story_pipeline.LEGACY_HOLD
    assert _approval_refusal(row) == [], "a clean legacy draft must be approvable by the owner's click"
    # nothing else publishes it: the Panel's legacy writer still waits for the owner
    assert autopublish_audit.legacy_episode_blocking(row, "A clean spoken line.", DATE)
    # the sweep only ever holds (owner ruling 2026-11-13): it has no publish call at all
    src = (_REPO / "lambdas" / "emails" / "chronicle_approve_lambda.py").read_text(encoding="utf-8")
    sweep = src[src.index("def _sweep_stale_drafts") : src.index("# HANDLER")]
    assert "publish_side_effects" not in sweep and "_publish" not in sweep


def test_a_craft_note_on_a_clean_legacy_draft_is_answered_by_the_click_as_on_a_desk_draft():
    findings = _audit(_md(CLEAN)) + ["craft: the dek runs long"]
    row = _row(findings)
    craft = json.loads(row["desk_craft_json"])
    assert "craft: the dek runs long" in craft and all(autopublish_audit.is_style_finding(f) for f in craft), craft
    assert _approval_refusal(row) == []
    assert any(b.startswith("craft hold") for b in autopublish_audit.blocking_items(row)), "the craft note still waits for the click"


def test_the_checked_note_is_never_written_by_the_switch_off_path():
    off = _audit(_md(CLEAN), eligible=False)
    assert autopublish_audit.LEGACY_CHECKED_NOTE not in off
    assert autopublish_audit.LEGACY_HOLD == story_pipeline.LEGACY_HOLD
