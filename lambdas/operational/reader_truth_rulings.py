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
"""

import re
from datetime import date

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
# comparison below is a date comparison).
_NOTE_ISO_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")


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


def is_wake_frame_correct(finding):
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

    Structural conditions, all required: temporal_contradiction; a night-scoped
    surface the deterministic pass grades; night-frame language in the note; and
    every cited ISO date fitting one single-day span. A >1-day spread (a genuinely
    stale night), a single-date note, or any other surface survives at full severity.
    """
    if finding.get("category") != "temporal_contradiction":
        return False
    if finding.get("page") not in CODE_OWNED_TEMPORAL_SURFACES:
        return False
    note = finding.get("note") or ""
    if not any(t in note.lower().replace(" ", "_") for t in _NIGHT_FRAME_TOKENS):
        return False
    dates = {date.fromisoformat(d) for d in _NOTE_ISO_DATE_RE.findall(note)}
    if len(dates) < 2:
        return False
    return (max(dates) - min(dates)).days == 1


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

# The model quotes page copy with the page's own typography — the live notes carry
# U+2011 NON-BREAKING HYPHEN in "Day‑1" while the rubric writes an ASCII hyphen, and
# curly quotes appear in both directions. Comparing raw strings would silently never
# match, which is the failure mode where a gate looks wired and is not.
_DASHES = dict.fromkeys(map(ord, "‐‑‒–—―−"), "-")
_QUOTED_SPAN_RE = re.compile(r"[‘’']([^‘’']{4,})[‘’']|[“”\"]([^“”\"]{4,})[“”\"]")


def _normalize_copy(s):
    """Casefold, unify every Unicode dash to '-', and collapse whitespace."""
    return " ".join(str(s or "").translate(_DASHES).casefold().split())


def quoted_spans(note):
    """The quoted page-copy spans inside a model note, in order.

    Apostrophes inside quoted prose ("What's different") make single-quote pairing
    ambiguous. That is fine and deliberate: an ambiguous parse yields spans that do
    not match the registry, and the all-spans-must-match rule below then KEEPS the
    finding. The failure direction preserves the old behaviour rather than silencing
    it — the same fail-closed posture as `_confirm_high_findings`.
    """
    return [m.group(1) if m.group(1) is not None else m.group(2) for m in _QUOTED_SPAN_RE.finditer(note or "")]


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
# SCOPE — narrow on purpose. Fires only on temporal_contradiction, and only when
# the note EXPLICITLY rests on vagueness ("is vague", "vague about", "ambiguous
# as to", "unclear whether", …). A note that asserts an impossibility without
# hedging language survives at full severity. The residue accepted: a note that
# both proves a real impossibility AND uses this hedging language gets demoted —
# but a note that hedges its own accusation is the model telling us it is not
# sure, and per ADR-105 an unsure verdict does not get to fail a gate.
_VAGUENESS_OBJECTION_RE = re.compile(
    r"\b(?:is|are|was|were|being|remains?|seems?|appears?)\s+(?:somewhat\s+|rather\s+|too\s+)?(?:vague|ambiguous|unclear|imprecise)\b"
    r"|\b(?:vague|ambiguous|unclear|imprecise)\s+(?:about|as\s+to|whether|on|regarding)\b",
    re.I,
)


def is_vagueness_objection(finding):
    """True when a temporal_contradiction's note explicitly rests on vagueness (#3003).

    Structural conditions, both required: the finding is a temporal_contradiction,
    and its note states that the flagged phrasing is vague/ambiguous/unclear —
    which is an editorial complaint, not an impossibility, and never `high`.
    """
    if finding.get("category") != "temporal_contradiction":
        return False
    return bool(_VAGUENESS_OBJECTION_RE.search(finding.get("note") or ""))


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
_DAY_N_RE = re.compile(r"\bday\s+(\d{1,3})\b", re.I)

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

_TEXT_DATE_RE = re.compile(
    r"\b(january|february|march|april|may|june|july|august|september|october|november|december)" r"\s+(\d{1,2}),?\s+(\d{4})\b",
    re.IGNORECASE,
)
_MONTHS = {
    m: i + 1
    for i, m in enumerate(
        ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]
    )
}
_CYCLE_LABEL_RE = re.compile(r"\bcycle\s+(\d{1,3})\b", re.IGNORECASE)
_ARCHIVE_PATH_PREFIXES = ("/story/", "/journal/")


def _note_dates(note):
    """Every date the note cites, as ISO strings — ISO literals + 'July 8, 2026' forms."""
    dates = list(_NOTE_ISO_DATE_RE.findall(note or ""))
    for mon, day, year in _TEXT_DATE_RE.findall(note or ""):
        dates.append(f"{year}-{_MONTHS[mon.lower()]:02d}-{int(day):02d}")
    return dates


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


def is_self_refuted(finding):
    """True when the note's own final sentence withdraws the contradiction (#2959)."""
    note = (finding.get("note") or "").strip()
    if not note:
        return False
    sentences = [s.strip() for s in re.split(r"[.?!]", note) if s.strip()]
    return bool(sentences) and bool(_WITHDRAWAL_RE.search(sentences[-1]))


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
# THE PHRASING IS LOOSELY MATCHED ON PURPOSE (the #3199 sparsity-objection sibling
# measured, live, that a keyword-matched suppressor does not survive the oracle's
# rephrasing, #2959): the silence verb and the Day-1/current-cycle clause each
# tolerate the ordinary paraphrases observed across this file's other #2959
# members, rather than requiring the wire note's exact word order.
_ACTIVE_LOGGING_SILENT_RE = re.compile(
    r"\bactive\s+(?:logging|tracking)\b[^.?!]{0,60}?\b(?:went\s+silent|has\s+been\s+silent|silent|stopped|paused|gone\s+quiet|quiet)\b",
    re.I,
)
_SINCE_DAY_ONE_RE = re.compile(r"\bis\s+Day\s+1\b[^.?!]{0,40}?\b(?:cycle|genesis)\b", re.I)
_TODAY_IS_DAY_N_RE = re.compile(r"\btoday\b[^.?!]{0,20}?\bDay\s+(\d{1,3})\b|\bDay\s+(\d{1,3})\b[^.?!]{0,20}?\btoday\b", re.I)


def is_active_vs_passive_objection(finding):
    """True when a temporal_contradiction objects to an active-logging-silence
    claim with nothing but a Day-1/today restatement (#3199).

    Structural conditions, all required: temporal_contradiction; the note quotes
    an "active logging/tracking … silent" claim; the note states that the claimed
    since-date is Day 1 of the current cycle; and the note states today's day
    number, which must be greater than 1 (the elapsed-time restatement this class
    is). A note offering any OTHER evidence against the claim (a cited
    active-category entry after the since-date, a since-date that is NOT Day 1 —
    the banner-itself-wrong shape, #2941) is a live objection and survives.
    """
    if finding.get("category") != "temporal_contradiction":
        return False
    note = finding.get("note") or ""
    if not _ACTIVE_LOGGING_SILENT_RE.search(note):
        return False
    if not _SINCE_DAY_ONE_RE.search(note):
        return False
    m = _TODAY_IS_DAY_N_RE.search(note)
    if not m:
        return False
    today_n = int(m.group(1) or m.group(2))
    return today_n > 1
