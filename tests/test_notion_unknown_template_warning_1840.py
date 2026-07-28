"""tests/test_notion_unknown_template_warning_1840.py — #1840 AC2.

notion_lambda.parse_page()'s "unknown template" fallback (an entry whose
Template select value IS present but not in TEMPLATE_SK) used to log at
INFO, so future code<->Notion-schema drift on this path would never surface
in CloudWatch without a manual audit — exactly the class of drift that let
#1572/#1573 (Video Diary / Solo Recording) ship inert for weeks. This pins
the level bump to WARNING and checks the message still carries the
offending template string for diagnosability.
"""

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for p in (os.path.join(ROOT, "lambdas"), os.path.join(ROOT, "lambdas", "ingestion")):
    if p not in sys.path:
        sys.path.insert(0, p)

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

import notion_lambda as nl  # noqa: E402


def _select(name):
    return {"type": "select", "select": {"name": name}}


def _date(d):
    return {"type": "date", "date": {"start": d}}


def _page(template_name, page_id="abcd1234-ef56-7890-1234-56789abcdef0", date="2026-07-25"):
    return {
        "id": page_id,
        "created_time": "2026-07-25T02:00:00.000Z",
        "last_edited_time": "2026-07-25T02:05:00.000Z",
        "properties": {"Date": _date(date), "Template": _select(template_name)},
    }


def test_unknown_template_logs_at_warning_not_info(monkeypatch):
    # A template string that IS present but not registered in TEMPLATE_SK —
    # e.g. a new Notion template added live before the code caught up.
    #
    # notion_lambda.logger is a PlatformLogger (propagate=False, structured JSON
    # to stdout) — pytest's caplog fixture listens on the root logger and never
    # sees these records, so intercept the level-specific methods directly
    # instead of relying on caplog.
    warning_calls = []
    info_calls = []
    monkeypatch.setattr(nl.logger, "warning", lambda msg, *a, **k: warning_calls.append(msg))
    monkeypatch.setattr(nl.logger, "info", lambda msg, *a, **k: info_calls.append(msg))

    page = _page("Future Template Nobody Wired Up Yet")
    result = nl.parse_page(page)

    assert result is not None
    date_str, template, item = result
    assert template == "journal"  # still falls back cleanly

    assert warning_calls, f"expected a logger.warning() call, got none (info calls: {info_calls})"
    assert any("Future Template Nobody Wired Up Yet" in m for m in warning_calls)
    assert any("unknown template" in m for m in warning_calls)

    # Regression guard: the pre-#1840 bug logged this exact message at INFO instead.
    assert not any("unknown template" in m for m in info_calls)


def test_known_template_does_not_warn(monkeypatch):
    # Sanity: a registered template (no drift) must not trip the new WARNING.
    warning_calls = []
    monkeypatch.setattr(nl.logger, "warning", lambda msg, *a, **k: warning_calls.append(msg))

    page = _page("Morning")
    result = nl.parse_page(page)

    assert result is not None
    _, template, _ = result
    assert template == "Morning"
    assert not any("unknown template" in m for m in warning_calls)
