"""board_quality_gate.py — the #1973 cycle-boundary rule for coach narratives.

WHAT THIS MODULE IS NOW (#3413, 2026-09-01). It was #968: the ADR-108 coach
quality gate wrapper for the public board, running `coach-quality-gate`
synchronously while a reader waited, evaluate-then-regenerate-once under a hard
time budget, fail-open. That wrapper is gone. What remains is
`cycle_boundary_violations` — a deterministic, in-process rule that
`ai_calls._invoke_quality_gate_sync` merges into the SAME report both surfaces
already use, so the rule still covers the daily brief and the board from one
definition. Nothing here does I/O any more.

WHY THE WRAPPER WENT. It never once worked, and it was the direct cause of
/api/board_ask serving 504s on launch day. Measured 2026-09-01:

    coach-quality-gate Duration, from CloudWatch Logs REPORT lines:
        7d   n=211   p50=10434ms   p90=20580ms   max=30637ms
        48h  n=68    p50=16371ms   p90=30000ms (its own timeout ceiling)

    aws logs filter-log-events --log-group-name /aws/lambda/coach-quality-gate \
      --start-time <now-604800s> --filter-pattern '"REPORT"' \
      --query 'events[].message' --output text \
      | grep -oE 'Duration: [0-9.]+' | awk '{print $2}' | sort -n

    Both windows are given because they disagree, and the weaker one still
    settles it: the 10s client cap sat below the callee's p50 in BOTH — the
    gate could not return at its MEDIAN speed on the most favourable sample
    available, and the 14s evaluate budget sat below p90 in both.

The client-side cap was 10s and the evaluate budget 14s, both written against a
comment claiming the gate cost "≈2-5s". The median call was 10.4-16.4s. So the
cap sat below the callee's own p50 — it could not return a verdict at its
TYPICAL speed, never mind its slow end, and 4% of its invocations exceeded
even its own 30s ceiling.

The live consequence, 7 days of real board traffic to 2026-09-01:

    8 gate attempts -> 6 "quality gate skipped", 2 read timeouts, 0 verdicts
    LifePlatform/AI::BoardQualityGateFired: no datapoint in all of August

Zero verdicts, ever. The gate was ~10s of guaranteed reader latency per grounded
coach with the answer thrown away, inside a 30s Lambda budget already shared
with up to 8 SEQUENTIAL coach generations. Removing it therefore forfeits no
measured capability — the instrument had never produced one. Note what this does
NOT establish: the board's true voice-fidelity failure rate is still unknown,
because the gate never completed here. That is an open question, not a settled
one, and it belongs to #3414 (recover the verdict on an async channel, where the
gate lambda already runs to completion and is already paid for).

Fabrication protection is untouched and was never this gate's job: that is the
ADR-104 grounding gate (`ai/grounded_generation.py` — pure, deterministic, no
network, fail-closed), which runs before this ever did and independently of it.
This gate's scope was voice fidelity only, and its own #968 docstring set the
tie-break: "an off-voice-but-grounded answer beats no answer." Readers were
getting no answer.

The guard that keeps this from coming back is
tests/test_board_quality_gate_968.py — a synchronous cross-Lambda invoke may not
be reintroduced onto the board reader path, and any client-side invoke cap must
be justified against the callee's MEASURED latency rather than an assumed one.
"""

import logging
import re

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# #1973 — Day<=3 cycle-boundary framing rule. A graded/prior-call reference in
# present tense with no cycle marker; both regexes are deliberately narrow
# (concrete self-referential prediction language, not any past-tense verb) to
# keep false-positive risk low on a fail-closed rule.
_GRADED_CALL_RE = re.compile(
    r"\bi\s+(?:called|predicted|said|thought|expected)\b"
    r"|\bmy\s+(?:call|prediction|read)\s+(?:was|is)\b"
    r"|\b(?:that|it)\s+(?:hasn'?t|has\s+not)\s+materialized\b"
    r"|\bi\s+was\s+(?:wrong|right)\s+about\b"
    r"|\b(?:confirmed|refuted)\s+(?:my|the)\s+(?:call|prediction)\b",
    re.IGNORECASE,
)
_CYCLE_FRAMING_RE = re.compile(
    r"\b(?:last|prior|previous)\s+cycle\b"
    r"|\bcycle\s+\d+\b"
    r"|\bbefore\s+(?:the|this)\s+(?:reset|genesis|cycle)\b"
    r"|\bpre-genesis\b"
    r"|\bprior\s+to\s+(?:the\s+)?reset\b",
    re.IGNORECASE,
)


def _day_n_today():
    """Live Day-N under the current EXPERIMENT_START_DATE, resolved at CALL
    time (never import-time-frozen — mirrors `weight_recency._resolve_genesis`,
    #2104). Returns None if constants can't be read (fail-soft: the rule this
    feeds is then skipped, never mis-armed on a bad day count).

    #2812: was `date.today()` (naive, Lambda TZ=UTC) — every 17:00-24:00 PDT a
    reader board request armed `cycle_boundary_violations` (#1973) with
    TOMORROW's Day-N while the #2414 guard reported green (the `date as _date`
    import alias evaded the matcher's plain-owner-name check). The site's day
    boundary is Pacific by owner decision — use the same helper #2675 already
    established for this exact class."""
    try:
        from common.constants import day_n as _day_n
        from common.pacific_time import pacific_today

        return _day_n(pacific_today())
    except Exception:
        return None


def cycle_boundary_violations(output_text: str, day_n: int = None) -> list:
    """#1973: on an early-cycle day (1-3), a narrative that references a
    graded/prior prediction in present tense MUST carry explicit prior-cycle
    framing ("last cycle", "cycle N", "before the reset", ...).

    Cross-cycle coach memory is deliberate design (ADR-108's verifier already
    confirmed coaches should remember past cycles); the gap this closes is
    narrower — a real record narrated with no cycle marker reads as
    self-contradiction to a reader whose /api/predictions shows the new
    cycle's own decided count at zero. Deterministic (regex, no LLM) so a
    prompt instruction drifting under load can't silently stop enforcing it
    — this repo's own "prompt rules can't guarantee structure" lesson.

    `day_n` defaults to the LIVE Day-N (`_day_n_today()`, resolved at call
    time); pass it explicitly to pin a day in tests. Returns `[]` (no
    violation) when day_n is unknown, out of the 1-3 window, no graded-call
    language is present, or cycle-boundary framing already appears anywhere
    in the text.
    """
    if day_n is None:
        day_n = _day_n_today()
    if not output_text or day_n is None or not (1 <= day_n <= 3):
        return []
    match = _GRADED_CALL_RE.search(output_text)
    if not match or _CYCLE_FRAMING_RE.search(output_text):
        return []
    excerpt = output_text[max(0, match.start() - 20) : match.end() + 60].strip()
    return [
        {
            "excerpt": excerpt,
            "reason": (
                f"Day {day_n} of a new cycle: references a prior call/prediction in present tense "
                'with no cycle-boundary framing (e.g. "last cycle", "cycle N").'
            ),
        }
    ]


def _pt_day_contract_extract_day_n(findings):
    """#2813 sweep extractor: recover the calendar date `_day_n_today()` resolved
    to from the finding's own reason text, so the standing sweep can compare it
    against `common.pacific_time.pacific_today()` like every other registered
    entry (a day_n int alone isn't a calendar date; this converts it back via
    the same EXPERIMENT_START_DATE the gate itself anchors to)."""
    import re as _re
    from datetime import date as _date, timedelta as _timedelta

    from common.constants import EXPERIMENT_START_DATE as _genesis

    if not findings:
        raise AssertionError(
            "cycle_boundary_violations produced no finding at the sweep's PT-evening instant — "
            "either the fixture text stopped matching _GRADED_CALL_RE, or day_n fell outside the 1-3 window"
        )
    m = _re.search(r"Day (\d+) of a new cycle", findings[0]["reason"])
    if not m:
        raise AssertionError(f"could not recover day_n from cycle_boundary_violations' finding: {findings[0]!r}")
    return (_date.fromisoformat(_genesis) + _timedelta(days=int(m.group(1)) - 1)).isoformat()


try:  # #2813 — register with the standing PT-day producer/gate contract sweep
    # (tests/test_pt_day_contract_sweep_2813.py). `day_n=None` resolves via
    # `_day_n_today()` — the #2812 instance of this exact defect class, already
    # fixed. Optional and inert on a partial bundle.
    from common.pt_day_contract import pt_day_contract as _pt_day_contract

    cycle_boundary_violations = _pt_day_contract(
        extract=_pt_day_contract_extract_day_n,
        args=("I called this outcome last week.",),
    )(cycle_boundary_violations)
except Exception:  # noqa: BLE001
    pass
