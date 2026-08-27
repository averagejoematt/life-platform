"""#3139 — the cache-aware model-tiering decision, held to its arithmetic.

ADR-049 routes structured tasks to Haiku. #3139 asked whether prompt-caching
economics invert that: a Sonnet cache read ($0.30/M) is 3.3x cheaper than an
uncached Haiku input token ($1.00/M). The decision was to RE-AFFIRM Haiku, on a
measured per-feature comparison (see `scripts/cache_aware_model_tiering.py` and
the ADR-049 amendment).

What these tests guard is not the verdict as a stored string — that would be a
`Verified` stamp, which is a human claim (#973/#2619). They guard the two things
the verdict actually rests on:

  1. The break-even threshold is DERIVED from the live price table, so if Bedrock
     re-prices Sonnet cache reads or Haiku input, the threshold moves and the
     screen re-runs against the new numbers instead of quoting the old answer.
  2. The screen is CAPABLE of saying "invert" — the negative control below feeds
     it a profile that genuinely should flip, and fails if it does not. A screen
     that answers "no" unconditionally would pass a corpus assertion vacuously
     and prove nothing (the #3199-class defect: a control that cannot fail).
"""

from __future__ import annotations

import os
import sys
from unittest import mock

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "lambdas"))
sys.path.insert(0, os.path.join(_ROOT, "scripts"))

import cache_aware_model_tiering as cat  # noqa: E402
from ai.bedrock_client import _PRICES  # noqa: E402


def test_headline_ratio_from_the_issue_is_real() -> None:
    """#3139's premise, verified against the live table rather than remembered.

    This half of the issue is TRUE and the re-affirmation does not depend on
    denying it — a Sonnet cache read really is ~3.3x cheaper per token than an
    uncached Haiku input token.
    """
    ratio = _PRICES["haiku"]["in"] / _PRICES["sonnet"]["cache_read"]
    assert ratio == pytest.approx(3.33, abs=0.01), f"issue #3139 claims 3.3x; live table gives {ratio:.2f}x"


def test_the_omitted_ratio_is_also_real() -> None:
    """The half the issue omits: a cache WRITE is 3.75x DEARER than Haiku input.

    A read only exists if a write for a byte-identical prefix landed inside the
    TTL. For a once-daily cron singleton the hit rate is 0 by construction, so
    the achievable comparison is write-vs-uncached, not read-vs-uncached.
    """
    penalty = _PRICES["sonnet"]["cache_write"] / _PRICES["haiku"]["in"]
    assert penalty > 1.0, "if a Sonnet cache write ever gets cheaper than Haiku input, re-run the screen"
    assert penalty == pytest.approx(3.75, abs=0.01)


def test_threshold_is_derived_from_prices_not_hardcoded() -> None:
    """Re-price the table and the break-even threshold must move with it.

    This is the anti-staleness guard. If `prefix_multiple_required` had the 14.29
    baked in as a literal, this test would fail — which is the point.
    """
    live = cat.prefix_multiple_required(1000.0)
    assert live == pytest.approx(14285.7, rel=0.001), "at live prices, 1k output tokens needs ~14.3k prefix tokens"

    cheaper_sonnet_output = dict(_PRICES)
    cheaper_sonnet_output["sonnet"] = dict(_PRICES["sonnet"], out=6.00)
    with mock.patch.dict(cat._PRICES, cheaper_sonnet_output, clear=False):
        moved = cat.prefix_multiple_required(1000.0)
    assert moved < live / 5, "threshold must track the output-price gap, not a frozen constant"


def test_screen_can_say_invert_negative_control() -> None:
    """MUST-FAIL CONTROL: a profile that genuinely should flip, and does.

    A 60k-token stable prefix against a 100-token payload and 50 tokens of output,
    read on every run — the exact shape #3139 hypothesises. If the screen refused
    to invert even here it would be a rubber stamp, and this assertion fails.
    """
    prefix, volatile, output = 60_000.0, 100.0, 50.0
    assert prefix > cat.prefix_multiple_required(output), "control profile must clear the arithmetic screen"

    sonnet = cat.sonnet_cost(prefix, volatile, output, hit_rate=1.0)
    haiku = cat.haiku_cost(prefix, volatile, output)
    assert sonnet < haiku, f"Sonnet-cached must win on this profile: ${sonnet:.6f} vs ${haiku:.6f}"

    hr = cat.required_hit_rate(prefix, volatile, output)
    assert hr is not None and 0.0 <= hr < 1.0, "a winnable profile must report an achievable hit rate"


def test_cold_cache_never_wins_positive_control() -> None:
    """The cadence gate: at h=0 the swap loses on EVERY profile, including the
    one that wins at h=1. This is why once-daily crons cannot be inverted."""
    prefix, volatile, output = 60_000.0, 100.0, 50.0
    assert cat.sonnet_cost(prefix, volatile, output, hit_rate=0.0) > cat.haiku_cost(prefix, volatile, output)


@pytest.mark.parametrize("feature,calls,in_tok,out_tok", cat.SNAPSHOT_30D)
def test_measured_corpus_verdicts(feature: str, calls: int, in_tok: int, out_tok: int) -> None:
    """Every structured feature, screened at its most generous possible shape.

    `P avail` is total input — the absolute ceiling on any stable prefix — and the
    screen runs at h=1 with V=0. A feature that fails here cannot be rescued by
    prompt restructuring, because the screen already assumes the restructuring
    worked perfectly.

    The two features that survive the arithmetic are recorded as survivors, NOT as
    inversions: both are falsified at the next gate by their actual prompt shape
    (see the ADR-049 amendment). If a third one ever survives, this test fails and
    someone re-runs the decision.
    """
    per_in, per_out = in_tok / calls, out_tok / calls
    survives = per_in > cat.prefix_multiple_required(per_out)
    expected_survivors = {"life-platform-qa-smoke", "life-platform-site-api-ai"}
    assert survives == (feature in expected_survivors), (
        f"{feature}: arithmetic screen now says survives={survives}; the #3139 decision was made "
        f"against survivors={sorted(expected_survivors)}. Re-run scripts/cache_aware_model_tiering.py."
    )


def test_no_structured_feature_is_currently_worth_inverting() -> None:
    """The decision itself, re-derived rather than quoted.

    Both arithmetic survivors need a near-perfect hit rate AND a 100%-stable
    prompt. This asserts the hit-rate requirement stays implausible; the
    prompt-stability half is falsified in code (`coach_checkin.build_generation_prompt`
    interpolates the per-coach name and bio at byte 0 of its 'stable' system
    prompt; `site_api_ai._ask_build_prompt` builds its system prompt from
    question-selected retrieval, #2348) and cited in the ADR.
    """
    for feature, calls, in_tok, out_tok in cat.SNAPSHOT_30D:
        per_in, per_out = in_tok / calls, out_tok / calls
        if per_in <= cat.prefix_multiple_required(per_out):
            continue
        hr = cat.required_hit_rate(per_in, 0.0, per_out)
        assert hr is not None and hr > 0.90, (
            f"{feature} now breaks even at a hit rate of {hr:.1%} — below the 90% implausibility bar. "
            "That is a genuine inversion candidate; re-open #3139."
        )
