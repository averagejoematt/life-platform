"""#4694 — the stale-draft sweep publishes an unapproved chronicle only when the deterministic audit passes.

Specimen: Week 5 (DATE#2026-10-06). Nobody clicked approve; the 2026-10-09 18:00Z sweep published it while its own row
carried the Story Desk's unresolved findings — a 23-day training streak the dossier contradicts, a "season high" that
was not one, a quote the platform does not hold, and body weights spoken in the episode. ``WEEK5_DESK_FINDINGS`` below
is ABRIDGED from that row's ``desk_findings_json`` as read back from DynamoDB on 2026-10-09 — not the wire verbatim (a
public repo does not carry the production row byte for byte). What is kept exact: every finding's prefix and wrapper
(``craft:``, ``repeat:``, ``quote:``, ``dek: fact:``, ``turn N (elena): body-number:``), which is all the audit reads.
What is abridged: the two dek ``fact:`` explanations are shortened, and the live row's 5th episode finding — a
``fact: 'graded_this_week_count' ... not reportable. → N/A`` non-finding — is carried in abridged form. It is a
non-finding the audit ignores (#4749), so the live row has 3 blocking episode findings, not 4.

The rule held here: an unapproved draft whose audit has a blocking item stays a draft and the sweep logs
``HELD_TOKEN`` naming the week (the ``chronicle-autopublish-held`` alarm keys on it); an audited draft publishes as
before; the approve click is untouched; and the Panel refuses a desk episode the desk left with a blocking finding.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "lambdas"))

from content import autopublish_audit  # noqa: E402

WEEK5_DESK_FINDINGS = {
    "post": [
        "craft: 2 'not X — it's Y' constructions (max 1) — the tic readers flag first as AI",
        'craft: paragraph 3 carries 6 figures (max 3): "Lisa Park is the team\'s most prolific predictor — an AI persona whose domain is sleep arch"',
        'craft: paragraph 7 carries 4 figures (max 3): "Marcus Webb, the team\'s nutritionist — the worst record on the team at 6 right and 18 wron"',
        "craft: paragraph 13 carries 4 figures (max 3): 'The body-composition scan on Day 31 — scale bio-impedance, which carries enough noise that'",
        "craft: paragraph 14 carries 5 figures (max 3): 'The streak question that drove the last two installments has a partial answer. Rest days a'",
        "quote: not exact words the platform holds — paraphrase it without quotation marks: 'His best single logged day came "
        "October 1st at 186g protein, but the running average across 29 logged days is '",
        "repeat: 1 7-word run(s) already used in Week 4, e.g. 'of the measured life a year long' — say it new or cut it",
        "dek: fact: 'After 23 consecutive training days' — The dossier does not support 23 consecutive training days entering "
        "this week. → Remove or verify the '23 consecutive training days' claim.",
        "dek: fact: 'a season high' — The dossier shows the season-to-date recovery high was 99.0 on the morning of "
        "2026-09-25, not 98%. → Change 'a season high'.",
    ],
    "episode": [
        "turn 1 (elena): body-number: '18 pounds'",
        "turn 25 (elena): body-number: '46 pounds'",
        "turn 27 (elena): body-number: '199.8 pounds'",
        "craft: 37 figures across the episode (max 30) — round, gloss, or move to the post",
        # the live row's N/A non-finding, abridged (#4749): the fact reader saying a fact does not apply
        "fact: 'graded_this_week_count' — the dossier field is not reportable for this week. → N/A",
    ],
}


def _iso(hours_ago):
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


def _draft(findings, **extra):
    row = {
        "pk": "USER#matthew#SOURCE#chronicle",
        "sk": "DATE#2026-10-06",
        "date": "2026-10-06",
        "status": "draft",
        "generated_at": _iso(75),
        "week_number": 5,
        "title": "The Rest Day He Took",
        "stats_line": "Day 31 to Day 37 · 6 training sessions",
        "content_markdown": "He took a rest day on Saturday, October 3, and the morning after his recovery read 98%.",
        "draft_journal_posts_json": "{}",
    }
    if findings is not None:
        row["desk_findings_json"] = json.dumps(findings)
    row.update(extra)
    return row


@pytest.fixture
def approve(monkeypatch):
    monkeypatch.setenv("S3_BUCKET", "matthew-life-platform")
    spec = importlib.util.spec_from_file_location(
        "chronicle_approve_lambda_4694", _REPO / "lambdas" / "emails" / "chronicle_approve_lambda.py"
    )
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _run_sweep(mod, drafts):
    with (
        mock.patch.object(mod, "_find_stale_drafts", return_value=drafts),
        mock.patch.object(mod.s3, "put_object") as put,
        mock.patch.object(mod, "_invalidate_cloudfront"),
        mock.patch.object(mod, "_commit_recap"),
        mock.patch.object(mod, "_commit_ledger"),
        mock.patch.object(mod, "_mark_published") as markp,
        mock.patch.object(mod, "_index_for_recall"),
        mock.patch.object(mod, "_invoke_elena_state_updater"),
        mock.patch.object(mod, "_invoke_email_sender") as sender,
        mock.patch.object(mod, "_invoke_coach_panel_podcast") as podcast,
    ):
        out = mod._sweep_stale_drafts(48)
    return out, put, markp, sender, podcast


@pytest.fixture
def held(approve, monkeypatch):
    """Every ERROR line the sweep logs that carries the token — the rendered message the CloudWatch MetricFilter reads.
    (platform_logger's handler binds the real stdout at import, so capsys cannot see it.)"""
    lines = []
    real = approve.logger.error

    def _record(msg, *args, **kw):
        text = msg % args if args else str(msg)
        if autopublish_audit.HELD_TOKEN in text:
            lines.append(text)
        return real(msg, *args, **kw)

    monkeypatch.setattr(approve.logger, "error", _record)
    return lines


# ── the sweep ────────────────────────────────────────────────────────────────


def test_the_week5_specimen_is_held_not_published_and_the_hold_names_the_week(approve, held):
    out, put, markp, sender, podcast = _run_sweep(approve, [_draft(WEEK5_DESK_FINDINGS)])
    assert out == []
    put.assert_not_called()
    markp.assert_not_called()
    sender.assert_not_called()
    podcast.assert_not_called()  # the Panel is never woken by a week that did not publish
    held = held
    assert len(held) == 1, held
    assert "Week 5 (2026-10-06)" in held[0]
    assert "23 consecutive training days" in held[0] and "body-number" in held[0]


def test_an_audited_draft_still_publishes_itself(approve, held):
    """Mutation control: the same week, with only the desk's style notes left, is the 'forgot to click' case SS-01
    exists for — and it goes out exactly as before."""
    style_only = {"post": [f for f in WEEK5_DESK_FINDINGS["post"] if f.startswith(("craft:", "repeat:"))], "episode": []}
    out, put, markp, sender, podcast = _run_sweep(approve, [_draft(style_only)])
    assert out == [{"date": "2026-10-06", "week": 5}]
    markp.assert_called_once_with("2026-10-06")
    sender.assert_called_once()
    podcast.assert_called_once()
    assert held == []


def test_a_draft_with_no_audit_on_record_is_held(approve, held):
    """The legacy writer (or a pre-desk row) leaves no desk record: no audit ran, so the sweep may not publish it."""
    out, put, markp, *_ = _run_sweep(approve, [_draft(None)])
    assert out == [] and not markp.called
    assert "no audit on record" in held[0]


def test_an_audit_that_cannot_run_holds_the_week(approve, held):
    with mock.patch.object(autopublish_audit, "blocking_items", side_effect=RuntimeError("boom")):
        out, put, markp, *_ = _run_sweep(approve, [_draft({"post": [], "episode": []})])
    assert out == [] and not markp.called
    assert "the audit could not run: boom" in held[0]


def test_a_held_week_does_not_stop_an_audited_one_in_the_same_sweep(approve):
    clean = _draft({"post": [], "episode": []}, sk="DATE#2026-09-29", date="2026-09-29", week_number=4)
    out, put, markp, sender, podcast = _run_sweep(approve, [_draft(WEEK5_DESK_FINDINGS), clean])
    assert out == [{"date": "2026-09-29", "week": 4}]
    markp.assert_called_once_with("2026-09-29")


def test_the_dry_run_reports_a_hold_too(approve, held):
    with mock.patch.object(approve, "_find_stale_drafts", return_value=[_draft(WEEK5_DESK_FINDINGS)]):
        assert approve._sweep_stale_drafts(48, dry_run=True) == []
    assert len(held) == 1


def test_the_approve_click_is_still_the_owner_s_way_through(approve):
    """An owner approval publishes the very draft the sweep refuses — the gate is on the UNAPPROVED path only."""
    row = _draft(WEEK5_DESK_FINDINGS, approval_token="t" * 64)
    with (
        mock.patch.object(approve, "_get_draft", return_value=row),
        mock.patch.object(approve, "_publish_to_s3", return_value=[]) as pub,
        mock.patch.object(approve, "_invalidate_cloudfront"),
        mock.patch.object(approve, "_commit_recap"),
        mock.patch.object(approve, "_commit_ledger"),
        mock.patch.object(approve, "_mark_published") as markp,
        mock.patch.object(approve, "_index_for_recall"),
        mock.patch.object(approve, "_invoke_email_sender"),
        mock.patch.object(approve, "_invoke_elena_state_updater"),
        mock.patch.object(approve, "_invoke_coach_panel_podcast"),
    ):
        resp = approve._handle({"queryStringParameters": {"date": "2026-10-06", "token": "t" * 64, "action": "approve"}})
    assert resp["statusCode"] == 200
    pub.assert_called_once_with(row, failures=[])
    markp.assert_called_once_with("2026-10-06")


# ── the audit itself ─────────────────────────────────────────────────────────


def test_style_notes_never_block_and_every_other_finding_does():
    blocking = autopublish_audit.desk_blocking(json.dumps(WEEK5_DESK_FINDINGS))
    assert not any("craft:" in b or "repeat:" in b for b in blocking)
    assert sum(b.startswith("desk post: ") for b in blocking) == 3  # the quote + the two dek facts
    assert sum(b.startswith("desk episode: ") for b in blocking) == 3  # the three spoken body weights
    # an unknown gate the desk adds later blocks until someone decides otherwise
    assert autopublish_audit.desk_blocking(json.dumps({"post": ["newgate: something"], "episode": []})) == ["desk post: newgate: something"]


def test_an_unreadable_audit_record_blocks():
    passed = [
        raw
        for raw in ("{not json", json.dumps(["a"]), json.dumps({"post": "x", "episode": []}))
        if not autopublish_audit.desk_blocking(raw)
    ]
    assert passed == []


def test_a_dated_weekday_must_be_the_real_weekday():
    assert autopublish_audit.weekday_mismatches("He rested on Saturday, October 3.", "2026-10-06") == []
    wrong = autopublish_audit.weekday_mismatches("He rested on Thursday, October 3rd.", "2026-10-06")
    assert len(wrong) == 1 and "2026-10-03 was a Saturday" in wrong[0]
    assert autopublish_audit.weekday_mismatches("on Monday, Sept 31", "2026-10-06")  # not a real date
    # a January installment recalling December reads last year's calendar
    assert autopublish_audit.weekday_mismatches("on Thursday, December 31", "2027-01-05") == []


def test_a_wrong_dated_weekday_in_the_stored_text_blocks_the_sweep(approve, held):
    """The weekday check is wired into blocking_items, not just callable: an otherwise-clean draft that names the wrong
    weekday for a date is held, and the hold carries the weekday finding."""
    wrong = _draft({"post": [], "episode": []}, content_markdown="He took a rest day on Thursday, October 3, and slept.")
    assert [b for b in autopublish_audit.blocking_items(wrong) if b.startswith("dated weekday: ")] == [
        "dated weekday: 'Thursday, October 3' — 2026-10-03 was a Saturday"
    ]
    out, put, markp, *_ = _run_sweep(approve, [wrong])
    assert out == [] and not markp.called
    assert len(held) == 1 and "2026-10-03 was a Saturday" in held[0]


def test_the_stored_text_is_re_run_through_the_reader_door():
    row = _draft({"post": [], "episode": []}, content_markdown="This is the fifteenth reset, and he means it.")
    assert any(b.startswith("reader surface: ") for b in autopublish_audit.blocking_items(row))
    assert autopublish_audit.blocking_items(_draft({"post": [], "episode": []})) == []


# ── the Panel ────────────────────────────────────────────────────────────────


def test_the_panel_holds_a_desk_episode_the_desk_left_unaudited(monkeypatch):
    for k, v in {"TABLE_NAME": "life-platform", "S3_BUCKET": "matthew-life-platform", "AWS_REGION": "us-west-2"}.items():
        monkeypatch.setenv(k, v)
    sys.path.insert(0, str(_REPO / "lambdas" / "emails"))
    from emails import coach_panel_podcast_lambda as panel

    ep = {"title": "The Rest Day", "excerpt": "x", "turns": [{"speaker": "elena", "line": "Day 37."}], "guest": {"name": "Marcus Webb"}}
    row = _draft(WEEK5_DESK_FINDINGS, desk_episode_json=json.dumps(ep))
    table = mock.Mock()
    table.get_item.return_value = {"Item": row}
    monkeypatch.setattr(panel, "table", table)
    got = panel._desk_episode({"date": "2026-10-06"})
    assert len(got["_audit_blocking"]) == 3
    held = json.loads(panel._publish_desk_episode(5, {"date": "2026-10-06"}, got, dry_run=True)["body"])
    assert held["would"] == "HOLD" and any(r.startswith("audit: ") for r in held["reasons"])
    # mutation control: the same script with a style-only record renders
    row["desk_findings_json"] = json.dumps({"post": [], "episode": ["craft: the cold open runs past 70 words"]})
    clean = panel._desk_episode({"date": "2026-10-06"})
    assert json.loads(panel._publish_desk_episode(5, {"date": "2026-10-06"}, clean, dry_run=True)["body"])["would"] == "PUBLISH"


# ── the loud half: one token, three places ───────────────────────────────────


def test_the_held_token_is_one_literal_in_the_lambda_the_module_and_the_metric_filter(approve):
    assert approve.HELD_TOKEN == autopublish_audit.HELD_TOKEN == "CHRONICLE-AUTOPUBLISH-HELD"
    cdk = (_REPO / "cdk" / "stacks" / "monitoring_silence_alarms.py").read_text()
    block = cdk[cdk.index("AutopublishHeldLgChronicleApprove") :]
    assert re.search(r'FilterPattern\.literal\(\'"CHRONICLE-AUTOPUBLISH-HELD"\'\)', block)
    assert '"/aws/lambda/chronicle-approve"' in block[:200]
    assert 'alarm_name="chronicle-autopublish-held"' in block


def _fact_reply_4749(findings):
    """A fact-reader reply in the wire shape ``story_writers.fact_check`` parses (abridged, synthetic findings)."""
    return {"stop_reason": "end_turn", "content": [{"type": "text", "text": json.dumps({"findings": findings})}]}


def _writer_findings_4749(findings):
    from content import story_writers

    return story_writers.fact_check("text", {}, invoke=lambda body, model: _fact_reply_4749(findings))


# (a) Week 5's real shape, abridged: the reader saying a dossier field does not apply, answered N/A.
WEEK5_NA_SHAPE = {"claim": "graded_this_week_count", "problem": "the dossier field is not reportable for this week.", "fix": "N/A"}

# (b) Privacy findings the reader answered with "→ N/A" instead of "remove" (synthetic, abridged). Every one says
# "not reportable"/"does not apply" so ONLY the privacy veto stands between it and being dropped.
PRIVACY_NA_FINDINGS = [
    {"claim": "his 17th start", "problem": "a cycle count is not reportable on a reader surface.", "fix": "N/A"},
    {"claim": "the reset tally", "problem": "reset counts are not reportable.", "fix": "N/A"},
    {"claim": "attempt history", "problem": "the attempt count does not apply to reader copy.", "fix": "N/A"},
    {"claim": "biological_age", "problem": "an owner-only field; not reportable.", "fix": "N/A"},
    {"claim": "what his wife said", "problem": "off the record, not reportable.", "fix": "N/A"},
    {"claim": "the journal entry", "problem": "private; not applicable to the installment.", "fix": "N/A"},
]


def test_week5_na_shape_is_a_non_finding_at_writer_and_audit_4749():
    """(a) Week 5's stored findings re-verdicted: 3 blocking episode findings, not 4. Mutation control: make
    is_na_outcome return False -> 4, and the writer emits the N/A line."""
    blocking = autopublish_audit.desk_blocking(json.dumps(WEEK5_DESK_FINDINGS))
    assert not any("N/A" in b for b in blocking)
    assert len([b for b in blocking if b.startswith("desk episode:")]) == 3
    for prefix in ("fact:", "dek: fact:", "newgate:", "turn 2 (elena): fact:"):
        raw = json.dumps({"post": [f"{prefix} 'x' — not reportable. → N/A"], "episode": [f"{prefix} 'x' — does not apply here. -> n/a."]})
        assert autopublish_audit.desk_blocking(raw) == [], prefix
    out = _writer_findings_4749([WEEK5_NA_SHAPE, {"claim": "23 days", "problem": "dossier says 12", "fix": "say 12 days"}])
    assert len(out) == 1 and "23 days" in out[0]


def test_an_na_fix_alone_is_not_a_non_finding_4749():
    """Narrow: N/A is a non-finding only when the problem SAYS the fact does not apply."""
    for problem in ("nope.", "the dossier says 12, not 23.", "wrong figure."):
        raw = json.dumps({"post": [f"fact: 'x' — {problem} → N/A"], "episode": []})
        assert len(autopublish_audit.desk_blocking(raw)) == 1, problem
        assert len(_writer_findings_4749([{"claim": "x", "problem": problem, "fix": "N/A"}])) == 1, problem
    # a real fix that merely mentions N/A still blocks
    real = json.dumps({"post": ["fact: 'x' — not reportable → write N/A days"], "episode": []})
    assert len(autopublish_audit.desk_blocking(real)) == 1


def test_a_privacy_finding_answered_na_still_blocks_at_writer_and_audit_4749():
    """(b) A privacy finding the reader answered '→ N/A' keeps blocking at BOTH the desk writer and the autopublish
    audit. Mutation control (run): drop the ``touches_privacy`` veto from ``story_checks.is_na_nonfinding`` and every
    case below is dropped at both sites — this test goes red."""
    offenders = []
    out = _writer_findings_4749(PRIVACY_NA_FINDINGS)
    if len(out) != len(PRIVACY_NA_FINDINGS):
        offenders.append(f"writer dropped {len(PRIVACY_NA_FINDINGS) - len(out)} privacy finding(s)")
    # the stored shape the writer emits, built independently so the audit is judged on its own
    stored = [f"fact: {f['claim']!r} — {f['problem']} → {f['fix']}" for f in PRIVACY_NA_FINDINGS]
    for prefix in ("", "dek: ", "turn 3 (elena): "):
        raw = json.dumps({"post": [prefix + s for s in stored], "episode": [prefix + s for s in stored]})
        blocking = autopublish_audit.desk_blocking(raw)
        if len(blocking) != 2 * len(stored):
            offenders.append(f"audit ({prefix or 'bare'}) blocked {len(blocking)} of {2 * len(stored)}")
    assert not offenders, offenders
    # and alongside the Week 5 non-finding, only the privacy line survives
    mixed = _writer_findings_4749([WEEK5_NA_SHAPE, PRIVACY_NA_FINDINGS[0]])
    assert len(mixed) == 1 and "17th start" in mixed[0]
