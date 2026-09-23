"""tests/test_rate_n_contract_4035.py — any front-end consumer showing the weekly loss
RATE also shows its n (#4035, box 3).

WHAT "the rate" MEANS HERE. `journey.weekly_rate_lbs` (+ its `_ci_low`/`_ci_high` bounds)
is a slope computed from the weigh-in record — `lambdas/health/weight_trend.py` docstring:
"Returns ... weekly_rate_lbs ... rate_provisional, weighin_span_days ..." as ONE set
(`site_api_journey._WEIGHT_ABSENT_FIELDS`). A rate from a thin record read as confidently
as a rate from a mature one is exactly the newcomer harm #4035 names: "never sees a rate
computed from one observation presented as a rate." `lost_lbs` (the raw signed delta) is
NOT a rate — a single weigh-in still gives a true point-in-time number — so it is out of
scope for this gate; the platform's existing single-weigh-in honesty branches (see
`daily_line.heroProofLine`, `story.js`'s pre-projection branch) cover it separately.

THE CONTRACT. Any `site/assets/js/**/*.js` or non-legacy `site/**/index.html` file that
references `weekly_rate_lbs` in its source MUST also reference at least one of the three
n-signals the backend ships beside it: `rate_provisional`, `weighin_count`,
`weighin_span_days`. Consumers are found by grepping the live tree (never a hand list) so
a new rate-rendering file is caught automatically, not opted in.

MUTATION PROOF: `test_planted_fixture_reds_a_rate_without_its_n` writes a synthetic module
that renders `j.weekly_rate_lbs` with no n-signal anywhere in the file and asserts the
SAME scanner reds it by name — the falsifiable half, isolated from the live tree.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"

RATE_RE = re.compile(r"\bweekly_rate_lbs\b")
N_SIGNAL_RE = re.compile(r"\brate_provisional\b|\bweighin_count\b|\bweighin_span_days\b")


def _candidate_files():
    """Every non-legacy site source file that could render reader-visible copy —
    JS modules plus built HTML pages. Legacy (`/legacy/**`) is the frozen v1 archive,
    out of scope for every v4 gate (same exclusion `tests/test_glossary_4035.py` uses)."""
    for path in sorted((SITE / "assets" / "js").rglob("*.js")):
        yield path
    for path in sorted(SITE.rglob("index.html")):
        if "legacy" in path.relative_to(SITE).parts:
            continue
        yield path


def rate_consumers_missing_n(files) -> list[str]:
    """The scanner itself, isolated so both the live-tree test and the planted-fixture
    mutation-proof test call the identical logic."""
    offenders = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        if RATE_RE.search(text) and not N_SIGNAL_RE.search(text):
            offenders.append(str(path))
    return offenders


def test_any_rate_consumer_also_shows_its_n():
    """Gate: every live file that renders `weekly_rate_lbs` also carries at least one
    of rate_provisional / weighin_count / weighin_span_days in the same file."""
    files = list(_candidate_files())
    assert files, "no candidate site files found — the gate didn't run over anything"
    rate_files = [f for f in files if RATE_RE.search(f.read_text(encoding="utf-8"))]
    assert rate_files, "no live consumer of weekly_rate_lbs found — the gate has nothing to check"
    offenders = rate_consumers_missing_n(files)
    assert not offenders, (
        "file(s) render weekly_rate_lbs with no rate_provisional / weighin_count / "
        "weighin_span_days anywhere in the same file — a reader sees a rate with no n "
        "behind it:\n" + "\n".join(f"  {o}" for o in sorted(offenders))
    )


def test_planted_fixture_reds_a_rate_without_its_n(tmp_path):
    """Mutation proof: a synthetic module rendering the rate with NO n-signal anywhere
    in the file is caught by NAME, isolated from the live site tree."""
    bad = tmp_path / "fake_rate_widget.js"
    bad.write_text(
        "export function renderRate(j) { return `trend ${j.weekly_rate_lbs} lb/wk`; }\n",
        encoding="utf-8",
    )
    good = tmp_path / "fake_rate_widget_honest.js"
    good.write_text(
        "export function renderRate(j) { " 'return j.rate_provisional ? "too early" : `trend ${j.weekly_rate_lbs} lb/wk`; }\n',
        encoding="utf-8",
    )
    offenders = rate_consumers_missing_n([bad, good])
    assert offenders == [str(bad)]
