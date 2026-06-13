"""
tests/test_email_render_goldens.py — golden-snapshot net for the weekly/monthly
email render functions (companion to tests/test_daily_brief_golden.py).

The daily brief had a golden; the other emails did not. Each of these render
functions is a pure (inputs → HTML string) builder, so we pin the full output
for a frozen fixture. Any future refactor (e.g. the deferred build_html split,
or shared-layer changes) that alters an email's output shows up as a golden
diff in the PR instead of going unnoticed until it's in someone's inbox.

To intentionally change an email's output:
    GOLDEN_UPDATE=1 python3 -m pytest tests/test_email_render_goldens.py
then review the golden diff.

Covers the three flat-signature renderers (nutrition_review, weekly_plate,
monday_compass). weekly_digest/monthly_digest take nested data packets — added
as a follow-up (see task list).
"""

import os
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))
sys.path.insert(0, str(ROOT / "lambdas" / "emails"))

# Module-level boto3 clients are constructed at import — give them a region so
# import succeeds offline (no network call happens at construction).
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("EMAIL_RECIPIENT", "test@example.com")
os.environ.setdefault("EMAIL_SENDER", "noreply@example.com")

GOLDEN_DIR = Path(__file__).parent / "fixtures" / "email_goldens"

_AI = (
    '<div style="color:#cbd5e1;font-size:14px;line-height:1.6;">'
    "<p>Synthetic AI body for the golden — protein held, deficit honest, recovery climbing.</p></div>"
)
_TABLE = '<table style="width:100%;"><tr><td>Calories</td><td>1480 / 1500</td></tr><tr><td>Protein</td><td>185 g</td></tr></table>'


def _render_nutrition_review():
    import nutrition_review_lambda as m

    return m.build_email_html(
        _TABLE,
        _AI,
        {"this_start": "2026-06-01", "this_end": "2026-06-07"},
        {"latest_weight_lbs": 306.9, "change_30d_lbs": -4.7},
    )


def _render_weekly_plate():
    import weekly_plate_lambda as m

    return m.build_email_html(
        _AI,
        {"end": "2026-06-07"},
        {"latest_weight_lbs": 306.9, "change_7d_lbs": -1.8},
    )


def _render_monday_compass():
    import monday_compass_lambda as m

    return m.build_email_html(
        _AI,
        {"char_level": 4, "char_tier": "Foundation", "recovery": 68, "week_num": 2},
        "2026-06-08",
    )


RENDERERS = {
    "nutrition_review": _render_nutrition_review,
    "weekly_plate": _render_weekly_plate,
    "monday_compass": _render_monday_compass,
}

# Strip fragments derived from the current date/run so the snapshot is stable.
_NORMALIZERS = [(re.compile(r"\b\d{4}-\d{2}-\d{2}T[\d:.+-]+"), "<TS>")]


def _normalize(html: str) -> str:
    for pat, repl in _NORMALIZERS:
        html = pat.sub(repl, html)
    return html


@pytest.mark.parametrize("name", sorted(RENDERERS))
def test_email_render_golden(name):
    html = _normalize(RENDERERS[name]())
    # Structural floor — must hold regardless of golden churn.
    assert len(html) > 1000, f"{name} rendered suspiciously small"
    for leak in ("None", "{ai_content}", "{summary_table}", "[object", "undefined"):
        assert leak not in html, f"{name}: template/None leakage: {leak!r}"

    golden = GOLDEN_DIR / f"{name}.html"
    if os.environ.get("GOLDEN_UPDATE") or not golden.exists():
        golden.parent.mkdir(parents=True, exist_ok=True)
        golden.write_text(html)
        if not os.environ.get("GOLDEN_UPDATE"):
            raise AssertionError(f"{name}: golden created — commit it and re-run")
        return
    assert html == golden.read_text(), (
        f"{name} email HTML changed vs golden. If intentional: "
        f"GOLDEN_UPDATE=1 python3 -m pytest tests/test_email_render_goldens.py — then review the diff."
    )
