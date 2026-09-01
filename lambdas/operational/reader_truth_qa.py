"""
reader_truth_qa.py — the shared phase-aware "reader truth" rubric (#1095/#1096).

The visual AI-QA layer (tests/visual_ai_qa.py) judges whether pages RENDER; this
module judges whether their PROSE can be TRUE at the current experiment phase.
Matthew's 2026-07-11 manual review found ~10 truth-class items by hand (week-long
trends narrated on day 0, numbers that could not exist yet, the same paragraph
pasted across lenses) — this rubric turns that read-through into a machine gate.

ONE prompt, TWO hooks (both import this module so the rubric can never fork):
  - CI post-deploy: tests/visual_ai_qa.assess_reader_truth() over the harness's
    rendered-prose dumps (visual_qa.py --reader-truth), gating like AI-vision.
  - Nightly: lambdas/operational/qa_smoke_lambda.check_reader_truth() over a
    small HTTPS-fetched surface set, so truth regressions surface between
    deploys too. Fail-soft there — a Bedrock outage must never red the nightly.

Phase ground truth is computed at runtime from constants.EXPERIMENT_START_DATE
(never hardcoded — it moves on every experiment reset, ADR-058/077).

Model: Haiku (structured task per ADR-049/063 tiering), override via
READER_TRUTH_MODEL. Budget: feature "reader_truth_qa" in budget_guard's ladder —
OPERATOR-TRUTH band, pauses at tier 3 only (ADR-125 as amended 2026-08-03 by #1927,
which measured this gate dark 26 of 30 days at its old tier-1 cutoff); both hooks
report the skip honestly, never silent green.

Lives at lambdas/ root so it ships in every function bundle (#781) AND is
importable by the CI-side harness (tests/ already puts lambdas/ on sys.path).
Stdlib-only — safe to import anywhere.
"""

import json
import os
import re
from datetime import date
from html.parser import HTMLParser

# Haiku by default — structured verdict task (ADR-049 tiering, ADR-063 budget).
DEFAULT_MODEL = os.environ.get("READER_TRUTH_MODEL", "claude-haiku-4-5-20251001")

# budget_guard._FEATURE_CUTOFF key — operator-truth band, pauses at tier 3 (ADR-125/#1927).
BUDGET_FEATURE = "reader_truth_qa"

# #1440 (ADR-104 applied to the QA system itself): a budget-tier pause of this AI
# QA pass must never look like a pass. Both hooks below call emit_budget_pause_metric()
# when they pause on budget_guard.allow(BUDGET_FEATURE) — a daily CloudWatch alarm on
# this metric (monitoring_stack.py, to_digest=True) routes into the SAME digest
# pipeline every other alarm uses (→ life-platform-alerts-digest topic →
# alert_digest_lambda's batched email), so a paused day surfaces even when nothing
# else about the run failed and no other email would otherwise be sent.
_QA_PAUSE_NAMESPACE = "LifePlatform/QA"
_QA_PAUSE_METRIC = "QAPausedByBudget"


def emit_budget_pause_metric(source: str, tier: int) -> None:
    """Emit the QAPausedByBudget CloudWatch metric for a budget-tier pause.

    `source` identifies which hook paused ("visual_ai_qa" — the CI/local
    Playwright harness; "qa_smoke" — the nightly Lambda) for the caller's own
    log line only; the metric itself carries no dimensions so ONE alarm
    (monitoring_stack.py) catches a pause fired by either hook.

    Fail-soft by design, matching this module's posture everywhere else: a
    metrics-emission hiccup must never break (or further degrade) a QA pass
    that is already paused. boto3 is imported lazily so the module stays
    stdlib-importable everywhere (including the CI harness, which may run
    under a read-only diagnosis role or with no AWS creds at all — see
    infra/iam/README.md; the emit there is genuinely best-effort).
    """
    try:
        import boto3

        boto3.client("cloudwatch", region_name=os.environ.get("AWS_REGION", "us-west-2")).put_metric_data(
            Namespace=_QA_PAUSE_NAMESPACE,
            MetricData=[{"MetricName": _QA_PAUSE_METRIC, "Value": 1.0, "Unit": "Count"}],
        )
    except Exception as e:
        print(f"  ⚠ {_QA_PAUSE_METRIC} metric emit failed (non-fatal) [{source}, tier {tier}]: {str(e)[:140]}")


# The rubric categories (#1095). parse/normalize coerce anything else to "other".
# "impossible_number" was RETIRED by #1922: numeric phase-bound claims (window-
# named fields, span declarations, day fields, bare "Day N" in strict payloads)
# are now checked deterministically by operational/phase_plausibility.py, which
# still emits that category name so downstream consumers see one taxonomy. The
# LLM keeps the genuinely semantic categories — including WORD-number phase
# claims in prose ("seven days of an experiment", #1897), which remain
# temporal_contradiction.
CATEGORIES = (
    "temporal_contradiction",
    "duplicated_narrative",
    "audience_violation",
)

SEVERITIES = ("low", "med", "high")

# ── the ruling ledger (#2959) — split to reader_truth_rulings.py 2026-08-23 ───
# The predicates + their measured histories live in reader_truth_rulings.py
# (the #1665 module ceiling forced the split; the ledger had outgrown the
# rubric). Re-exported here so every consumer keeps ONE import surface.
from operational.reader_truth_rulings import (  # noqa: F401
    CODE_OWNED_TEMPORAL_SURFACES,
    DURABLE_DESIGN_COPY,
    JUDGE_BASIS_FIELD,
    JUDGE_BASIS_VALUES,
    RULINGS_FIELD,
    _is_registered_span,
    _normalize_copy,
    _note_dates,
    _pacific_renderings,
    advisory_rulings,
    is_active_vs_passive_objection,
    is_advisory,
    is_coach_surface_audience,
    is_code_owned_temporal,
    is_day_counter_bound_inference,
    is_durable_design_copy,
    is_position_banner_misread,
    is_prior_cycle_archive,
    is_self_refuted,
    is_sparsity_objection,
    is_utc_offset_misread,
    is_vagueness_objection,
    is_wake_frame_correct,
    judge_basis,
    quoted_spans,
)

# Batch 4-6 surfaces per call so the duplicated-narrative check sees pages
# side-by-side (a single-page call structurally cannot catch duplication).
DEFAULT_BATCH_SIZE = 5

# Per-surface prose cap — bounds tokens (~1.5k tokens/page at 6k chars) so a
# 6-surface batch stays comfortably inside a Haiku context + pennies per run.
MAX_PROSE_CHARS = 6000


# ── phase ground truth ─────────────────────────────────────────────────────────


_cycle_probe = {"done": False, "value": None}


def _current_cycle():
    """Current experiment cycle (int) or None — fail-soft, never raises.

    #2959 ground truth: the oracle repeatedly INFERRED the cycle number from page
    content (misstating cycle 14 as 10 on the first armed sweep) because the
    prompt never told it. The number lives in SSM /life-platform/experiment-cycle
    (stamped by the restart pipeline); `coach_checkin.read_cycle` is the cached,
    fail-soft reader every other consumer uses. No AWS → None → the phase line
    simply omits the cycle sentence (tests inject `cycle=` explicitly).

    Probed ONCE per process (unlike read_cycle, which retries failures per call —
    right for a warm Lambda writing stamps, wrong here: a creds-less test or CI
    run would otherwise re-attempt SSM on every phase_context call).
    """
    if _cycle_probe["done"]:
        return _cycle_probe["value"]
    try:
        from coach.coach_checkin import read_cycle

        _cycle_probe["value"] = read_cycle()
    except Exception:  # noqa: BLE001 — ground truth is optional, never fatal
        _cycle_probe["value"] = None
    _cycle_probe["done"] = True
    return _cycle_probe["value"]


def phase_context(today_iso=None, cycle=None):
    """The experiment phase, computed at runtime from constants.EXPERIMENT_START_DATE.

    Returns {"today", "start_date", "day_n", "pre_start", "days_until_start", "cycle"}.
    day_n is 1-indexed (constants.day_n); 0 == pre-genesis countdown state.
    `today_iso` is injectable for tests (derive fixtures from EXPERIMENT_START_DATE,
    never wall-clock literals); default is today in the site's Pacific timezone.
    `cycle` is injectable for tests; default is the SSM-stamped current cycle,
    fail-soft None (#2959 — feed the ground truth, never let the model infer it).
    """
    from common.constants import EXPERIMENT_START_DATE, day_n

    if today_iso is None:
        from common.pacific_time import pacific_today  # #1964: the one Pacific frame

        today_iso = pacific_today()
    n = day_n(today_iso)
    days_until = 0
    if n == 0:
        days_until = (date.fromisoformat(EXPERIMENT_START_DATE) - date.fromisoformat(today_iso)).days
    return {
        "today": today_iso,
        "start_date": EXPERIMENT_START_DATE,
        "day_n": n,
        "pre_start": n == 0,
        "days_until_start": days_until,
        "cycle": cycle if cycle is not None else _current_cycle(),
    }


try:  # #2813 — register with the standing PT-day producer/gate contract sweep
    # (tests/test_pt_day_contract_sweep_2813.py) — the reader-truth window rules'
    # own phase anchor. A local, optional import so the module's own "stdlib-only,
    # safe to import anywhere" contract (see the module docstring) stays intact —
    # this is registration, never a runtime dependency of the rubric itself.
    from common.pt_day_contract import pt_day_contract as _pt_day_contract

    phase_context = _pt_day_contract(extract=lambda r: r["today"])(phase_context)
except Exception:  # noqa: BLE001 — never let registration break an import
    pass


def _cycle_line(phase):
    # #2959: the first armed sweep's oracle MISSTATED the current cycle as 10 —
    # it was never told, so it inferred from a labeled prior-cycle diary card.
    # Ground truth is fed, never inferred; when SSM is unreachable the sentence
    # is omitted rather than guessed.
    c = phase.get("cycle")
    if not c:
        return ""
    return (
        f" This is CYCLE {c} of the experiment. Cycles 1–{c - 1} are prior attempts whose artifacts "
        f"(diary cards, essays, post-mortems, archives) remain published, labeled with their own cycle "
        f"numbers and dates — content explicitly labeled or dated to a prior cycle is historical record, "
        f"not a contradiction. Never infer the current cycle number from page content; this sentence is "
        f"the ground truth."
    )


def _phase_line(phase):
    if phase["pre_start"]:
        return (
            f"The experiment has NOT started yet — Day 1 is {phase['start_date']}, "
            f"{phase['days_until_start']} day(s) away (today is {phase['today']}). The site runs an honest "
            f"pre-start countdown; ZERO days of current-experiment data can exist yet." + _cycle_line(phase)
        )
    return (
        f"Today ({phase['today']}) is Day {phase['day_n']} of the experiment (Day 1 = {phase['start_date']}). "
        f"At most {phase['day_n']} day(s) of current-experiment data can exist; any claim of a longer "
        f"in-experiment history (trends, streaks, averages, counts) is impossible unless it is explicitly "
        f"labeled lifetime / all-time / a previous cycle / the pilot. "
        # #1917: the rubric stated only the upper bound, so the model inferred that any
        # window number DIFFERING from day_n was a contradiction and flagged 5-on-Day-6
        # as an "impossible number" on three consecutive runs. After a cycle restart
        # EVERY trailing window is deliberately clamped to the cycle start (ADR-077
        # "clamped, not hidden"), so short windows are the honest path, not the failure
        # mode. Stating the lower bound explicitly is what the model was missing.
        f"A window, span, average or count SMALLER than {phase['day_n']} day(s) is EXPECTED and CORRECT — "
        f"trailing windows are deliberately clamped to the cycle start, so on Day {phase['day_n']} a field "
        f"may honestly report any span from 0 to {phase['day_n']} day(s). Only a span LONGER than "
        f"{phase['day_n']} day(s) is impossible. Never flag a number for being smaller than {phase['day_n']}." + _cycle_line(phase)
    )


# ── prompt ─────────────────────────────────────────────────────────────────────
# The DO-NOT-flag list is the rubric's false-positive ledger, grown the same way
# #1917 grew the lower-bound clause: only after a repeated, verified-false finding
# class, stated as the general principle. 2026-08-09 (cycle-13 reset, the first
# truth-gated FUTURE genesis): the grader flagged the "··" honest-absence glyph
# (ADR-104) and durable design copy ("starts at the Day-1 weigh-in") as claims of
# existing data on a countdown day — four highs, all against the DESIGNED #931/#939
# pre-start state. The two clauses below teach it what "··" and habitual-present
# design copy mean; genuinely-asserted past measurements stay flaggable.
#
# ── 2026-08-11 (#2575): the GENESIS-WEEK ruling, written down ──────────────────
# The 2026-08-11 nightly published "2 high truth finding(s) at Day 1". Both were
# false, and both are the same shape: the grader treating a CORRECT genesis-week
# artefact as a contradiction.
#
#   (a) Home: "This attempt starts at the Day-1 weigh-in, aimed at 185 lbs held for
#       90 …". This is verbatim the string the 2026-08-09 clause above was written
#       for. It recurred because that clause reads as PRE-START-scoped ("including
#       pre-start"), and Day 1 is not pre-start. Same copy, same correctness, one
#       phase later. Widened below to name the genesis week.
#   (b) /api/sleep_detail: `night_of: 2026-08-09` (the night before Day 1) under
#       `as_of_date: 2026-08-10`. That is not a contradiction, it is the #1923
#       wake-date frame being right: sleep/recovery/HRV/RHR are keyed to the MORNING
#       they were recorded against, so the night behind Day 1's morning is
#       necessarily the night before Day 1. It is unavoidable on every Day 1 of
#       every cycle — which is exactly why leaving it unruled makes it #1966
#       normalized noise.
#
# WHY A CLAUSE AND NOT A SURFACE FIX. The deterministic half of this question is
# already asked and already passes: `phase_plausibility._night_label_findings` (R5,
# #1968) requires every night-scoped figure to NAME its night, and the live payload
# names it three ways — `frame: "last_night"`, `night_of`, and a `figure_scope`
# block spelling the convention out in English. ADR-105 puts deterministic
# computation ahead of any LLM verdict, so where the two layers disagree about a
# payload the deterministic one has already graded, the LLM is the one that is
# wrong. There is nothing left to correct on the surface.
#
# SCOPED, NOT A BLANKET SUPPRESSION. The clause exempts one thing: a night-scoped
# figure whose night is the day before the cycle's genesis, on a surface dated at or
# after genesis. A pre-genesis night on a surface claiming any OTHER day, a
# pre-genesis MEASUREMENT presented as this cycle's, or prose asserting history that
# genesis makes impossible all stay flaggable at full severity.
#
# ── 2026-08-13 (#2613): the SAME ruling, one locus wider — the trend SERIES ────
# The clause above was written against the scalar `night_of`, and that is exactly how
# far it reached. Three consecutive nightlies (2026-08-12 and twice on 2026-08-13)
# published a high finding on /api/sleep_detail at **Day 3**, which #2583's Day-1
# genesis clause cannot cover. The log line truncates each finding at 90 chars
# (qa_check_reader_truth._fmt), so all three read as different defects; reproduced
# untruncated at the real call site, they are one finding with three phrasings:
#
#   "sleep_trend contains a row dated 2026-08-10 with sleep_start timestamp
#    2026-08-10T05:05:46.420Z. Per the figure_scope documentation, trend rows are
#    keyed by WAKE date, so this row represents the night of 2026-08-09. However,
#    the experiment started on 2026-08-10 (Day 1); data from the night of 2026-0…"
#
# The three truncated tails — "but the e…", "but the sleep_s…", "with the 202…" —
# are "the experiment started", "the sleep_start timestamp", and "the 2026-08-10
# row". Same claim each night.
#
# THE RULING: the surface is correct; the check is under-scoped. The trend is clamped
# to genesis (ADR-077) and keyed by WAKE date (#1923), so its EARLIEST row is dated
# exactly the cycle start and its bedtime necessarily falls the evening before Day 1.
# The payload already declares the convention in three places (`frame`,
# `figure_scope.trend_date_convention`, and a `trend_note` sentence) — and #2344's
# trend_note is what taught the model the wake-date rule it then used to build the
# accusation.
#
# IT RECURS ON EVERY CYCLE RESET, AND NOT ONLY ON DAY 1 — that is the finding worth
# more than this instance. The trend window is `_experiment_date(30)` clamped to
# genesis, so the genesis-dated first row sits in the payload for the FIRST 30 DAYS of
# every cycle, then ages out on its own. A Day-1-scoped clause (#2583's shape) would
# have gone quiet on Day 2 and left 29 more nights of noise; the clause below is
# written for the recurrence, keyed off "the cycle start", never a 2026-08 date.
#
# WHY THIS WIDENING IS SAFE. The defect it resembles — a row genuinely dated before
# genesis, i.e. an ADR-077 clamp breach — is now caught deterministically by
# phase_plausibility R6 (#2613), which is arithmetic and therefore never budget-paused.
# Per ADR-105 the deterministic layer leads; the prose clause only exempts what that
# layer has already cleared. R6 checks the row's own `date`; the clause exempts the
# NIGHT behind a genesis-dated row. They cover disjoint halves of the same question.
#
# ── THE CLAUSE DID NOT WORK, SO THE CLASS IS RETIRED (#2613, 2026-08-13) ──────
# Measured against the live surface set at the real call site (Haiku, the nightly's
# own batching), the ruling above did NOT silence the finding:
#     before any change ................ 3 of 3 runs raised the high finding
#     + the ruling clause .............. 3 of 3 runs still raised it
#     + the payload disclosure too ..... 4 of 5 runs still raised it
#     + this branch's own re-baseline .. 3 of 6 runs (same code, wider n)
# The model does not miss the clause; it re-derives the accusation FROM the payload's
# own `trend_note`, quoting it approvingly in the same sentence that flags it. A
# false-positive class that survives both a rubric clause and an explicit in-payload
# disclosure is not a wording problem, and widening the prose further was the exact
# failure mode #2613 was told to avoid.
#
# So the class is RETIRED from the LLM, exactly as #1922 retired `impossible_number`
# after the model mis-graded `weight_delta_window_days: 5` six times with six
# different rationales. #1922's line was "numbers in a strict payload are code's";
# this extends it to "and so are the DATES". Per ADR-105 the deterministic layer
# leads, and R6/R7 have already decided this question — arithmetic, run identically
# every time, never budget-paused — so an LLM verdict on the same question is not a
# second opinion, it is a competing one, and the measured record says it is the
# unreliable one.
#
# HOW THE RETIREMENT IS ENFORCED — and why prose alone could not do it. #1922 could
# retire a whole CATEGORY (drop it from CATEGORIES, drop its name from the prompt).
# Here the category survives: prose temporal contradictions are still the LLM's. What
# is retired is one LOCUS × one CLASS — pre-cycle DATES on the four code-swept strict
# payloads — so the prompt states the division (below) AND `assess_prose` drops any
# finding that still comes back in it (`is_code_owned_temporal`). The drop is
# structural, not a phrase match: the page must be a code-swept payload and the note
# must cite an ISO date at or before the cycle start. Every drop is printed.
#
# WHAT IS *NOT* RETIRED, stated so the reduction is legible:
#   · HTML pages keep the whole class — R6/R7 read JSON payloads only, so nothing
#     code-owned covers a pre-genesis date narrated in page prose. The wake-date
#     exemption below stays for exactly that reader.
#   · /api/coaches keeps it too — it is swept non-strict (it may narrate a labeled
#     prior cycle), so R6/R7 never run there and the LLM remains the only check.
#   · On the strict payloads, every NON-date temporal question stays with the LLM: a
#     summary and a trend row disagreeing about the same night, two surfaces
#     disagreeing about what day it is, word-number spans ("three weeks") in a string
#     value. None of those cite a pre-genesis date, so none are dropped.
#   · The residue genuinely lost: a pre-cycle date on a strict payload in a key R6/R7
#     do not read (neither a row `date` nor a night field) — e.g. a stale
#     `last_weighin_date`. R6/R7 were NOT widened to every ISO-valued key on
#     speculation: a baseline/anchor date may legitimately predate genesis (the
#     restart pipeline's `--override-weight-lbs` case), and inventing a rule for an
#     unobserved shape is how a check earns its next false positive. Named here
#     rather than retired silently; file it if it is ever observed.

_PROMPT_HEADER = """You are a meticulous editorial truth reviewer for a public "measured life" \
experiment site. Below is the RENDERED TEXT of {k} of its surfaces (page prose and/or API payloads — \
no images). The site's data legitimately changes daily; you are judging whether the WORDS AND NUMBERS \
CAN BE TRUE at the current experiment phase, not whether they match any baseline.

EXPERIMENT PHASE (ground truth, computed from the codebase — trust this over anything the pages say):
{phase_line}

FLAG findings in exactly these three categories (with severity low|med|high):
1. "temporal_contradiction" — PROSE asserting a history the phase makes impossible: e.g. "over the \
past three weeks" early in the experiment, "seven days of an experiment" on Day 1 (word-numbers \
count), a day number or date inconsistent with the phase above, or two surfaces disagreeing about \
what day it is. Judge sentences, not bare JSON numerics — numeric window/span/day FIELDS are \
checked deterministically by code before you run and are not your concern. NEITHER ARE THE DATES \
IN AN /api/… PAYLOAD: every date and timestamp in those payloads is compared against the cycle \
start by code on this same run, so do not reason about whether one of them falls before the \
experiment began — that verdict is already made and is not yours. Judge the human-readable \
sentences there instead. A temporal_contradiction must be an IMPOSSIBILITY your own arithmetic \
establishes against the phase above. Prose being vague, ambiguous, or imprecise about exactly when \
something happened is NOT a contradiction — if your objection resolves to "the phrase is \
vague/unclear/ambiguous", do not flag it in this category, and never above severity low.
2. "duplicated_narrative" — the SAME substantive narrative paragraph (or a near-identical one) \
appearing on two or more of the surfaces below. Shared navigation, footers, taglines, and short \
labels do NOT count — only real narrative/analysis prose.
3. "audience_violation" — copy that assumes the reader saw private context: unexplained internal \
jargon, references to private conversations or sessions ("as discussed", "like I told you"), or \
second-person notes clearly addressed to the site's owner rather than a public reader. EXCEPTION: \
surfaces under /coaching/ publish the coach-to-owner dialogue AS their content — the reader is \
deliberately observing the coaching relationship, so coaches addressing the owner by name or in \
the second person there is the designed format, never a violation. This exception is scoped to \
/coaching/ paths only; the same copy on any other surface stays flaggable.

Severity: "high" = a first-time reader would conclude the site is lying or broken; "med" = \
noticeably wrong but survivable; "low" = borderline/cosmetic.

DO NOT flag (these are CORRECT):
- lifetime / all-time / cross-cycle / "pilot" / previous-cycle / "pre-cut" / pre-experiment stats \
and framings labeled as such — history from before Day 1 legitimately exists and may be large;
- a day count in narrated or quoted prose that differs from your own date arithmetic by ONE — \
prose legitimately counts inclusively of both endpoints ("three days quiet" spanning the 19th to \
the 21st) or counts from an announcement day; flag an elapsed-time claim only when it is off by \
two or more days;
- an "as of <yesterday's date>" stamp on a daily-computed surface — the pipeline publishes data \
through the last COMPLETE day, so as-of = yesterday is the design, not staleness;
- a deadline or window "closing early" when the page never states the window's length — never \
flag against a window length you assumed;
- cost/billing charts using UTC day boundaries: AWS bills on UTC days, so a spend chart's point \
count or latest date may legitimately run one day ahead of Pacific today — that is the billing \
frame, not a fabricated day;
- the pre-start countdown copy itself, and honest sparse/empty states ("awaiting data", "N readings \
so far", "no data yet");
- the "··" placeholder glyph — it is the site's honest-absence marker (ADR-104): a tile, chart, \
metric or section reading "··" is DECLARING that no data exists, never claiming data. Pre-start and \
early-cycle pages deliberately stage their instruments with "··" (empty scaffolding is the designed \
honest state, not an implied history);
- durable design copy and structural UI affordances describing what the experiment DOES once \
running — {durable_copy}, section headings for \
instruments that currently read "··". Habitual-present descriptions of the design are correct in \
EVERY phase — before Day 1, ON Day 1, and after; flag only prose asserting that specific \
measurements or progress ALREADY happened when the phase makes that impossible;
- a sleep/recovery/HRV/RHR figure whose narrated night is the day BEFORE the cycle start, on a \
page dated on or after the cycle start. These metrics are keyed to the MORNING they were recorded \
against, so the night behind Day 1's morning is necessarily the night before Day 1 — that is the \
frame being correct, not two surfaces disagreeing about the date;
- story/archive/chronicle content clearly dated before the current cycle;
- the same header/nav/footer chrome appearing on every page;
- API field names or JSON structure — judge only human-readable narrative values inside them;
- a window/span/n SMALLER than the elapsed day count — e.g. "5 day(s)" or "n = 5" on Day 6, or a \
field named for 30 days reading null. In-cycle windows clamp to the cycle start, so an under-filled \
window is the CORRECT behaviour and a null "30d" field is the system being honest, not broken;
- a trailing window or average LONGER than the elapsed day count over a continuous signal — a \
"7-day average" of HRV/RHR/sleep/weight on Day 6 is CORRECT: those baselines are computed over the \
raw timeseries, which continues across cycle restarts by design (only experiment-scoped stats reset \
at Day 1). The experiment day counter ("DAY N") counts the current cycle; it NEVER bounds how much \
data, history, or narrative a page may show, and "only N days of data can exist" is not a valid \
inference from it. Flag a too-long window ONLY when the page explicitly claims the window is \
in-cycle ("this cycle's 7-day average") while the cycle is younger than the window.

SURFACES ({k}):
"""

# ── #3399 (2026-09-01): `basis` is a POST-NOTE field — order is the mechanism ──
#
# THE OBSERVED FAILURE (run 33451827346, the cycle-15 pre-start eve; the artifact
# is replayed verbatim in tests/test_reader_truth_withdrawn_basis_3399.py).
# /method/voicefidelity/ FAILed the sweep on a high whose own note narrates a
# re-check and ends "…This is correctly framed as historical. Withdrawing this
# finding." — labelled `basis: "impossibility"`, precisely what this footer's old
# closing sentence forbade in prose. Measured over all 35 findings in that run,
# `basis: "withdrawn"` was emitted ZERO times: the structured channel #3337 built
# was populated and WRONG, which is worse than absent.
#
# WHY: the old schema ordered each finding `severity, basis, note`. Generation is
# autoregressive — the judge had committed its basis tokens before writing one
# word of the note, so a retraction it reasons its way to MID-NOTE had no
# structured place left to land. Instructing it not to do that was a prose
# clause, and prose clauses measure 3-of-3 / 25-of-60 ignored (#2613/#2741).
#
# THE FIX is the field order: `basis` now closes each finding, emitted AFTER the
# note, so the classification happens after the re-check the note narrates.
# `basis: "withdrawn"` is thereby the judge's own post-note structured withdrawal
# marker — `_normalize_finding` keeps it and `is_self_refuted` channel 1 drops
# the finding on the FIELD, no phrase list anywhere (`_WITHDRAWAL_RE` stays a
# logged tiebreak that can never decide alone). A first-pass mislabel gets its
# second structured chance at the #2741/#3102 confirm passes, which re-judge
# every would-gate high under this same contract before anything gates.
# Emission rate on live runs is the #3399 acceptance measurement — if it stays
# at 0 the field is not carrying its design load, and that is its own finding.
_PROMPT_FOOTER = """
Respond with ONLY a JSON object, no prose, no markdown fences:
{{"findings": [{{"page": "<path of the surface, exactly as given>", \
"category": "temporal_contradiction"|"duplicated_narrative"|"audience_violation", \
"severity": "low"|"med"|"high", "note": "string", \
"basis": "impossibility"|"ambiguity"|"withdrawn"}}], \
"severity": "ok"|"low"|"med"|"high", "summary": "one sentence"}}
Set top-level "severity" to the maximum finding severity, or "ok" if there are no findings.
"basis" is each finding's LAST field, filled after its note is written: re-read what the note \
actually concluded and record that — "impossibility" = the phase makes the copy impossible; \
"ambiguity" = the copy is unclear/imprecise but not impossible; "withdrawn" = the note's own \
re-check retracted the finding. If the note ends by withdrawing or retracting, "basis" MUST \
be "withdrawn" — a retraction reached while writing the note belongs in this field, never \
only in the prose."""


def build_prompt(pages, phase, max_chars=MAX_PROSE_CHARS):
    """Build the reader-truth prompt for one batch of surfaces.

    `pages`: [{"name": str, "path": str, "prose": str}, ...] (4-6 per batch so the
    duplicated-narrative check sees the surfaces side-by-side).
    """
    # #2741: the exempt-copy examples render from DURABLE_DESIGN_COPY, the same
    # tuple the deterministic drop enforces — one vocabulary, so the clause the
    # model reads and the clause code applies cannot drift (charter primitive 1).
    parts = [
        _PROMPT_HEADER.format(
            k=len(pages),
            phase_line=_phase_line(phase),
            durable_copy=", ".join(f'"{s}"' for s in DURABLE_DESIGN_COPY),
        )
    ]
    for i, p in enumerate(pages, 1):
        prose = (p.get("prose") or "").strip()
        if len(prose) > max_chars:
            prose = prose[:max_chars] + "\n…[truncated]"
        parts.append(f"\n--- SURFACE {i}: {p.get('name', '?')} ({p.get('path', '?')}) ---\n{prose}\n")
    parts.append(_PROMPT_FOOTER)
    return "".join(parts)


# ── verdict parsing ────────────────────────────────────────────────────────────


def parse_verdict(text):
    """Pull the JSON verdict out of the model reply, tolerating stray prose/fences.

    Unparseable output degrades to a no-findings verdict (never raises) — the
    hooks treat a missing verdict as advisory, not as a pass OR a fail.
    """
    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not m:
        return {"findings": [], "severity": "ok", "summary": "(no structured verdict)", "raw": (text or "")[:200]}
    try:
        v = json.loads(m.group(0))
    except json.JSONDecodeError:
        return {"findings": [], "severity": "ok", "summary": "(unparseable verdict)", "raw": (text or "")[:200]}
    if not isinstance(v.get("findings"), list):
        v["findings"] = []
    return v


def _normalize_finding(f, batch_paths):
    """Coerce one model finding into the canonical shape; never raises."""
    if not isinstance(f, dict):
        return None
    sev = f.get("severity")
    if sev not in SEVERITIES:
        sev = "low"  # an unrecognized severity must never gate
    cat = f.get("category")
    if cat not in CATEGORIES:
        cat = "other"
    page = str(f.get("page") or "")
    if page not in batch_paths:
        # tolerate missing/extra slashes from the model
        norm = "/" + page.strip("/") + "/" if page.strip("/") else page
        if norm in batch_paths:
            page = norm
    # #3003: the note is stored IN FULL — this used to be `[:300]`, which meant the
    # artifact of record (qa-screenshots/report.json) kept only a mid-word fragment
    # of every finding's evidence, and triage necessarily worked from a partial
    # sentence (the [never diagnose from a truncated log line] trap built into the
    # instrument's own record). The note is already bounded by the model's own
    # max_tokens (1500/batch); truncation belongs at PRINT time only.
    out = {"page": page, "category": cat, "severity": sev, "note": str(f.get("note") or "")}
    # #3337: the judge's own structured basis, kept ONLY when it is one of the three
    # enum values. Absent or unrecognized → the field is omitted and every ruling
    # falls back to its structural evidence channel, exactly as before this shipped.
    if f.get(JUDGE_BASIS_FIELD) in JUDGE_BASIS_VALUES:
        out[JUDGE_BASIS_FIELD] = f[JUDGE_BASIS_FIELD]
    return out


# ── assessment loop ────────────────────────────────────────────────────────────


def _batches(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def assess_prose(pages, invoke, model_name=None, today_iso=None, batch_size=DEFAULT_BATCH_SIZE, max_chars=MAX_PROSE_CHARS):
    """Run the reader-truth rubric over `pages` in 4-6 surface batches.

    Args:
        pages: [{"name", "path", "prose"}, ...] — surfaces with rendered text.
        invoke: a bedrock_client.invoke-compatible callable (injectable for tests).
        model_name: model override; default Haiku (DEFAULT_MODEL).
        today_iso: phase anchor override (tests derive it from EXPERIMENT_START_DATE).

    Returns (findings, errors):
        findings: normalized dicts {"page", "category", "severity", "note"}.
        errors: per-batch error strings — a failed batch is reported, never raised
                (fail-soft: a Bedrock outage degrades to "no verdict", not a crash).
    """
    phase = phase_context(today_iso)
    pages = [p for p in pages if (p.get("prose") or "").strip()]
    findings, errors = [], []
    for batch in _batches(pages, max(1, batch_size)):
        prompt = build_prompt(batch, phase, max_chars=max_chars)
        batch_paths = {p.get("path") for p in batch}
        try:
            resp = invoke(
                {"messages": [{"role": "user", "content": [{"type": "text", "text": prompt}]}], "max_tokens": 1500},
                model_name=model_name or DEFAULT_MODEL,
            )
            text = "".join(b.get("text", "") for b in resp.get("content", []) if b.get("type") == "text")
            for raw in parse_verdict(text).get("findings", []):
                f = _normalize_finding(raw, batch_paths)
                if not f:
                    continue
                # #2613: the retirement, enforced. The deterministic pass graded this
                # payload's dates against the cycle start on this same run and cannot
                # be budget-paused, so a competing LLM verdict on that question is
                # discarded — printed, never silently swallowed.
                if is_code_owned_temporal(f, phase["start_date"]):
                    print(
                        f"  ↩ reader-truth: dropped a code-owned pre-cycle-date finding on {f['page']} "
                        f"(phase_plausibility R6/R7 owns this, #2613): {f['note'][:120]}"
                    )
                    continue
                # #2780: same discipline for the mid-cycle wake-date frame — printed,
                # never silently swallowed.
                if is_wake_frame_correct(f, phase["today"]):
                    print(
                        f"  ↩ reader-truth: dropped a wake-frame-correct night finding on {f['page']} "
                        f"(night_of + 1 = as_of IS the convention, #2780): {f['note'][:120]}"
                    )
                    continue
                # 2026-08-21: the model's own UTC→Pacific arithmetic is wrong (it
                # applied PST in August), so the contradiction it reports rests on a
                # timestamp that does not exist. Deterministic computation precedes the
                # LLM verdict (ADR-105) — printed, never silently swallowed.
                if is_utc_offset_misread(f):
                    print(
                        f"  ↩ reader-truth: dropped a finding on {f['page']} whose own UTC→Pacific "
                        f"conversion is wrong (DST offset misapplied): {f['note'][:120]}"
                    )
                    continue
                # #2741: the durable-design-copy retirement, enforced. Every quoted
                # span in the note is registered exempt copy, so the finding is a
                # re-reading of the DO-NOT-FLAG clause, not a truth finding —
                # printed, never silently swallowed.
                if is_durable_design_copy(f):
                    print(
                        f"  ↩ reader-truth: dropped a durable-design-copy finding on {f['page']} "
                        f"(the rubric names this copy exempt in every phase, #2741): {f['note'][:120]}"
                    )
                    continue
                # #2959 (2026-08-23): an archival-surface finding whose own
                # evidence cites the pre-cycle date/label that exempts it —
                # printed, never silently swallowed.
                if is_prior_cycle_archive(f, phase["start_date"], phase.get("cycle")):
                    print(
                        f"  ↩ reader-truth: dropped a labeled-prior-cycle archive finding on {f['page']} "
                        f"(dated archival content is the exemption, #2959): {f['note'][:120]}"
                    )
                    continue
                # #2959 (2026-08-23): the coach-surface audience adjudication —
                # /coaching/ publishes the coach→owner dialogue as its content.
                # Printed, never silently swallowed.
                if is_coach_surface_audience(f):
                    print(
                        f"  ↩ reader-truth: dropped a coach-surface audience finding on {f['page']} "
                        f"(the /coaching/ door publishes the dialogue as content, #2959): {f['note'][:120]}"
                    )
                    continue
                # #2959: the note's own last sentence withdraws the claim ("No
                # contradiction here on rechecking arithmetic" — and it still came
                # back `high`, run 32618360726). Gating on a claim its own evidence
                # retracts is gating on nothing. Printed, never silently swallowed.
                if is_self_refuted(f, phase["start_date"], phase["today"]):
                    print(
                        f"  ↩ reader-truth: dropped a self-refuted finding on {f['page']} "
                        f"(its own final sentence withdraws the contradiction, #2959): {f['note'][:120]}"
                    )
                    continue
                # ── the ADVISORY rulings (#2959/#3003/#3199), one table ────────
                # Each of these five adjudicated a measured false-positive class
                # and each says, in its own comment block, that the finding it
                # catches stays "visible as advisory, never gating". #3258 makes
                # that true in two ways the old shape could not:
                #
                #   (a) CONSULTED AT EVERY SEVERITY. This block used to be five
                #       `if f["severity"] != "low" and <ruling>(f)` statements, so
                #       a finding the model itself rated `low` was never
                #       adjudicated — and `low` is exactly the severity
                #       qa-smoke-warnings still fires on. The live Day-11 `539c6d`
                #       retraction is a `low` on which `is_vagueness_objection`
                #       returns True; the ledger simply never asked.
                #   (b) RECORDED AS A FIELD, not as a severity side-effect. The
                #       ruling ids land on the finding (`rulings`), which is what
                #       qa_check_reader_truth routes on — adjudicated findings go
                #       to the non-alarmed ChronicWarnCount, so WarnCount means
                #       "no reconsideration fired on this one".
                #
                # The severity demotion is unchanged and still only applies above
                # `low` (demoting a low to a low was always a no-op). Every ruling
                # is printed, never silently swallowed.
                # #3337: `phase["today"]` (the resolved Pacific date), never the raw
                # `today_iso` argument — which is None on every production run, so
                # every today-aware ruling was silently running without a clock.
                for ruling_id, label, fires, reason in advisory_rulings(phase["start_date"], phase["today"]):
                    if not fires(f):
                        continue
                    f = dict(f, **{RULINGS_FIELD: sorted(set(f.get(RULINGS_FIELD) or ()) | {ruling_id})})
                    if f["severity"] != "low":
                        print(f"  ↩ reader-truth: demoted {label} on {f['page']} " f"{f['severity']}→low ({reason}): {f['note'][:120]}")
                        f = dict(f, severity="low")
                    else:
                        print(
                            f"  ↩ reader-truth: adjudicated {label} on {f['page']} as ADVISORY at low "
                            f"({reason}) — visible, never alarmed (#3258): {f['note'][:120]}"
                        )
                findings.append(f)
        except Exception as e:
            errors.append(f"batch [{', '.join(str(p.get('path')) for p in batch)}]: {str(e)[:140]}")
    return findings, errors


# ── HTML → text (for the nightly hook's HTTPS-fetched pages) ──────────────────


class _TextExtractor(HTMLParser):
    _SKIP = {"script", "style", "noscript", "template"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._chunks = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip_depth += 1

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data):
        if not self._skip_depth and data.strip():
            self._chunks.append(data.strip())

    def text(self):
        return "\n".join(self._chunks)


def html_to_text(html):
    """Visible-ish text from an HTML document (stdlib only; script/style stripped).

    Static-HTML approximation of the browser's innerText — good enough for the
    nightly hook (server-rendered prose + labels); the CI hook gets the real
    rendered innerText from the Playwright harness.
    """
    try:
        p = _TextExtractor()
        p.feed(html or "")
        return re.sub(r"\n{3,}", "\n\n", p.text())
    except Exception:
        return re.sub(r"<[^>]+>", " ", html or "")  # crude fallback, never raises


# ── deterministic vitals-freshness rule (#1226 / recurrence of #787) ─────────────
#
# The LLM rubric above judges prose narratively; this rule is DETERMINISTIC (no
# Bedrock) so it gates the same way every run and is unit-testable offline. It
# encodes the #1226 defect directly: the "EACH COACH'S READ" digest cards quoted
# Day-1 vitals ("recovery dip 60% → 44%", "resting heart rate 62 bpm") with no
# as-of date, one click from a cockpit showing recovery 96% / RHR 57. #787's fix
# added an as-of stamp only to the by-coach surface; this rule guards the digest
# surface it missed. Rule: any coach narrative quoting recovery/HRV/RHR must
# carry an as-of date; a DATED quote diverging > divergence_pct from that date's
# true vitals is a stale-as-current read.

# Divergence threshold — a recovery of 44 vs a true 96 is ~54% off, well over this.
VITALS_DIVERGENCE_PCT = 20.0

# (metric, window regex from the metric word, value regex inside that window).
# Windowed so "resting heart rate 62 bpm ... 315.6 lbs" only reads the 62, and a
# "60% → 44%" dip yields BOTH endpoints for the divergence check.
_VITALS_WINDOWS = (
    ("recovery", re.compile(r"recovery[^.]{0,40}", re.I), re.compile(r"(\d{1,3})\s*%")),
    ("hrv", re.compile(r"\bhrv\b[^.]{0,30}", re.I), re.compile(r"(\d{1,3})\s*ms", re.I)),
    ("rhr", re.compile(r"(?:resting heart rate|\brhr\b)[^.]{0,30}", re.I), re.compile(r"(\d{1,3})\s*bpm", re.I)),
)

# Any of these markers anywhere in a surface's prose counts as an as-of stamp —
# matches every string coachAsOf() can emit ("as of Jul 13", "… refresh paused",
# "… next refresh pending") plus the ISO/"read on" forms.
_AS_OF_MARKER = re.compile(r"\b(?:as of|as-of|read on|refresh paused|next refresh pending)\b", re.I)


def quoted_vitals(prose):
    """{metric: [int, ...]} for every recovery %/HRV ms/RHR bpm quoted in `prose`."""
    text = prose or ""
    out = {}
    for metric, win_re, num_re in _VITALS_WINDOWS:
        vals = []
        for w in win_re.finditer(text):
            for n in num_re.findall(w.group(0)):
                try:
                    vals.append(int(n))
                except (TypeError, ValueError):
                    pass
        if vals:
            out[metric] = vals
    return out


def _has_as_of(prose):
    return bool(_AS_OF_MARKER.search(prose or ""))


def _diverges(quoted, actual, pct):
    """True if `quoted` is more than `pct`% away from `actual`."""
    try:
        actual = float(actual)
    except (TypeError, ValueError):
        return False
    if actual == 0:
        return quoted != 0
    return abs(quoted - actual) / abs(actual) * 100.0 > pct


def check_vitals_freshness(surfaces, vitals_by_date=None, divergence_pct=VITALS_DIVERGENCE_PCT):
    """Deterministic reader-truth rule (#1226): flag coach narratives that quote
    recovery/HRV/RHR without an as-of date, and dated quotes that diverge from the
    known vitals of their as-of date.

    Args:
        surfaces: [{"name", "path", "prose", optional "as_of": "YYYY-MM-DD"}, ...].
        vitals_by_date: {"YYYY-MM-DD": {"recovery": float, "hrv": float, "rhr": float}}
            — optional; enables the divergence sub-check for surfaces carrying an
            explicit ISO `as_of`.
        divergence_pct: percentage tolerance before a dated quote is flagged.

    Returns normalized findings [{"page", "category", "severity", "note"}] in the
    same shape as the LLM path (category "temporal_contradiction"). Never raises.
    """
    vitals_by_date = vitals_by_date or {}
    findings = []
    for s in surfaces or []:
        prose = s.get("prose") or ""
        quoted = quoted_vitals(prose)
        if not quoted:
            continue
        page = s.get("path") or s.get("name") or "?"
        metrics = ", ".join(sorted(quoted))
        if not (s.get("as_of") or _has_as_of(prose)):
            findings.append(
                {
                    "page": page,
                    "category": "temporal_contradiction",
                    "severity": "high",
                    "note": (
                        f"coach narrative quotes {metrics} with no as-of date (#1226/#787) — "
                        "a reader can't tell these from the current cockpit vitals"
                    ),
                }
            )
            continue
        # Dated — check quoted values against that date's true vitals when known.
        truth = vitals_by_date.get(s.get("as_of")) if s.get("as_of") else None
        if not truth:
            continue
        for metric, vals in quoted.items():
            actual = truth.get(metric)
            if actual in (None, ""):
                continue
            for v in vals:
                if _diverges(v, actual, divergence_pct):
                    findings.append(
                        {
                            "page": page,
                            "category": "temporal_contradiction",
                            "severity": "med",
                            "note": f"quoted {metric} {v} diverges >{divergence_pct:.0f}% from the {s['as_of']} value {actual}",
                        }
                    )
    return findings


# ── #1224: reader-facing excerpts/summaries hard-cut mid-word ──────────────────
# A second DETERMINISTIC reader-truth rule (no Bedrock). The /story/ chronicle
# excerpt and the /coaching/ "EACH COACH'S READ" cards were built by a fixed-length
# `text[:N]` slice, so they ended on a bare mid-word fragment ("…before any dat",
# "…1,500 calories alloc") with no ellipsis — to a cold reader on the door aimed at
# friends/family that reads as a rendering bug. Rule: a reader-facing excerpt/summary
# field must not end in a lowercase letter (the issue's regex) while its underlying
# SOURCE text continues past the cut. A field ending in an ellipsis (the
# `truncate_at_word` fix), terminal punctuation, or equal to its full source is clean.

# Ends in a lowercase letter — the mid-word-fragment tell from the issue.
_MIDWORD_END = re.compile(r"[a-z]$")


def check_midword_truncation(surfaces):
    """Deterministic reader-truth rule (#1224): flag reader-facing excerpt/summary
    fields that were hard-cut mid-word.

    Args:
        surfaces: [{"name"/"path", optional "field", "value", "source"}], where
            `value` is the rendered excerpt/summary and `source` the full text it was
            derived from. A finding fires only when `value` is shorter than `source`
            (an actual truncation) AND ends on a bare lowercase letter with no
            ellipsis / terminal punctuation.

    Returns normalized findings [{"page","category","severity","note"}] in the same
    shape as the LLM/vitals paths (category "audience_violation"). Never raises.
    """
    findings = []
    for s in surfaces or []:
        value = (s.get("value") or "").rstrip()
        source = (s.get("source") or "").strip()
        if not value:
            continue
        # Not actually truncated (field carries the whole source) → clean.
        if len(value) >= len(source):
            continue
        # Cleanly terminated — the fix appends "…"; a real sentence end is also fine.
        if value.endswith("…") or value.endswith("...") or value[-1] in ".!?—":
            continue
        if _MIDWORD_END.search(value):
            page = s.get("path") or s.get("name") or "?"
            field = s.get("field") or "excerpt"
            findings.append(
                {
                    "page": page,
                    "category": "audience_violation",
                    "severity": "med",
                    "note": (
                        f"{field} ends mid-word ('…{value[-24:]}') while the source text continues (#1224) — "
                        "reads as a rendering bug on the door aimed at friends/family"
                    ),
                }
            )
    return findings
