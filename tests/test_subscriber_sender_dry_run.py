"""#2111 — subscriber-facing senders must honor {"dry_run": true} with zero SES calls.

`chronicle-email-sender` had no dry_run gate at all: any diagnostic invoke — including
the house-convention `{"dry_run": true}` payload — was a live send to every confirmed
subscriber. `daily_brief_lambda` (DRY_RUN gate) and `between_chronicle_lambda`
(`event.get("dry_run")`) were the in-repo precedent; this closes the gap on the one
lambda where a mistaken invoke reaches OUTSIDE readers.

Guard the SET, not the instance: the list of subscriber-facing senders is derived from
the `email_stack.py` "SUBSCRIBER-facing senders (...)" comment, not hardcoded here — a
sender added to that comment without a dry_run rig below fails this test loudly, so the
gate can't silently go stale the next time a fourth sender joins the list.
"""

import json
import os
import re
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (os.path.join(_REPO, "lambdas"), os.path.join(_REPO, "lambdas", "emails"), os.path.join(_REPO, "lambdas", "compute")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _derive_subscriber_facing_senders() -> list[str]:
    """Parse the function names out of email_stack.py's "SUBSCRIBER-facing senders
    (...)" comment — the SET, read from source, never a copy pasted into this file."""
    stack_src = open(os.path.join(_REPO, "cdk/stacks/email_stack.py")).read()
    m = re.search(r"SUBSCRIBER-facing senders\s*\(([^()]*?)\)", stack_src)
    assert m, "email_stack.py's 'SUBSCRIBER-facing senders (...)' comment moved/changed — update the derivation regex"
    raw = re.sub(r"#", " ", m.group(1)).replace("\n", " ")
    names = [n.strip() for n in raw.split(",") if n.strip()]
    assert names, "derivation found zero senders — check the comment format"
    return names


def _module_name_for_function(function_name: str) -> str:
    """Map a function_name (as it appears in the stack comment / CDK wiring) to its
    importable flat module name via ci/lambda_map.json — the same map deploy tooling
    uses, so this never drifts from what actually deploys under that name."""
    lm = json.load(open(os.path.join(_REPO, "ci/lambda_map.json")))
    for source_file, meta in lm["lambdas"].items():
        if meta.get("function") == function_name:
            return os.path.splitext(os.path.basename(source_file))[0]
    raise AssertionError(f"ci/lambda_map.json has no entry mapping to function {function_name!r}")


# ── Per-sender dry_run rigs ────────────────────────────────────────────────────
# Each rig monkeypatches that lambda's data-fetch functions to deterministic fixtures
# (so the render path has real content to build from) and returns
# (module, expected_recipient_count_or_None). expected_recipient_count is asserted
# against the dry_run response's "recipient_count" field when not None — chronicle-
# email-sender and weekly-signal report it; between-chronicle's existing (already-
# shipped) dry_run contract doesn't, so that rig returns None.


def _rig_chronicle_email_sender(monkeypatch):
    import chronicle_email_sender_lambda as m

    installment = {
        "title": "Test Installment",
        "week_number": 9,
        "date": "2026-08-05",
        "content_html": "<p>one</p><p>two</p>",
        "status": "published",
    }
    subs = [{"email": "reader1@example.com", "status": "confirmed"}]
    monkeypatch.setattr(m, "_get_this_weeks_installment", lambda: installment)
    monkeypatch.setattr(m, "_get_confirmed_subscribers", lambda: subs)
    return m, len(subs)


def _rig_weekly_signal(monkeypatch):
    import weekly_signal_lambda as m

    subs = [{"email": "reader2@example.com", "status": "confirmed"}]
    monkeypatch.setattr(m, "_s3_json", lambda key: None)
    monkeypatch.setattr(m, "_get_weekly_insight", lambda: None)
    monkeypatch.setattr(m, "_get_confirmed_subscribers", lambda: subs)
    return m, len(subs)


def _rig_between_chronicle(monkeypatch):
    import between_chronicle_lambda as m

    digest = {
        "deltas": [
            {
                "label": "Recovery",
                "this_month_avg": 62.1,
                "prior_month_avg": 58.4,
                "delta": 3.7,
                "unit": "%",
                "direction": "improved",
            }
        ],
        "unlocked": [],
        "decided": [],
        "stance_shifts": [],
    }
    monkeypatch.setattr(m, "gather_digest", lambda: digest)

    class _T:
        def get_item(self, Key):
            return {}

    monkeypatch.setattr(m, "table", _T())
    return m, None  # between-chronicle's existing dry_run contract has no recipient_count


_RIGS = {
    "chronicle-email-sender": _rig_chronicle_email_sender,
    "weekly-signal": _rig_weekly_signal,
    "between-chronicle": _rig_between_chronicle,
}


def test_dry_run_covers_every_subscriber_facing_sender(monkeypatch):
    senders = _derive_subscriber_facing_senders()
    missing_rig = [s for s in senders if s not in _RIGS]
    assert not missing_rig, (
        f"subscriber-facing sender(s) {missing_rig} have no dry_run test rig in this file — "
        "add a dry_run gate to the lambda AND a _rig_* entry here before shipping"
    )

    for function_name in senders:
        _module_name_for_function(function_name)  # asserts wiring resolves; raises if not
        mod, expected_recipients = _RIGS[function_name](monkeypatch)

        def _no_send(**kw):
            raise AssertionError(f"{function_name}: dry_run must not call ses.send_email")

        monkeypatch.setattr(mod.ses, "send_email", _no_send)

        out = mod.lambda_handler({"dry_run": True}, None)

        assert out.get("statusCode") == 200, f"{function_name}: dry_run must return 200"
        assert out.get("dry_run") is True, f"{function_name}: dry_run event must set dry_run=True in the response"
        assert out.get("subject"), f"{function_name}: dry_run must return a rendered subject"
        assert out.get("html_bytes", 0) > 0, f"{function_name}: dry_run must return non-zero html_bytes"
        if expected_recipients is not None:
            assert out.get("recipient_count") == expected_recipients, f"{function_name}: recipient_count mismatch"


def test_chronicle_email_sender_dry_run_sends_zero_normal_path_sends(monkeypatch):
    """#2111 acceptance (2): dry_run makes zero SES calls; the normal event path
    (mocked SES) still sends."""
    import chronicle_email_sender_lambda as cel

    installment = {
        "title": "Test Installment",
        "week_number": 9,
        "date": "2026-08-05",
        "content_html": "<p>one</p><p>two</p>",
        "status": "published",
    }
    subs = [{"email": "reader1@example.com", "status": "confirmed"}]
    monkeypatch.setattr(cel, "_get_this_weeks_installment", lambda: installment)
    monkeypatch.setattr(cel, "_get_confirmed_subscribers", lambda: subs)

    def _no_send(**kw):
        raise AssertionError("dry_run must not call ses.send_email")

    monkeypatch.setattr(cel.ses, "send_email", _no_send)
    dry = cel.lambda_handler({"dry_run": True}, None)
    assert dry["dry_run"] is True
    assert dry["recipient_count"] == 1
    assert dry["html_bytes"] > 0

    sent_calls = []

    def _record_send(**kw):
        sent_calls.append(kw)
        return {"MessageId": "test-id"}

    monkeypatch.setattr(cel.ses, "send_email", _record_send)
    # #2820: the live path now emits the delivery-heartbeat datapoint; silenced
    # here (its own contract lives in test_chronicle_delivery_deadman_2820.py).
    monkeypatch.setattr(cel, "_emit_sent_metric", lambda *a, **k: None)
    live = cel.lambda_handler({}, None)
    assert live["sent"] == 1
    assert len(sent_calls) == 1
    assert sent_calls[0]["Destination"]["ToAddresses"] == ["reader1@example.com"]


def test_weekly_signal_dry_run_sends_zero_normal_path_sends(monkeypatch):
    """Same proof for weekly-signal — the other sender this issue newly gates."""
    import weekly_signal_lambda as wsl

    subs = [{"email": "reader2@example.com", "status": "confirmed"}]
    monkeypatch.setattr(wsl, "_s3_json", lambda key: None)
    monkeypatch.setattr(wsl, "_get_weekly_insight", lambda: None)
    monkeypatch.setattr(wsl, "_get_confirmed_subscribers", lambda: subs)

    def _no_send(**kw):
        raise AssertionError("dry_run must not call ses.send_email")

    monkeypatch.setattr(wsl.ses, "send_email", _no_send)
    dry = wsl.lambda_handler({"dry_run": True}, None)
    assert dry["dry_run"] is True
    assert dry["recipient_count"] == 1
    assert dry["html_bytes"] > 0

    sent_calls = []

    def _record_send(**kw):
        sent_calls.append(kw)
        return {"MessageId": "test-id"}

    monkeypatch.setattr(wsl.ses, "send_email", _record_send)
    # #2820: silenced as above — the emit contract lives in its own test file.
    monkeypatch.setattr(wsl, "_emit_sent_metric", lambda *a, **k: None)
    live = wsl.lambda_handler({}, None)
    assert live["sent"] == 1
    assert len(sent_calls) == 1
    assert sent_calls[0]["Destination"]["ToAddresses"] == ["reader2@example.com"]


def test_chronicle_email_sender_dry_run_bypasses_kill_switch(monkeypatch):
    """The point of dry_run is to be safely exercisable regardless of the
    EXTERNAL_EMAILS_ENABLED switch state — matching between_chronicle_lambda's
    precedent, where dry_run also runs ahead of the kill-switch check."""
    import chronicle_email_sender_lambda as cel

    installment = {"title": "T", "week_number": 1, "date": "2026-08-05", "content_html": "<p>x</p>", "status": "published"}
    monkeypatch.setattr(cel, "_get_this_weeks_installment", lambda: installment)
    monkeypatch.setattr(cel, "_get_confirmed_subscribers", lambda: [])
    monkeypatch.setenv("EXTERNAL_EMAILS_ENABLED", "false")

    def _no_send(**kw):
        raise AssertionError("dry_run must not call ses.send_email")

    monkeypatch.setattr(cel.ses, "send_email", _no_send)
    out = cel.lambda_handler({"dry_run": True}, None)
    assert out["dry_run"] is True
    assert out["recipient_count"] == 0

    # But the live path still honors the kill switch as before.
    live = cel.lambda_handler({}, None)
    assert live["skipped"] is True
    assert "external emails disabled" in live["body"]
