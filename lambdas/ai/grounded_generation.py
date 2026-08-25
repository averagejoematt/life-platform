"""grounded_generation.py — ADR-104: one grounded-generation harness for every
AI narrative surface.

The platform's rule is "the model never does the math" (ADR-062) — this module
is that rule's enforcement arm at generation time. It composes the three proven
pieces that previously lived apart:

  1. Fact injection    — authoritative_facts_block() renders canonical_facts as
                         the AUTHORITATIVE FACTS prompt block (the analyzer's
                         battle-tested wording, incl. the no-invent-trends rule).
  2. Deterministic     — grounding_findings() = hard canonical contradictions
     post-check          (grounding_guard, RHR/recovery/HRV) + the er03-style
                         allow-list number gate generalized for narratives:
                         every number in the output must appear in the input.
                         This is what kills "climbed from X to Y" fabrication —
                         the invented X isn't in anything the model was given.
                         Full calendar dates are a distinct token class (#1242):
                         "2026-07-08" is invisible to the number gate (2026/7/8 are
                         all benign), so an optional date allow-list catches an
                         invented ISO/long-form date the number gate cannot see.
  3. Regen-once        — regen_once() extracts the duplicated keep-if-strictly-
                         improved harness (ai_expert_analyzer / field_notes) so
                         every surface corrects the same way: one rewrite,
                         kept only if findings strictly decrease, never worse.
  4. Cycle-freshness   — baseline_freshness_findings() (#1691, epic #1687) catches
                         the "reset-window stale-baseline" class the DATA-grounding
                         gates above cannot see: a brief that cites a stale STARTING
                         weight or a stale "Day N" framing (cycle-9 "315 lbs" / "Day 1"
                         after a cycle-10 genesis) is digit-grounded yet cycle-wrong.
                         Takes the cycle constants as params so it stays pure.
  5. Behavioral-log    — ungrounded_behavioral_findings() (#1699, epic #1687) catches
     grounding           the "hallucinated behavior" class the DATA-grounding gates
                         cannot see: a same-day completed-action claim ("you maintained
                         your eating window today", "you hit your steps") with no
                         corresponding log. Log-aware and deterministic — takes the
                         caller-supplied availability map so it stays pure (no I/O).
                         Lives in ai/behavior_logs.py since #2056 (this file is at its
                         §2 ceiling) and is re-exported here; that module also owns the
                         honest per-generation-date DERIVATIONS of the map, which is
                         what let the class arm beyond the one coach-v2 surface.

Reset suppression (AC, #1691): baseline_freshness_findings() IS the promotable
suppression hook a reset needs — restart_pipeline itself is untouched. A reset-window
stale brief trips this gate's advisory finding (surfaced in the review pack + stamped
into qa_archive meta at generation time); promoting the caller from "log + stamp" to
"hold + regenerate" (the ADR-108 regenerate-or-hold shape) keeps a stale brief from
reaching a reader without any restart_pipeline change.

Pure functions, no AWS, no HTTP — the caller supplies the regeneration callable.
Fail modes are the caller's choice: keep-best (internal narratives) or
fail-closed (reader-facing surfaces drop/fallback, like the podcast gate).

Import paths: bundled at lambdas/ root in every function's deploy package (with a
flat copy of grounding_guard) so every consumer (ai_calls' V2 coach render)
can use it.
"""

import datetime as _dt
import json
import re

# The tight canonical-contradiction detector (SS-10). Dual path: package-style
# (bundled lambdas/), flat (layer / flattened bundle). Fail-soft to None — the
# number gate still runs; only the vitals-contradiction check is skipped.
try:
    from intelligence.grounding_guard import hard_canonical_contradictions as _hard_contradictions
except ImportError:  # pragma: no cover — environment-dependent
    try:
        # dual package/flat import-fallback idiom; both branches bind the same name.
        from grounding_guard import hard_canonical_contradictions as _hard_contradictions  # type: ignore[no-redef]
    except ImportError:
        _hard_contradictions = None

# 6. Night-scope (#1968) lives in ai/night_scope.py — this file is at its §2 ceiling, and
# that gate is the one callers want WITHOUT the generation harness (serve-time re-checks).
try:
    from ai import night_scope as _night_scope
except ImportError:  # pragma: no cover — flat/layer bundle layout
    import night_scope as _night_scope  # type: ignore[no-redef]

# 7. Discard telemetry (#3086) lives in ai/regen_discard_telemetry.py — same §2-ceiling
# reason as night_scope above, plus this module's own "no AWS" contract (its put_metric_data
# call does not belong here).
try:
    from ai import regen_discard_telemetry as _regen_telemetry
except ImportError:  # pragma: no cover — flat/layer bundle layout
    import regen_discard_telemetry as _regen_telemetry  # type: ignore[no-redef]

# 5. Behavioral-log (#1699) moved to ai/behavior_logs.py with #2056, for the same §2
# ceiling reason — and because deriving its per-generation-date availability map is real
# work that belongs next to the gate, not smeared across every caller. Re-exported here
# so no caller's import path changes; `LogAvailability` rides along because it is the
# argument type callers now pass as `available_logs`.
#
# #2382 adds the absence-TRANSITION family alongside it: the sets answer "was there a log
# that day", and could not tell "logged, then stopped four days ago" apart from "never
# logged in this window at all" — so six live coach cards narrated a pause that never
# happened. `AbsenceTransition` / `absence_transition_findings` ride along the same way.
try:
    from ai.behavior_logs import (  # noqa: F401
        LOG_CATEGORIES,
        AbsenceTransition,
        LogAvailability,
        absence_transition,
        absence_transition_findings,
        absence_transitions,
        transition_from_presence_signal,
        ungrounded_behavioral_findings,
    )
except ImportError:  # pragma: no cover — flat/layer bundle layout
    from behavior_logs import (  # type: ignore[no-redef]  # noqa: F401
        LOG_CATEGORIES,
        AbsenceTransition,
        LogAvailability,
        absence_transition,
        absence_transition_findings,
        absence_transitions,
        transition_from_presence_signal,
        ungrounded_behavioral_findings,
    )

_NUM_RE = re.compile(r"\d+(?:\.\d+)?")
_THOUSANDS_RE = re.compile(r"(?<=\d),(?=\d{3}\b)")

# Numbers narrative prose may always use without them appearing in the input:
# small counts ("three meals", "2 of the last 5 days"), the common prescriptive
# durations, round anchors, and years. Everything else must be earned from the
# input — a plausible-but-invented vital (58, 13.8, 172) is never benign.
_BENIGN_NUMBERS = (
    set(float(x) for x in range(0, 13)) | {15.0, 20.0, 30.0, 45.0, 60.0, 90.0, 100.0} | set(float(y) for y in range(2020, 2031))
)


def numbers_in_text(text: str) -> set:
    """Distinct numeric values in a string (floats), thousands-separators handled."""
    out = set()
    for m in _NUM_RE.findall(_THOUSANDS_RE.sub("", text or "")):
        try:
            out.add(round(float(m), 4))
        except ValueError:
            pass
    return out


def allowed_numbers(*sources) -> set:
    """The allow-list: every number present in what the model was given.

    Accepts strings and any JSON-serializable structure (dicts/lists are
    json.dumps'd, so nested values count). Pass the prompt, the data blob,
    and the canonical facts — the union is the model's numeric vocabulary.
    """
    allowed = set()
    for src in sources:
        if src is None:
            continue
        text = src if isinstance(src, str) else json.dumps(src, default=str)
        allowed |= numbers_in_text(text)
    return allowed


# ── The numeric match window (#2290) ────────────────────────────────────────
# Two named tolerances, because two kinds of caller want different things.
#
# TOLERANT (0.01) is the historical behaviour and stays the default. It exists so a
# narrative surface that legitimately rounds isn't refused. Its cost, measured in #2290:
# a corruption confined to a TRAILING DECIMAL (74.61 -> 74.62) lands inside the window
# and passes the gate *regardless of what is on the allow-list*. #2276 narrowed the
# allow-list; it did not touch this, and the two are independent.
#
# EXACT (0.0) disables the window entirely. It does NOT mean "no rounding allowed" —
# rounding is handled separately below, so a caller on EXACT still accepts 64 or 64.2
# for 64.23. What it refuses is a number that is near an allowed one without being a
# rounding of it, which is precisely the corrupted-decimal class.
NUMBER_TOLERANCE_TOLERANT = 0.01
NUMBER_TOLERANCE_EXACT = 0.0

# Float-comparison slop for the rounding check. Numbers are already quantised to 4dp by
# numbers_in_text(), so this only absorbs binary-representation noise.
_ROUNDING_EPS = 1e-9
_MAX_ROUNDING_PRECISION = 4


def _is_restatement(x: float, a: float) -> bool:
    """True when ``x`` is ``a`` rounded to some precision — a restatement, not a fabrication.

    Generalises the old integer-restatement branch (which was precision 0 only, "64 for
    64.2") to every precision up to the 4dp quantisation ``numbers_in_text`` applies. This
    is what makes NUMBER_TOLERANCE_EXACT usable rather than punitive: a reader-facing
    surface may still say "74.6" for 74.61, it simply may not say "74.62".
    """
    return any(abs(x - round(a, d)) <= _ROUNDING_EPS for d in range(_MAX_ROUNDING_PRECISION + 1))


def fabricated_numbers(text: str, allowed: set, *, tolerance: float = NUMBER_TOLERANCE_TOLERANT) -> list:
    """Numbers in the output that appear nowhere in the input (minus benign).

    ``tolerance`` is the half-window a number may sit from an allowed one and still count
    as grounded. Pass ``NUMBER_TOLERANCE_EXACT`` on a surface where the gate IS the honesty
    claim being made to a reader (ADR-104) — see the module note above and #2290.
    """
    out = []
    for x in sorted(numbers_in_text(text)):
        if x in _BENIGN_NUMBERS:
            continue
        if tolerance > 0 and any(abs(x - a) < tolerance for a in allowed):
            continue
        if any(_is_restatement(x, a) for a in allowed):
            continue
        out.append(x)
    return out


# ── weekday↔date grounding (#1220) ──────────────────────────────────────────
# A weekday paired with a calendar date is a mechanically checkable fact — the
# ADR-104 number gate never looked at it, so the cycle-6 chronicle draft called
# 2026-07-13 (a Monday) a "Sunday" (stale cycle-5 genesis, which WAS a Sunday)
# and the gate passed it. This deterministic, zero-AI check regexes weekday+date
# pairs out of the narrative and verifies each against the real calendar.
_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_WEEKDAY_RE = re.compile(r"\b(" + "|".join(_WEEKDAYS) + r")\b", re.IGNORECASE)
_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}
_MONTH_DAY_RE = re.compile(r"\b(" + "|".join(_MONTHS) + r")\s+(\d{1,2})(?:st|nd|rd|th)?\b", re.IGNORECASE)
_THE_NTH_RE = re.compile(r"\bthe\s+(\d{1,2})(?:st|nd|rd|th)\b", re.IGNORECASE)


def _safe_date(year, month, day):
    """A real date or None (guards Feb-30, day 0, non-leap Feb-29, bad types)."""
    try:
        return _dt.date(int(year), int(month), int(day))
    except (ValueError, TypeError):
        return None


def weekday_date_findings(text: str, year: int, month_hint: int = None, proximity: int = 60) -> list:
    """Deterministic weekday↔date check. Returns [{type: "weekday_mismatch", ...}] — empty = consistent.

    Every weekday word (Monday…Sunday) is paired with the nearest calendar date
    within `proximity` characters — a full "Month Day" ("July 13th") always, and a
    bare "the Nth" ("the 14th") when `month_hint` is supplied. The pair is verified
    against `datetime`; a mismatch (e.g. "Sunday … July 13th" when 2026-07-13 was a
    Monday) is a finding. No date near a weekday ⇒ nothing to check (no finding).
    """
    text = text or ""
    if year is None:
        return []
    # (start, end, date_obj, matched_text) for every resolvable date token.
    tokens = []
    for m in _MONTH_DAY_RE.finditer(text):
        d = _safe_date(year, _MONTHS[m.group(1).lower()], m.group(2))
        if d:
            tokens.append((m.start(), m.end(), d, m.group(0)))
    if month_hint:
        for m in _THE_NTH_RE.finditer(text):
            d = _safe_date(year, month_hint, m.group(1))
            if d:
                tokens.append((m.start(), m.end(), d, m.group(0)))
    findings = []
    seen = set()
    for wm in _WEEKDAY_RE.finditer(text):
        stated = wm.group(1).capitalize()
        w_start, w_end = wm.start(), wm.end()
        best, best_dist = None, None
        for ds, de, dobj, dstr in tokens:
            if ds >= w_end:
                dist = ds - w_end
            elif de <= w_start:
                dist = w_start - de
            else:
                dist = 0
            if dist <= proximity and (best_dist is None or dist < best_dist):
                best, best_dist = (dobj, dstr, ds), dist
        if best is None:
            continue
        dobj, dstr, ds = best
        actual = dobj.strftime("%A")
        if actual.lower() != stated.lower():
            key = (w_start, ds)
            if key in seen:
                continue
            seen.add(key)
            findings.append(
                {
                    "type": "weekday_mismatch",
                    "stated_weekday": stated,
                    "date": dobj.isoformat(),
                    "actual_weekday": actual,
                    "detail": (f'the narrative pairs "{stated}" with {dstr} ({dobj.isoformat()}), ' f"but that date was a {actual}"),
                }
            )
    return findings


# ── fabricated-date grounding (#1242) ────────────────────────────────────────
# A full calendar date is structurally INVISIBLE to the number gate above: the
# ADR-104 allow-list whitelists small counts (range(0,13)) and years (2020–2030),
# and numbers_in_text splits "2026-07-08" into 2026 / 7 / 8 — all benign — so a
# wholly invented ISO date passes fabricated_numbers() even against an EMPTY
# allow-list. The wednesday chronicle already solved this locally (build_recap's
# "set of dates a beat may legitimately cite" cross-check), but that lived only in
# the recap's structured-field path and never generalized. This promotes the
# concept into the shared gate: a date is a DISTINCT token class from a float —
# extracted whole, normalized to ISO, and required to appear in a supplied
# allow-list. The number gate stays untouched (dates are strings, not floats).
#
# Only COMPLETE dates (carrying a year) are extracted here — a bare "July 8th" has
# no year and is left to weekday_date_findings(); this gate is about invented full
# calendar dates.
_ISO_DATE_RE = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")
_MONTH_NAMES_ALT = "|".join(_MONTHS)
# "July 8, 2026" / "July 8 2026" / "Jul... " — full month name, day, year.
_LONGFORM_MDY_RE = re.compile(r"\b(" + _MONTH_NAMES_ALT + r")\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", re.IGNORECASE)
# "8 July 2026" / "8th July, 2026" — day, full month name, year.
_LONGFORM_DMY_RE = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(" + _MONTH_NAMES_ALT + r"),?\s+(\d{4})\b", re.IGNORECASE)


def dates_in_text(text: str) -> set:
    """Full calendar dates named in a string, normalized to ISO (YYYY-MM-DD strings).

    Matches ISO (``2026-07-08``) and long-form (``July 8, 2026`` / ``8 July 2026``)
    tokens, validating each against the real calendar (Feb-30, day 0, non-leap
    Feb-29 are rejected via _safe_date). Only dates carrying a year are returned —
    a bare "July 8th" is a partial token this gate deliberately ignores.
    """
    out = set()
    text = text or ""
    for m in _ISO_DATE_RE.finditer(text):
        d = _safe_date(m.group(1), m.group(2), m.group(3))
        if d:
            out.add(d.isoformat())
    for m in _LONGFORM_MDY_RE.finditer(text):
        d = _safe_date(m.group(3), _MONTHS[m.group(1).lower()], m.group(2))
        if d:
            out.add(d.isoformat())
    for m in _LONGFORM_DMY_RE.finditer(text):
        d = _safe_date(m.group(3), _MONTHS[m.group(2).lower()], m.group(1))
        if d:
            out.add(d.isoformat())
    return out


def allowed_dates(*sources) -> set:
    """The legitimate-date allow-list: every full calendar date present in what the
    model was given (prompt + data packet + canonical facts), normalized to ISO.

    The date-token analogue of allowed_numbers() — generalizes the wednesday
    chronicle recap's "set of dates a beat may legitimately cite" so any grounded
    surface can build its allow-list the same way. Accepts strings and any
    JSON-serializable structure (dicts/lists are json.dumps'd so nested dates count).
    """
    allowed = set()
    for src in sources:
        if src is None:
            continue
        text = src if isinstance(src, str) else json.dumps(src, default=str)
        allowed |= dates_in_text(text)
    return allowed


def fabricated_dates(text: str, allowed) -> list:
    """ISO strings for calendar dates cited in the output that appear in no input date.

    ``allowed`` is a set/iterable of date strings in ANY format — each is normalized
    to ISO before comparison, so an ISO date in the input matches a long-form
    restatement in the output (and vice versa). Returns the sorted list of ISO dates
    that are cited but ungrounded — the fabricated-date finding class.
    """
    allowed_iso = set()
    for a in allowed or ():
        if isinstance(a, str):
            allowed_iso |= dates_in_text(a)
    return [d for d in sorted(dates_in_text(text)) if d not in allowed_iso]


def authoritative_facts_block(facts: dict) -> str:
    """Render canonical facts as the AUTHORITATIVE FACTS system-prompt block.

    The analyzer's proven wording (truth audit Phase 3 + the no-invent-trends
    hard rule) — one source so every surface injects facts identically.
    Returns "" when no facts are available (caller simply omits the block).
    """
    facts = facts or {}
    # #2113: when the record behind these facts predates the current cycle's genesis,
    # canonical_facts has already WITHHELD its observed values (they are not this
    # cycle's readings at any age). The withholding is the load-bearing half — the
    # allow-list gate does the rest. This rider is the second half: without it the
    # coach is merely handed a thinner fact set on Day 1 and is free to reach for a
    # remembered figure, which is precisely how "Day one of this experiment ... your
    # Whoop recovery came in at 59%" got published against a cockpit serving 44%.
    # Rendered even when no numeric line survives, so silence is never the only
    # instruction.
    rider = ""
    if facts.get("facts_are_pre_genesis"):
        rider = (
            "CYCLE BOUNDARY — READ BEFORE CITING ANY VITAL:\n"
            f"  The experiment restarted on {facts.get('cycle_genesis')}. The most recent daily-metrics "
            f"record available is from {facts.get('as_of')}, BEFORE that reset, so its recovery, HRV, "
            "resting heart rate, weight and weight-rate figures belong to the PREVIOUS cycle and have "
            "been withheld from the facts below on purpose. Do NOT state a 'latest' or 'current' "
            "recovery, HRV, resting HR, weight or weekly rate, and never present a prior-cycle figure "
            "as this cycle's — least of all under a 'day one' frame. If a current value does not appear "
            "below, say plainly that the reading has not landed yet. Honest absence is the correct "
            "answer; a recalled or inferred number is not.\n"
        )
    # #1968: name the night these wake-date-keyed vitals describe (see ai/night_scope.py).
    lines = [ln for ln in (_night_scope.night_label_line(facts),) if ln]
    if facts.get("protein_g_avg") is not None:
        lines.append(
            f"  - Protein INTAKE averages {facts['protein_g_avg']:g} g/day "
            f"(target {int(facts.get('protein_g_target') or 190)} g, floor {int(facts.get('protein_g_floor') or 170)} g). "
            f"His actual intake is ~{facts['protein_g_avg']:g} g — never state intake as the target or floor."
        )
    if facts.get("recovery_pct") is not None:
        lines.append(f"  - Latest Whoop recovery: {facts['recovery_pct']:g}%")
    if facts.get("hrv_ms") is not None:
        lines.append(f"  - Latest HRV: {facts['hrv_ms']:g} ms (HRV is in MILLISECONDS, never bpm)")
    if facts.get("rhr_bpm") is not None:
        lines.append(f"  - Latest resting HR: {facts['rhr_bpm']:g} bpm")
    if facts.get("latest_weight") is not None:
        lines.append(f"  - Latest weight: {facts['latest_weight']:g} lb")
    if facts.get("weekly_rate_lbs") is not None:
        _rate_line = f"  - Weekly weight rate: {facts['weekly_rate_lbs']:g} lb/week (signed; negative = losing)"
        # #535: the rate carries its interval — narrative must not present it as exact.
        if facts.get("weekly_rate_ci_low") is not None and facts.get("weekly_rate_ci_high") is not None:
            _rate_line += f" [80% CI {facts['weekly_rate_ci_low']:g} to {facts['weekly_rate_ci_high']:g}]"
        # #914-B: a provisional rate (short weigh-in span) must be framed as provisional.
        if facts.get("rate_provisional"):
            _rate_line += " — PROVISIONAL (short weigh-in span; frame as an early estimate, never a settled rate)"
        lines.append(_rate_line)
    # #914-B: scale recency — the live incident was "maintained a 7.3 lb/week
    # trajectory" cited 14 days after the last weigh-in. When the caller supplies
    # weigh-in recency, render it; past ~a week of scale darkness the rate is
    # HISTORY, and present-tense rate claims ("maintaining", "is losing") are
    # fabrication. Callers without these keys render exactly as before.
    if facts.get("last_weighin_date"):
        _dsw = facts.get("days_since_weighin")
        _w_line = f"  - Last weigh-in: {facts['last_weighin_date']}"
        if _dsw is not None:
            _w_line += f" ({int(_dsw)} days ago)"
        lines.append(_w_line)
        if _dsw is not None and int(_dsw) >= 7:
            lines.append(
                "  - SCALE DARK: there has been NO weigh-in since the date above. Any weight-rate claim must be "
                "PAST-TENSE and dated (e.g. 'was losing ~X lb/week through "
                f"{facts['last_weighin_date']}; no weigh-in since') — never 'maintained', 'maintaining', or any "
                "present-tense trajectory. The current weight is UNKNOWN."
            )
    if facts.get("projected_goal_date_earliest") and facts.get("projected_goal_date_latest"):
        lines.append(
            f"  - Projected goal-weight date: a RANGE of {facts['projected_goal_date_earliest']} to "
            f"{facts['projected_goal_date_latest']} (never a single certain date)"
        )
    if not lines:
        return rider
    return rider + (
        "AUTHORITATIVE FACTS (cite these EXACT numbers; do not invent, round away, or "
        "substitute a target/floor for an actual value):\n" + "\n".join(lines) + "\n"
        "HARD RULE for resting HR, HRV, and recovery: state ONLY the exact value above. "
        "Do NOT invent a trend, a range, a multi-day figure, or a 'climbed/dropped from X to Y' "
        "for these — you do not have that history. If you have no specific number for a claim, "
        "describe the pattern qualitatively instead of inventing a figure."
    )


# ── band↔adjective grounding (#1208) ─────────────────────────────────────────
# A number can be digit-grounded yet its VERDICT semantically false: the live
# mind-expert analysis called 44% Whoop recovery "Strong biometric recovery" —
# 44% is Whoop's YELLOW band. The ADR-104 number gate (above) checks digits only,
# never the adjective attached to them. This deterministic, zero-AI check maps a
# metric's canonical value to its documented band and flags a top-band superlative
# ("strong", "excellent", …) sitting next to a sub-band value. Thresholds are the
# source's documented band (ADR-105: personal_baselines has no absolute recovery
# band, so Whoop's published cutoffs are the authority).
#
# Whoop recovery bands (documented): red <34, yellow 34–66, green 67+. A top-band
# superlative is honest ONLY for green.
_RECOVERY_GREEN_FLOOR = 67.0

# Superlatives that assert a HIGH / top-band reading. Scoped tight to claims of
# strength — honest yellow-band words ("moderate", "steady", "middling", "fair")
# are deliberately absent so they never flag.
_HIGH_BAND_ADJECTIVES = (
    "strong",
    "excellent",
    "great",
    "solid",
    "robust",
    "outstanding",
    "superb",
    "stellar",
    "elite",
    "peak",
    "roaring",
    "exceptional",
    "impressive",
    "terrific",
    "fantastic",
)
_HIGH_BAND_RE = re.compile(r"\b(" + "|".join(_HIGH_BAND_ADJECTIVES) + r")\b", re.IGNORECASE)
# Recovery mentions — the noun the adjective must be attached to.
_RECOVERY_KW_RE = re.compile(r"\brecover(?:y|ed|ing)\b", re.IGNORECASE)


def band_adjective_findings(text: str, facts: dict = None, proximity: int = 40) -> list:
    """Deterministic band↔adjective check. Returns [{type: "band_contradiction", ...}].

    For each metric with a documented band and a sub-band canonical value, flag a
    top-band superlative sitting within `proximity` characters of the metric's noun
    (so "strong … recovery" is caught, an unrelated "strong squat" far away is not).
    A superlative that is genuinely consistent (attached to a GREEN-band value) does
    not flag. Empty list = no band mischaracterization.
    """
    text = text or ""
    facts = facts or {}
    findings = []

    rec = facts.get("recovery_pct")
    try:
        rec = float(rec) if rec is not None else None
    except (TypeError, ValueError):
        rec = None
    if rec is not None and rec < _RECOVERY_GREEN_FLOOR:
        band = "red" if rec < 34 else "yellow"
        for km in _RECOVERY_KW_RE.finditer(text):
            lo = max(0, km.start() - proximity)
            hi = km.end() + proximity
            window = text[lo:hi]
            am = _HIGH_BAND_RE.search(window)
            if am:
                findings.append(
                    {
                        "type": "band_contradiction",
                        "metric": "Whoop recovery",
                        "band": band,
                        "value": rec,
                        "adjective": am.group(1),
                        "detail": (
                            f'the narrative calls recovery "{am.group(1)}", but the authoritative '
                            f"Whoop recovery is {rec:g}% — the {band} band, not a strong reading"
                        ),
                    }
                )
                break  # one finding per metric is sufficient signal
    return findings


# ── baseline-freshness grounding (#1691, epic #1687) ─────────────────────────
# A coach brief can be perfectly digit-grounded against the DATA it was handed yet
# still cite a STALE cycle constant. On 2026-07-22 the 07-20 briefs were frozen
# with cycle-9 baselines — "starting weight of 315 lbs" (the real cycle-10 baseline
# is 321.38) and "Day 1" during the pre-start window (genesis 2026-07-22, so 07-20
# is PRE-START, not Day 1). `grounded:True` passed them because the number/date
# gates above check claims-vs-DATA, never framing-vs-CYCLE-STATE — 4 of 5
# high-concern items that day were exactly this "reset-window stale-baseline" class.
#
# This deterministic, zero-AI check closes that gap. It takes the cycle constants
# as PARAMS (baseline_lbs = constants.EXPERIMENT_BASELINE_WEIGHT_LBS, start_date_iso
# = constants.EXPERIMENT_START_DATE) so it stays pure + unit-testable and never
# imports AWS or the site-api. Its phase logic MUST agree with
# site_api_common.pre_start_meta() / constants.day_n(): gen_date < start_date ⇒
# pre_start (any "Day N" claim is stale framing); gen_date >= start_date ⇒ the
# expected day is (gen_date - start_date).days + 1 (1-indexed, matching day_n).
#
# PROMOTION HOOK (ADR-104/105 posture): this is the deterministic layer, which CAN
# graduate to a hard/HELD gate. It ships ADVISORY first (surfaced in the review pack
# + stamped into qa_archive meta at generation time); a reset-window stale brief is
# exactly what its advisory finding trips, and flipping the caller from "log + stamp"
# to "hold + regenerate" is the promotable suppression hook the reset AC refers to —
# no restart_pipeline change is required to satisfy "no stale brief reaches a reader".

# A body-weight token: a 2–3 digit number (optionally decimal) tied to a lb/pound
# unit. The lookbehind stops it from biting a fragment of a longer number.
_WEIGHT_LB_RE = re.compile(r"(?<![\d.])(\d{2,3}(?:\.\d+)?)\s*(?:lbs?|pounds?)\b", re.IGNORECASE)

# Baseline/starting-weight FRAMING context. Only a weight sitting next to one of
# these is a candidate — a current-weight mention ("you now weigh 315 lb") never
# flags because it carries none of this framing. Mirrors band_adjective_findings'
# proximity approach.
#
# 2026-08-25 (#3154): "start(?:ed|ing)? the experiment at" / "began the experiment
# at" hardcoded the determiner to "the" — "started THIS experiment at" (or my/our)
# sailed straight through. #3050's eval-matrix build caught it by adversarial
# canary construction (staged as a KNOWN MISS in PR #3153, flipped to CAUGHT here).
# Scoped to the same four determiners _SPAN_RE already covers below, so the fix
# closes the class without widening past it.
_BASELINE_FRAMING_RE = re.compile(
    r"\b("
    r"starting weight|start weight|baseline weight|baseline|"
    r"started at|began at|start(?:ed|ing)? (?:the|this|my|our) experiment at|began (?:the|this|my|our) experiment at|"
    r"day 1 weight|day one weight|starting point|initial weight|started out at|started from"
    r")\b",
    re.IGNORECASE,
)

# "Day N" experiment-day framing. N is captured; N==0 is treated as a non-claim
# for the pre-start case (a "Day 0"/countdown framing is the CORRECT pre-start form).
_DAY_N_RE = re.compile(r"\bday\s+(\d{1,4})\b", re.IGNORECASE)


def _phase_for(generation_date_iso: str, start_date_iso: str):
    """Pure phase resolver mirroring pre_start_meta()/day_n().

    Returns ("pre_start", None) when generation_date < start_date, else
    ("in_experiment", expected_day) with expected_day 1-indexed off start_date.
    Returns (None, None) on unparseable dates (caller skips the phase check).
    """
    try:
        gen = _dt.date.fromisoformat(generation_date_iso)
        start = _dt.date.fromisoformat(start_date_iso)
    except (TypeError, ValueError):
        return None, None
    if gen < start:
        return "pre_start", None
    return "in_experiment", (gen - start).days + 1


# ── #1897: experiment-age claims spelled out in words ───────────────────────
# On 2026-07-27 (Day 1) /api/ai_analysis?expert=nutrition published "Zero food
# logs in seven days of an experiment". Every gate was blind to it: _NUM_RE is
# digits-only so "seven" is invisible; 7 is in _BENIGN_NUMBERS anyway; and
# _DAY_N_RE matches "Day N" tokens, not "N days OF the experiment". A span claim
# is the same arithmetic as a Day-N claim wearing different clothes.
#
# This is the parser #1922 deliberately deferred: that issue moved NUMERIC
# phase-bound claims into deterministic code and left word-numbers with the LLM
# precisely because "seven" is not arithmetic until something parses it. This
# parses it, so the class comes back to the deterministic side.
_WORD_NUMBERS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "ninety": 90,
    "a": 1,
    "an": 1,
}

# "N days of the experiment" / "three weeks into this experiment" / "seven days in".
# Requires the experiment framing — a bare "six days" may be about anything
# (a training block, a sleep streak), and flagging those would make the gate noise.
#
# 2026-08-25 (#3154 sibling sweep): this one already spans the/this/my/our (plus
# his/her) before the noun — no determiner-width gap here, unlike the
# _BASELINE_FRAMING_RE class this pattern sits alongside.
_SPAN_RE = re.compile(
    r"\b(?P<n>\d{1,4}|" + "|".join(sorted(_WORD_NUMBERS, key=len, reverse=True)) + r")\s+"
    r"(?P<unit>days?|weeks?|months?)\s+"
    r"(?:of|into|in\b(?!\s+a\s+row))\s+"
    r"(?:this\s+|the\s+|an\s+|my\s+|his\s+|her\s+|our\s+)?"
    r"(?:current\s+|new\s+|fresh\s+)?"
    r"(?:experiment|cycle|season|run|protocol)\b",
    re.IGNORECASE,
)
_SPAN_UNIT_DAYS = {"day": 1, "days": 1, "week": 7, "weeks": 7, "month": 30, "months": 30}


def _span_to_days(n_token: str, unit_token: str):
    """(count, unit) -> days, or None when the count is not a number we parse."""
    tok = (n_token or "").strip().lower()
    n = _WORD_NUMBERS.get(tok)
    if n is None:
        try:
            n = int(tok)
        except (TypeError, ValueError):
            return None
    return n * _SPAN_UNIT_DAYS.get((unit_token or "").strip().lower(), 1)


def absence_span_findings(text: str, *, known_absence_days: dict = None) -> list:
    """#2756: a narrated ABSENCE span must match the measured one.

    Live case: the nutrition coach said MacroFactor had "been blank for four
    days" while the platform's own absence derivation said 52 — the fact pack
    carried None for an empty window and the model filled the vacuum. The span
    gate above could not catch it (4 < elapsed is a legal span); this class can,
    because the caller HANDS IT the measured truth.

    `known_absence_days` maps a category label to the measured dark-day count
    (e.g. {"food": 52}). A sentence that talks about absence (blank/dark/quiet/
    no logs/hasn't logged) and states a day-span differing from the measured
    value by more than 1 day is a finding. Precision-first: sentences without
    absence vocabulary are never touched, and a ±1 tolerance absorbs the
    end-of-day boundary. Findings use the shared {"type", "detail"} shape.
    """
    if not text or not known_absence_days:
        return []
    findings = []
    sentences = re.split(r"(?<=[.!?])\s+", text)
    word_nums = "|".join(_WORD_NUMBERS)
    span_re = re.compile(rf"\b(\d{{1,4}}|{word_nums})[-\s]day(?:s)?\b|\b(\d{{1,4}}|{word_nums})\s+days?\b", re.IGNORECASE)
    absent_re = re.compile(
        r"blank|dark|quiet|silen|no (?:food )?log|hasn'?t (?:been )?logg|nothing (?:has been )?logged|without (?:a )?(?:single )?log|unlogged",
        re.IGNORECASE,
    )
    for cat, true_days in known_absence_days.items():
        if true_days is None:
            continue
        for sent in sentences:
            if not absent_re.search(sent):
                continue
            for m in span_re.finditer(sent):
                raw = (m.group(1) or m.group(2) or "").lower()
                n = _WORD_NUMBERS.get(raw) if raw in _WORD_NUMBERS else (int(raw) if raw.isdigit() else None)
                if n is None or n == 0:
                    continue
                if abs(n - int(true_days)) > 1:
                    findings.append(
                        {
                            "type": "absence_span",
                            "category": cat,
                            "claimed_days": n,
                            "true_days": int(true_days),
                            "detail": (
                                f"the narrative states a {n}-day {cat} absence, but the measured span is "
                                f"{int(true_days)} day(s) dark — an understated absence reads as a smaller "
                                f"lapse than the record shows (#2756)"
                            ),
                        }
                    )
    return findings


def experiment_span_findings(text: str, *, generation_date_iso: str, start_date_iso: str) -> list:
    """Deterministic check on claimed experiment AGE, digits or words (#1897).

    Flags "seven days of an experiment" / "three weeks into this cycle" when the
    span exceeds the days actually elapsed. Pre-start (generation before genesis)
    flags ANY positive span — zero days of the current experiment exist yet.

    A span SHORTER than the elapsed days is correct and never flagged: trailing
    windows clamp to genesis (ADR-077 "clamped, not hidden"), which is the same
    lower-bound rule #1917 had to teach the LLM rubric after it flagged 5-on-Day-6
    three times. Only a LONGER span is impossible.

    Findings use the shared {"type", "detail"} shape (type "experiment_span") so
    they compose with grounding_findings() / correction_prompt().
    """
    phase, expected_day = _phase_for(generation_date_iso, start_date_iso)
    if phase is None:
        return []
    findings = []
    seen = set()
    for m in _SPAN_RE.finditer(text or ""):
        days = _span_to_days(m.group("n"), m.group("unit"))
        if days is None:
            continue
        claim = m.group(0).strip()
        if claim.lower() in seen:
            continue
        if phase == "pre_start":
            seen.add(claim.lower())
            findings.append(
                {
                    "type": "experiment_span",
                    "claim": claim,
                    "detail": (f'the narrative claims "{claim}", but the experiment has not started yet — ' f"zero days of it exist"),
                }
            )
        elif days > expected_day:
            seen.add(claim.lower())
            findings.append(
                {
                    "type": "experiment_span",
                    "claim": claim,
                    "detail": (
                        f'the narrative claims "{claim}" ({days} day(s)), but only {expected_day} day(s) '
                        f"have elapsed since genesis — that history does not exist"
                    ),
                }
            )
    return findings


def baseline_freshness_findings(
    text: str,
    *,
    generation_date_iso: str,
    baseline_lbs: float = None,
    start_date_iso: str,
    weight_tolerance_lbs: float = 1.0,
    proximity: int = 45,
) -> list:
    """Deterministic cycle-freshness check for coach-authored output (#1691).

    Two finding classes, both zero-AI and framing-scoped:

    - "stale_baseline": a cited STARTING/baseline weight (a weight token within
      `proximity` chars of baseline framing — "starting weight", "baseline",
      "started at", "Day 1 weight", …) that disagrees with `baseline_lbs` by more
      than `weight_tolerance_lbs`. Current-weight mentions carry no baseline framing
      and never flag. Skipped entirely when `baseline_lbs` is None.
    - "stale_phase": a "Day N" experiment-day framing that disagrees with the true
      phase of `generation_date_iso`. If pre_start (gen < start): ANY "Day N" (N>=1)
      is a finding — correct framing is the pre-start countdown. If in-experiment:
      a cited N != the real day (day_n(gen)) is a finding.

    Same ``{"type": ..., "detail": ...}`` shape as the other grounded_generation
    finding classes, so it composes with grounding_findings()/correction_prompt().
    """
    text = text or ""
    findings = []

    # ── stale_baseline ────────────────────────────────────────────────────────
    if baseline_lbs is not None:
        try:
            baseline = float(baseline_lbs)
        except (TypeError, ValueError):
            baseline = None
        if baseline is not None:
            weight_tokens = []  # (start, end, value)
            for wm in _WEIGHT_LB_RE.finditer(text):
                try:
                    weight_tokens.append((wm.start(1), wm.end(1), float(wm.group(1))))
                except ValueError:
                    continue
            seen_tokens = set()
            for fm in _BASELINE_FRAMING_RE.finditer(text):
                f_start, f_end = fm.start(), fm.end()
                # Nearest weight token to THIS baseline-framing phrase, within window.
                best, best_dist = None, None
                for ws, we, val in weight_tokens:
                    if ws >= f_end:
                        dist = ws - f_end
                    elif we <= f_start:
                        dist = f_start - we
                    else:
                        dist = 0
                    if dist <= proximity and (best_dist is None or dist < best_dist):
                        best, best_dist = (ws, val), dist
                if best is None:
                    continue
                ws, val = best
                if ws in seen_tokens:
                    continue
                seen_tokens.add(ws)
                if abs(val - baseline) > weight_tolerance_lbs:
                    findings.append(
                        {
                            "type": "stale_baseline",
                            "claimed": round(val, 4),
                            "expected": round(baseline, 4),
                            "detail": (
                                f"the narrative cites a starting/baseline weight of {val:g} lb next to baseline framing, "
                                f"but the current cycle baseline is {baseline:g} lb"
                            ),
                        }
                    )

    # ── stale_phase ───────────────────────────────────────────────────────────
    phase, expected_day = _phase_for(generation_date_iso, start_date_iso)
    if phase is not None:
        seen_days = set()
        for dm in _DAY_N_RE.finditer(text):
            n = int(dm.group(1))
            if n in seen_days:
                continue
            if phase == "pre_start":
                if n >= 1:
                    seen_days.add(n)
                    findings.append(
                        {
                            "type": "stale_phase",
                            "claimed_day": n,
                            "detail": (
                                f'the narrative frames this as "Day {n}", but the generation date '
                                f"{generation_date_iso} is BEFORE genesis {start_date_iso} (pre-start) — the correct "
                                f"framing is the pre-start countdown, not a Day count"
                            ),
                        }
                    )
            else:  # in_experiment
                if n != expected_day:
                    seen_days.add(n)
                    findings.append(
                        {
                            "type": "stale_phase",
                            "claimed_day": n,
                            "expected_day": expected_day,
                            "detail": (
                                f'the narrative cites "Day {n}", but generation date {generation_date_iso} is '
                                f"Day {expected_day} of the experiment (genesis {start_date_iso})"
                            ),
                        }
                    )
    return findings


# ── #1896: a coach's own track-record claims ────────────────────────────────
# The gates above check claims about MATTHEW (his numbers, his dates, his logged
# behavior). None of them check a claim the coach makes about ITSELF — and on
# 2026-07-27 Dr. Webb published "I called lunch wrong… That's a prediction miss,
# and I'm logging it as one" while every stored PREDICTION# was status=pending
# and the same paragraph admitted "I have zero food logs. Nothing." The verdict
# was then persisted as a THREAD# row and baked into the committed noscript, so
# a fabricated grade fed forward into later generations.
#
# The prompt actively invites this (intelligence_common.build_thread_prompt_block:
# 'If a prediction resolved: explicitly call it out. "I predicted [X]. I was
# [right/wrong]."'), and ADR-105 says the deterministic computation comes FIRST:
# a self-graded outcome is only sayable if an evaluated record exists to say it
# from. That is a count, not a judgment.

# Sentence splitting for this gate. It used to borrow the #1699 gate's regex, which
# moved to ai/behavior_logs.py with #2056 — so it is stated here, next to the only gate
# in this file that still needs it, rather than reaching across a module boundary for a
# private name. (night_scope.py restates the same one-liner for the same reason.)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")

_SGV_VERDICT_PATTERNS = [
    # explicit self-grading of a call
    re.compile(r"\bprediction\s+(?:miss|hit)\b", re.IGNORECASE),
    re.compile(r"\b(?:i|my)\s+(?:called|predicted)\b[^.!?]{0,60}\b(?:wrong|right|correctly|incorrectly)\b", re.IGNORECASE),
    re.compile(r"\bi\s+was\s+(?:right|wrong)\b", re.IGNORECASE),
    re.compile(r"\b(?:that|this)(?:'s| is| was)\s+a\s+(?:miss|hit)\b", re.IGNORECASE),
    re.compile(r"\blogging\s+it\s+as\s+(?:a\s+)?(?:miss|hit|one)\b", re.IGNORECASE),
    re.compile(r"\bmy\s+(?:call|prediction|forecast)\s+(?:was|proved)\b[^.!?]{0,40}\b(?:right|wrong|correct)\b", re.IGNORECASE),
    # outcome-framed comparison against a prior prediction — the softer form the
    # same coach was still publishing on 2026-08-01 ("week-one protein
    # consistency exceeded predictions") with all 50 predictions still pending.
    re.compile(
        r"\b(?:exceeded|beat|outperformed|fell short of|missed|undershot|overshot)\s+(?:\w+\s+){0,2}(?:my\s+|the\s+|his\s+|her\s+|their\s+)?(?:baseline\s+)?(?:prediction|predictions|forecast|forecasts)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:better|worse)\s+than\s+(?:\w+\s+){0,3}(?:predicted|forecast|expected by my)\b", re.IGNORECASE),
]

# Hypotheticals and forward-looking framing are not verdicts. Scoped to the text
# BEFORE the verdict phrase, not the whole sentence: "consistency exceeded
# predictions, but cannot determine if adherence is system-driven" is a verdict
# followed by an unrelated conditional, and a whole-sentence modal test let
# exactly that sentence through when I first wrote this.
_SGV_MODAL_RE = re.compile(
    r"\b(?:if|would|could|should|might|may|will|going to|expect to|plan to|when it resolves|once .{0,20}resolves)\b",
    re.IGNORECASE,
)


def self_graded_verdict_findings(text: str, *, evaluated_predictions) -> list:
    """Deterministic check that a coach's self-graded verdict has a record (#1896).

    Flags any sentence in which the coach grades its OWN prediction — "that's a
    prediction miss", "I was wrong", "protein consistency exceeded predictions" —
    when `evaluated_predictions` is 0. An evaluated prediction is one whose
    status has actually resolved (confirmed/refuted/graded); `pending` is not a
    verdict, and neither is a prediction that merely exists.

    `evaluated_predictions` is REQUIRED and caller-supplied (the caller owns the
    lookup; this function does no I/O and stays pure). Passing ``None`` returns []
    — the caller has opted out, the same contract ungrounded_behavioral_findings
    uses for `available_logs`. A positive count returns [] too: once real graded
    records exist, WHICH one the coach means is a semantic question, and this
    gate deliberately does not answer semantic questions (ADR-105: deterministic
    first, LLM for what is genuinely semantic).

    Findings use the shared {"type", "detail"} shape (type
    ``"self_graded_verdict"``) so they compose with grounding_findings() and
    correction_prompt().
    """
    if evaluated_predictions is None:
        return []
    try:
        n_evaluated = int(evaluated_predictions)
    except (TypeError, ValueError):
        return []
    if n_evaluated > 0:
        return []
    findings = []
    seen = set()
    for raw in _SENTENCE_SPLIT_RE.split((text or "").strip()):
        sent = raw.strip()
        if not sent:
            continue
        for rx in _SGV_VERDICT_PATTERNS:
            m = rx.search(sent)
            if not m:
                continue
            if _SGV_MODAL_RE.search(sent[: m.end()]):  # the clause GOVERNING the phrase is conditional
                continue
            key = m.group(0).lower()
            if key in seen:
                continue
            seen.add(key)
            snippet = sent if len(sent) <= 140 else sent[:137].rstrip() + "…"
            findings.append(
                {
                    "type": "self_graded_verdict",
                    "claim": m.group(0).strip(),
                    "detail": (
                        f'the narrative grades its own prediction ("{snippet}"), but ZERO predictions '
                        f"have been evaluated — every stored record is still pending, so there is no "
                        f"verdict to report"
                    ),
                }
            )
    return findings


def grounding_findings(
    text: str,
    facts: dict = None,
    allowed: set = None,
    allowed_dates: set = None,
    *,
    baseline_lbs: float = None,
    generation_date_iso: str = None,
    start_date_iso: str = None,
    weight_tolerance_lbs: float = 1.0,
    available_logs=None,
    known_absence_days=None,
    evaluated_predictions=None,
    nightly_vitals=None,
    number_tolerance: float = NUMBER_TOLERANCE_TOLERANT,
) -> list:
    """Deterministic grounding check. Returns [{type, detail, ...}] — empty = grounded.

    - "contradiction": a stated RHR/recovery/HRV hard-contradicts canonical facts
      (grounding_guard's per-metric tolerances + grounded-anywhere logic).
    - "band_contradiction": a top-band superlative ("strong recovery") attached to
      a sub-band canonical value (44% = Whoop yellow) — #1208, band_adjective_findings.
    - "fabricated_number": a number appears in the output but nowhere in the
      input allow-list (and isn't benign) — the trend/range fabrication class.
      ``number_tolerance`` sets how close counts as "in" (#2290). The default keeps
      every existing caller's behaviour; a reader-facing surface whose refusal copy IS
      an honesty claim should pass ``NUMBER_TOLERANCE_EXACT``, which still accepts a
      rounding of an allowed number but refuses a corrupted trailing decimal.
    - "fabricated_date": a full calendar date is cited in the output that appears in
      no supplied legitimate date — #1242, fabricated_dates(). Checked ONLY when
      ``allowed_dates`` is passed (an empty set means "no dates are legitimate");
      callers that don't supply it keep the pre-#1242 behavior exactly (no date check).
    - "stale_baseline"/"stale_phase": a cited starting weight or "Day N" framing that
      disagrees with the current cycle constants — #1691, baseline_freshness_findings().
      Checked ONLY when BOTH ``generation_date_iso`` and ``start_date_iso`` are passed
      (``baseline_lbs`` additionally enables the stale_baseline class); callers that
      don't supply them keep the pre-#1691 behavior exactly — identical discipline to
      the optional ``allowed_dates`` param.
    - "ungrounded_behavioral": a same-day completed-behavior claim ("you maintained
      your eating window today") whose supporting log category is absent from
      ``available_logs`` — #1699, ungrounded_behavioral_findings(). Checked ONLY when
      ``available_logs`` is passed; callers that don't supply it keep the pre-#1699
      behavior exactly — same optional-param discipline as ``allowed_dates`` / the
      #1691 params. Two shapes (#2056): a plain iterable is FULL coverage (an empty
      set means "no logs today"), a ``behavior_logs.LogAvailability`` declares which
      categories the caller can answer for at all — an uncovered category is unknown
      and never flags, which is what lets partial-visibility surfaces arm honestly.
    - "unlabeled_night_figure"/"night_value_mismatch": a vitals figure naming no night,
      or naming one and disagreeing with what is stored for it NOW — #1968, and the one
      class that also runs at serve time. Checked ONLY when ``nightly_vitals`` is passed
      (night-keyed); see ``ai/night_scope.py``.
    """
    findings = []
    if facts and _hard_contradictions is not None:
        for c in _hard_contradictions(text, facts):
            findings.append({"type": "contradiction", **c})
    if facts:
        findings.extend(band_adjective_findings(text, facts))
    if allowed is not None:
        for x in fabricated_numbers(text, allowed, tolerance=number_tolerance):
            findings.append(
                {
                    "type": "fabricated_number",
                    "claimed": x,
                    "detail": f"the number {x:g} appears in the narrative but nowhere in the data provided",
                }
            )
    if allowed_dates is not None:
        for d in fabricated_dates(text, allowed_dates):
            findings.append(
                {
                    "type": "fabricated_date",
                    "claimed": d,
                    "detail": f"the date {d} appears in the narrative but is not among the dates the data provided",
                }
            )
    if generation_date_iso is not None and start_date_iso is not None:
        findings.extend(
            baseline_freshness_findings(
                text,
                generation_date_iso=generation_date_iso,
                baseline_lbs=baseline_lbs,
                start_date_iso=start_date_iso,
                weight_tolerance_lbs=weight_tolerance_lbs,
            )
        )
    if generation_date_iso and start_date_iso:
        findings.extend(experiment_span_findings(text, generation_date_iso=generation_date_iso, start_date_iso=start_date_iso))
    if available_logs is not None:
        findings.extend(ungrounded_behavioral_findings(text, available_logs=available_logs))
    if known_absence_days:
        # #2756: narrated absence spans must match the measured span; armed only
        # when the caller hands the truth in (same optional-param discipline).
        findings.extend(absence_span_findings(text, known_absence_days=known_absence_days))
    if evaluated_predictions is not None:
        findings.extend(self_graded_verdict_findings(text, evaluated_predictions=evaluated_predictions))
    if nightly_vitals is not None:
        findings.extend(
            _night_scope.night_scoped_vitals_findings(text, nightly_vitals=nightly_vitals, generation_date_iso=generation_date_iso)
        )
    return findings


def correction_prompt(findings: list) -> str:
    """The correction addendum for the single rewrite (analyzer's proven shape)."""
    lines = ["CORRECTION REQUIRED — your draft states numbers that are not grounded in the data:\n"]
    for i, f in enumerate(findings, 1):
        if f.get("type") == "contradiction" and f.get("canonical") is not None:
            lines.append(f"{i}. {f['detail']}. Use {f['canonical']:g}, or omit the metric — never invent one.")
        elif f.get("type") == "band_contradiction":
            lines.append(
                f"{i}. {f['detail']}. Use an accurate band word for a {f['band']} reading "
                f"(e.g. 'moderate' or 'low'), never a superlative."
            )
        elif f.get("type") == "weekday_mismatch":
            lines.append(f"{i}. {f['detail']}. Use {f['actual_weekday']} for that date, or drop the day-of-week — never guess a weekday.")
        elif f.get("type") == "fabricated_date":
            lines.append(f"{i}. {f['detail']}. Remove the date or cite only a date that appears in the source material — never invent one.")
        elif f.get("type") == "stale_baseline":
            lines.append(
                f"{i}. {f['detail']}. Use {f['expected']:g} lb for the starting/baseline weight, or omit the baseline — never a stale one."
            )
        elif f.get("type") == "stale_phase":
            if f.get("expected_day") is not None:
                lines.append(f"{i}. {f['detail']}. Use Day {f['expected_day']}, or drop the day count — never a stale one.")
            else:
                lines.append(f"{i}. {f['detail']}. Frame it as the pre-start countdown, not a Day count.")
        elif f.get("type") == "self_graded_verdict":
            lines.append(
                f"- Remove the self-graded verdict \"{f.get('claim')}\": no prediction has been evaluated yet, "
                f"so you cannot report a hit or a miss. State the prediction as still open, or say nothing about it."
            )
        elif f.get("type") == "experiment_span":
            lines.append(f"- Remove or correct \"{f.get('claim')}\": {f.get('detail')}. State the real elapsed time or drop the span.")
        elif f.get("type") == "ungrounded_behavioral":
            lines.append(
                f"{i}. {f['detail']}. Remove the claim or hedge it (\"if you kept your window today\"), or cite the "
                f"actual log — never assert a completed behavior with no record behind it."
            )
        elif f.get("type") in _night_scope.FINDING_TYPES:  # #1968
            lines.append(f"{i}. {_night_scope.correction_line(f)}")
        elif f.get("type") == "unresolvable_precedent":
            lines.append(
                f"{i}. {f['detail']}. Cite ONLY a precedent date that was provided to you (with its link + similarity), "
                f"or drop the precedent entirely — never invent one the archive can't back."
            )
        else:
            lines.append(f"{i}. {f['detail']}. Remove it or describe the pattern qualitatively — never invent a figure.")
    lines.append("\nRewrite with these corrected. Keep your voice and length; do not mention that a correction was made.")
    return "\n".join(lines)


def regen_once(text: str, findings_fn, regen_fn, surface: str = "unknown"):
    """One corrective rewrite, kept only if strictly better. Never regresses.

    findings_fn(text) -> list of findings (e.g. a grounding_findings closure).
    regen_fn(correction: str) -> str — the caller's single regeneration call
    (model, tokens, prompt assembly all stay the caller's business).
    surface -- caller identity for discard telemetry (#3086); same convention
    as ai_calls._ground_legacy_output's `label` param.

    Returns (best_text, findings_for_best_text, corrected: bool).
    """
    findings = findings_fn(text)
    if not findings:
        return text, [], False
    try:
        fixed = regen_fn(correction_prompt(findings))
    except (TimeoutError, ConnectionError, OSError) as e:  # #3059 precedent: named, not bare
        _regen_telemetry.log_discard("transport_error", surface, len(findings), reason=type(e).__name__)
        return text, findings, False
    except Exception as e:
        _regen_telemetry.log_discard("unexpected_error", surface, len(findings), reason=type(e).__name__)
        return text, findings, False
    if not (fixed or "").strip():
        _regen_telemetry.log_discard("empty_response", surface, len(findings))
        return text, findings, False
    fixed_findings = findings_fn(fixed)
    if len(fixed_findings) < len(findings):
        return fixed, fixed_findings, True
    _regen_telemetry.log_discard("not_strictly_better", surface, len(findings))
    return text, findings, False
