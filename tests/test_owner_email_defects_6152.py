"""#6152 — owner-email honesty: no literal age/start month in prompts, a live Compass
AI-failure check, DRY-RUN never logs `Sent:`, a failed confirmation never logs success,
the anomaly subject names its direction."""

import importlib
import os
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
EMAILS = ROOT / "lambdas" / "emails"

# Literal ages (the platform rule: no output reads or states age) and the stale start month.
_AGE = re.compile(r"\b3\d[- ]year[- ]old\b|\bage[d]? 3\d\b|\b3\d years old\b|Matthew Walker, 3\d,", re.I)
_START_MONTH = re.compile(r"started \((January|February|March|April|May|June|July|August|September) 20\d\d\)")


def test_no_email_prompt_carries_a_literal_age_or_start_month():
    offenders = []
    for path in sorted(EMAILS.glob("*.py")):
        text = path.read_text()
        for pat in (_AGE, _START_MONTH):
            for hit in pat.finditer(text):
                offenders.append(f"{path.name}: {hit.group(0)}")
    # The Chronicle's Elena fallback template predates this rule and is owned by the
    # chronicle lane (not in #6152's list); it is the one named, counted exemption.
    offenders = [o for o in offenders if not o.startswith("wednesday_chronicle_lambda.py")]
    assert not offenders, offenders


def test_partner_prompt_takes_its_start_month_from_the_constant():
    os.environ.setdefault("EMAIL_RECIPIENT", "x@example.com")
    os.environ.setdefault("EMAIL_SENDER", "y@example.com")
    sys.path.insert(0, str(ROOT / "lambdas"))
    p = importlib.import_module("emails.partner_email_lambda")
    assert "{start_month}" in p.BOARD_PROMPT


def _load_compass(monkeypatch):
    os.environ.setdefault("EMAIL_RECIPIENT", "x@example.com")
    os.environ.setdefault("EMAIL_SENDER", "y@example.com")
    sys.path.insert(0, str(ROOT / "lambdas"))
    return importlib.import_module("emails.monday_compass_lambda")


def test_compass_failed_ai_fallback_is_recognised_as_not_ok(monkeypatch):
    c = _load_compass(monkeypatch)
    failed = c._AI_FALLBACK_MARKER + (
        '<div style="background:#16213e;border-radius:8px;padding:20px;color:#e0e0e0;">'
        "Monday Compass AI unavailable this week. Check CloudWatch logs.</div>"
    )
    # The old check: `"unavailable" not in ai_content[:50]` was True for this very string.
    assert "unavailable" not in failed[:50]
    assert c._ai_ok(failed) is False
    assert c._ai_ok("") is False and c._ai_ok(None) is False
    assert c._ai_ok("<p>Week 11 plan</p>") is True


def test_compass_handler_marks_an_ai_exception_as_fallback():
    src = (EMAILS / "monday_compass_lambda.py").read_text()
    assert '"unavailable" not in ai_content[:50]' not in src
    assert src.count(" and _ai_ok(ai_content)") == 2


def test_no_sent_log_line_without_a_dry_run_branch():
    for name in ("monday_compass_lambda", "weekly_plate_lambda", "ai_review_pack_lambda", "monthly_digest_lambda"):
        src = (EMAILS / f"{name}.py").read_text()
        assert not re.search(r'logger\.info\(f?"Sent:', src), name
        assert "DRY-RUN (not sent)" in src, name


def test_failed_confirmation_send_does_not_log_success(monkeypatch, caplog):
    os.environ.setdefault("EMAIL_SENDER", "y@example.com")
    sys.path.insert(0, str(ROOT / "lambdas"))
    try:
        sub = importlib.import_module("web.email_subscriber_lambda")
    except Exception as e:  # pragma: no cover - env-dependent import
        pytest.skip(f"subscriber not importable here: {e}")

    def boom(*a, **k):
        raise RuntimeError("ses down")

    monkeypatch.setattr(sub, "guarded_send_email", boom)
    assert sub._send_confirmation_email("a@example.com", "https://x", dry_run=False) is False
    monkeypatch.setattr(sub, "guarded_send_email", lambda *a, **k: {"MessageId": "m"})
    assert sub._send_confirmation_email("a@example.com", "https://x", dry_run=False) is True
    assert sub._send_confirmation_email("a@example.com", "https://x", dry_run=True) is False


def test_anomaly_subject_names_the_direction():
    os.environ.setdefault("EMAIL_RECIPIENT", "x@example.com")
    os.environ.setdefault("EMAIL_SENDER", "y@example.com")
    sys.path.insert(0, str(ROOT / "lambdas"))
    a = importlib.import_module("emails.anomaly_detector_lambda")
    assert a._direction_word([{"direction": "low"}]) == "low"
    assert a._direction_word([{"direction": "high"}]) == "elevated"
    assert a._direction_word([{"direction": "low"}, {"direction": "high"}]) == "off baseline"
