"""#4622 — the Saturday skipped-habits queue (lambdas/emails/habit_skip_review_lambda.py).

A stored `skipped` is an unconfirmed day (Habitify's bedtime automation marks anything
unlogged). Once a week the owner gets ONE list of them to settle — and nothing at all on a
week with none, while the run is still recorded so the dead-man can tell the two apart.

Fully offline: a fake table answers the habitify Query, a fake SES records sends.

Run:  python3 -m pytest tests/test_habit_skip_review_4622.py -v
"""

import ast
import json
import os
import re
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "lambdas"))
sys.path.insert(0, os.path.join(REPO, "lambdas", "emails"))

import habit_skip_review_lambda as hsr  # noqa: E402

SOURCE_FILE = os.path.join(REPO, "lambdas", "emails", "habit_skip_review_lambda.py")
TODAY = "2026-10-03"  # a Saturday; the window is Sat 09-26 .. Fri 10-02


@pytest.fixture(autouse=True)
def _frozen_clock(monkeypatch):
    """Freeze the handler's own Pacific clock to the fixture's TODAY, so a path that does
    not pass `today` explicitly can never drift onto the real date (#2376)."""
    monkeypatch.setattr(hsr, "pacific_today", lambda: TODAY)


def _hs(status, periodicity="daily", **kw):
    return {"status": status, "periodicity": periodicity, "group": "Hygiene", **kw}


def _row(date, statuses):
    return {"pk": "USER#matthew#SOURCE#habitify", "sk": f"DATE#{date}", "date": date, "habit_statuses": statuses}


class _Table:
    def __init__(self, items):
        self.items = items
        self.queries = []

    def query(self, **kwargs):
        self.queries.append(kwargs)
        vals = kwargs["ExpressionAttributeValues"]
        lo, hi = vals[":s"], vals[":e"]
        return {"Items": [i for i in self.items if i["pk"] == vals[":pk"] and lo <= i["sk"] <= hi]}


class _Ses:
    def __init__(self):
        self.sent = []

    def send_email(self, **kwargs):
        self.sent.append(kwargs)
        return {"MessageId": "m-1"}


def _emf_lines(capsys):
    out = []
    for line in capsys.readouterr().out.splitlines():
        try:
            doc = json.loads(line)
        except ValueError:
            continue
        if isinstance(doc, dict) and "_aws" in doc:
            out.append(doc)
    return out


WEEK_WITH_SKIPS = [
    _row("2026-09-25", {"Floss": _hs("skipped")}),  # outside the window (8 days back)
    _row("2026-09-29", {"Floss": _hs("skipped"), "Mouthwash": _hs("skipped"), "Cold Shower": _hs("completed")}),
    _row("2026-09-30", {"Floss": _hs("completed"), "Mouthwash": _hs("failed", miss_source="vendor")}),
    _row("2026-10-01", {"Cold Shower": _hs("skipped"), "Sauna": _hs("skipped", periodicity="monthly")}),
    _row("2026-10-03", {"Floss": _hs("skipped")}),  # today — not closed, not in the window
]


def test_the_window_is_the_seven_closed_pacific_days_before_today():
    assert hsr.window_dates(TODAY) == [
        "2026-09-26",
        "2026-09-27",
        "2026-09-28",
        "2026-09-29",
        "2026-09-30",
        "2026-10-01",
        "2026-10-02",
    ]


def test_a_week_with_skips_renders_one_line_per_day(capsys):
    table, ses = _Table(WEEK_WITH_SKIPS), _Ses()
    out = hsr._run({"today": TODAY}, None, table=table, ses=ses)
    assert out["skipped_days"] == 2 and out["skipped_habits"] == 3 and out["sent"] is True
    assert len(ses.sent) == 1
    msg = ses.sent[0]
    assert msg["Destination"] == {"ToAddresses": [hsr.RECIPIENT]}
    text = msg["Content"]["Simple"]["Body"]["Text"]["Data"]
    assert "Tue 09-29: Floss, Mouthwash" in text
    assert "Thu 10-01: Cold Shower" in text
    assert "/habitify review" in text
    # Only the window, only skips, only daily habits:
    assert "09-25" not in text and "10-03" not in text  # outside the window
    assert "Sauna" not in text  # a monthly habit's day status is a period judgement
    day_lines = [ln for ln in text.splitlines() if re.match(r"^[A-Z][a-z]{2} \d{2}-\d{2}: ", ln)]
    assert day_lines == ["Tue 09-29: Floss, Mouthwash", "Thu 10-01: Cold Shower"]  # exactly two day lines, oldest first
    html_body = msg["Content"]["Simple"]["Body"]["Html"]["Data"]
    assert "Tue 09-29: Floss, Mouthwash" in html_body
    # The query read the habitify partition for the window only.
    q = table.queries[0]["ExpressionAttributeValues"]
    assert q[":pk"] == "USER#matthew#SOURCE#habitify"
    assert q[":s"] == "DATE#2026-09-26" and q[":e"].startswith("DATE#2026-10-02")
    emf = _emf_lines(capsys)
    assert len(emf) == 1 and emf[0][hsr.RUN_METRIC] == 1 and emf[0][hsr.HABITS_METRIC] == 3 and emf[0][hsr.DAYS_METRIC] == 2


def test_an_empty_week_sends_nothing_and_still_records_the_run(capsys):
    rows = [_row("2026-09-29", {"Floss": _hs("completed"), "Mouthwash": _hs("failed", miss_source="vendor")})]
    ses = _Ses()
    out = hsr._run({"today": TODAY}, None, table=_Table(rows), ses=ses)
    assert ses.sent == []
    assert out["sent"] is False and out["skipped_habits"] == 0
    emf = _emf_lines(capsys)
    assert len(emf) == 1, "an empty week must still emit its run record — that is what the dead-man tells apart"
    assert emf[0][hsr.RUN_METRIC] == 1 and emf[0][hsr.HABITS_METRIC] == 0
    assert emf[0]["_aws"]["CloudWatchMetrics"][0]["Namespace"] == "LifePlatform/Email"


def test_no_stored_rows_at_all_is_an_empty_week_not_a_crash(capsys):
    ses = _Ses()
    out = hsr._run({"today": TODAY}, None, table=_Table([]), ses=ses)
    assert ses.sent == [] and out["skipped_days"] == 0
    assert len(_emf_lines(capsys)) == 1


def test_a_dry_run_never_sends_and_returns_the_lines_to_the_invoker(capsys):
    ses = _Ses()
    out = hsr._run({"today": TODAY, "dry_run": True}, None, table=_Table(WEEK_WITH_SKIPS), ses=ses)
    assert ses.sent == []
    assert out["sent"] is False and out["dry_run"] is True
    assert out["lines"] == ["Tue 09-29: Floss, Mouthwash", "Thu 10-01: Cold Shower"]


def test_habit_names_never_reach_logs_or_metrics(capsys, caplog):
    """PRIVACY: names live only in the owner email body. The logs (including the dry-run
    send line, which prints the subject) and the EMF record carry counts."""
    caplog.set_level("INFO")
    hsr._run({"today": TODAY, "dry_run": True}, None, table=_Table(WEEK_WITH_SKIPS), ses=_Ses())
    printed = capsys.readouterr().out
    logged = "\n".join(r.getMessage() for r in caplog.records)
    for name in ("Floss", "Mouthwash", "Cold Shower", "Sauna"):
        assert name not in printed, f"{name} printed to stdout"
        assert name not in logged, f"{name} logged"
    subject, _, _ = hsr.build_email([("2026-09-29", ["Floss"])], hsr.window_dates(TODAY))
    assert "Floss" not in subject


def test_a_row_without_periodicity_is_treated_as_daily():
    queue = hsr.collect_skips({"2026-09-29": {"habit_statuses": {"Floss": {"status": "skipped"}}}}, ["2026-09-29"])
    assert queue == [("2026-09-29", ["Floss"])]


def test_non_daily_skips_are_excluded():
    leaked = [
        p
        for p in ("weekly", "monthly")
        if hsr.collect_skips({"2026-09-29": {"habit_statuses": {"Sauna": _hs("skipped", p)}}}, ["2026-09-29"])
    ]
    assert not leaked, f"non-daily periodicities queued as owed days: {leaked}"


def test_the_lambda_makes_no_ai_call_and_reads_no_secret():
    """The least-privilege role (no Bedrock, no secrets, no S3) is only honest while the
    code needs none of them."""
    tree = ast.parse(open(SOURCE_FILE, encoding="utf-8").read())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
            imported |= {f"{node.module}.{a.name}" for a in node.names}
    banned = ("bedrock", "secret", "ai_calls", "s3")
    hits = sorted(m for m in imported if any(b in m.lower() for b in banned))
    assert not hits, f"habit-skip-review imports {hits}; its role grants none of that"
    src = open(SOURCE_FILE, encoding="utf-8").read()
    assert "put_item" not in src and "update_item" not in src, "the role grants no DynamoDB write"


def test_the_role_is_query_only_on_the_habitify_partition():
    """Read from SOURCE (AST), not by importing role_policies: other test files stub
    aws_cdk.aws_iam with a PolicyStatement that drops `conditions`, so an import-based
    check would see a different object depending on test order."""
    path = os.path.join(REPO, "cdk", "stacks", "role_policies_email.py")
    tree = ast.parse(open(path, encoding="utf-8").read())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "email_habit_skip_review")
    stmts = []
    for call in ast.walk(fn):
        if isinstance(call, ast.Call) and getattr(call.func, "attr", None) == "PolicyStatement":
            kw = {k.arg: k.value for k in call.keywords}
            stmts.append(
                {
                    "sid": ast.literal_eval(kw["sid"]),
                    "actions": ast.literal_eval(kw["actions"]),
                    "conditions": ast.literal_eval(kw["conditions"]) if "conditions" in kw else None,
                }
            )
    actions = sorted({a for s in stmts for a in s["actions"]})
    assert actions == ["dynamodb:Query", "kms:Decrypt", "ses:SendEmail", "sesv2:SendEmail", "sqs:SendMessage"]
    ddb = next(s for s in stmts if s["sid"] == "HabitifyPartitionRead")
    assert ddb["conditions"] == {"ForAllValues:StringEquals": {"dynamodb:LeadingKeys": ["USER#matthew#SOURCE#habitify"]}}
    assert all(s["conditions"] is None for s in stmts if s["sid"] != "HabitifyPartitionRead")
    assert not any(a.startswith("dynamodb:") for s in stmts if s["sid"] != "HabitifyPartitionRead" for a in s["actions"])
