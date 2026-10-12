"""#4839 — the committed kit page captures may not be more than 30 days old.

The kit page gate and the kit JS tests render committed captures of the live site's routes
(tests/fixtures/kit_pages_4586/, written only by scripts/capture_kit_page_fixtures.py). Left alone they
described the edition a month before the site served it, and 45 JS tests pinned that month's numbers.

Two holds: (1) the manifest's ``captured_at`` is no older than ``MAX_AGE_DAYS`` against the real clock
(this is the gate: it reds on purpose when the captures go stale, and the fix is to re-run the script);
(2) the "Last recaptured" line in the script's docstring names the same day as the manifest, so the
line a reader trusts cannot drift from the file. The age RULE is proven on a frozen clock below, with
no literal expectation passed through the live clock (#4848).
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import capture_kit_page_fixtures as cap  # noqa: E402

MANIFEST = os.path.join(cap.FIXTURES_DIR, cap.MANIFEST)


def _captured_at() -> str:
    with open(MANIFEST, encoding="utf-8") as fh:
        return json.load(fh)["captured_at"]


def test_the_age_rule_on_a_frozen_clock():
    taken = "2026-10-12T15:35:22Z"
    at = datetime(2026, 10, 12, 15, 35, 22, tzinfo=timezone.utc)
    assert cap.age_days(taken, at) == 0
    assert cap.age_days(taken, at + timedelta(days=29, hours=23)) < cap.MAX_AGE_DAYS
    assert cap.age_days(taken, at + timedelta(days=30, hours=1)) > cap.MAX_AGE_DAYS
    assert cap.MAX_AGE_DAYS == 30


def test_the_committed_captures_are_not_older_than_thirty_days():
    age = cap.age_days(_captured_at(), datetime.now(timezone.utc))
    assert age <= cap.MAX_AGE_DAYS, (
        f"tests/fixtures/kit_pages_4586/ was captured {_captured_at()}, {age:.0f} days ago (limit {cap.MAX_AGE_DAYS}). "
        "Re-run `python3 scripts/capture_kit_page_fixtures.py`, re-pin anything it reds, and update the "
        "'Last recaptured' line in the script's docstring."
    )


def test_the_docstring_date_is_the_manifests_date():
    said = re.search(r"Last recaptured: (\d{4}-\d{2}-\d{2})", cap.__doc__ or "")
    assert said, "scripts/capture_kit_page_fixtures.py has no 'Last recaptured: YYYY-MM-DD' line in its docstring"
    assert said.group(1) == _captured_at()[:10], f"docstring says {said.group(1)}, the manifest says {_captured_at()[:10]}"
