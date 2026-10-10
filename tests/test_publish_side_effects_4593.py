"""#4593 — one function owns chronicle-approve's publish-time side effects; every publish path calls it.

2026-10-02 the season promote (scripts/season_promote.py) published the rebuilt week 4 by writing the chronicle row
directly. The side effects lived inline in chronicle-approve's two publish paths, so the third path ran none of them:
no share kit (qa-smoke's hook-liveness leg red on generated/moments/share-kits/week-07/kit.json), no delivery email
and no recorded decision not to send one (chronicle-delivery-heartbeat in ALARM).

Pinned here:
  A. contract — the approve click, the stale-draft sweep and the season promote all call
     `chronicle_approve_lambda.publish_side_effects`, and no publish path calls a side-effect helper around it.
  B. the owner — every name in SIDE_EFFECTS runs, is declined with a reason, or is deferred; nothing is silent.
  C. the promote, end to end over a fake table shaped like the live partition: the week-4 row gets its share kit at
     week-07 (the slot its page renders at), the recall index runs, delivery is declined WITH a no-send stamp on the
     row, and the effects a promote step owns (recap, ledger, panel, mark-published) never fire twice.
  D. the sender honours the stamp — a no-send row is never mailed by the cron inside its 7-day window.

Mutation control (run by hand, recorded in the PR): replacing season_promote.apply_effects' call to
`approve.publish_side_effects(...)` with `{}` fails test_every_publish_path_calls_the_one_owner and
test_promote_effects_write_the_week_07_kit_and_stamp_no_send.
"""

from __future__ import annotations

import ast
import importlib
import json
import os
import sys
from unittest import mock

import pytest

for _k, _v in {
    "TABLE_NAME": "life-platform",
    "S3_BUCKET": "matthew-life-platform",
    "USER_ID": "matthew",
    "AWS_REGION": "us-west-2",
}.items():
    os.environ.setdefault(_k, _v)

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (
    os.path.join(_REPO, "lambdas"),
    os.path.join(_REPO, "lambdas", "emails"),
    os.path.join(_REPO, "deploy"),
    os.path.join(_REPO, "scripts"),
):
    if _p not in sys.path:
        sys.path.insert(0, _p)

approve = importlib.import_module("chronicle_approve_lambda")
sp = importlib.import_module("season_promote")
cel = importlib.import_module("chronicle_email_sender_lambda")

_APPROVE_SRC = os.path.join(_REPO, "lambdas", "emails", "chronicle_approve_lambda.py")
_PROMOTE_SRC = os.path.join(_REPO, "scripts", "season_promote.py")

# the helpers that ARE side effects — only publish_side_effects (and the sweep's one batch trigger) may call them
_HELPERS = {
    "_publish_to_s3",
    "_invalidate_cloudfront",
    "_commit_recap",
    "_commit_ledger",
    "_mark_published",
    "_index_for_recall",
    "_invoke_email_sender",
    "_invoke_elena_state_updater",
    "_invoke_coach_panel_podcast",
}


def _functions(path):
    tree = ast.parse(open(path, encoding="utf-8").read())
    return {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}


def _called(fn):
    out = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Call):
            f = n.func
            out.add(f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", ""))
        elif isinstance(n, ast.Name):  # a helper passed as a value (the runners table) counts as a call site
            out.add(n.id)
    return out


# ── A. contract ──────────────────────────────────────────────────────────────


def test_every_publish_path_calls_the_one_owner():
    fa = _functions(_APPROVE_SRC)
    fp = _functions(_PROMOTE_SRC)
    missing = [
        name
        for name, fn in (("approve _handle", fa["_handle"]), ("sweep", fa["_sweep_stale_drafts"]), ("promote", fp["apply_effects"]))
        if "publish_side_effects" not in _called(fn)
    ]
    assert missing == [], f"publish path(s) that bypass publish_side_effects: {missing}"
    assert "apply_effects" in _called(fp["main"]), "season_promote.main never runs the effects step"
    assert "effects" in sp.STEPS


def test_no_publish_path_calls_a_side_effect_helper_around_the_owner():
    fa = _functions(_APPROVE_SRC)
    offenders = {}
    for name in ("_handle", "_sweep_stale_drafts"):
        direct = _called(fa[name]) & _HELPERS
        if name == "_sweep_stale_drafts":
            direct -= {"_invoke_email_sender", "_invoke_coach_panel_podcast"}  # the batch's one trigger for what it defers
        if direct:
            offenders[name] = sorted(direct)
    owner = _called(fa["publish_side_effects"]) & _HELPERS
    assert offenders == {}, f"side effects called outside publish_side_effects: {offenders}"
    assert owner == _HELPERS, f"publish_side_effects does not own: {sorted(_HELPERS - owner)}"


# ── B. the owner ─────────────────────────────────────────────────────────────


@pytest.fixture
def rec(monkeypatch):
    calls = []
    for h in sorted(_HELPERS - {"_invalidate_cloudfront", "_publish_to_s3"}):
        monkeypatch.setattr(approve, h, lambda *a, _h=h, **k: calls.append(_h))
    monkeypatch.setattr(approve, "_publish_to_s3", lambda item, failures=None: calls.append("_publish_to_s3") or ["/x"])
    monkeypatch.setattr(approve, "_invalidate_cloudfront", lambda paths: calls.append("_invalidate_cloudfront"))
    return calls


def test_approve_runs_every_side_effect_in_order(rec, monkeypatch):
    row = {"sk": "DATE#2026-10-06", "date": "2026-10-06", "status": "draft", "approval_token": "t" * 64, "week_number": 5}
    monkeypatch.setattr(approve, "_get_draft", lambda d: row)
    resp = approve._handle({"queryStringParameters": {"date": "2026-10-06", "token": "t" * 64, "action": "approve"}})
    assert resp["statusCode"] == 200
    assert rec == [
        "_publish_to_s3",
        "_invalidate_cloudfront",
        "_commit_recap",
        "_commit_ledger",
        "_mark_published",
        "_index_for_recall",
        "_invoke_email_sender",
        "_invoke_elena_state_updater",
        "_invoke_coach_panel_podcast",
    ]


def test_the_result_names_every_side_effect(rec, monkeypatch):
    monkeypatch.setattr(approve, "_record_no_send", lambda item, d, r: f"declined: {r} (no-send decision recorded)")
    out = approve.publish_side_effects(
        {"sk": "DATE#d"}, "d", decline={"recap": "owned elsewhere", "delivery": "owner"}, defer=("panel_podcast",)
    )
    assert list(out) == list(approve.SIDE_EFFECTS)
    assert out["recap"] == "declined: owned elsewhere" and out["panel_podcast"] == "deferred" and out["s3_artifacts"] == "ran"
    assert out["delivery"].startswith("declined: owner")
    assert "_commit_recap" not in rec and "_invoke_email_sender" not in rec and "_invoke_coach_panel_podcast" not in rec


def test_a_decline_must_name_a_real_effect_and_a_reason(rec):
    cases = [
        ({"decline": {"share_kitt": "typo"}}, "unknown"),
        ({"decline": {"recap": "  "}}, "needs a reason"),
        ({"defer": ("recap",)}, "can be deferred"),
        ({"decline": {"delivery": "x"}, "defer": ("delivery",)}, "both declined and deferred"),
    ]
    accepted = []
    for kwargs, match in cases:
        try:
            approve.publish_side_effects({"sk": "DATE#d"}, "d", **kwargs)
            accepted.append(kwargs)
        except ValueError as exc:
            if match not in str(exc):
                accepted.append((kwargs, str(exc)))
    assert accepted == [], f"malformed declines not refused as expected: {accepted}"
    assert rec == [], "a malformed decline ran side effects before refusing"


def test_record_no_send_stamps_the_row_and_never_overwrites_a_delivery(monkeypatch):
    t = mock.MagicMock()
    monkeypatch.setattr(approve, "table", t)
    out = approve._record_no_send({"sk": "DATE#2026-07-21", "date": "2026-09-05"}, "2026-09-05", "owner declined")
    kw = t.update_item.call_args.kwargs
    assert kw["Key"]["sk"] == "DATE#2026-07-21"  # the row's own sk, not DATE#{date}
    assert kw["ExpressionAttributeValues"][":d"] == "no-send" and "attribute_not_exists(delivered_at)" in kw["ConditionExpression"]
    assert "recorded" in out
    t.reset_mock()
    out = approve._record_no_send({"sk": "DATE#x", "delivered_at": "2026-09-25T18:00Z"}, "x", "owner declined")
    t.update_item.assert_not_called()
    assert "already delivered" in out


# ── C. the promote, end to end ───────────────────────────────────────────────

_PK = "USER#matthew#SOURCE#chronicle"


def _row(sk, date, week, **extra):
    r = {
        "pk": _PK,
        "sk": sk,
        "date": date,
        "week_number": week,
        "status": "published",
        "phase": "experiment",
        "title": f"Title {sk}",
        "stats_line": "Day 22-28 · 301.2 lbs (-1.4 this week) · 5 training sessions",
        "content_markdown": f'"Title {sk}"\n\n'
        + "The week opened on a measured morning and kept its own counsel through every reading. " * 3,
        "draft_share_kit_json": '{"canonical_url": "https://averagejoematt.com/journal/posts/week-99/"}',  # a STALE draft kit
        "desk_ledger_json": '{"date": "stale"}',
    }
    r.update(extra)
    return r


# the live partition's visible rows on 2026-10-09 (read-only probe): week 4 is the 7th by (date, sk) → week-07
_LIVE = [
    _row("DATE#2026-02-28", "2026-02-28", 0),
    _row("DATE#2026-07-21", "2026-09-05", 1, unlisted=True),
    _row("DATE#2026-09-05", "2026-09-05", 0),
    _row("DATE#2026-09-08", "2026-09-08", 1, delivered_at="2026-09-11T18:00:47Z"),
    _row("DATE#2026-09-15", "2026-09-15", 2, delivered_at="2026-09-18T18:00:47Z"),
    _row("DATE#2026-09-22", "2026-09-22", 3, delivered_at="2026-09-25T18:00:47Z"),
    _row("DATE#2026-09-29", "2026-09-29", 4),
]


class _FakeTable:
    def __init__(self, rows):
        self.rows = {r["sk"]: dict(r) for r in rows}
        self.updates = []
        self.puts = []

    def query(self, **kw):
        return {"Items": [dict(r) for r in self.rows.values()]}

    def get_item(self, Key):
        r = self.rows.get(Key["sk"])
        return {"Item": dict(r)} if r else {}

    def update_item(self, **kw):
        self.updates.append(kw)

    def put_item(self, Item):
        self.puts.append(Item)


def _run_promote_effects(monkeypatch, sks, deliver=False):
    ft = _FakeTable(_LIVE)
    s3_puts, invokes, recall = [], [], []
    fake_boto3 = mock.MagicMock()
    fake_boto3.resource.return_value.Table.return_value = ft
    monkeypatch.setitem(sys.modules, "boto3", fake_boto3)
    monkeypatch.setattr(approve, "table", ft)
    monkeypatch.setattr(approve.s3, "put_object", lambda **kw: s3_puts.append(kw))
    monkeypatch.setattr(approve.cf, "create_invalidation", lambda **kw: None)
    monkeypatch.setattr(approve.lam, "invoke", lambda **kw: invokes.append(kw["FunctionName"]))
    monkeypatch.setattr(approve, "CHRONICLE_EMAIL_SENDER_ARN", "arn:chronicle-email-sender")
    monkeypatch.setattr(approve, "_index_for_recall", lambda d, sk="": recall.append((d, sk)))
    results = sp.apply_effects(sks, deliver=deliver)
    return ft, s3_puts, invokes, recall, results


def test_promote_effects_write_the_week_07_kit_and_stamp_no_send(monkeypatch):
    ft, s3_puts, invokes, recall, results = _run_promote_effects(monkeypatch, ["DATE#2026-09-29"])
    keys = [p["Key"] for p in s3_puts]
    assert keys == ["generated/moments/share-kits/week-07/kit.json"], keys  # the kit only — never a draft page/manifest
    kit = json.loads(s3_puts[0]["Body"])
    assert kit["canonical_url"] == "https://averagejoematt.com/journal/posts/week-07/" and kit["title"] == "Title DATE#2026-09-29"
    assert recall == [("2026-09-29", "")]  # sk="" default: the plain DATE#{date} row
    stamp = [u for u in ft.updates if ":d" in u.get("ExpressionAttributeValues", {})]
    assert len(stamp) == 1 and stamp[0]["Key"]["sk"] == "DATE#2026-09-29" and stamp[0]["ExpressionAttributeValues"][":d"] == "no-send"
    assert invokes == [], f"the promote fired {invokes} — delivery/Elena/Panel are declined here"
    assert ft.puts == [], "the promote re-wrote a recap/ledger row its own steps own"
    assert not [u for u in ft.updates if "approved_at" in u.get("UpdateExpression", "")], "mark_published ran on a promoted row"
    assert set(results["DATE#2026-09-29"]) == set(approve.SIDE_EFFECTS)


def test_promote_effects_with_deliver_invokes_the_sender_and_stamps_nothing(monkeypatch):
    monkeypatch.setattr(sp, "_sender_pick", lambda: {"sk": "DATE#2026-09-29"})
    ft, s3_puts, invokes, recall, results = _run_promote_effects(monkeypatch, ["DATE#2026-09-29"], deliver=True)
    assert invokes == ["arn:chronicle-email-sender"]
    assert not [u for u in ft.updates if ":d" in u.get("ExpressionAttributeValues", {})]
    assert results["DATE#2026-09-29"]["delivery"] == "ran"


def test_a_redated_unlisted_row_keeps_its_own_slot_and_recall_key(monkeypatch):
    """DATE#2026-07-21 is dated 2026-09-05 — the kit follows the sk ordering, and recall is told the sk."""
    ft, s3_puts, invokes, recall, results = _run_promote_effects(monkeypatch, ["DATE#2026-07-21"])
    assert [p["Key"] for p in s3_puts] == ["generated/moments/share-kits/week-02/kit.json"]
    assert recall == [("2026-09-05", "DATE#2026-07-21")]


def test_promote_refuses_a_row_that_is_not_published(monkeypatch):
    rows = [dict(r) for r in _LIVE]
    rows[-1]["status"] = "draft"
    monkeypatch.setattr(sys.modules[__name__], "_LIVE", rows)
    with pytest.raises(SystemExit, match="not published"):
        _run_promote_effects(monkeypatch, ["DATE#2026-09-29"])


def test_effects_only_dry_run_writes_nothing(monkeypatch, capsys):
    monkeypatch.setattr(sp, "apply_effects", lambda *a, **k: pytest.fail("dry run applied"))
    assert sp.main(["--effects-only", "--weeks", "4"]) == 0
    out = capsys.readouterr().out
    assert "DATE#2026-09-29" in out and "no-send" not in out and sp.NO_DELIVER_REASON in out


def test_deliver_takes_exactly_one_week():
    with pytest.raises(SystemExit, match="exactly one week"):
        sp.main(["--effects-only", "--weeks", "0-4", "--deliver"])


# ── D. the sender honours the stamp ──────────────────────────────────────────


def test_sender_never_mails_a_row_carrying_a_no_send_decision(monkeypatch):
    row = _row("DATE#2026-09-29", "2026-09-29", 4, delivery_decision="no-send", delivery_decision_reason="owner")
    monkeypatch.setattr(cel.table, "query", lambda **kw: {"Items": [row]})
    assert cel._get_this_weeks_installment() is None
    row.pop("delivery_decision")  # control: the same row without the stamp IS deliverable
    assert cel._get_this_weeks_installment()["sk"] == "DATE#2026-09-29"


# ── E. #4729: the printed effect map is proof of what happened ───────────────


def test_deliver_on_a_week_the_sender_would_not_mail_is_skipped_not_ran(monkeypatch):
    """The sender mails the NEWEST in-window row; naming an older week must not invoke it nor report delivery=ran."""
    monkeypatch.setattr(sp, "_sender_pick", lambda: {"sk": "DATE#2026-10-06"})
    ft, s3_puts, invokes, recall, results = _run_promote_effects(monkeypatch, ["DATE#2026-09-29"], deliver=True)
    assert invokes == [], "the sender was invoked although it would mail a different row"
    assert results["DATE#2026-09-29"]["delivery"].startswith("skipped: not the sender's newest in-window row")
    assert not [u for u in ft.updates if ":d" in u.get("ExpressionAttributeValues", {})], "a skip must not stamp a no-send decision"
    monkeypatch.setattr(sp, "_sender_pick", lambda: None)
    _, _, invokes, _, results = _run_promote_effects(monkeypatch, ["DATE#2026-09-29"], deliver=True)
    assert invokes == [] and results["DATE#2026-09-29"]["delivery"].startswith("skipped:")


def test_a_failed_share_kit_put_reports_s3_artifacts_failed(monkeypatch):
    ft, s3_puts, invokes, recall, results = _run_promote_effects(monkeypatch, ["DATE#2026-09-29"])
    assert results["DATE#2026-09-29"]["s3_artifacts"] == "ran"  # control

    def boom(**kw):
        raise RuntimeError("AccessDenied")

    monkeypatch.setattr(approve.s3, "put_object", boom)
    monkeypatch.setattr(approve.cf, "create_invalidation", lambda **kw: None)
    only_s3 = {e: "not under test" for e in approve.SIDE_EFFECTS if e not in ("s3_artifacts", "delivery")}
    only_s3["delivery"] = "not under test"
    monkeypatch.setattr(approve, "_record_no_send", lambda item, d, r: "declined")
    item = {"sk": "DATE#x", "phase": "experiment", "draft_share_kit_json": '{"canonical_url": "https://x/week-1/"}'}
    out = approve.publish_side_effects(item, "x", decline=only_s3)
    assert out["s3_artifacts"].startswith("failed: share kit write failed") and "AccessDenied" in out["s3_artifacts"]
