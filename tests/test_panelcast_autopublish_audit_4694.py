"""tests/test_panelcast_autopublish_audit_4694.py — #4694 (owner ruling 2026-10-11): the Panel's LEGACY writer — the
Mon/Wed cron and the SS-02 hold sweep — publishes only with the owner's approval or a passed audit, the contract the
chronicle stale-draft sweep has (content/autopublish_audit.py, PR #4728). Editor + QA alone is no longer enough.

Driven end to end through ``_run_weekly`` and ``_sweep_held_episodes`` with every side effect captured: the hold
(no approval, no passed audit), the audited publish, the owner-approved publish, and the fail-closed edges."""

from __future__ import annotations

import io
import json
import os
import sys
from datetime import datetime, timedelta, timezone

for k, v in {
    "TABLE_NAME": "life-platform",
    "S3_BUCKET": "matthew-life-platform",
    "USER_ID": "matthew",
    "AWS_REGION": "us-west-2",
    "AWS_DEFAULT_REGION": "us-west-2",
    "EMAIL_RECIPIENT": "test@example.com",
    "EMAIL_SENDER": "noreply@example.com",
}.items():
    os.environ.setdefault(k, v)

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "emails"))

from ai import budget_guard, gemini_tts  # noqa: E402
from content import autopublish_audit  # noqa: E402
from emails import coach_panel_podcast_lambda as panel  # noqa: E402

DATE = "2026-10-06"
WEEK = 5
CLEAN_AUDIT = json.dumps({"post": [], "episode": []})
WEEK5_POST_FINDINGS = json.dumps(
    {"post": ["ungrounded number: 23-day training streak — the dossier says 9"], "episode": ["craft: the cold open runs long"]}
)


class _S3:
    def __init__(self):
        self.store: dict = {}

    def put_object(self, Bucket, Key, Body, **kw):
        self.store[Key] = Body if isinstance(Body, bytes) else Body.encode("utf-8")

    def get_object(self, Bucket, Key, **kw):
        if Key not in self.store:
            raise Exception(f"NoSuchKey {Key}")
        return {"Body": io.BytesIO(self.store[Key])}

    def delete_object(self, Bucket, Key, **kw):
        self.store.pop(Key, None)


class _Table:
    """The chronicle row the audit reads, by key; `boom` makes the read raise (an audit that cannot run)."""

    def __init__(self, row=None, boom=False):
        self.row, self.boom, self.reads = row, boom, []

    def get_item(self, Key):
        self.reads.append(Key)
        if self.boom:
            raise RuntimeError("ddb throttled")
        return {"Item": self.row} if self.row is not None and Key["sk"] == f"DATE#{DATE}" else {}


def _row(**extra):
    return {
        "pk": "USER#matthew#SOURCE#chronicle",
        "sk": f"DATE#{DATE}",
        "status": "published",
        "generated_at": f"{DATE}T15:00:00Z",
        **extra,
    }


def _turns():
    lines = ["A steady week.", "Sleep held.", "Why did it hold?", "Earlier nights.", "And training?", "Ordinary, and that is fine."]
    return [{"speaker": panel.ELENA if i % 2 == 0 else "marcus_webb", "line": s} for i, s in enumerate(lines)]


def _wire(monkeypatch, table):
    """The legacy writer, offline, with every gate before #4694's passing — so the only thing that can hold is the audit."""
    seen: dict = {"held": [], "audio": 0}
    post = {"week": WEEK, "date": DATE, "title": "The Rest Day"}
    beats = {
        "week": WEEK,
        "date": DATE,
        "title": "The Rest Day",
        "chronicle": "A steady week.",
        "coach_reads": [{"name": "Marcus Webb", "summary": "Sleep held."}],
        "guest": {"id": "marcus_webb", "name": "Marcus Webb"},
    }
    fs = _S3()
    monkeypatch.setattr(budget_guard, "current_tier", lambda *a, **k: 0)
    monkeypatch.setattr(panel, "table", table)
    monkeypatch.setattr(panel, "s3", fs)
    monkeypatch.setattr(panel, "_select_week_post", lambda *a: dict(post))
    monkeypatch.setattr(panel, "_episode_exists", lambda week: None)
    monkeypatch.setattr(panel, "_episode_published", lambda week: False)
    monkeypatch.setattr(panel, "_desk_episode", lambda p: None)  # no desk script: the LEGACY writer runs
    monkeypatch.setattr(panel, "_load_bible", lambda: {})
    monkeypatch.setattr(panel, "_state_read", lambda: {})
    monkeypatch.setattr(panel, "_gather_week", lambda p, st: dict(beats))
    monkeypatch.setattr(panel, "_sensitivity_hold_reasons", lambda b: [])
    monkeypatch.setattr(panel._zeitgeist, "fetch_zeitgeist", lambda: [])
    monkeypatch.setattr(panel._zeitgeist, "zeitgeist_truth_block", lambda z: "")
    monkeypatch.setattr(panel, "_build_weekly_script_v2", lambda b, bible: {"turns": _turns(), "episode_title": "A Steady Week"})
    monkeypatch.setattr(panel, "_editor_review", lambda turns, bible: {"verdict": "pass"})
    monkeypatch.setattr(panel, "_weekly_gate", lambda turns, allowed, gid: (list(turns), []))
    monkeypatch.setattr(panel._repair, "repair_structure", lambda clean, *a, **k: (clean, 0, 0))
    monkeypatch.setattr(panel._repair, "log_ledger", lambda *a, **k: None)
    monkeypatch.setattr(panel, "_craft_check", lambda clean: [])
    monkeypatch.setattr(panel._craft, "punch_up_script", lambda clean, *a, **k: (clean, False))
    monkeypatch.setattr(panel, "_qa_review", lambda clean, rubric, gt: (True, []))
    monkeypatch.setattr(panel, "_craft_judge", lambda clean, rubric: (True, [], []))
    # the hold: the real _hold_and_alert writes the private draft; SNS/pending/outcome are captured
    monkeypatch.setattr(panel, "_set_pending", lambda *a, **k: None)
    monkeypatch.setattr(panel, "_emit_outcome", lambda reason: seen.setdefault("outcomes", []).append(reason))

    class _SNS:
        def publish(self, **kw):
            seen["held"].append(kw)

    monkeypatch.setattr(panel.boto3, "client", lambda *a, **k: _SNS())
    # the publish: every side effect after the gates
    monkeypatch.setattr(gemini_tts, "synthesize_dialogue", lambda *a, **k: seen.__setitem__("audio", seen["audio"] + 1) or b"RIFF")
    monkeypatch.setattr(panel, "_gemini_voice", lambda pid: "voice")
    monkeypatch.setattr(panel, "_publish_episode_audio", lambda week, audio: {"url": "u", "bytes": 4, "duration_sec": 1})
    monkeypatch.setattr(panel, "_state_write", lambda st: None)
    monkeypatch.setattr(panel, "_write_indexes", lambda eps: seen.setdefault("episodes", eps))
    monkeypatch.setattr(panel, "_write_show_memory", lambda *a, **k: None)
    monkeypatch.setattr(panel, "_emit_published_metric", lambda: None)
    monkeypatch.setattr(panel, "_notify_new_episode", lambda ep: None)
    return seen, fs


def _hold_record(fs):
    return json.loads(fs.store[f"{panel.HOLD_PREFIX}/wk{WEEK}.json"])


# ── the hold: neither approval nor a passed audit ───────────────────────────


class _Log:
    def __init__(self):
        self.errors: list = []

    def error(self, msg, *args):
        self.errors.append(msg % args)

    def info(self, *a, **k):
        pass

    warning = info


def test_the_cron_holds_a_legacy_week_with_no_audit_on_record_and_names_it(monkeypatch):
    """The Mon/Wed cron's shape (no keys). Editor + QA passed; the chronicle row carries no desk audit — HOLD, loudly."""
    seen, fs = _wire(monkeypatch, _Table(_row()))
    log = _Log()
    monkeypatch.setattr(panel, "logger", log)
    out = json.loads(panel.lambda_handler({}, None)["body"])
    assert out["held"] is True and out["hold_class"] == "safety"  # human review only — the sweep never retries it
    assert seen["audio"] == 0 and "episodes" not in seen  # nothing synthesized, nothing in the feed
    rec = _hold_record(fs)
    assert any(r.startswith("autopublish-audit: no audit on record") for r in rec["reasons"]), rec["reasons"]
    assert rec["draft"]["turns"]  # the QA-passed script is kept for the human
    assert seen["held"] and f"wk{WEEK}" in seen["held"][0]["Subject"]
    lines = [ln for ln in log.errors if ln.startswith(autopublish_audit.PANEL_HELD_TOKEN)]
    assert len(lines) == 1 and f"wk{WEEK} ({DATE}) held" in lines[0] and "owner_approved" in lines[0], lines
    assert seen["outcomes"] == ["held-safety"]


def test_a_blocking_post_finding_on_the_chronicle_holds_the_episode(monkeypatch):
    seen, fs = _wire(monkeypatch, _Table(_row(desk_findings_json=WEEK5_POST_FINDINGS)))
    out = json.loads(panel._run_weekly(force=False)["body"])
    assert out["held"] is True and seen["audio"] == 0
    assert any("23-day training streak" in r for r in _hold_record(fs)["reasons"])


def test_an_audit_that_cannot_run_holds_the_week(monkeypatch):
    seen, fs = _wire(monkeypatch, _Table(boom=True))
    out = json.loads(panel._run_weekly(force=False)["body"])
    assert out["held"] is True and seen["audio"] == 0
    assert any("the audit could not run" in r for r in _hold_record(fs)["reasons"])


def test_a_tombstoned_chronicle_row_is_no_record(monkeypatch):
    seen, _fs = _wire(monkeypatch, _Table(_row(desk_findings_json=CLEAN_AUDIT, tombstone=True)))
    assert json.loads(panel._run_weekly(force=False)["body"])["held"] is True and seen["audio"] == 0


def test_the_dry_run_reports_the_audit_hold(monkeypatch):
    seen, fs = _wire(monkeypatch, _Table(_row()))
    out = json.loads(panel._run_weekly(force=False, dry_run=True)["body"])
    assert out["would"] == "HOLD" and out["stage"] == "autopublish-audit"
    assert fs.store == {} and seen["held"] == []  # a dry run writes nothing


def test_the_hold_sweep_cannot_publish_an_unapproved_unaudited_week(monkeypatch):
    """SS-02: a quality hold aged past the window regenerates through _run_weekly — and the audit gate holds it again,
    as a human-only hold the sweep will not retry a second time."""
    seen, fs = _wire(monkeypatch, _Table(_row()))
    aged = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%d")
    fs.store[f"{panel.HOLD_PREFIX}/wk{WEEK}.json"] = json.dumps(
        {"week": WEEK, "reasons": ["weekly-qa: flat"], "draft": {}, "held_at": aged, "first_held_at": aged, "hold_class": "quality"}
    ).encode()
    out = json.loads(panel.lambda_handler({"sweep_holds": True}, None)["body"])
    assert out["retried"] is True and out["published"] is False
    assert seen["audio"] == 0
    rec = _hold_record(fs)
    assert rec["hold_class"] == "safety" and any(r.startswith("autopublish-audit: ") for r in rec["reasons"])
    assert json.loads(json.dumps(panel._sweep_held_episodes()))["skipped"].startswith("safety")


# ── the ways through: a passed audit, the owner's approval ──────────────────


def test_an_audited_week_publishes_itself(monkeypatch):
    """Mutation control for every hold above: the same week with a clean desk audit on the chronicle row publishes. The
    episode half of the record is the desk's OWN script, which the legacy writer is not rendering — it does not count."""
    row = _row(desk_findings_json=json.dumps({"post": ["craft: long"], "episode": ["ungrounded number: 41"]}))
    seen, fs = _wire(monkeypatch, _Table(row))
    out = json.loads(panel._run_weekly(force=False)["body"])
    assert out["published"] is True and seen["audio"] == 1
    assert [e["week"] for e in seen["episodes"]] == [WEEK]
    assert fs.store.get(f"{panel.HOLD_PREFIX}/wk{WEEK}.json") is None


def test_the_owner_approved_invoke_publishes_without_an_audit(monkeypatch):
    table = _Table(_row())  # no audit on record — the hold above, unless the owner approved
    seen, _fs = _wire(monkeypatch, table)
    out = json.loads(panel.lambda_handler({"owner_approved": True}, None)["body"])
    assert out["published"] is True and seen["audio"] == 1
    assert table.reads == []  # approval is the other way through: the audit is not consulted


def test_only_a_literal_true_is_an_approval(monkeypatch):
    for event in ({"owner_approved": "true"}, {"owner_approved": 1}, {"approved": True}, {"force": True}):
        seen, _fs = _wire(monkeypatch, _Table(_row()))
        out = json.loads(panel.lambda_handler(event, None)["body"])
        assert out.get("held") is True and seen["audio"] == 0, event


# ── the audit itself ────────────────────────────────────────────────────────


def test_the_episode_text_goes_through_the_reader_door_and_the_weekday_check():
    row = _row(desk_findings_json=CLEAN_AUDIT)
    assert autopublish_audit.legacy_episode_blocking(row, "A steady week.", DATE) == []
    assert autopublish_audit.legacy_episode_blocking(row, "Tuesday, October 6 was quiet.", DATE) == []
    wrong_day = autopublish_audit.legacy_episode_blocking(row, "Monday, October 6 was quiet.", DATE)
    assert wrong_day and "was a Tuesday" in wrong_day[0]
    assert autopublish_audit.legacy_episode_blocking(row, "", DATE) == ["no episode text to audit"]
    assert autopublish_audit.legacy_episode_blocking(None, "A steady week.", DATE)[0].startswith("no audit on record")
