"""reader_truth_rulings.py — the reader-truth oracle's ruling ledger (#2959).

Split from reader_truth_qa.py 2026-08-23 when the rulings outgrew the module's
1200-line ceiling (#1665): this file is the LEDGER — every deterministic
predicate that drops or demotes an oracle finding, each carrying the measured
history that earned it (#2613's discipline: a clause first, a structural drop
only after the clause measurably failed). reader_truth_qa.py is the RUBRIC —
prompt, phase ground truth, assessment loop — and re-exports these names so
every existing consumer (phase_plausibility, the CI harness, the nightly hook,
tests) keeps one import surface.

Read the per-predicate comment blocks before touching anything here: each one
is a ruling of record, not dead prose.

────────────────────────────────────────────────────────────────────────────────
THE BAR FOR ANY FUTURE `is_*` — STRUCTURAL, NEVER PHRASE-MATCHED (#3337).
────────────────────────────────────────────────────────────────────────────────
A ruling in this file may decide ONLY on:

  * the finding's `category`;
  * its `page` / surface, or the claim class the quoted copy belongs to;
  * PARSED EVIDENCE VALUES — dates, day numbers, claimed spans, quoted payload
    field values — compared against the phase ground truth
    (`reader_truth_evidence.py` is the parsing layer; use it, never inline a
    fresh regex); or
  * a STRUCTURED FIELD the judge emits because the prompt asks for it
    (`basis`, below) — a field is data, a sentence is not.

It may NOT decide on how the judge worded itself. A regex over the note's
adjectives may survive only as a TIEBREAK: it may confirm a decision a
structural predicate has already made possible, it may never make one alone,
and when it breaks a tie it PRINTS that it did (`_tiebreak`), so the residue is
countable in the logs rather than invisible.

WHY, measured — this is not style. #2613: 3 of 3 runs ignored a prompt-only
ruling clause. #2741: 25 of 60 runs flagged copy the DO-NOT-FLAG list named
exempt. #3199: a live re-run reproduced the same objection with none of the
matcher's keywords. #3208: main's visual-qa gated on a finding this ledger had
already ruled exempt, because the demotion was lexical — the INCIDENT_LOG calls
it "the third phrase-matched-suppressor instance in one session". The oracle's
finding population is NON-STATIONARY: one objection wears three phrasings on
three consecutive nights. A suppressor keyed to one phrasing is therefore both
one novel wording away from gating a healthy deploy AND one novel wording away
from silently exempting a real defect. Every rule below is classified
structural-vs-lexical in #3337's dated sweep, and the mutation tests in
tests/test_reader_truth_structural_rulings_3337.py hold each one to it.
"""

import re
from datetime import date

# The evidence layer (#3337) — the parsers and the judge's structured `basis`
# field that a structural ruling decides on. `quoted_spans`, `normalize_copy`,
# `note_dates` and the two regexes are re-exported through this module (and onward
# through reader_truth_qa) because consumers imported them from here before the
# split; nothing about their behaviour changed.
from operational.reader_truth_evidence import (  # noqa: F401
    DAY_N_RE as _DAY_N_RE,
    ISO_DATE_RE,
    JUDGE_BASIS_FIELD,
    JUDGE_BASIS_VALUES,
    MONTHS as _MONTHS,
    cites_payload_date_field,
    cycle_day,
    day_numbers,
    elapsed_spans,
    evidence_is_phase_anchors_only,
    judge_basis,
    normalize_copy as _normalize_copy,
    note_dates,
    out_of_phase_quantities,
    payload_dating_is_the_convention,
    payload_field_dates,
    quoted_spans,
    spans_scoped_to_cycle_start,
    tiebreak as _tiebreak,
    unquoted,
)

# #2613: the surfaces whose PRE-CYCLE-DATE question is owned by code, not by the
# rubric. These are exactly the payloads qa_check_reader_truth sweeps STRICTLY
# through phase_plausibility (R6: no row dated before the cycle start; R7: no
# night-scoped field reaching further back than genesis-1), which imports this set
# rather than keeping its own copy — one list, so the two passes' division of
# labour cannot drift apart silently.
CODE_OWNED_TEMPORAL_SURFACES = frozenset(
    {
        "/api/vitals",
        "/api/journey",
        "/api/glucose",
        "/api/sleep_detail",
    }
)

# An ISO date cited as evidence inside a model's note (not a phrase match — the
# comparison below is a date comparison). One copy, in the evidence layer.
_NOTE_ISO_DATE_RE = ISO_DATE_RE


def is_code_owned_temporal(finding, start_date):
    """True when `finding` is the pre-cycle-date class phase_plausibility R6/R7 owns.

    Three structural conditions, all required: the finding is a temporal_contradiction,
    it is against a payload the deterministic pass sweeps strictly, and its own cited
    evidence includes a date at or before the cycle start. A finding on an HTML page,
    on /api/coaches, or one citing only in-cycle dates (a summary disagreeing with a
    trend row, two surfaces disagreeing about today) is NOT this class and survives.
    """
    if finding.get("category") != "temporal_contradiction":
        return False
    if finding.get("page") not in CODE_OWNED_TEMPORAL_SURFACES:
        return False
    return any(d <= start_date for d in _NOTE_ISO_DATE_RE.findall(finding.get("note") or ""))


# Night-frame language in a finding's note ("night_of", "last_night", "night of" —
# matched after collapsing spaces to underscores so all three spellings converge).
_NIGHT_FRAME_TOKENS = ("night_of", "last_night")


# ── WIDENED STRUCTURALLY (#3337, 2026-08-30) ──────────────────────────────────
#
# THE OBSERVED FAILURE — live, and lighting `qa-smoke-warnings` as this was
# written. Wire note, `/aws/lambda/life-platform-qa-smoke`, Day 14, finding
# `fcd7d5`, `/api/sleep_detail`, temporal_contradiction/med (the log's own "full
# note (551 chars)" record, never the truncated WARN line):
#
#   "The payload states 'as_of_date': '2026-08-29' and 'night_of': '2026-08-28',
#    but today is 2026-08-30 (Day 14). The as_of_date should not be two days in
#    the past on a daily-computed surface; the design allows as_of_date to be
#    yesterday (2026-08-29), but this payload is dated to two days ago. The
#    trend_note acknowledges the wake-date convention and notes that 'sleep_trend
#    rows are keyed by WAKE date', but the primary sleep_detail object's
#    as_of_date being 2026-08-29 while the payload was generated 2026-08-31
#    exceeds the acceptable staleness window."
#
# Every field value it quotes is the convention being RIGHT: night_of + 1 =
# as_of, and as_of = today - 1 (the pipeline publishes through the last COMPLETE
# day — the rubric's own DO-NOT-FLAG list says so in as many words). The note
# even states the design allows yesterday, then re-anchors on a THIRD date (the
# generation timestamp, 08-31) to call yesterday "two days ago". The original
# 2026-08-16 channel below could not see it: the note cites four dates spanning
# three days, so the "one single-day span" test fails.
#
# THE STRUCTURAL FIX — a second channel that decides on the payload's OWN quoted
# field values rather than on the spread of every date in the prose. When the
# note quotes `as_of_date` and `night_of` and those two values satisfy the
# convention (night_of + 1 == as_of) AND as_of is fresh against the phase clock
# (today - as_of <= 1 day), the objection restates the convention whatever
# further dates the note brings in. A genuinely stale payload — as_of three days
# behind today — fails the freshness test and keeps gating, which is the whole
# discriminator.
def is_wake_frame_correct(finding, today=None):
    """True when `finding` restates the wake-date convention as a contradiction (#2780).

    The first production run of the confirm-before-FAIL path (#2741, 2026-08-16)
    confirmed a temporal_contradiction on /api/sleep_detail: 'last_night' carrying
    `night_of` D under `as_of_date` D+1. Measured against the whoop partition and the
    live payload, that is the #1923 convention being RIGHT: a night is dated by the
    evening it began, the payload by the morning it serves, so night_of + 1 day =
    as_of IS last night — mid-cycle, every day, not just at genesis (#2583 covered
    only the genesis edge). The deterministic night-label pass (R5, #1968) already
    requires these surfaces to name their night; per ADR-105 the LLM does not get to
    overrule the layer that already graded it.

    Two structural channels, either sufficient. Both require a
    temporal_contradiction on a night-scoped surface the deterministic pass grades,
    with night-frame language in the note.

      1. #2780 — every cited ISO date fits one single-day span. A >1-day spread (a
         genuinely stale night) or a single-date note survives at full severity.
      2. #3337 — the note quotes the payload's own `as_of_date` and `night_of`
         values, night_of + 1 == as_of (the convention), and as_of is no more than
         one day behind `today` (the design: data through the last COMPLETE day).
         Needs the phase clock; without `today` this channel is unavailable and the
         finding survives, which is the fail-closed direction.

    Any other surface, or any other category, survives at full severity.
    """
    if finding.get("category") != "temporal_contradiction":
        return False
    if finding.get("page") not in CODE_OWNED_TEMPORAL_SURFACES:
        return False
    note = finding.get("note") or ""
    if not any(t in note.lower().replace(" ", "_") for t in _NIGHT_FRAME_TOKENS):
        return False
    dates = {date.fromisoformat(d) for d in _NOTE_ISO_DATE_RE.findall(note)}
    if len(dates) >= 2 and (max(dates) - min(dates)).days == 1:
        return True
    return payload_dating_is_the_convention(note, today)


# ── the model does UTC→Pacific arithmetic, and gets the DST offset wrong ──────
#
# THE OBSERVED FAILURE (2026-08-21, confirmed on a second pass, so not a one-off).
# `/api/sleep_detail` carries UTC instants (`sleep_start`, trailing Z) alongside
# Pacific calendar dates. The model converted, and got it wrong by exactly one hour:
#
#   "sleep_start at 2026-08-21T07:02:51.150Z (7:02 AM UTC = ~11:02 PM prior Pacific
#    evening, but this is bedtime on the morning of Day 5, not the night before)"
#
# 07:02Z in August is **00:02 PDT (UTC-7)**, not 23:02. It applied PST (UTC-8). That
# hour is load-bearing: it moves the instant back across midnight onto the previous
# calendar day, which is the entire substance of the "contradiction" it then reported.
# The finding was rated `high` — the severity that FAILs a blocking gate.
#
# This is not a new class for this repo. `deploy/backfill_eightsleep_hours.py` exists
# because ingestion once "converted UTC timestamps to local hours with a FIXED
# standard-time offset (-8)", corrupting every PDT-season night. Same arithmetic, same
# off-by-one-hour, different actor — there it was our code, here it is the model.
#
# WHY A SUPPRESSOR RATHER THAN A BETTER PROMPT. #2741 measured what prose achieves
# here: a clause the model was told to honour was ignored in 25 of 60 runs, with
# severity flipping run-to-run on byte-identical input. The payload ALREADY ships
# `figure_scope.trend_sleep_start_note` spelling out the UTC-vs-Pacific split, and the
# model read it and still miscomputed. Per ADR-105 and charter primitive 4,
# deterministic computation precedes the LLM verdict: if the model's own arithmetic is
# demonstrably wrong, the conclusion resting on it is unsound and does not get to fail
# a gate. The finding is PRINTED, never silently swallowed.
#
# SCOPE — narrow on purpose. This fires only when the note quotes a UTC instant, states
# at least one local clock time, and NONE of the times it states is the correct Pacific
# rendering of that instant. A note that converts correctly and still objects is a real
# finding and survives untouched.
_UTC_INSTANT_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2})(?::\d{2}(?:\.\d+)?)?Z\b")
# Clock times as prose renders them: "11:02 PM", "7:02 AM", "23:02", "00:02".
_CLOCK_RE = re.compile(r"\b(\d{1,2}):(\d{2})\s*(AM|PM)?\b", re.I)


def _pacific_renderings(iso_date, hh, mm):
    """Every spelling of the correct America/Los_Angeles time for a UTC instant.

    Converts at the instant's OWN date, so DST is exact rather than a fixed offset —
    which is the whole bug this guards.

    The frame comes from `common.pacific_time.PACIFIC`, the ONE canonical definition
    (#1964), never a locally-constructed `ZoneInfo`. Re-deriving it here is how the
    platform ends up with two Pacific frames that can disagree — and it would be an
    especially poor look inside the function whose entire job is catching a wrong
    Pacific conversion. The #1964 guard caught exactly that in this file's first draft.
    """
    from datetime import datetime, timezone

    from common.pacific_time import PACIFIC

    utc_dt = datetime(int(iso_date[:4]), int(iso_date[5:7]), int(iso_date[8:10]), hh, mm, tzinfo=timezone.utc)
    local = utc_dt.astimezone(PACIFIC)
    h24, minute = local.hour, local.minute
    h12 = h24 % 12 or 12
    ampm = "AM" if h24 < 12 else "PM"
    return {
        f"{h24}:{minute:02d}",
        f"{h24:02d}:{minute:02d}",
        f"{h12}:{minute:02d} {ampm}",
        f"{h12}:{minute:02d}{ampm}",
    }


def is_utc_offset_misread(finding):
    """True when the note's own UTC→Pacific arithmetic is wrong (2026-08-21).

    Structural conditions, all required: a temporal_contradiction; on a surface whose
    temporal grading code already owns; the note quotes a UTC instant; the note states
    at least one clock time; and none of the clock times it states matches the correct
    Pacific rendering of that instant.
    """
    if finding.get("category") != "temporal_contradiction":
        return False
    if finding.get("page") not in CODE_OWNED_TEMPORAL_SURFACES:
        return False
    note = finding.get("note") or ""
    instants = _UTC_INSTANT_RE.findall(note)
    if not instants:
        return False
    # Scan for STATED clock times in the prose only — with the instants removed first.
    # An ISO instant contains its own "07:02", and counting that as the model's stated
    # conversion made a note that offers NO conversion look like a wrong one. The
    # timestamp is the input to the arithmetic, never its output.
    prose = _UTC_INSTANT_RE.sub(" ", note)
    stated = {f"{int(h)}:{m}" + (f" {ap.upper()}" if ap else "") for h, m, ap in _CLOCK_RE.findall(prose)}
    if not stated:
        return False
    correct = set()
    for iso_date, hh, mm in instants:
        try:
            correct |= _pacific_renderings(iso_date, int(hh), int(mm))
        except Exception:  # noqa: BLE001 — an unparseable instant is not this class
            return False
    normalized_stated = {s.upper().replace("  ", " ").strip() for s in stated}
    normalized_correct = {c.upper().replace("  ", " ").strip() for c in correct}
    return not (normalized_stated & normalized_correct)


# ── durable design copy: the rubric's exempt vocabulary, enforced (#2741) ─────
#
# THE REGISTRY. These strings were named as exempt in the prompt's DO-NOT-FLAG
# list from 2026-08-09, widened at #2575, and re-stated at #2741 — and the model
# went on flagging them anyway. Measured from the qa-smoke log group over the ten
# days to 2026-08-18: a home-page `temporal_contradiction` was raised in **25 of
# 60 runs (42%)**, spanning Day 6 of cycle 13, the pre-start countdown, Day 1 and
# Day 2 of cycle 14 — i.e. in every phase, which is exactly the claim the clause
# makes. Severity flipped run to run on byte-identical copy: two runs 35 minutes
# apart produced `med` then `high`, and `high` is what FAILs a blocking alarm.
#
# That is #1922's and #2613's signature, and both of those retired their class
# STRUCTURALLY after measuring that prose could not fix it. Per ADR-105 and
# charter primitive 4, the exemption stops being an instruction the model may
# ignore and becomes a decision code makes: the vocabulary lives here, ONE copy,
# and `build_prompt` renders the prompt's example list from it — so the clause the
# model reads and the clause the code enforces cannot drift apart (charter
# primitive 1 + 2; the derivation is asserted in tests/test_durable_design_copy_2741.py).
#
# SCOPE — deliberately narrow, per the issue's own bar. A finding is dropped only
# when EVERY quoted span in the model's note is one of these strings. A note that
# also quotes something else (a progress claim, a number, any other sentence) is
# NOT this class and survives at full severity, because the thing being retired is
# the re-litigation of design copy, not the ability to catch a page that claims
# progress it has not made.
DURABLE_DESIGN_COPY = (
    "starts at the Day-1 weigh-in",
    "tap any day",
    "the week ahead",
    # #3003 (2026-08-22): /data/habits/' 90-day adherence heatmap caption. The heatmap
    # deliberately shows pre-genesis history (ADR-077 cross-phase, "clamped, not
    # hidden") and this caption is the DISCLOSURE that makes it honest — the page
    # saying, in as many words, that the history predates the cut. The oracle raised
    # a high temporal_contradiction against the disclosure itself; render-verified
    # against the live page (the current-cycle series next to it is separately and
    # correctly windowed "AUG 17–AUG 22 · 6 PTS"). Habitual-present design copy,
    # correct in every phase.
    "90-day history predates the cut",
)

# The quoted-span parser and the dash/case normalizer moved to
# reader_truth_evidence.py in #3337 (imported above, re-exported unchanged): the
# typography lesson they carry — live notes quote page copy with U+2011 hyphens and
# curly quotes, so a raw string compare silently never matches — is recorded there.


def is_durable_design_copy(finding):
    """True when `finding` re-litigates registered durable design copy (#2741).

    Structural conditions, all required: the finding is a temporal_contradiction;
    its note quotes at least one span; and EVERY quoted span contains a registered
    durable-design string. A note quoting any other page copy alongside it survives,
    as does any finding in another category.
    """
    if finding.get("category") != "temporal_contradiction":
        return False
    spans = quoted_spans(finding.get("note"))
    if not spans:
        return False
    registry = [_normalize_copy(s) for s in DURABLE_DESIGN_COPY]
    return all(_is_registered_span(_normalize_copy(span), registry) for span in spans)


# A quoted span counts as registered copy in either direction of containment. The
# 2026-08-15 21:49Z production note quotes the whole string AND the bare fragment
# 'starts at' — a note re-litigating exempt copy naturally quotes pieces of it, and
# requiring whole-string equality would have kept that finding while dropping its
# near-identical siblings. The fragment direction carries a length floor so a stray
# common word inside a registered phrase ("the", "day") can never exempt a finding.
_MIN_FRAGMENT_CHARS = 8


def _is_registered_span(span, registry):
    return any(r in span or (len(span) >= _MIN_FRAGMENT_CHARS and span in r) for r in registry)


# ── a "contradiction" whose own objection resolves to vagueness (#3003) ────────
#
# THE OBSERVED FAILURE (2026-08-22, CI run 32601989142 — one of the two highs that
# held the site publish path). /story/timeline/ rendered "DAY 6 · WEEK 1, SINCE
# AUGUST 17 2026" and "The logs have gone quiet — 4 days without an entry" (fed by
# the fail-closed /api/presence, which reported gap_days=4.0 at that moment — the
# copy was TRUE). The oracle's note did the arithmetic itself — "the last entry
# would have been on Day 2 or earlier" — which places the last entry INSIDE the
# cycle, i.e. its own arithmetic establishes consistency, not contradiction. It
# then retreated to "The phrase '4 days without an entry' is vague abou[t]…" and
# still graded the finding `high`, the severity that FAILs a blocking gate.
#
# THE RULING (#3003 acceptance): "vague" is not a temporal_contradiction. The
# category is defined as prose asserting a history the phase makes IMPOSSIBLE;
# an objection that resolves to the phrasing being vague/ambiguous/unclear is by
# construction not an impossibility claim, and the rubric's own severity bar
# ("high = a first-time reader would conclude the site is lying or broken")
# cannot be met by an admitted ambiguity. A high that resolves to vagueness
# costs a deploy.
#
# WHY CODE AND NOT ONLY A PROMPT CLAUSE. This file's own measured record
# (#2613: 3 of 3 runs ignored the ruling clause; #2741: 25 of 60 runs flagged
# copy the DO-NOT-FLAG list named exempt) is that prose alone does not retire a
# false-positive class. The prompt states the principle (category 1 below) AND
# this predicate enforces it. DEMOTED to "low" rather than dropped — the model's
# observation may still be worth a human glance as an advisory warning, it just
# never gates. Printed, never silently swallowed.
#
# ── RESHAPED STRUCTURALLY (#3337, 2026-08-30) ─────────────────────────────────
#
# THE DEFECT IN THE RULING ITSELF. As shipped, the only structural condition was
# `category == "temporal_contradiction"`; the verdict was an adjective regex. Two
# failure directions, both one wording away and both live:
#
#   * a rephrased identical objection ("the wording does not commit to a tense",
#     "creates ambiguity about which date is current") passes at full severity and
#     can gate a deploy — the exact non-stationarity #2613/#2741/#3199 measured;
#   * a GENUINE impossibility that happens to say "unclear whether" is demoted, so
#     the phrasing hides a real defect.
#
# THE STRUCTURAL PREDICATE. The rubric defines this category as "an IMPOSSIBILITY
# your own arithmetic establishes against the phase". Establishing one requires
# CITING a value the phase cannot hold: a date outside [cycle start, today], a day
# number past today's, or a claimed elapsed span longer than the cycle. So the
# question a ruling can actually decide is arithmetic, not editorial — did the
# judge assert anything out of phase? `out_of_phase_quantities()` answers it from
# the judge's OWN prose (quoted page copy excluded: it is the claim under dispute,
# not the judge's evidence — the #3258 note's quoted "90 consecutive days" goal is
# why that distinction is load-bearing).
#
# Two guards keep the demotion off real findings, both derived from live wire
# notes rather than imagined:
#
#   * A NAMED PAYLOAD DATE FIELD IS A DATA CLAIM, NOT AN EDITORIAL ONE. Two live
#     wire notes make the point, both citing only in-phase values and both TRUE:
#     `/api/vitals` d1c6a0 ("weight_as_of is 2026-08-24 (6 days ago), but the API
#     metadata states as_of_date is 2026-08-30") — a real 6-day scale gap, still
#     lighting the alarm as this shipped; and `/api/glucose` e5eafd ("as_of_date
#     is 2026-08-22, but the payload was generated on 2026-08-24 (Day 8)") — which
#     the deterministic plausibility pass independently FAILED with arithmetic two
#     days later. A ruling about how page copy READS never adjudicates a note that
#     names a payload date field.
#   * IT MUST BE GROUNDED IN TODAY'S COUNTER. The note has to cite the current day
#     number (±1) — the "on Day 6 …" shape this class always takes. A note that
#     never places itself on the cycle clock is not this class.
#
# The adjective regex survives ONLY as a logged tiebreak for notes that clear the
# out-of-phase test but are not grounded in the day counter (the #3258 `539c6d`
# home-page retraction is exactly that shape: it cites "Day-1" and nothing else).
# It cannot fire alone, and when it decides it says so in the log.
#
# DEMOTED to "low" + recorded as adjudicated, never dropped — unchanged.
#
# RESIDUE, named honestly (2026-08-30): a temporal_contradiction that cites
# nothing out of phase, sets no payload fields against each other, and IS grounded
# in today's day number is demoted to advisory even when its substance is two
# HTML surfaces disagreeing about the same in-cycle day. That objection is still
# printed, still travels with its full note, and still lands in the check list and
# the digest email — it just rides ChronicWarnCount instead of gating. The trade
# is deliberate: the alternative is deciding "is this an impossibility or an
# ambiguity?" on the judge's adjectives, which is the thing this issue retires.
_VAGUENESS_OBJECTION_RE = re.compile(
    r"\b(?:is|are|was|were|being|remains?|seems?|appears?)\s+(?:somewhat\s+|rather\s+|too\s+)?(?:vague|ambiguous|unclear|imprecise)\b"
    r"|\b(?:vague|ambiguous|unclear|imprecise)\s+(?:about|as\s+to|whether|on|regarding)\b",
    re.I,
)


def is_vagueness_objection(finding, start_date=None, today=None):
    """True when a temporal_contradiction establishes no impossibility (#3003, #3337).

    Channels, in order — the first two decide structurally, the third may only
    break a tie the first two left open, and it prints when it does:

      1. the judge's own `basis` field says "ambiguity" (a field, not a phrase);
      2. the note asserts nothing out of phase, names no payload date field, and
         is grounded in today's day number (±1);
      3. the legacy adjective regex, ALLOWED ONLY when (2)'s out-of-phase test is
         clean — i.e. the note could not have proved an impossibility anyway.

    Fail-closed: without the phase anchors nothing but channel 1 can fire, so a
    caller that cannot supply them keeps the finding at full severity.
    """
    if finding.get("category") != "temporal_contradiction":
        return False
    if judge_basis(finding) == "ambiguity":
        return True
    n = cycle_day(start_date, today)
    if n is None:
        return False
    note = finding.get("note") or ""
    if cites_payload_date_field(note):
        return False
    days = day_numbers(note)
    if not out_of_phase_quantities(note, start_date, today) and days and abs(max(days) - n) <= 1:
        return True
    # THE TIEBREAK, and the one place a phrase is admitted. Same out-of-phase test,
    # with one narrowing: a span the judge never states in its OWN sentences does not
    # count against it (#3258's note quotes a 90-day GOAL from the page and never
    # restates it; every impossibility note this must spare says its number out loud
    # — "A 57-day history is impossible"). Dates and day numbers still bind in full,
    # so a note citing a pre-genesis date or a day beyond today can never be talked
    # out of gating by an adjective.
    if not out_of_phase_quantities(note, start_date, today, spans_in_quotes=False) and _VAGUENESS_OBJECTION_RE.search(note):
        return _tiebreak("vagueness_objection", finding, "hedged objection, nothing out of phase in the judge's own words")
    return False


# ── the day counter is not a data bound (#2959, 2026-08-23) ───────────────────
#
# THE OBSERVED FAILURE, five instances in 24h across two blocked deploys: the
# prompt hands the model the phase ground truth ("today is Day 6, Day 1 =
# 2026-08-17") and the model turns the day counter into a BOUND on what data can
# exist — "only 6 days of current-experiment data can exist", "a maximum of 5
# days of in-cycle data is possible" — then flags anything wider as a
# contradiction: a trailing 7-day HRV average (/, /cockpit/, run 32618360726),
# the cross-phase build log (/story/build/, run 32616299944), the graded-forecast
# count (/method/board/, #3015). The inference is wrong BY DESIGN of the data
# model: ADR-077's taxonomy resets only experiment_scoped partitions at genesis —
# raw timeseries, archives, and the build narrative are cross-phase, so trailing
# windows and pre-cycle history legitimately coexist with a young day counter.
# The strict payloads where pre-cycle rows genuinely ARE defects are exactly the
# CODE_OWNED_TEMPORAL_SURFACES phase_plausibility sweeps deterministically.
#
# The tell is self-contained (no clock needed): the note states a day-count bound
# AND names the same number as the current day ("Day 6" … "only 6 days") — i.e.
# the bound's only source is the day counter the prompt itself injected. DEMOTED
# to low rather than dropped: on the off-chance a page CLAIMS in-cycle scope
# while showing out-of-cycle data, the finding stays visible as advisory and the
# baseline machinery still records the pair.
_DAY_BOUND_RE = re.compile(
    r"\b(?:only|a maximum of|at most|max(?:imum)?(?: of)?)\s+(\d{1,3})\s+days?\b[^.?!]{0,100}?"
    r"\b(?:data|entr(?:y|ies)|history|narrative|exist|possible)",
    re.I,
)

# ── WIDENED STRUCTURALLY (#3208, 2026-08-26) ───────────────────────────────────
#
# THE OBSERVED FAILURE. CI run 33001307897 (job 98291865117) gated main's
# post-deploy visual-qa on /method/intelligence/ — verbatim wire note, pulled
# from the run artifact (never the truncated log line, per
# reference_judge_flake_ground_truth):
#
#   "States 'DAYS OF DATA TOWARD THE FIRST CORRELATION MATRIX · 9/10' and 'No
#    correlations yet — the honest state, not a broken pipeline. The weekly
#    matrix computes its first pairs once 10 overlapping days of this cycle's
#    data exist.' On Day 10 of the cycle, 10 days of data should exist, making
#    this claim impossible. The page claims correlations cannot compute until
#    10 days exist, yet we are on Day 10, so this is contradictory."
#
# Same substance as every #2959 instance above — the day counter (Day 10) turned
# into a bound on what data can exist — but "once 10 overlapping days … exist"
# and "10 days of data should exist" never say only / at most / a maximum of, so
# `_DAY_BOUND_RE` missed it. A live re-run of the identical scoped sweep against
# the same page reproduced the same underlying objection worded two more ways in
# the same evening — one that DID happen to carry "a maximum of" (coincidence,
# not the fix) and a second, independent generation that again used neither
# keyword and went on to a #3102 non-reproduction rather than a demotion. Three
# independently-generated notes, one true shape, and the lexical matcher caught
# it by luck in one of the three — #2613's and #2741's measured lesson (a
# suppressor keyed to one phrasing does not survive the oracle's non-stationary
# rephrasing) applies here too.
#
# THE STRUCTURAL FIX. Alongside the original lexical scaffold (kept — it still
# fires on every previously-observed note, so no regression), a SECOND, purely
# numeric channel: an "N/M" progress-fraction claim (the '9/10' shape) whose
# denominator M is the day counter is exactly the same tell as the lexical
# "only M days" bound — a claimed data-quantity that coincides with the injected
# day counter — just spelled as a fraction instead of a sentence. Guarded two
# ways against a false read: the numerator must not exceed the denominator (a
# completed/total shape, never a reversed or unrelated ratio — a date written
# "8/17" has numerator > nothing special, but a 'day' progress fraction is
# always <= 1, so this alone would not exclude it) AND the word "data" must
# appear within a short window around the fraction — every observed note pairs
# the count with a "data" framing ('DAYS OF DATA', "cycle's data exist",
# "current-cycle data"), which an unrelated fraction (a score, a calendar date
# written N/M) will not carry beside it.
#
# RESIDUE, named honestly: a genuine day-arithmetic defect — the page's own day
# stamp actually wrong, so the claimed number and the true day number disagree
# by MORE than 1 (the #2941 wrong-Day-number shape) — is not swept in by either
# channel; the ±1 tolerance is the whole discriminator, unchanged from #2959.
_PROGRESS_FRACTION_RE = re.compile(r"\b(\d{1,3})\s*/\s*(\d{1,3})\b")
_FRACTION_CONTEXT_CHARS = 60


def _fraction_day_bound_candidates(note):
    """Denominators of 'N/M' progress-fraction spans that plausibly claim a
    day-count threshold (#3208) — e.g. 'DAYS OF DATA … 9/10'. See the comment
    block above for the two guards (numerator <= denominator; 'data' nearby)."""
    candidates = set()
    for m in _PROGRESS_FRACTION_RE.finditer(note):
        n, denom = int(m.group(1)), int(m.group(2))
        if n > denom:
            continue
        window = note[max(0, m.start() - _FRACTION_CONTEXT_CHARS) : m.end() + _FRACTION_CONTEXT_CHARS]
        if "data" in window.lower():
            candidates.add(denom)
    return candidates


def is_day_counter_bound_inference(finding):
    """True when a temporal_contradiction's bound is the day counter itself
    (#2959, widened structurally #3208).

    Structural conditions, all required: temporal_contradiction; the note cites
    the experiment day ("Day M"); and the note also states a claimed
    data-quantity number matching M (±1 for the PT/UTC boundary) — either the
    original lexical "only/at most/maximum N days … data/entries/history/
    exist/possible" scaffold, OR an "N/M" progress-fraction claim in a
    data-quantity context (the '9/10' shape that escaped the lexical-only
    matcher, #3208). A bound unrelated to the day counter (retention windows,
    product limits), an unrelated fraction (no 'data' framing nearby), or a
    note that never mentions the day number survives untouched. A genuinely
    wrong day-count — the claimed number differs from the cited day by MORE
    than 1, the #2941 shape — also survives: that gap is a real defect, not the
    injected-counter artifact this predicate exists to catch.
    """
    if finding.get("category") != "temporal_contradiction":
        return False
    note = finding.get("note") or ""
    day_ns = {int(m) for m in _DAY_N_RE.findall(note)}
    if not day_ns:
        return False
    candidates = set()
    bound = _DAY_BOUND_RE.search(note)
    if bound:
        candidates.add(int(bound.group(1)))
    candidates |= _fraction_day_bound_candidates(note)
    return any(abs(c - m) <= 1 for c in candidates for m in day_ns)


# ── a finding whose own note withdraws the claim (#2959, 2026-08-23) ──────────
#
# THE OBSERVED FAILURE (run 32618360726, twice in one sweep): the model narrates
# its re-check and ends by withdrawing — "… making this Day 6 elapsed — the label
# is accurate. No contradiction here on rechecking arithmetic." (/data/wall/),
# "This is self-consistent and correct: … No contradiction." (/method/survival/)
# — and still emits the finding at `high`, which FAILs a blocking gate. Gating on
# a claim its own evidence retracts is gating on nothing. Only the LAST sentence
# counts: a mid-note "this is internally consistent. But the header …" is a live
# objection and survives (the /method/postmortems/ shape, same run).
# Phrase list widened same-day: the third blocked deploy's surviving high ended
# "This is within phase bounds and internally consistent." — a withdrawal the
# first list was too narrow to see. Last-sentence scoping is what keeps the
# widening safe: a mid-note "internally consistent. But …" still survives.
_WITHDRAWAL_RE = re.compile(
    r"\b(?:no contradiction|not a contradiction|self-consistent|internally consistent" r"|within phase bounds|label is accurate)\b",
    re.I,
)


# ── #2959 (2026-08-23): the labeled-prior-cycle-archive class, RETIRED ────────
# The DO-NOT-FLAG list has said "story/archive/chronicle content clearly dated
# before the current cycle" since #2575, and the 2026-08-23 cycle ground-truth
# sentence restated it — and the same sweep that carried both STILL raised highs
# on /story/diary/ ("'DAY 5 · CYCLE 10' dated 'JULY 26, 2026'"), /story/journal/
# ("dated 2026-07-08") and /journal/essays/org-chart-of-one/ ("dated JULY 8,
# 2026"), each note QUOTING the very date or cycle label that exempts it and
# then demanding a further "archive" label. That is the #2613 shape: a clause
# the model re-derives an accusation straight through. Per that precedent the
# class is retired structurally, scoped to the ARCHIVAL surfaces (/story/,
# /journal/ — the writing hubs, dated by design): a temporal_contradiction
# there whose own evidence cites a pre-cycle date or a prior cycle label is a
# re-read of the exemption, not a truth finding.
#
# Residue, named honestly: on those two path families a prose temporal
# contradiction that cites a pre-genesis date can no longer gate. A /story/ or
# /journal/ surface misrepresenting the CURRENT cycle (its notes cite in-cycle
# dates) stays fully flaggable, as does every other surface.

_CYCLE_LABEL_RE = re.compile(r"\bcycle\s+(\d{1,3})\b", re.IGNORECASE)
_ARCHIVE_PATH_PREFIXES = ("/story/", "/journal/")


def _note_dates(note):
    """Every date the note cites, as ISO strings — ISO literals + 'July 8, 2026' forms.

    Deliberately calls `note_dates` with NO default year, so a yearless "August 16"
    stays unparsed exactly as it was before the #3337 split. Widening this ruling's
    date vocabulary is a separate, argued change — not a side effect of extracting
    the parser.
    """
    return note_dates(note)


def is_prior_cycle_archive(finding, start_date, cycle=None):
    """True when an archival-surface temporal finding's own evidence cites a
    pre-cycle date or a prior cycle label (#2959 — the exemption, enforced)."""
    if finding.get("category") != "temporal_contradiction":
        return False
    page = str(finding.get("page") or "")
    if not page.startswith(_ARCHIVE_PATH_PREFIXES):
        return False
    note = str(finding.get("note") or "")
    if any(d < start_date for d in _note_dates(note)):
        return True
    if cycle:
        return any(0 < int(n) < cycle for n in _CYCLE_LABEL_RE.findall(note))
    return False


# ── #2959 (2026-08-23): the position banner is a clock, not a content label ───
#
# THE OBSERVED FAILURE (run 32650063358 — the high that auto-rolled-back the
# receipts-caption deploy): /story/ and /story/chronicle/ list a chronicle piece
# correctly dated 'WEEK 1 · 2026-08-18' (cycle-14 genesis 2026-08-17 ⇒ 08-18 IS
# Day 2 of Week 1 — the label is arithmetically right), and the model raised it
# `high`: "the prose intro states 'DAY 7 · WEEK 1, SINCE AUGUST 17 2026'.
# August 18 is Day 2 (Aug 17 = Day 1), not Day 7. The chronicle's own date …
# contradicts the page header claiming it is Day 7 content." The header claims
# no such thing: 'DAY N · WEEK K, SINCE <genesis>' is the site-wide position
# banner — TODAY's coordinate on the cycle, rendered identically on every page —
# not a label on the content listed beneath it. Earlier-in-cycle entries under
# today's banner are the design of a chronological archive. This is the #2959
# non-stationary tail producing a novel shape: prior sweeps carried the same
# banner on the same pages and never flagged it.
#
# THE RULING: a temporal_contradiction that (a) quotes the position banner as a
# header/intro claim, and (b) derives its contradiction by mapping a cited
# CONTENT date to a day number different from the banner's, is a misread of the
# clock as a content label. The residue that stays fully flaggable: a note that
# maps TODAY to a day number conflicting with the banner (the banner itself
# being wrong IS a real defect — the #2941 class) — the mapping check skips any
# date that is today; and a note that never quotes the banner survives
# untouched. DEMOTED to low, not dropped (the day-counter precedent): visible
# as advisory, recorded by the baseline machinery, never gating.
_POSITION_BANNER_RE = re.compile(
    r"\b(?:header|intro|banner)\b[^.?!]{0,80}?\bDAY\s+(\d{1,3})\s*[·\-]\s*WEEK\s+\d{1,2}\b",
    re.I,
)
# "<Month> <day>[, <year>] is Day M" and "<ISO date> is Day M" mappings.
_CONTENT_DAY_MAP_RE = re.compile(
    r"\b(?:(january|february|march|april|may|june|july|august|september|october|november|december)"
    r"\s+(\d{1,2})(?:,?\s+(\d{4}))?|(\d{4})-(\d{2})-(\d{2}))\s+is\s+Day\s+(\d{1,3})\b",
    re.I,
)


def is_position_banner_misread(finding, start_date, today=None):
    """True when a temporal_contradiction reads the DAY/WEEK position banner as a
    label on dated content rather than as today's clock (#2959).

    Structural conditions, all required: temporal_contradiction; the note quotes
    the banner ("header/intro … 'DAY N · WEEK K'"); and the note maps a cited
    content date — in-cycle, and not today — to a day number ≠ N. A note whose
    day-mapping is about TODAY (the banner itself wrong) survives untouched.
    """
    if finding.get("category") != "temporal_contradiction":
        return False
    note = finding.get("note") or ""
    banner = _POSITION_BANNER_RE.search(note)
    if not banner:
        return False
    banner_day = int(banner.group(1))
    default_year = str(start_date)[:4]
    for m in _CONTENT_DAY_MAP_RE.finditer(note):
        mon, day, year, iso_y, iso_m, iso_d = m.groups()[:6]
        mapped_day = int(m.group(7))
        if mon:
            date_iso = f"{year or default_year}-{_MONTHS[mon.lower()]:02d}-{int(day):02d}"
        else:
            date_iso = f"{iso_y}-{iso_m}-{iso_d}"
        if today and date_iso == today:
            continue
        if date_iso >= start_date and mapped_day != banner_day:
            return True
    return False


# ── #2959 (2026-08-23): the coach-surface audience ruling, ADJUDICATED ─────────
# The first armed full sweep (run 32545820852) raised audience_violation on
# /coaching/ and /coaching/by-coach/#physical_coach for coaches addressing Matthew
# by name / in the second person. The baseline entries said "adjudicate the
# audience rubric for coach pages" — this is the adjudication: the /coaching/
# door's designed content IS the coach→owner dialogue (the reader observes the
# coaching relationship; that is the product). The prompt states the exception;
# this predicate ENFORCES it structurally, because the module's own measured
# record (#2613: a clause survived by 3-of-3 runs; #2741) says prose clauses
# alone fail about half the time. Scoped to /coaching/ paths only — the same
# copy on /method/board/ (the #2972 producer-side debt, tracked in #3018) or any
# other surface stays fully flaggable.


def is_coach_surface_audience(finding):
    """True for an audience_violation finding on a /coaching/ surface (#2959)."""
    return finding.get("category") == "audience_violation" and str(finding.get("page") or "").startswith("/coaching/")


# ── RESHAPED STRUCTURALLY (#3337, 2026-08-30) ─────────────────────────────────
#
# THE DEFECT IN THE RULING ITSELF. A withdrawal is a speech act, and as shipped
# this ruling had nowhere to look but the words: a six-phrase list tested against
# the note's last sentence. #3258 hit its limit head-on — the live `539c6d`
# retraction ends "No flag warranted on reconsideration", which is not on the
# list — and refused to add a seventh phrase, naming the real fix instead: "the
# response contract — a per-finding `verdict: flag|withdrawn` field the judge
# fills, so a retraction has a structured place to live instead of leaking into
# prose". #3337 ships that field as `basis: "withdrawn"` (see the top of this
# file) and it is now the FIRST channel here.
#
# The phrase list is not extended — `tests/test_reader_truth_retracted_3258.py`
# still asserts it was not — but it is no longer allowed to decide alone. It is
# admitted only for a note that asserts NOTHING out of phase and names no payload
# date field: a judge that has cited a real out-of-phase value has not withdrawn
# anything, whatever its last sentence says, and a note objecting to a payload's
# own dating is a live data finding (the `/api/vitals` d1c6a0 and `/api/glucose`
# e5eafd shapes, both true, both in phase). This is a DROP ruling, so the narrowing
# direction matters: every case it stops firing on now keeps gating.
#
# RESIDUE, named honestly (2026-08-30): until the judge fills `basis`, a
# withdrawal worded outside the six phrases still reaches the buckets — the
# #3258 residue, unchanged and unhidden. What #3337 removes is the other half:
# a note that proves a real impossibility and happens to close with "internally
# consistent" is no longer silently dropped.
#
# ── #3399 (2026-09-01): the field arrived POPULATED AND WRONG ─────────────────
# The first live measurement of the #3337 channel (run 33451827346, 35 findings):
# `basis: "withdrawn"` was emitted ZERO times, and the run's one genuine
# withdrawal — a /method/voicefidelity/ note ending "Withdrawing this finding."
# — arrived as `basis: "impossibility"` at `high` and GATED. Channel 2 was also
# blind (that literal matches none of the six phrases); extending the list would
# be the family's fifth field failure and was refused. THE FIX lives in the
# response contract, not here: the old schema emitted `basis` BEFORE the note,
# so an autoregressive judge had committed the label before its note's own
# re-check could reach it. #3399 moves `basis` to the END of each finding (see
# reader_truth_qa._PROMPT_FOOTER's comment block) — a POST-NOTE withdrawal
# marker; channel 1 below is unchanged and remains the decider, and a first-pass
# mislabel is enforced at the #2741/#3102 confirm passes, whose re-judge under
# the same post-note contract is dropped here so the high demotes visibly.
# WHAT SURVIVES OF `_WITHDRAWAL_RE`, ruled for the record (#3399 acceptance):
# the six phrases remain EXACTLY a logged tiebreak — they may confirm a drop the
# structural predicates already allowed, they can never decide alone, and every
# firing prints via `_tiebreak`. Regression + controls (the wire finding, the
# 35-finding replay census, a contract guard that reds if `basis` moves back
# ahead of the note or "withdrawn" leaves the enum):
# tests/test_reader_truth_withdrawn_basis_3399.py.


def is_self_refuted(finding, start_date=None, today=None):
    """True when the finding's own note withdraws the contradiction (#2959, #3337).

    Channel 1 (structural, decides): the judge's `basis` field says "withdrawn".
    Channel 2 (logged tiebreak): the note's FINAL sentence matches the #2959
    withdrawal phrases AND the note asserts nothing the phase cannot hold AND it
    names no payload date field. Only the last sentence
    counts — a mid-note "internally consistent. But the header …" is a live
    objection and survives.

    Fail-closed: without the phase anchors only channel 1 can fire, so a caller
    that cannot supply them keeps the finding.
    """
    if judge_basis(finding) == "withdrawn":
        return True
    note = (finding.get("note") or "").strip()
    if not note:
        return False
    if cycle_day(start_date, today) is None:
        return False
    if out_of_phase_quantities(note, start_date, today):
        return False
    if cites_payload_date_field(note):
        return False
    sentences = [s.strip() for s in re.split(r"[.?!]", note) if s.strip()]
    if sentences and _WITHDRAWAL_RE.search(sentences[-1]):
        return _tiebreak("self_refuted", finding, "nothing out of phase; the final sentence withdraws")
    return False


# ── #3199 (2026-08-26): a cross-signal cadence gap is not a temporal_contradiction ─
#
# THE OBSERVED FAILURE. The #3186 evidence run's visual-qa red decoded to
# /method/results/: the page correctly reads "LATEST 326.2 LB · 1 READING SO FAR"
# (ADR-104 honest-absence copy — the DO-NOT-FLAG list has named "N readings so far"
# exempt since before this class existed) next to an HRV series with 9 daily
# readings, because Withings weigh-ins are owner-initiated and HRV is passive-daily
# — different cadences, not a contradiction. The oracle graded it `high`
# temporal_contradiction anyway: "A single weight reading across 9 days of an
# active tracking experiment is impossible." Its own arithmetic never disputes the
# COUNT (one reading did happen); it disputes that the count is SMALL relative to
# the elapsed days — i.e. it is re-litigating the exact honest-sparsity disclosure
# the rubric already tells it to leave alone.
#
# THE RULING. Two signals legitimately carrying different reading counts over the
# same span is not a temporal impossibility — it is the data model (ADR-154's
# per-source cadence facets) doing its job. A finding is this class only when it
# (a) quotes the page's own honest "<N> reading(s) so far" disclosure, AND (b)
# ALSO cites the current day number, with N no greater than that day number —
# i.e. the count is a deficiency (at most one reading per elapsed day), not an
# excess. A genuinely corrupted count — MORE readings than days could hold — is a
# real defect and does not match this shape; that residue keeps gating.
#
# WHY A NUMERIC COMPARISON, NOT A KEYWORD MATCH. A live re-run of this exact page
# during the fix's own verification (#3199) reproduced the SAME finding worded
# differently — "implausibly sparse", "a data collection failure not acknowledged
# as such" — with no "impossible" and no "across N days" anywhere in the note.
# That is #2613's and #2741's measured lesson again: a suppressor keyed to one
# phrasing does not survive the oracle's non-stationary rephrasing (#2959). The
# invariant that DOES survive rephrasing is the arithmetic itself: whatever words
# it uses, the objection is unsound exactly when the honestly-disclosed count is
# ≤ the day number it is being compared against. DEMOTED to low, not dropped —
# this module's constant discipline (#2959/#3003): the observation stays visible
# as advisory, never gates. Printed, never silently swallowed.
_HONEST_READING_COUNT_RE = re.compile(r"\b(\d{1,4})\s+readings?\s+so\s+far\b", re.I)


def is_sparsity_objection(finding):
    """True when a temporal_contradiction's objection is that an honestly-labeled
    reading count is small relative to the current day number (#3199).

    Structural conditions, both required: temporal_contradiction; and the note
    quotes the page's own "<N> reading(s) so far" honest-count disclosure while
    also citing a day number ("Day M") that is >= N. A note that never quotes the
    honest-count phrasing, never cites a day number, or cites a count that
    EXCEEDS every cited day number (a genuinely corrupted count — a real defect)
    survives at full severity.
    """
    if finding.get("category") != "temporal_contradiction":
        return False
    note = finding.get("note") or ""
    m = _HONEST_READING_COUNT_RE.search(note)
    if not m:
        return False
    day_ns = {int(d) for d in _DAY_N_RE.findall(note)}
    if not day_ns:
        return False
    return int(m.group(1)) <= max(day_ns)


# ── #3199 (2026-08-26): a claim scoped to ACTIVE logging is not disproved by day arithmetic ─
#
# THE OBSERVED FAILURE. The very redeploy that carried #3198's fix was itself
# auto-rolled-back by a second flake on /method/board/: coach Dr. Eli Marsh's copy
# states "active logging went silent across food, training, habits, and journal
# since August 17th" — a claim scoped explicitly to the deliberately-logged,
# opt-in categories (food/nutrition, training, habits, journal), as distinct from
# the passive-daily signals (HRV, sleep, RHR) that keep recording regardless of
# whether Matthew acts. Ground-truthed against DDB the same night: TRUE (zero
# macrofactor/hevy/journal rows and zero habitify check-ins since genesis). The
# oracle graded it `high` temporal_contradiction anyway, its entire cited evidence
# being "August 17 is Day 1 of the current cycle, and today is Day 9" — date
# arithmetic that never disputes the claim (nothing logs before Day 1 by
# construction; the claim is that nothing logged AFTER it either). The same
# finding had already been non-reproduced on an earlier pass (#3102) and demoted
# by #3003 on a third — a coin-flip judge treating a true, honestly-scoped absence
# claim as a defect and costing a healthy deploy its own rollback.
#
# THE RULING. A claim naming the active-logging categories as silent SINCE the
# cycle's own start date, objected to with nothing but a restatement of that same
# start date and the current day number, is not a temporal impossibility — the
# window it describes is exactly as old as the cycle itself, and passive signals
# continuing elsewhere corroborates nothing about whether the ACTIVE categories
# were touched. DEMOTED to low, never dropped — advisory, printed, never silently
# swallowed.
#
# ── RESHAPED STRUCTURALLY (#3337, 2026-08-30) ─────────────────────────────────
#
# THE DEFECT IN THE RULING ITSELF. As shipped it was anchored on a verb list —
# "active logging/tracking … went silent | stopped | paused | gone quiet" — with a
# comment claiming the looseness was protection. It is not: "no entries in the
# opt-in categories since genesis", "the deliberate-logging surfaces have recorded
# nothing", "food, training, habits and journal are all empty for the cycle" all
# state the same claim and none of them match. The ruling was one paraphrase from
# letting this exact flake auto-roll-back another healthy deploy, which is what it
# did on 2026-08-25.
#
# THE STRUCTURAL PREDICATE — the objection carries NO evidence of its own. Two
# parsed conditions, and no verbs anywhere:
#
#   1. THE CLAIM CLASS, from the quoted copy: the note quotes a page span whose
#      only date is the cycle start and which states no day number of its own —
#      i.e. a claim scoped to exactly the cycle window ("… since August 17th").
#      A banner span ('DAY 9 · WEEK 2, SINCE AUGUST 17 2026') carries its own day
#      number and is excluded on purpose: a wrong banner day is a real defect
#      (#2941) and must never be adjudicated here.
#   2. THE EVIDENCE SET, from the judge's own prose: every value it asserts is one
#      of the four anchors the prompt itself injected — the cycle start, today,
#      Day 1, today's day number. Nothing else. An objection whose entire evidence
#      is the window it is objecting to has disproved nothing; "August 17 is Day 1
#      and today is Day 9" is elapsed time, not a contradiction.
#
# The residue this keeps flaggable is now enforced rather than asserted: a note
# citing an active-category entry AFTER the since-date introduces a date that is
# not an anchor and survives; a since-date that is not genesis ("silent since
# August 16th") is out of phase and survives. Both are covered by the mutation
# tests. DEMOTED to low, never dropped — unchanged.
#
# `_ACTIVE_LOGGING_SILENT_RE` is kept for one job only: naming, in the log, that
# the classic wording was present. It is never consulted in the verdict.
_ACTIVE_LOGGING_SILENT_RE = re.compile(
    r"\bactive\s+(?:logging|tracking)\b[^.?!]{0,60}?\b(?:went\s+silent|has\s+been\s+silent|silent|stopped|paused|gone\s+quiet|quiet)\b",
    re.I,
)


def is_active_vs_passive_objection(finding, start_date=None, today=None):
    """True when a temporal_contradiction objects to a whole-cycle-scoped claim
    with nothing but the phase's own anchors (#3199, reshaped #3337).

    Structural conditions, all required: temporal_contradiction; the note quotes a
    claim whose window is exactly the cycle (its only date is the cycle start, and
    it states no day number of its own); the note asserts nothing out of phase; it
    names no payload date field; and every value it does
    assert is one of the four injected anchors (cycle start, today, Day 1, today's
    day number). Any other cited value is evidence, and the finding survives.

    Fail-closed: without the phase anchors the ruling cannot fire at all.
    """
    if finding.get("category") != "temporal_contradiction":
        return False
    if cycle_day(start_date, today) is None:
        return False
    note = finding.get("note") or ""
    if not spans_scoped_to_cycle_start(note, start_date):
        return False
    if out_of_phase_quantities(note, start_date, today):
        return False
    if cites_payload_date_field(note):
        return False
    if not evidence_is_phase_anchors_only(note, start_date, today):
        return False
    if not _ACTIVE_LOGGING_SILENT_RE.search(note):
        # Not a verdict — a census. Every line here is a wording the pre-#3337
        # matcher would have missed, so the paraphrase rate this ruling was
        # reshaped for is countable in the log group instead of inferred.
        print(
            f"  ↩ reader-truth: active_vs_passive caught a PARAPHRASE on {finding.get('page')} "
            f"(the #3199 wording is absent; decided on the anchors-only evidence set, #3337)"
        )
    return True


# ── #3258 (2026-08-27): the ledger's ADVISORY verdict, recorded as a FIELD ─────
#
# THE OBSERVED FAILURE. `/aws/lambda/life-platform-qa-smoke`, Day 11, finding
# `539c6d`, severity `low` — verbatim wire note (576 chars, matching the log's own
# "full note (576 chars)" stamp; replayed in tests/test_reader_truth_retracted_3258.py):
#
#   "Home page states 'This attempt starts at the Day‑1 weigh‑in, aimed at 185 lbs
#    held for 90 consecutive days' but does not explicitly label this as a
#    forward-looking goal or checkpoint. … However, the context ('aimed at', 'or
#    the checkpoint fails') makes clear it is a prospective goal. This is ambiguous
#    rather than contradictory — the phrasing is acceptable for describing a cycle
#    objective. No flag warranted on reconsideration."
#
# The judge reasoned its way to a verdict of NO finding and the structured output
# still carried one. `qa_check.split_warns()` saw a non-chronic WARN, routed it to
# `WarnCount`, and `qa-smoke-warnings` lit.
#
# WHY THE OBVIOUS FIX IS THE WRONG ONE. `is_self_refuted` above is a phrase list
# ("no contradiction", "self-consistent", "within phase bounds", "label is
# accurate"). "No flag warranted on reconsideration" is not on it, and adding it
# would be the fifth member of a family this repo has measured failing in the field
# three times (#2959 → #3003 → #3199, and #3208's own widening comment). A
# suppressor keyed to one phrasing does not survive the oracle's non-stationary
# rephrasing. The phrase list is NOT extended here, deliberately.
#
# WHAT IS ACTUALLY BROKEN — and it is not the wording. Two structural facts,
# measured against the live predicate set on the wire note above:
#
#   1. `is_vagueness_objection(f)` is **True** on it ("This is ambiguous rather
#      than contradictory"). #3003 already adjudicated this exact class. But
#      `assess_prose` only CONSULTED the demotion predicates under
#      `if f["severity"] != "low"`, so a finding the model itself rated `low` was
#      never adjudicated at all — the ledger was blind to precisely the severity
#      the warnings alarm still fires on.
#   2. Every demotion ruling in this file states, in its own comment, that the
#      finding it adjudicates is "visible as advisory, **never gating**"
#      (#2959 ×2, #3003, #3199 ×2). All five demote to `low` — and `low` gates:
#      `qa_check_reader_truth` puts low/med in one WARN and `split_warns` sends
#      that to the alarmed `WarnCount`. There was no channel below `low`, so five
#      rulings have been asserting an outcome the pipeline could not deliver.
#
# THE FIX, structurally. The adjudication stops being a severity side-effect and
# becomes DATA on the finding: every ruling that fires appends its id to the
# finding's `rulings` list, at EVERY severity. `qa_check_reader_truth` then routes
# on that field — adjudicated findings ride `ChronicWarnCount` (fully visible in
# the check list, the email and the logs; watched by no alarm, #1958), and
# `WarnCount` counts exactly the findings on which NO reconsideration fired. That
# is the issue's Outcome made literal: a lit `qa-smoke-warnings` means a
# reader-truth finding survived the judge's own reconsideration.
#
# RESIDUE, named honestly rather than papered over: a retraction that no predicate
# in this ledger adjudicates still reaches `WarnCount`. The durable fix for THAT is
# the response contract — a per-finding `verdict: flag|withdrawn` field the judge
# fills, so a retraction has a structured place to live instead of leaking into
# prose. It is deliberately not shipped here: it cannot be measured from a worktree
# (a Bedrock invoke is a write), and no recorded payload carries the field, so it
# could not have a must-fail case replayed from the wire — which is exactly the
# unmeasured-prompt-change shape #2613 and #2741 charge a deploy for.


# ── an objection that cites no temporal value at all (#3379, 2026-08-31) ──────
#
# THE OBSERVED FAILURE (qa-smoke 2026-08-31, finding 539c6d, high, "confirmed on
# a second pass" — held `qa-smoke-failures` in ALARM): the home page's protagonist
# copy ("every climb before this one ended the same way…" — TRUE, phase-neutral
# by design per site/index.html's #732/#1087 comments; that sentence was later
# retired from home for the 2026-09-01 launch re-anchor — an editorial call, not a
# concession, and it changes nothing here: this ruling is structural and reads only
# the judge's own note) was graded high because
# current editorial voice "should be moved to a labeled 'previous attempts'
# archive". The note cites no date, no day number, no span — nothing the phase
# could contradict. It escaped #3337's channel 2 (not grounded in the day
# counter, so the channel cannot fire) and the tiebreak regex ("ambiguously
# blurs" carries none of the adjective forms) — the fourth field failure of a
# lexical member of this family, this time in the demotion-miss direction.
#
# THE RULING. The rubric defines the category as an impossibility the judge's
# own arithmetic establishes, and establishing one requires CITING a temporal
# value the phase cannot hold. A note whose OWN sentences (quoted page copy
# excluded — the claim under dispute is not the judge's evidence, the #3258
# distinction) cite no date, no day number, and no elapsed span has done no
# arithmetic at all: whatever it objects to, it is not a temporal impossibility.
# Structural in the #3337 sense — every input is a parsed-evidence ABSENCE; no
# wording is consulted. Guards, from the live wire notes that must stay
# flaggable: a note naming a payload date field is a data claim (d1c6a0,
# e5eafd) and is refused outright; an empty note is refused (fail closed).
# RESIDUE, named honestly: a real defect the judge describes with zero temporal
# citation ("entries from before the experiment began", no date given) is
# demoted — but by the rubric such a note has established nothing, and it stays
# visible as advisory, recorded, never dropped. DEMOTED to low — unchanged.
def is_uncited_temporal_objection(finding):
    """True when a temporal_contradiction's own sentences cite no temporal
    value at all — no date, day number, or elapsed span — so no impossibility
    can have been established (#3379)."""
    if finding.get("category") != "temporal_contradiction":
        return False
    note = str(finding.get("note") or "")
    if not note.strip() or cites_payload_date_field(note):
        return False
    own = unquoted(note)
    return not (note_dates(own) or day_numbers(own) or elapsed_spans(own))


RULINGS_FIELD = "rulings"


def advisory_rulings(start_date, today=None):
    """The ledger's ADVISORY rulings as ``(id, label, predicate, reason)`` (#3258).

    ONE table, so the set the assessment loop consults and the set this file
    documents cannot drift apart (charter primitive 1). Ordering is the order the
    rulings were written; a finding may match more than one and records all of
    them. `start_date`/`today` are the phase anchors the two date-aware
    predicates need — bound here so every caller passes the same frame.

    `label` is the human phrase the assessment loop prints ("a vagueness-objection
    finding"); it carries its own article and noun so the five log lines stay
    byte-identical to the ones each ruling shipped with, while `id` — the machine
    key recorded on the finding — stays a stable snake_case token.

    DROP rulings (`is_code_owned_temporal`, `is_wake_frame_correct`,
    `is_utc_offset_misread`, `is_durable_design_copy`, `is_prior_cycle_archive`,
    `is_coach_surface_audience`, `is_self_refuted`) are deliberately NOT in this
    table: a dropped finding never reaches a bucket at all, so it needs no
    channel. This table is only the rulings whose own stated outcome is
    "visible as advisory, never gating".
    """
    return (
        (
            "day_counter_bound",
            "a day-counter-bound finding",
            is_day_counter_bound_inference,
            "the day counter is not a data bound, #2959",
        ),
        (
            "position_banner_misread",
            "a position-banner misread",
            lambda f: is_position_banner_misread(f, start_date, today),
            "the banner is a clock, not a content label, #2959",
        ),
        (
            "vagueness_objection",
            "a vagueness-objection finding",
            lambda f: is_vagueness_objection(f, start_date, today),
            "no impossibility is established against the phase, #3003/#3337",
        ),
        (
            "sparsity_objection",
            "a sparsity-objection finding",
            is_sparsity_objection,
            "a cadence gap is not a temporal_contradiction, #3199",
        ),
        (
            "active_vs_passive",
            "an active-vs-passive objection",
            lambda f: is_active_vs_passive_objection(f, start_date, today),
            "day arithmetic alone does not disprove it, #3199",
        ),
        (
            "uncited_temporal_objection",
            "an uncited temporal objection",
            is_uncited_temporal_objection,
            "no temporal value is cited, so no impossibility is established, #3379",
        ),
    )


def is_advisory(finding):
    """True when the ruling ledger adjudicated `finding` as advisory (#3258).

    The routing key `qa_check_reader_truth` reads. Reads a FIELD the assessment
    loop wrote, never the note — a finding with no `rulings` entry is one no
    reconsideration touched, and it keeps its place in the alarmed `WarnCount`.
    """
    return bool((finding or {}).get(RULINGS_FIELD))
