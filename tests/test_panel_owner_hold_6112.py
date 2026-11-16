"""tests/test_panel_owner_hold_6112.py — #6112: an owner-held Panel week is HELD, not missing, and nothing publishes it.

Owner ruling 2026-11-16: week 10's episode is intentionally held (its script retained two blocking findings). The
hold is recorded in the existing hold store (`panelcast-holds/wk{N}.json`, hold_class "owner"), its public face is
episodes.json's `held` list, and:

  * qa-smoke's story_season:episode_or_hold distinguishes DELIVERED / HELD / MISSING — only MISSING fails; an empty
    or malformed held line is NOT a hold; a hold past OWNER_HOLD_REVIEW_DAYS WARNs (alarmed), never FAILs.
  * every Panel publisher refuses a held week, and refuses when the hold store cannot be read (fail closed).
  * a new publisher cannot appear without passing the refusal (the set-level sweep at the bottom).

All fixtures are SYNTHETIC — no held script text, no finding text, no journal content. Offline: in-memory S3/DDB fakes,
fixed clocks (no assertion reaches the wall clock).
"""

import ast
import io
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import pytest

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "emails"))
sys.path.insert(0, os.path.join(_REPO, "scripts"))

from emails import (
    coach_panel_podcast_lambda as panel,  # noqa: E402
    panelcast_hold as ph,  # noqa: E402
)
from operational import story_season_qa as ssq  # noqa: E402
from operational.census_probe import ProbeBudget  # noqa: E402
from operational.qa_check import CONTENT_TRUTH, Check  # noqa: E402

UTC = timezone.utc
EP_KEY = f"{panel.PREFIX}/episodes.json"
HOLDS = panel.HOLD_PREFIX
SITE = "https://averagejoematt.com"
PUBLISHED_AT = datetime(2026, 11, 14, 0, 24, 35, tzinfo=UTC)  # synthetic: a week published, then held
SHA = "a" * 64


def _record(week=10, decided="2026-11-16", **over):
    rec = ph.build_record(
        week,
        decided_at=decided,
        decided_by="owner",
        ruling="owner ruling (synthetic)",
        reason="script retained two blocking findings",
        findings=[
            {"id": "desk_findings_json.episode[2]", "category": "fact", "sha256": SHA, "source": "ddb://synthetic", "text": "synthetic"},
            {"id": "desk_findings_json.episode[3]", "category": "fact", "sha256": "b" * 64, "source": "ddb://synthetic", "text": "x"},
        ],
        lift="an explicit owner release only",
    )
    rec.update(over)
    return rec


# ══════════════════════════════════════════════════════════════════════════════
# 1. The record and its public face — one validator, shared by the writer and the check
# ══════════════════════════════════════════════════════════════════════════════


def test_a_built_record_is_complete_and_its_public_line_is_a_hold_the_check_accepts():
    rec = _record()
    assert ph.record_problems(rec) == []
    assert rec["status"] == "held" and rec["status"] not in ("delivered", "missing")
    line = ph.public_entry(rec)
    assert ph.public_problems(line) == []
    assert line == {
        "week": 10,
        "status": "held",
        "held_at": "2026-11-16",
        "decided_by": "owner",
        "reason": "held by the owner: the script retained 2 blocking audit findings",
    }
    # the public line carries no finding text, no finding id, no hash
    assert "synthetic" not in json.dumps(line) and SHA not in json.dumps(line)
    # the check reads with the WRITER's validator — not a re-derivation that can drift
    assert ssq.owner_hold_problems is ph.public_problems


@pytest.mark.parametrize(
    "mutation, problem",
    [
        ({"hold_class": "safety"}, "hold_class"),
        ({"status": "delivered"}, "status"),
        ({"decided_at": ""}, "decided_at"),
        ({"decided_by": " "}, "decided_by"),
        ({"reason": ""}, "reason"),
        ({"lift": ""}, "lift"),
        ({"findings": None}, "findings"),
        ({"findings": [{"id": "x", "category": "fact", "source": "s", "sha256": "nothex"}]}, "sha256"),
        ({"week": "ten"}, "week"),
    ],
)
def test_MUTATION_an_incomplete_record_is_named(mutation, problem):
    rec = _record()
    rec.update(mutation)
    assert any(problem in p for p in ph.record_problems(rec))


# ══════════════════════════════════════════════════════════════════════════════
# 2. The check: delivered / held / missing — and the malformed-hold control
# ══════════════════════════════════════════════════════════════════════════════

WEEKS = {9: {"published": PUBLISHED_AT - timedelta(days=7)}, 10: {"published": PUBLISHED_AT}}
EP9 = {"week": 9, "title": "EP9 · Synthetic", "date": "2026-11-07", "url": "/panelcast/wk9.mp3"}
EP10 = {"week": 10, "title": "EP10 · Synthetic", "date": "2026-11-14", "url": "/panelcast/wk10.mp3"}
NOW = datetime(2026, 11, 16, 19, 0, tzinfo=UTC)  # past week 10's 48 h window


def _doc(episodes, held=None):
    doc = {"episodes": list(episodes)}
    if held is not None:
        doc["held"] = held
    return doc


def test_DELIVERED_every_week_with_an_episode_row():
    v = ssq.episode_verdicts(WEEKS, _doc([EP10, EP9]), NOW)
    assert v["delivered"] == ["week 9", "week 10"] and not v["missing"] and not v["held"]


def test_HELD_a_valid_owner_hold_is_named_and_aged_never_missing():
    v = ssq.episode_verdicts(WEEKS, _doc([EP9], [ph.public_entry(_record())]), NOW)
    assert v["missing"] == [] and v["escalated"] == [] and v["aged"] == []
    assert len(v["held"]) == 1 and v["held"][0].startswith("week 10 HELD by owner since 2026-11-16 (0.8 d)")


def test_MISSING_neither_an_episode_nor_a_hold():
    v = ssq.episode_verdicts(WEEKS, _doc([EP9]), NOW)
    assert v["held"] == [] and len(v["missing"]) == 1 and v["missing"][0].startswith("week 10 ")


@pytest.mark.parametrize(
    "line",
    [
        {},  # empty marker
        {"week": 10},  # names the week, nothing else
        {"week": 10, "held_at": "2026-11-16", "decided_by": "owner", "reason": ""},  # no reason
        {"week": 10, "held_at": "2026-11-16", "decided_by": "", "reason": "r"},  # no decider
        {"week": 10, "held_at": "not-a-date", "decided_by": "owner", "reason": "r"},  # undated
        "week 10 held",  # not an object
    ],
)
def test_MALFORMED_an_empty_or_incomplete_held_line_is_not_a_hold(line):
    v = ssq.episode_verdicts(WEEKS, _doc([EP9], [line]), NOW)
    assert v["held"] == [] and len(v["missing"]) == 1 and v["missing"][0].startswith("week 10 ")


def test_MUTATION_a_hold_on_another_week_excuses_nothing():
    v = ssq.episode_verdicts(WEEKS, _doc([EP9], [ph.public_entry(_record(week=11))]), NOW)
    assert len(v["missing"]) == 1 and v["missing"][0].startswith("week 10 ")


def test_AGED_an_owner_hold_past_the_review_bound_is_aged_not_missing():
    old = ph.public_entry(_record(decided="2026-10-01"))
    v = ssq.episode_verdicts(WEEKS, _doc([EP9], [old]), NOW)
    assert v["missing"] == [] and v["held"] == [] and len(v["aged"]) == 1


# ── end to end through check_story_season: the verdict each state produces ──


class _Table:
    def __init__(self, rows):
        self.rows = rows

    def query(self, **kw):
        prefix = kw["KeyConditionExpression"].get_expression()["values"][1].get_expression()["values"][1]
        return {"Items": [r for r in self.rows if str(r["sk"]).startswith(prefix)]}


ROWS = [
    {"sk": "DATE#2026-11-03", "date": "2026-11-03", "status": "published", "week_number": "9", "approved_at": "2026-11-07T00:00:00+00:00"},
    {"sk": "DATE#2026-11-10", "date": "2026-11-10", "status": "published", "week_number": "10", "approved_at": PUBLISHED_AT.isoformat()},
    {"sk": "LEDGER#2026-11-03"},
    {"sk": "LEDGER#2026-11-10"},
]


def _episode_check(doc, now=NOW):
    def opener(url, timeout):
        return 200, json.dumps(doc)

    out = ssq.check_story_season(
        _Table(ROWS), "USER#matthew#SOURCE#", Check, CONTENT_TRUTH, lambda: now, site_base_url=SITE, budget=ProbeBudget(opener=opener)
    )
    return next(c for c in out if c.name == ssq.EPISODE_CHECK)


def test_check_delivered_is_green():
    c = _episode_check(_doc([EP10, EP9]))
    assert c.passed is True and "2 of the 2 published season week(s) delivered" in c.message


def test_check_held_is_green_and_names_the_hold_and_its_age():
    c = _episode_check(_doc([EP9], [ph.public_entry(_record())]))
    assert c.passed is True and not c.chronic
    assert "week 10 HELD by owner since 2026-11-16" in c.message and "blocking audit findings" in c.message


def test_check_missing_fails():
    c = _episode_check(_doc([EP9]))
    assert c.passed is False and "week 10" in c.message and "silently skipped" in c.message


def test_check_malformed_hold_fails_and_says_why():
    c = _episode_check(_doc([EP9], [{"week": 10, "held_at": "2026-11-16", "decided_by": "owner"}]))
    assert c.passed is False and "not accepted as a hold (no reason)" in c.message


def test_check_an_aged_owner_hold_WARNS_alarmed_and_never_fails():
    c = _episode_check(_doc([EP9], [ph.public_entry(_record(decided="2026-10-01"))]))
    assert c.passed is None and c.chronic is False  # yellow, counted by qa-smoke-warnings; never qa-smoke-failures
    assert f"older than {ssq.OWNER_HOLD_REVIEW_DAYS} days" in c.message and "week 10" in c.message


def test_the_review_bound_counts_from_the_decided_day():
    """held_at is a day; its age counts from that midnight UTC. A day inside the bound is green, a day past it WARNs."""
    inside = (NOW - timedelta(days=ssq.OWNER_HOLD_REVIEW_DAYS - 1)).date().isoformat()
    past = (NOW - timedelta(days=ssq.OWNER_HOLD_REVIEW_DAYS + 1)).date().isoformat()
    assert _episode_check(_doc([EP9], [ph.public_entry(_record(decided=inside))])).passed is True
    assert _episode_check(_doc([EP9], [ph.public_entry(_record(decided=past))])).passed is None


# ══════════════════════════════════════════════════════════════════════════════
# 3. The refusal — every publisher, fail closed
# ══════════════════════════════════════════════════════════════════════════════


class _NoSuchKey(Exception):
    response = {"Error": {"Code": "NoSuchKey"}}


class _FakeS3:
    def __init__(self, list_raises=None):
        self.store = {}
        self.writes = []
        self.list_raises = list_raises
        self.exceptions = type("E", (), {"NoSuchKey": _NoSuchKey})

    def put_object(self, Bucket, Key, Body, **kw):
        self.writes.append(("put", Key))
        self.store[Key] = Body if isinstance(Body, bytes) else Body.encode("utf-8")

    def get_object(self, Bucket, Key, **kw):
        if Key not in self.store:
            raise _NoSuchKey(Key)
        return {"Body": io.BytesIO(self.store[Key])}

    def delete_object(self, Bucket, Key, **kw):
        self.writes.append(("delete", Key))
        self.store.pop(Key, None)

    def list_objects_v2(self, Bucket, Prefix, **kw):
        if self.list_raises:
            raise self.list_raises
        return {"Contents": [{"Key": k} for k in sorted(self.store) if k.startswith(Prefix)], "IsTruncated": False}


def _seeded(weeks=(10,), list_raises=None):
    fs = _FakeS3(list_raises=list_raises)
    for w in weeks:
        fs.store[f"{HOLDS}/wk{w}.json"] = json.dumps(_record(week=w)).encode()
    fs.store[f"{HOLDS}/wk6.json"] = json.dumps({"week": 6, "hold_class": "safety", "reasons": ["synthetic"]}).encode()
    fs.store[f"{HOLDS}/wk6.retired.json"] = json.dumps({"week": 6}).encode()
    fs.store[EP_KEY] = json.dumps({"episodes": [EP9]}).encode()
    return fs


@pytest.fixture
def wired(monkeypatch):
    def wire(fs):
        monkeypatch.setattr(panel, "s3", fs)
        monkeypatch.setattr(panel, "_invalidate_cdn", lambda: None)
        monkeypatch.setattr(panel, "EXPERIMENT_START_DATE", "2026-09-06")
        monkeypatch.setattr(panel, "_published_posts", lambda: [{"week": w, "date": d, "title": f"Week {w}"} for w, d in POSTS])
        return fs

    return wire


POSTS = [(8, "2026-10-27"), (9, "2026-11-03"), (10, "2026-11-10")]


def test_owner_held_weeks_reads_only_owner_records():
    fs = _seeded(weeks=(8, 10))
    assert sorted(ph.owner_held_weeks(fs, "b", HOLDS)) == [8, 10]  # wk6 is an automated hold; .retired.json is not a hold


def test_FAIL_CLOSED_an_unreadable_store_raises_never_reads_as_none_held():
    with pytest.raises(ph.HoldStateUnreadable):
        ph.owner_held_weeks(_FakeS3(list_raises=RuntimeError("AccessDenied")), "b", HOLDS)
    fs = _seeded()
    fs.store[f"{HOLDS}/wk7.json"] = b"{not json"
    with pytest.raises(ph.HoldStateUnreadable):
        ph.owner_held_weeks(fs, "b", HOLDS)


def test_chokepoint_publish_episode_audio_refuses_a_held_week_before_any_put(wired):
    fs = wired(_seeded())
    with pytest.raises(ph.HeldWeekRefused):
        panel._publish_episode_audio(10, b"RIFF....")
    assert fs.writes == []


def test_chokepoint_publish_episode_audio_fails_closed_when_the_store_is_unreadable(wired):
    fs = wired(_seeded(list_raises=RuntimeError("AccessDenied")))
    with pytest.raises(ph.HoldStateUnreadable):
        panel._publish_episode_audio(11, b"RIFF....")
    assert fs.writes == []


def test_chokepoint_write_indexes_refuses_a_feed_that_lists_a_held_week(wired):
    fs = wired(_seeded())
    with pytest.raises(ph.HeldWeekRefused):
        panel._write_indexes([EP10, EP9])
    assert fs.writes == []


def test_write_indexes_carries_the_held_line_re_derived_from_the_store(wired):
    fs = wired(_seeded(weeks=(8, 10)))
    fs.store[EP_KEY] = json.dumps({"episodes": [EP9], "held": [{"week": 3, "bogus": True}]}).encode()  # a stale line
    panel._write_indexes([EP9])
    doc = json.loads(fs.store[EP_KEY])
    assert [h["week"] for h in doc["held"]] == [8, 10]  # from the private records; the stale line is gone
    assert all(ph.public_problems(h) == [] for h in doc["held"])
    assert "<itunes:episode>10<" not in fs.store[f"{panel.PREFIX}/feed.xml"].decode()


@pytest.mark.parametrize(
    "event",
    [
        {},  # the chronicle-approve async invoke / a manual run: the newest week is the held one
        {"source": "chronicle-approve"},
        {"week": 10},
        {"week": 10, "force": True},
        {"week": 10, "owner_approved": True},  # approval answers an audit; it does not release an owner hold
        {"week": 10, "force": True, "owner_approved": True},
    ],
)
def test_every_weekly_invoke_shape_refuses_the_held_week_before_generation(wired, monkeypatch, event):
    """The DLQ consumer re-drives a failed async invoke with its ORIGINAL payload, so these shapes are also every
    redrive and every Lambda async retry."""
    fs = wired(_seeded())
    monkeypatch.setattr(panel, "_desk_episode", lambda post: pytest.fail("a held week reached the script read"))
    monkeypatch.setattr(panel, "_gather_week", lambda *a, **k: pytest.fail("a held week reached generation"))
    out = json.loads(
        panel._run_weekly(bool(event.get("force")), week=event.get("week"), approved=event.get("owner_approved") is True)["body"]
    )
    assert out == {"week": 10, "held": "owner"}
    assert fs.writes == []


def test_weekly_run_refuses_when_the_store_is_unreadable(wired, monkeypatch):
    fs = wired(_seeded(list_raises=RuntimeError("AccessDenied")))
    monkeypatch.setattr(panel, "_desk_episode", lambda post: pytest.fail("generated with no proof the week is not held"))
    resp = panel._run_weekly(False)
    assert resp["statusCode"] == 503 and json.loads(resp["body"])["refused"] == "hold state unreadable"
    assert fs.writes == []


def test_dry_run_reports_the_owner_hold_skip(wired):
    wired(_seeded())
    out = json.loads(panel._run_weekly(False, dry_run=True)["body"])
    assert out["would"] == "SKIP" and out["stage"] == "owner-hold"


def test_MUTATION_CONTROL_with_no_hold_the_same_invoke_reaches_the_desk_render(wired, monkeypatch):
    """Without the record the week proceeds — so the refusals above are the hold's doing, not a broken fixture."""
    wired(_seeded(weeks=()))
    reached = []
    monkeypatch.setattr(panel, "_episode_exists", lambda week: None)
    monkeypatch.setattr(panel, "_desk_episode", lambda post: {"turns": [{"speaker": "elena", "line": "x"}]})
    monkeypatch.setattr(panel, "_publish_desk_episode", lambda week, post, ep, dry_run=False: reached.append(week) or {"body": "{}"})
    panel._run_weekly(False)
    assert reached == [10]


def test_the_hold_sweep_never_retries_an_owner_hold(wired):
    fs = wired(_seeded())
    out = panel._sweep_held_episodes()
    assert out["swept"] == [] and "owner hold" in out["skipped"]
    assert fs.writes == []


def test_an_automated_hold_never_overwrites_the_owners_record(wired, monkeypatch):
    fs = wired(_seeded())
    monkeypatch.setattr(panel, "sns", None, raising=False)
    before = fs.store[f"{HOLDS}/wk10.json"]
    panel._hold_and_alert(10, ["synthetic"], {"turns": []}, hold_class="safety")
    assert fs.store[f"{HOLDS}/wk10.json"] == before


def test_weeks_8_and_9_are_refused_by_the_same_path_once_recorded(wired):
    wired(_seeded(weeks=(8, 9, 10)))
    for w in (8, 9, 10):
        with pytest.raises(ph.HeldWeekRefused):
            panel._publish_episode_audio(w, b"RIFF")


def test_weeks_8_and_9_are_refused_today_even_without_a_record_their_chapters_are_unpublished(wired, monkeypatch):
    """Today's independent refusal for 8-9: the Panel selects only PUBLISHED chapters (posts.json), so a named week
    whose chapter is held has no post and the run raises before any read of its script."""
    wired(_seeded(weeks=()))
    monkeypatch.setattr(panel, "_published_posts", lambda: [{"week": 10, "date": "2026-11-10", "title": "Week 10"}])
    for w in (8, 9):
        with pytest.raises(ValueError, match="no current-cycle chronicle post"):
            panel._run_weekly(False, week=w)


def test_season_promote_refuses_a_held_week_before_any_write(monkeypatch):
    import season_promote as sp

    fs = _seeded(weeks=(4,))
    import boto3

    monkeypatch.setattr(boto3, "client", lambda *a, **k: fs)
    assert sp.owner_hold_gate([3, 4], ["chronicle", "panel"]) and "week 4 is held" in sp.owner_hold_gate([3, 4], ["panel"])[0]
    assert sp.owner_hold_gate([3, 4], ["chronicle", "pages"]) == []  # no panel step, nothing to refuse
    monkeypatch.setattr(boto3, "client", lambda *a, **k: _FakeS3(list_raises=RuntimeError("AccessDenied")))
    assert "fail closed" in sp.owner_hold_gate([3], ["panel"])[0]


# ══════════════════════════════════════════════════════════════════════════════
# 4. The writer script — dry-run writes nothing, and nothing private is printed
# ══════════════════════════════════════════════════════════════════════════════


class _Row:
    def __init__(self, item):
        self.item = item

    def get_item(self, Key):
        return {"Item": self.item} if Key["sk"] == self.item["sk"] else {}


def _row():
    findings = {"post": [], "episode": ["craft: synthetic note", "fact: SYNTHETIC-PRIVATE-ONE", "fact: SYNTHETIC-PRIVATE-TWO"]}
    return {
        "sk": "DATE#2026-11-10",
        "week_number": 10,
        "status": "published",
        "desk_findings_json": json.dumps(findings),
        "desk_episode_json": json.dumps({"turns": [{"speaker": "elena", "line": "SYNTHETIC-SCRIPT"}]}),
    }


def _args(**over):
    import panel_owner_hold as poh

    ns = poh.argparse.Namespace(
        week=10,
        row="DATE#2026-11-10",
        expect_findings=2,
        decided="2026-11-16",
        decided_by="owner",
        ruling="r",
        reason="script retained two blocking findings",
        public_reason="",
        refs="#6112",
        re_record=False,
        apply=False,
        backup_dir=None,
    )
    for k, v in over.items():
        setattr(ns, k, v)
    return poh, ns


def test_writer_dry_run_builds_a_complete_record_writes_nothing_and_prints_no_private_text(capsys):
    poh, args = _args()
    fs = _FakeS3()
    fs.store[EP_KEY] = json.dumps({"episodes": [EP9]}).encode()
    assert poh.apply_hold(args, _Row(_row()), fs) == 0
    out = capsys.readouterr().out
    assert fs.writes == []
    assert "SYNTHETIC-PRIVATE" not in out and "SYNTHETIC-SCRIPT" not in out
    rec = poh.build(args, _Row(_row()), fs)
    assert ph.record_problems(rec) == [] and [f["id"] for f in rec["findings"]] == [
        "desk_findings_json.episode[1]",
        "desk_findings_json.episode[2]",
    ]
    assert [f["category"] for f in rec["findings"]] == ["fact", "fact"] and rec["findings"][0]["text"].startswith("fact: SYNTHETIC")


def test_writer_refuses_a_count_mismatch_an_aired_week_and_a_missing_backup_dir():
    poh, args = _args(expect_findings=3)
    with pytest.raises(SystemExit, match="--expect-findings says 3"):
        poh.build(args, _Row(_row()), _FakeS3())
    poh, args = _args()
    fs = _FakeS3()
    fs.store[EP_KEY] = json.dumps({"episodes": [EP10]}).encode()
    with pytest.raises(SystemExit, match="has a published episode"):
        poh.apply_hold(args, _Row(_row()), fs)
    poh, args = _args(apply=True)
    fs.store[EP_KEY] = json.dumps({"episodes": [EP9]}).encode()
    with pytest.raises(SystemExit, match="--backup-dir"):
        poh.apply_hold(args, _Row(_row()), fs)
    assert fs.writes == []


def test_writer_public_doc_re_derives_held_and_drops_the_weeks_pending_marker():
    poh, _ = _args()
    fs = _seeded()
    doc = poh.public_doc(fs, {"episodes": [EP9], "pending": {"week": 10, "reason": "held_for_review"}}, 10)
    assert "pending" not in doc and doc["held"] == [ph.public_entry(_record())]


# ══════════════════════════════════════════════════════════════════════════════
# 5. The SET — every Panel publisher passes the refusal
# premerge-gate: sweeps git ls-files for every first-party writer of the Panel's public prefix, so a new file reds it
# ══════════════════════════════════════════════════════════════════════════════

# A file that names the Panel's public prefix (or calls the Panel's publish functions) AND writes is a publisher. Each
# one is listed with HOW it is refused, and the reason is checked against the source where it can be.
_PANEL_TOKENS = re.compile(
    r"generated/panelcast|\bPANEL_PREFIX\b|panel\._publish_episode_audio|panel\._write_indexes|"
    r"_g\[[\"']_publish_episode_audio[\"']\]|_g\[[\"']_write_indexes[\"']\]|_g\[[\"']PREFIX[\"']\]"
)
_WRITE_TOKENS = re.compile(r"put_object|_publish_episode_audio\(|_write_indexes\(|upload_file|copy_object")
PUBLISHERS = {
    "lambdas/emails/coach_panel_podcast_lambda.py": "chokepoint: _publish_episode_audio + _write_indexes call panelcast_hold.refuse; "
    "_run_weekly skips an owner-held week before generation (run_skip)",
    "lambdas/emails/panelcast_desk.py": "renders through _g['_publish_episode_audio'] (refuses before its PUT) and writes the "
    "transcript only after it; indexes through _g['_write_indexes']",
    "lambdas/emails/panelcast_retire.py": "writes episodes.json's retired list for a week that never aired; publishes no episode",
    "scripts/season_promote.py": "owner_hold_gate before any write + the lambda's chokepoints in apply_panel",
    "scripts/panel_recut.py": "re-cuts an already-aired week only, through _publish_episode_audio + _write_indexes",
    "scripts/panel_owner_hold.py": "the hold writer itself: writes the hold record and the public held line, never an episode",
    "deploy/repair_published_content_4674.py": "one-shot rewrite of the week-2 row's title in the existing index; adds no week",
    "deploy/restart_media_reset.py": "restart tombstones (media_tombstone: not an episode); publishes no episode",
}
# the refusal a publisher must call, checked in source
_REFUSAL_CALLS = {
    "lambdas/emails/coach_panel_podcast_lambda.py": ("_panel_hold().refuse(", "_panel_hold().run_skip("),
    "scripts/season_promote.py": ("owner_hold_gate(weeks, steps)",),
    "scripts/panel_recut.py": ("panel._publish_episode_audio(", "panel._write_indexes("),
    "lambdas/emails/panelcast_desk.py": ('_g["_publish_episode_audio"](', '_g["_write_indexes"]('),
}


def _tracked_sources():
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "lambdas", "scripts", "deploy", "mcp"],
        cwd=_REPO,
        capture_output=True,
        text=True,
        check=True,
    )
    return [p for p in out.stdout.split() if p.endswith(".py")]


def test_SET_every_panel_publisher_is_registered_with_its_refusal():
    found = set()
    for rel in _tracked_sources():
        src = open(os.path.join(_REPO, rel), encoding="utf-8").read()
        if _PANEL_TOKENS.search(src) and _WRITE_TOKENS.search(src) and rel != "lambdas/emails/panelcast_hold.py":
            found.add(rel)
    unregistered = sorted(found - set(PUBLISHERS))
    assert not unregistered, (
        f"{unregistered} write near the Panel's public prefix and are not in PUBLISHERS. A Panel publisher must refuse an "
        "owner-held week (emails/panelcast_hold.refuse, fail closed) — publish through _publish_episode_audio/_write_indexes, "
        "or register it here with the reason it publishes no episode (#6112)."
    )
    stale = sorted(set(PUBLISHERS) - found)
    assert not stale, f"PUBLISHERS lists files that no longer publish (prune them): {stale}"
    for rel, calls in _REFUSAL_CALLS.items():
        src = open(os.path.join(_REPO, rel), encoding="utf-8").read()
        assert all(c in src for c in calls), f"{rel} no longer calls {calls}"


def test_SET_both_chokepoints_call_the_refusal_first():
    """The refusal is the FIRST statement of each chokepoint (after the docstring) — nothing is written before it."""
    tree = ast.parse(open(os.path.join(_REPO, "lambdas/emails/coach_panel_podcast_lambda.py"), encoding="utf-8").read())
    fns = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    for name in ("_publish_episode_audio", "_write_indexes"):
        body = [s for s in fns[name].body if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))]
        assert "_panel_hold().refuse(" in ast.unparse(body[0]), f"{name} does not refuse a held week before anything else"


# ══════════════════════════════════════════════════════════════════════════════
# 6. The reader's face — the Story door says the episode is on hold, never "yet"
# ══════════════════════════════════════════════════════════════════════════════


def test_the_edition_says_a_held_episode_is_on_hold_with_no_private_detail():
    from web import site_api_edition as ed

    doc = {"episodes": [EP9], "held": [ph.public_entry(_record())]}
    held = ed._podcast_part(doc, 10, lambda _: None)
    assert held["state"] == "absent" and held["absent_text"] == "This chapter's podcast episode is on hold."
    assert "finding" not in json.dumps(held) and "owner" not in json.dumps(held)
    # control: the same week with no held line still reads "yet"
    assert ed._podcast_part({"episodes": [EP9]}, 10, lambda _: None)["absent_text"] == "No podcast episode for this chapter yet."
