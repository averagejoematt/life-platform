"""cross_surface_qa.py — #1894: surfaces must agree with each other, not just
with themselves.

The live failure (Day 1, cycle 11): the coaching door's coach card opened
"Day 1 weight is 317.61 lbs" — a pre-genesis weigh-in — while home and
/api/vitals served 321.09. A reader crossing home → coaching hit a 3.5 lb
contradiction on the experiment's single most important number.

**No single surface was internally wrong.** Each was self-consistent, which is
exactly why every per-surface guard already in place passed it. The defect only
exists in the COMPARISON, so the check has to live between surfaces.

Pure module — no AWS, no network, no clock — so the assessors are unit-testable
offline. qa_smoke_lambda owns the fetching and the Check() wrapping, the same
split as `assess_hero_weight` and the `reader_truth_qa` helper.
"""

import re
from datetime import date as _date, timedelta as _timedelta

# Rounding and a same-day reweigh, not a cycle-old figure. The live gap was 3.5 lb.
CROSS_SURFACE_WEIGHT_TOL_LBS = 1.5

# Below this, a figure in coach prose is plate/dumbbell/equipment weight, not a
# claim about bodyweight ("add 10 lbs to the bar").
_BODYWEIGHT_FLOOR_LBS = 100

_WEIGHT_IN_PROSE = re.compile(r"\b(\d{2,3}(?:\.\d+)?)\s*(?:lbs?|pounds)\b", re.IGNORECASE)

# Coach fields that carry reader-facing prose.
_PROSE_FIELDS = ("position_summary", "analysis", "headline", "summary")

# #1924: a weight the prose ANCHORS TO A PAST POINT is not a claim about today.
# "the weight anchor I'm working from is 321.1 lbs at Day 1" is correct, dated,
# reader-honest prose — and the #1894 check flagged it anyway, because it compared
# every extracted figure against the current weight. That matters twice over: it
# fires on correct writing (which trains people to ignore a blocking gate), and it
# makes the *cure* for the real half of #1924 — telling the coach to date its
# citations, per intelligence/weight_recency — unable to clear the check.
#
# Deliberately narrow: only an explicit backward reference within a short distance
# AFTER the figure exempts it. A bare number is still judged as a present-tense
# claim, so the genuinely stale "the latest reading is 316.3 lbs" still FAILs.
_HISTORICAL_ANCHOR = re.compile(
    r"""^\s*(?:
          at\s+day\s+\d+                 # "321.1 lbs at Day 1"
        | on\s+day\s+\d+
        | at\s+(?:the\s+)?(?:start|baseline|outset|beginning)
        | as\s+of\s+\d{4}-\d{2}-\d{2}    # the dated form weight_recency asks for
        | back\s+(?:in|on)\b
        | in\s+(?:january|february|march|april|may|june|july|august|september|october|november|december)\b
    )""",
    re.IGNORECASE | re.VERBOSE,
)

# How far past the figure to look for that anchor. Long enough for "lbs at Day 1",
# short enough that a later sentence's date cannot launder an undated claim.
_ANCHOR_WINDOW_CHARS = 24

# ── #2738: an explicitly DATED reading is not a claim about now ────────────────
#
# Measured 2026-08-15, the sole driver of that night's `cross_surface:vitals` FAIL —
# and the content was correct, not the coach:
#
#   "I can see your wearables—Whoop caught 40% recovery and 35.3 ms HRV on the night
#    of 2026-08-13—but MacroFactor has been blank for four days."
#
# 40 / 35.32 IS the 2026-08-14 morning reading (the night of 08-13), confirmed against
# the `published_vitals` stamps two coaches still carry. The coach named the night it
# was talking about — exactly the provenance ADR-104 asks for — and the check called it
# a contradiction with today's cockpit.
#
# `_HISTORICAL_ANCHOR` above is the existing escape hatch and it missed this THREE ways,
# which is why the vocabulary alone is not the fix:
#   1. "on the night of <date>" is not in it (nor "on <date>", nor "last night");
#   2. it is forward-only and anchored at offset 0, so "On 2026-08-13, recovery was 40%"
#      — the date BEFORE the figure — can never match;
#   3. `_ANCHOR_WINDOW_CHARS = 24` cannot span a compound clause: recovery's window here
#      is " and 35.3 ms HRV on the n", so even a fixed vocabulary leaves recovery flagged.
#
# So this is SENTENCE-scoped, for the same reason `_VITALS_TARGET_SENTENCE` is and with
# the same #1985 rationale — a gate that fires on correct writing is a gate people learn
# to ignore. It stays narrow in the way that matters: it requires an EXPLICIT calendar
# date or a named past night, not any vague backward hint, so "the latest reading is
# 316.3 lbs" is still judged present-tense. The `_ANCHOR_WINDOW_CHARS` comment's worry —
# that a LATER sentence's date could launder an undated claim — is preserved exactly,
# because the scope here is the one sentence the figure lives in, never the blob.
#
# Deliberately asymmetric, like the target exemption: "recovery was 40% on 2026-08-13
# but is 92% now" exempts both figures. That is the correct direction to be wrong in —
# this gate exists to catch the undated-stale-number class escaping, and a coach who
# dates a number is doing the thing the platform wants.
# NOT "last night": in this domain that is the CURRENT reading, not a historical one —
# a whoop morning IS last night's sleep. The existing #2113 sleep test caught that on the
# first draft of this pattern, which is the behaviour it exists to protect.
#
# ── #3793: a coach writes dates the way a PERSON does, not the way a key does ──
#
# The second instance of the same class, measured 2026-09-14 and the sole driver of
# that day's five consecutive `cross_surface:vitals` FAILs (18:31Z→22:34Z) and of the
# `qa-smoke-failures` alarm:
#
#   "On September 12th, his Whoop recorded 73% recovery, 36.4 ms HRV, and 60 bpm
#    resting heart rate — solid single-night readings…"   (Dr. Max Reyes)
#
# Every number is right. 73 / 36.42 / 60 is `DATE#2026-09-13` verbatim, and that
# record's night is 2026-09-12 — which is not the coach's coinage but the platform's
# own published label: /api/vitals ships `night_of` = as-of minus one, and served
# `recovery_as_of 2026-09-14 / night_of 2026-09-13 / recovery_pct 63` at the same
# instant. Coach right, cockpit right, and the `published_vitals` stamp right too
# (63.0 as-of 2026-09-14, byte-identical to the cockpit, so the #2575 lag path was
# never even reached). Three correct surfaces and a red gate.
#
# The defect is here: the sentence rule above recognises a date only as an ISO string
# or "Day N". A prose calendar date — the form a narrative coach actually writes, and
# the form `night_of` describes in English — was invisible, so a correctly-dated
# citation was judged as a claim about now. #1985 again: this gate fired on a coach
# doing exactly what ADR-104 asks of it.
#
# Still an EXPLICIT calendar date: a month name with a day number beside it. A bare
# month ("in September") is not enough here — `_HISTORICAL_ANCHOR` already covers the
# adjacent-anchor form of that — and neither are "yesterday" / "last night", which in
# this domain name the CURRENT reading.
#
# `May` is carved out because it is also a modal verb: it needs an ordinal ("May 3rd"),
# a year ("May 3, 2026") or a date preposition ("on May 3") before it counts, so a
# sentence like "that may 3% of the time" cannot launder an undated figure.
_MONTHS_UNAMBIGUOUS = "jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"

_DATED_SENTENCE = re.compile(
    rf"""(?:
          \d{{4}}-\d{{2}}-\d{{2}}                    # an explicit ISO date in the sentence
        | \b(?:on|since)\s+day\s+\d+\b             # "on Day 3"
        | \b(?:{_MONTHS_UNAMBIGUOUS})\.?\s+\d{{1,2}}(?:st|nd|rd|th)?\b   # "September 12th", "Sep 12"
        | \b\d{{1,2}}(?:st|nd|rd|th)?\s+(?:of\s+)?(?:{_MONTHS_UNAMBIGUOUS})\b  # "12 September"
        | \bmay\s+\d{{1,2}}(?:st|nd|rd|th|\s*,\s*\d{{4}})               # "May 3rd", "May 3, 2026"
        | \b(?:on|since)\s+may\s+\d{{1,2}}\b                           # "on May 3"
    )""",
    re.IGNORECASE | re.VERBOSE,
)


def weights_cited_in(prose: str) -> list[float]:
    """Every bodyweight-scale figure asserted **as current** in a blob of prose.

    Figures the prose explicitly anchors to a past point are excluded — see
    `_HISTORICAL_ANCHOR`. A citation is a contradiction only if it presents itself
    as today's number.
    """
    out = []
    # Sentence-scoped first (#2738), so the dated escape hatch stays ONE seam shared
    # with vitals_cited_in; the adjacent-anchor check below is unchanged.
    for text in _sentences(prose):
        if _DATED_SENTENCE.search(text):
            continue
        for m in _WEIGHT_IN_PROSE.finditer(text):
            try:
                v = float(m.group(1))
            except ValueError:
                continue
            if v < _BODYWEIGHT_FLOOR_LBS:
                continue
            if _HISTORICAL_ANCHOR.match(text[m.end() : m.end() + _ANCHOR_WINDOW_CHARS]):
                continue  # dated, therefore not a claim about now
            out.append(v)
    return out


def assess_cross_surface_weight(vitals, coaches, tol: float = CROSS_SURFACE_WEIGHT_TOL_LBS):
    """Every weight a coach asserts must match the cockpit's current weight.

    Returns (ok, message). Absence is a clean pass (ADR-104): a pre-start or
    narrative-less payload has nothing to contradict — silence is not a failure.
    """
    if not isinstance(vitals, dict):
        return True, "no vitals payload — nothing to compare"
    truth = vitals.get("weight_lbs")
    if truth is None:
        return True, "cockpit weight is null (pre-start / no weigh-in) — nothing to compare"
    try:
        truth = float(truth)
    except (TypeError, ValueError):
        return True, f"cockpit weight not numeric ({truth!r}) — skipped"

    disagreements = []
    for c in coaches or []:
        if not isinstance(c, dict):
            continue
        name = c.get("name") or c.get("persona_id") or "coach"
        prose = " ".join(str(c.get(k) or "") for k in _PROSE_FIELDS)
        for cited in weights_cited_in(prose):
            if abs(cited - truth) > tol:
                disagreements.append(f"{name} cites {cited} lb vs cockpit {truth} lb")

    if disagreements:
        return False, "headline weight disagrees across surfaces — " + "; ".join(disagreements[:4])
    return True, f"coach narratives agree with the cockpit weight ({truth} lb)"


# ── #2113: the same cross-surface question, for the vitals coaches actually cite ──
#
# `assess_cross_surface_weight` above measured ONE number. Cycle 12's genesis proved
# that was too narrow: the sleep and training cards published "a recovery score of
# 59% ... and HRV of 42 ms" and "Day one of this experiment ... Your Whoop recovery
# came in at 59%, HRV at 42 ms" while /api/vitals served 44% and 35 ms. The weight
# check was green throughout — the contradiction was in metrics nothing compared, so
# qa-smoke could not see it at all. Same defect, same shape, different column.
#
# Tolerances are per metric because the units are not comparable. Each is set to
# absorb rounding and a same-day re-read, and nothing more — the live gaps were 15
# points of recovery and 7 ms of HRV, an order of magnitude past any of these.
VITALS_TOL = {
    "recovery": 2.0,  # percentage points
    "hrv": 1.5,  # ms
    "rhr": 1.5,  # bpm
    "sleep": 0.3,  # hours
}

# The cockpit field each coach-cited metric is judged against (/api/vitals).
_VITALS_TRUTH_FIELD = {"recovery": "recovery_pct", "hrv": "hrv_ms", "rhr": "rhr_bpm", "sleep": "sleep_hours"}

_VITALS_UNIT = {"recovery": "%", "hrv": " ms", "rhr": " bpm", "sleep": " h"}

# A figure counts only when its OWN metric names it. Recovery is a percentage, but so
# are REM share, deep share and sleep efficiency — all of which appear in the same
# sentence on a real sleep card — so "recovery" (or "readiness") has to be the word
# adjacent to the number, in either order. Bare units are never enough.
_VITALS_PATTERNS = {
    "recovery": (
        re.compile(r"\b(?:recovery|readiness)\b[^.\n;]{0,40}?(\d{1,3}(?:\.\d+)?)\s*(?:%|percent)", re.IGNORECASE),
        re.compile(r"(\d{1,3}(?:\.\d+)?)\s*(?:%|percent)\s*(?:whoop\s+)?(?:recovery|readiness)\b", re.IGNORECASE),
    ),
    "hrv": (
        re.compile(r"\bhrv\b[^.\n;]{0,40}?(\d{1,3}(?:\.\d+)?)\s*(?:ms\b|milliseconds\b)", re.IGNORECASE),
        re.compile(r"(\d{1,3}(?:\.\d+)?)\s*(?:ms\b|milliseconds\b)[^.\n;]{0,20}?\bhrv\b", re.IGNORECASE),
    ),
    "rhr": (
        re.compile(r"\b(?:rhr|resting (?:heart rate|hr|pulse))\b[^.\n;]{0,40}?(\d{2,3}(?:\.\d+)?)\s*(?:bpm\b)?", re.IGNORECASE),
        re.compile(r"(\d{2,3}(?:\.\d+)?)\s*bpm\b[^.\n;]{0,25}?\b(?:rhr|resting)\b", re.IGNORECASE),
    ),
    "sleep": (re.compile(r"\bslept?\b[^.\n;]{0,40}?(\d{1,2}(?:\.\d+)?)\s*(?:h\b|hr\b|hrs\b|hours?\b)", re.IGNORECASE),),
}

# Plausible ranges. A figure outside its metric's real domain is something else that
# happened to sit near the word — a set count, a year, a percentage of a percentage.
_VITALS_DOMAIN = {"recovery": (0, 100), "hrv": (5, 250), "rhr": (30, 120), "sleep": (0, 24)}

# The #1985 lesson, reused rather than re-derived: a gate that fires on correct
# writing teaches people to ignore it. A real card reads "The two targets embedded in
# your plan — RHR 55 bpm and HRV 50 ms — aren't arbitrary numbers", which is honest,
# clearly-labelled goal prose and must never be a finding. Nearest-marker-wins (the
# weight version below) does NOT save it there — the metric word sits closer to the
# number than "targets" does — so the exemption here is SENTENCE-scoped: a figure in
# a sentence that frames targets is not a claim about the current reading.
#
# Deliberately asymmetric. It under-fires on "recovery is 44%, below the 60% target"
# and that is the correct direction to be wrong in: the withheld-facts fix is what
# makes the narrative honest, and this gate exists to catch the class escaping, not
# to be the only thing standing between a reader and a wrong number.
_VITALS_TARGET_SENTENCE = re.compile(
    # Plurals and inflections matter here and the live prose proves it: the card reads
    # "The two TARGETS embedded in your plan", which `\btarget\b` does not match.
    r"\b(targets?|targeting|goals?|aims?|aiming|would put|by month|thresholds?|benchmarks?|ceilings?|floor of)\b",
    re.IGNORECASE,
)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?;…])\s+|\n+")

# #3793: "Sept. 12" is one date, and the splitter above would cut it in half at the
# abbreviation's own period — leaving the day number stranded in the next sentence
# where no date rule can see it. Normalising the period away before splitting keeps
# the abbreviated form working without teaching the splitter every abbreviation in
# English. Narrow by construction: the merge it can cause needs a sentence to END on
# a bare month name AND the next to OPEN on a 1-2 digit number, and the same
# `\b\d{1,2}\b` bound that stops "September 2026" from reading as a date stops that too.
_MONTH_ABBREV_DOT = re.compile(rf"\b({_MONTHS_UNAMBIGUOUS}|may)\.", re.IGNORECASE)


def _sentences(prose: str) -> list[str]:
    """The ONE sentence seam both cited-in readers use. See `_DATED_SENTENCE`.

    #4186: split on an ellipsis (`…`, the single-character form) too — the
    excerpted, ellided form a coach's own prose sample is quoted in
    ("...September 19th … Six days without logs") otherwise reads as ONE
    sentence, and the dated half's `_DATED_SENTENCE` match then silently
    swallows the undated half's numeric claim along with it. The 3-dot ASCII
    form ("...") already splits — it ends in a literal period the pre-existing
    rule already matches — so this only adds the one character that didn't.
    """
    return _SENTENCE_SPLIT.split(_MONTH_ABBREV_DOT.sub(r"\1", prose or ""))


# ── #4180: trend/aggregate language is not a claim about the current reading ──
#
# The specimen (2026-09-25, the sole driver of that night's `qa-smoke-failures`
# ALARM): "His recovery EWMA has climbed from 71.7% to 82.2% over seven days" —
# read, pre-#4180, as a bare claim of 71.7% (the pattern below simply finds the
# FIRST number near the word "recovery") and compared against the cockpit's
# CURRENT reading (99%). The coach was narrating honest smoothed history, not
# today's number — the same #1985 shape as the dated-sentence and
# target-sentence exemptions above: a gate that reddens correct writing trains
# readers to ignore it.
#
# Deliberately loose on "average"/"mean": a false positive here only ever
# WITHHOLDS a figure from the strict `current` comparison — it still gets
# compared, against a served rolling/aggregate fact if the caller has one
# (`classify_claims`'s `trend_end` bucket) — never manufactures a contradiction,
# so the failure direction stays the one #1985/#3793/#4025 already established.
_TREND_SENTENCE = re.compile(
    r"""\b(?:
          ewma
        | rolling
        | trailing
        | average
        | mean
        | over\s+\d+\s+(?:days?|nights?)\b
    )""",
    re.IGNORECASE | re.VERBOSE,
)

# "climbed/rose/fell/dropped ... from X to Y": the trend's two endpoints named in
# one sentence. X is categorically a past point — the same class as a dated
# citation — and Y is the trend's END, the only figure ever a candidate for
# comparison (against a served aggregate, never the raw current reading).
_FROM_TO_NUMBERS = re.compile(r"\bfrom\s+([−-]?\d+(?:\.\d+)?)\b.{0,30}?\bto\s+([−-]?\d+(?:\.\d+)?)\b", re.IGNORECASE)

# Bare keyword (no number) per quantity a from/to trend sentence can name — used
# ONLY to decide which quantity a from-to pair belongs to. Every non-trend
# ("current") figure, and every bare-aggregate trend figure, still goes through
# that quantity's own adjacency-scoped pattern in `patterns`, unchanged.
_QUANTITY_KEYWORD = {
    "recovery": re.compile(r"\b(?:recovery|readiness)\b", re.IGNORECASE),
    "hrv": re.compile(r"\bhrv\b", re.IGNORECASE),
    "rhr": re.compile(r"\b(?:rhr|resting (?:heart rate|hr|pulse))\b", re.IGNORECASE),
    "sleep": re.compile(r"\bslept?\b", re.IGNORECASE),
    "protein": re.compile(r"\b(?:protein|intake)\b", re.IGNORECASE),
}


def _quantity_matches(sentence: str, patterns, lo: float, hi: float) -> list[float]:
    """Every value `patterns` (one quantity's forward/backward regex pair, same
    shape as `_VITALS_PATTERNS`) finds in `sentence`, domain- and anchor-filtered.
    The one number-extraction seam `classify_claims`'s two branches share."""
    out = []
    for pat in patterns:
        for m in pat.finditer(sentence):
            try:
                v = float(m.group(1))
            except (TypeError, ValueError):
                continue
            if not (lo <= v <= hi):
                continue
            if _HISTORICAL_ANCHOR.match(sentence[m.end() : m.end() + _ANCHOR_WINDOW_CHARS]):
                continue  # dated / prior-cycle framing — not a claim about now
            out.append(v)
    return out


def classify_claims(prose: str, patterns: dict, domain: dict):
    """The ONE seam #4180 and #4186 share: every quantity a blob of prose states,
    split three ways so a caller can never mis-compare a figure that was never a
    claim about the present:

      * ``current``     — ``{quantity: [values]}``: a claim about NOW. Compared
        against a live/current fact (e.g. the cockpit's latest reading).
      * ``trend_end``    — ``{quantity: [values]}``: a trend's END point, or a
        bare aggregate's own value ("7-day average recovery is 84%", "protein
        EWMA sits at 154g"). Comparable ONLY to a served rolling/aggregate fact
        — never the raw current reading — and MUST be reported as skipped when
        no such fact is served (#4180's acceptance: a skip is visible, never
        silent).
      * ``trend_start``  — ``[(quantity, value)]``: a trend's START point (the
        "from X" in "climbed from X to Y"). Never comparable to anything — it
        is categorically a past point — and the caller must name it as skipped.

    Sentences an explicit calendar date/day-N/"as of" anchors, or that frame a
    target/goal, are excluded exactly as `vitals_cited_in` always excluded them
    — unchanged and silent, shared via `_sentences`/`_DATED_SENTENCE`/
    `_HISTORICAL_ANCHOR`/`_VITALS_TARGET_SENTENCE` so no two callers can drift
    on what "dated" or "goal-framed" means.

    ``patterns``/``domain`` are keyed the same way `_VITALS_PATTERNS`/
    `_VITALS_DOMAIN` are, so `vitals_cited_in` below is a thin, contract-frozen
    wrapper over this — every existing caller/test is unaffected.
    """
    current: dict[str, list[float]] = {}
    trend_end: dict[str, list[float]] = {}
    trend_start: list[tuple[str, float]] = []

    for sentence in _sentences(prose):
        if _VITALS_TARGET_SENTENCE.search(sentence) or _DATED_SENTENCE.search(sentence):
            continue
        is_trend = bool(_TREND_SENTENCE.search(sentence))
        from_to = _FROM_TO_NUMBERS.search(sentence) if is_trend else None
        for quantity, pats in patterns.items():
            lo, hi = domain[quantity]
            keyword = _QUANTITY_KEYWORD.get(quantity)
            if is_trend and from_to and keyword is not None and keyword.search(sentence):
                start = float(from_to.group(1).replace("−", "-"))
                end = float(from_to.group(2).replace("−", "-"))
                if lo <= start <= hi:
                    trend_start.append((quantity, start))
                if lo <= end <= hi:
                    trend_end.setdefault(quantity, []).append(end)
                continue  # from-to consumed this quantity for this sentence — never double-count
            vals = _quantity_matches(sentence, pats, lo, hi)
            if not vals:
                continue
            (trend_end if is_trend else current).setdefault(quantity, []).extend(vals)
    return current, trend_end, trend_start


def vitals_cited_in(prose: str) -> dict:
    """Every vital a blob of prose asserts **as a current reading**, by metric.

    Returns ``{metric: [values]}``. Excluded, by design: figures the prose anchors to
    a past point (`_HISTORICAL_ANCHOR`, shared with the weight assessor so the dated
    escape hatch is ONE seam), figures in a sentence that frames a target or goal,
    figures outside the metric's real domain, and — since #4180 — a trend/aggregate
    sentence's figures (its own `classify_claims` bucket; see `assess_cross_surface_vitals`
    for where those are compared instead, and named when they can't be).
    """
    current, _trend_end, _trend_start = classify_claims(prose or "", _VITALS_PATTERNS, _VITALS_DOMAIN)
    return current


# ── #2575: a FROZEN artifact vs a LIVE surface is not a comparison ──────────────
#
# #2583 fixed the real two-producer defect. What survived it was measured on
# 2026-08-12 and is the check's own: the coach narrative is frozen at ~17:0xZ, the
# cockpit is read hours later, and `vitals_resolver` serves the latest **FINALIZED**
# whoop morning — a record that is routinely unscored at 17:00Z and scored by
# midnight. Measured: coach cited recovery 54 / HRV 41.1 / RHR 56 (DATE#2026-08-11,
# the newest finalized reading at 17:02:59Z); the cockpit now serves 30 / 30.9 / 60
# (DATE#2026-08-12, finalized later). Neither surface was ever wrong. As written the
# check could not pass on any day a recovery finalizes after the brief — most days —
# and a gate that fires on correct output is a gate people learn to ignore (#1985).
#
# The fix is NOT a wider tolerance. Widening would blind the check to exactly the
# 8-point recovery gap #2575 was opened for. Instead the coach record now carries
# `published_vitals` (coach/published_vitals.py) — the Spine's own answer at the
# instant the narrative shipped — and a coach's prose is judged against THAT when the
# only thing separating the two surfaces is the finalization window.
#
# Bounded, so it cannot become an escape hatch:
#   * the stamp is used ONLY when it is STRICTLY OLDER than the cockpit's reading
#     (same as-of ⇒ nothing to reconcile ⇒ the cockpit stays the judge, so on any day
#     the coach speaks after finalization this is byte-for-byte the old behaviour);
#   * and no more than VITALS_ASOF_MAX_LAG_DAYS behind it. One morning is the whole
#     legitimate gap. Two is a coach reading a different, lagging producer — the
#     original #2575 defect — and that still FAILs against the cockpit;
#   * an unstamped coach is judged against the cockpit exactly as before, so the check
#     can never go dark by a stamp failing to be written.
VITALS_ASOF_MAX_LAG_DAYS = 1

# The stamp field each metric's value and provenance date live under. recovery/HRV/RHR
# share one date — they are three columns of ONE whoop morning (#1369).
_STAMP_VALUE_FIELD = {"recovery": "recovery_pct", "hrv": "hrv_ms", "rhr": "rhr_bpm", "sleep": "sleep_hours"}
_STAMP_ASOF_FIELD = {"recovery": "recovery_as_of", "hrv": "recovery_as_of", "rhr": "recovery_as_of", "sleep": "sleep_as_of"}


def _iso_day(value):
    """``date`` from a YYYY-MM-DD(-ish) string, or None. No clock is read."""
    try:
        return _date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def publication_baseline(vitals, coach, metric):
    """What ``metric`` should be judged against for this coach: (value, provenance).

    Returns ``(None, None)`` when the cockpit has no reading for the metric. Otherwise
    the cockpit's value, unless the coach carries a `published_vitals` stamp that is
    strictly older than the cockpit's reading and within VITALS_ASOF_MAX_LAG_DAYS of it
    — the finalization window — in which case the frozen value it shipped with wins.
    """
    field = _VITALS_TRUTH_FIELD[metric]
    try:
        live = float(vitals.get(field))
    except (TypeError, ValueError):
        return None, None

    stamp = (coach or {}).get("published_vitals")
    if not isinstance(stamp, dict):
        return live, "cockpit"
    date_key = _STAMP_ASOF_FIELD[metric]
    stamped_day, live_day = _iso_day(stamp.get(date_key)), _iso_day(vitals.get(date_key))
    if stamped_day is None or live_day is None or not (0 < (live_day - stamped_day).days <= VITALS_ASOF_MAX_LAG_DAYS):
        return live, "cockpit"  # same morning, ahead of the cockpit, or too far behind it
    try:
        return float(stamp[_STAMP_VALUE_FIELD[metric]]), f"as published {stamped_day.isoformat()}"
    except (KeyError, TypeError, ValueError):
        return live, "cockpit"


# ── #4025: a coach narrating a PAST reading BY DATE is not a currency claim ─────
#
# The live specimen: the "mind" coach's prose ties its number to a day — "the 97%
# recovery reading on September 18th" — while `publication_baseline` (above) judges
# every citation against the reading the CURRENT surface was published against. The
# stamp and the cockpit agreed (both 90%); the coach was simply, correctly, telling
# a story about yesterday. `_HISTORICAL_ANCHOR`/`_DATED_SENTENCE` already exempt a
# figure that anchors itself with a WORD ("as of", "on Day N") — this is the same
# idea for a figure that anchors itself with an actual CALENDAR DATE the platform can
# check: a citation that disagrees with today's baseline but matches some OTHER day's
# real Whoop reading in the trailing week is a dated citation, not a contradiction.
#
# Bounded on purpose, same shape as the `_HISTORICAL_ANCHOR` exemption above:
#   * only the trailing 7 days (from the cockpit's OWN as-of date for that metric,
#     never a wall-clock read — this function stays pure) are eligible, so a coach
#     citing a months-old number still fails exactly as before (the #2113 shape:
#     a pre-genesis 59% is not "dated", it's stale and uncited);
#   * a metric with no history entry in the window is left to the existing strict
#     compare — the exemption can only ever narrow a fail into a pass on a REAL
#     matching day, never widen what counts as agreement;
#   * `history=None` (the caller could not resolve it — e.g. the Whoop partition
#     read failed) disables the exemption entirely rather than defaulting it open,
#     and the returned message says so — absence of history is never a silent pass.
_WHOOP_HISTORY_FIELD = {"recovery": "recovery_score", "hrv": "hrv", "rhr": "resting_heart_rate", "sleep": "sleep_duration_hours"}

# How many trailing days a dated citation may reach back and still count — the #4025
# specimen matched 1 day back; #2113's stale 59% is ~30+ days back, well outside it.
DATED_CITATION_WINDOW_DAYS = 7


def _match_dated_history(day_values: dict, cited: float, tol: float, anchor) -> str | None:
    """The most recent day in `day_values` within the trailing window of `anchor`
    whose reading is within `tol` of `cited`, or None if none matches.

    `day_values` is ``{"YYYY-MM-DD": value}`` for one metric. `anchor` is a `date` (the
    cockpit's own as-of day for that metric) or None — no anchor means no window, so
    nothing can match (never treat a missing anchor as an unbounded lookback).
    """
    if not day_values or anchor is None:
        return None
    window_start = anchor - _timedelta(days=DATED_CITATION_WINDOW_DAYS - 1)
    matches = []
    for day_str, value in day_values.items():
        day = _iso_day(day_str)
        if day is None or not (window_start <= day <= anchor):
            continue
        try:
            v = float(value)
        except (TypeError, ValueError):
            continue
        if abs(cited - v) <= tol:
            matches.append(day)
    return max(matches).isoformat() if matches else None


def resolve_vitals_history(table, days: int = 14) -> dict | None:
    """Trailing `days` of Whoop readings, keyed `{metric: {"YYYY-MM-DD": value}}`.

    Read-only, key-bounded (one query, <= `days` rows, no scan). Fail-soft by design,
    matching `checks()`'s own network handling: a transient DDB error (or `table`
    being unavailable) returns None rather than raising, which degrades the vitals
    gate to its pre-#4025 strict behaviour instead of reddening the whole nightly
    over a read the gate can run perfectly well without.
    """
    if table is None:
        return None
    try:
        from boto3.dynamodb.conditions import Key
        from common.pacific_time import pacific_today, shift_day_key

        end = pacific_today()
        start = shift_day_key(end, -(days - 1))
        resp = table.query(
            KeyConditionExpression=Key("pk").eq("USER#matthew#SOURCE#whoop") & Key("sk").between(f"DATE#{start}", f"DATE#{end}~"),
        )
        items = resp.get("Items", [])
    except Exception:
        return None

    history: dict = {m: {} for m in _WHOOP_HISTORY_FIELD}
    for item in items:
        sk = str(item.get("sk", ""))
        if not sk.startswith("DATE#") or "#WORKOUT#" in sk:
            continue
        day = sk[len("DATE#") :]
        for metric, field in _WHOOP_HISTORY_FIELD.items():
            raw = item.get(field)
            if raw is None:
                continue
            try:
                history[metric][day] = float(raw)
            except (TypeError, ValueError):
                continue
    return history


def assess_cross_surface_vitals(vitals, coaches, tol: dict | None = None, history: dict | None = None):
    """Every recovery / HRV / resting-HR / sleep figure a coach asserts as current
    must match the reading that surface was published against.

    `history` (optional): ``{metric: {"YYYY-MM-DD": value}}`` per-day Whoop readings
    — see `resolve_vitals_history`. A citation that disagrees with the publication
    baseline but matches a real day's reading in the trailing
    `DATED_CITATION_WINDOW_DAYS` is reported as a dated citation instead of failing
    (#4025). `history=None` keeps the strict pre-#4025 behaviour and the message says
    so explicitly — omitting history is never a silent pass.

    #4180: a trend/aggregate sentence's figures (`classify_claims`'s `trend_end` /
    `trend_start` buckets) are never judged against the cockpit's raw current
    reading. A trend's START value is categorically a past point and is always
    skipped; its END value is compared against a served `{metric}_ewma` cockpit
    field IF ONE EXISTS (none is served today — this is forward-compatible, not
    a live comparison yet), otherwise skipped too. Every skip is named in the
    message so it is visible, never silent.

    Returns (ok, message). Absence is a clean pass (ADR-104) on BOTH sides: a null
    cockpit field has nothing to contradict, and a coach that cites nothing is silent,
    not wrong. Pure — no network, no clock — so the rule is unit-testable offline.
    """
    if not isinstance(vitals, dict):
        return True, "no vitals payload — nothing to compare"
    tol = tol or VITALS_TOL
    history = history if isinstance(history, dict) else None

    truth = {}
    for metric, field in _VITALS_TRUTH_FIELD.items():
        raw = vitals.get(field)
        if raw is None:
            continue
        try:
            truth[metric] = float(raw)
        except (TypeError, ValueError):
            continue
    if not truth:
        return True, "cockpit vitals are all null (pre-start / no readings) — nothing to compare"

    disagreements = []
    dated_matches = []
    skipped = []
    for c in coaches or []:
        if not isinstance(c, dict):
            continue
        name = c.get("name") or c.get("persona_id") or "coach"
        prose = " ".join(str(c.get(k) or "") for k in _PROSE_FIELDS)
        # `current` comes from `vitals_cited_in` (the frozen, current-only contract
        # every pre-#4180 caller/test already relies on) rather than re-deriving it
        # from `classify_claims`'s own `current` bucket — the two are byte-identical
        # (`vitals_cited_in` is a thin wrapper over `classify_claims`), but routing
        # through the named wrapper keeps it a live, exercised production caller
        # instead of a def nothing but a unit test ever reaches.
        current = vitals_cited_in(prose)
        _, trend_end, trend_start = classify_claims(prose, _VITALS_PATTERNS, _VITALS_DOMAIN)

        for metric, cited in trend_start:
            if metric not in truth:
                continue
            unit = _VITALS_UNIT[metric]
            skipped.append(
                f"{name} cites {metric} {cited:g}{unit} as a trend's START point — a past point by "
                "definition, never a claim about now, skipped (#4180)"
            )

        for metric, values in trend_end.items():
            if metric not in truth:
                continue
            unit = _VITALS_UNIT[metric]
            served_ewma = vitals.get(f"{metric}_ewma")
            served_ewma_f = None
            if served_ewma is not None:
                try:
                    served_ewma_f = float(served_ewma)
                except (TypeError, ValueError):
                    served_ewma_f = None
            for cited in values:
                if served_ewma_f is None:
                    skipped.append(
                        f"{name} cites {metric} {cited:g}{unit} as a trend/aggregate (EWMA/rolling/average) — "
                        "no served EWMA figure to compare against, skipped (#4180)"
                    )
                    continue
                if abs(cited - served_ewma_f) > tol[metric]:
                    disagreements.append(f"{name} cites {metric} trend/aggregate {cited:g}{unit} vs served EWMA {served_ewma_f:g}{unit}")

        for metric, values in current.items():
            if metric not in truth:
                continue
            unit = _VITALS_UNIT[metric]
            baseline, provenance = publication_baseline(vitals, c, metric)
            if baseline is None:
                continue
            for cited in values:
                if abs(cited - baseline) <= tol[metric]:
                    continue  # agrees with the reading it was published against
                matched_day = None
                if history is not None:
                    anchor = _iso_day(vitals.get(_STAMP_ASOF_FIELD[metric]))
                    matched_day = _match_dated_history(history.get(metric) or {}, cited, tol[metric], anchor)
                if matched_day:
                    dated_matches.append(f"{name} cites {metric} {cited:g}{unit} — dated citation (matched {matched_day})")
                else:
                    disagreements.append(f"{name} cites {metric} {cited:g}{unit} vs {provenance} {baseline:g}{unit}")

    no_history_note = " (no per-day history supplied — dated citations judged strictly)" if history is None else ""
    skipped_note = " — skipped (trend/aggregate): " + "; ".join(sorted(set(skipped))[:4]) if skipped else ""

    if disagreements:
        return (
            False,
            "coach-cited vitals disagree with the reading they were published against — "
            + "; ".join(sorted(set(disagreements))[:4])
            + no_history_note
            + skipped_note,
        )

    base = "coach narratives agree with the cockpit vitals (" + ", ".join(f"{k} {v:g}" for k, v in sorted(truth.items())) + ")"
    if dated_matches:
        base += " — " + "; ".join(sorted(set(dated_matches)))
    else:
        base += no_history_note
    base += skipped_note
    return True, base


# ── #3451: the OTHER cross-surface question — same night, different DEVICE ─────
#
# The live specimen: home vitals served 6.8h (Whoop, the #1369 Truth Spine SoT)
# while the /sleep hero served 1.1h (Eight Sleep's `total_sleep_hours`, a
# mattress-partial night) for the same night — no label on either figure. #2921
# already sanctioned dual numbers from two devices (a "correction" would be
# false precision neither sensor actually has); what it did NOT sanction was
# publishing the disagreement silently. Its closing rule — "saying so, every
# time" — is what this checks, not the arithmetic.
#
# Deliberately NOT judging the two devices against each other for accuracy: a
# real divergence is expected and fine. The only failure mode this catches is
# the API forgetting to disclose it — `figure_scope.total_sleep_hours_source`
# already ships unconditionally as of the #3451 fix, so this is a regression
# guard, not a live gap.
CROSS_SURFACE_SLEEP_DISCLOSURE_TOL_HRS = 0.5


def assess_cross_surface_sleep_disclosure(vitals, sleep_detail, tol: float = CROSS_SURFACE_SLEEP_DISCLOSURE_TOL_HRS):
    """Home vitals' Whoop-SoT sleep figure vs the /sleep hero's Eight Sleep figure.

    Returns (ok, message). A close agreement needs no disclosure (nothing to
    reconcile). A real divergence is fine TOO, as long as `sleep_detail` names
    the device its figure came from (`figure_scope.total_sleep_hours_source`) —
    only an undisclosed divergence fails. Absence on either side is a clean pass
    (ADR-104): no reading, nothing to compare.
    """
    if not isinstance(vitals, dict) or not isinstance(sleep_detail, dict):
        return True, "no payload — nothing to compare"
    home = vitals.get("sleep_hours")
    hero = sleep_detail.get("total_sleep_hours")
    if home is None or hero is None:
        return True, "home vitals or /sleep hero sleep figure is null — nothing to compare"
    try:
        home, hero = float(home), float(hero)
    except (TypeError, ValueError):
        return True, f"sleep figures not numeric (home={home!r}, hero={hero!r}) — skipped"

    diff = abs(home - hero)
    if diff <= tol:
        return True, f"home vitals ({home:g}h) and the /sleep hero ({hero:g}h) agree within {tol}h"

    source = (sleep_detail.get("figure_scope") or {}).get("total_sleep_hours_source")
    if source:
        return True, (
            f"home vitals ({home:g}h, Whoop) and the /sleep hero ({hero:g}h, {source}) diverge by "
            f"{diff:g}h but the hero discloses its device (#2921) — two sensors, not a contradiction"
        )
    return False, (
        f"home vitals ({home:g}h) and the /sleep hero ({hero:g}h) diverge by {diff:g}h with NO device "
        f"disclosure on the hero payload — a reader can't tell these are two different sensors, not one "
        f"surface correcting the other (#3451)"
    )


# ── #4186: coach-to-coach and coach-to-engine agreement on ONE served page ─────
#
# `assess_cross_surface_weight`/`assess_cross_surface_vitals` above each diff every
# coach against ONE truth (the cockpit). Neither compares coaches to EACH OTHER, and
# neither reaches nutrition or the loss rate at all. Measured live 2026-09-25 (Session
# AV B3 audit): the dashboard served protein as 106.9g / 141g / 154g and the loss rate
# as 3.7 and -4.4 lb/wk on ONE page, and `cross_surface:*` stayed green throughout —
# while the same leg went red on a TREND sentence (#4180) the same night. The
# instrument was firing on the wrong class.
#
# Both legs below reuse `classify_claims` (#4180) so a trend's start, or any
# dated/target-framed figure, is skipped and named exactly as it is for vitals —
# never mis-compared here either.

# Quantity domains + patterns beyond the vitals four. Protein/rate/days-logged use
# their own extraction (rate needs signed-number parsing `classify_claims`'s shared
# regex shape doesn't carry; days-logged/log-gap are two DIFFERENT questions — see
# `_days_and_gap_claims` — so neither fits the quantity-pattern shape either).
_PROTEIN_PATTERNS = (
    # "his average intake has dropped to 106.9 grams", "protein EWMA sits at 154g"
    re.compile(r"\b(?:protein|intake)\b[^.\n;]{0,40}?(\d{1,3}(?:\.\d+)?)\s*(?:g\b|grams?\b)", re.IGNORECASE),
    re.compile(r"(\d{1,3}(?:\.\d+)?)\s*(?:g\b|grams?\b)[^.\n;]{0,30}?\b(?:protein|intake)\b", re.IGNORECASE),
)
_PROTEIN_DOMAIN = (0.0, 400.0)

# The quantities `coach_quantity_claims` extracts via `classify_claims` — the vitals
# four plus protein. `weight`/`rate`/`days_logged`/`log_gap_days` are appended
# separately below (see `coach_quantity_claims`) because none of them fits this
# adjacency-scoped, unsigned, single-capture-group shape.
_CLAIM_PATTERNS = {**_VITALS_PATTERNS, "protein": _PROTEIN_PATTERNS}
_CLAIM_DOMAIN = {**_VITALS_DOMAIN, "protein": _PROTEIN_DOMAIN}

# The unit each quantity is rendered with in a check's detail line.
_CLAIM_UNIT = {
    "recovery": "%",
    "hrv": " ms",
    "rhr": " bpm",
    "sleep": " h",
    "protein": "g",
    "weight": " lb",
    "rate": " lb/wk",
    "days_logged": "d",
    "log_gap_days": "d",
}

# "3.7 pounds per week", "−4.4 lb/week" — the loss-rate figure a coach states in
# plain prose. Unicode minus (−, U+2212) travels through some renderers instead
# of an ASCII hyphen, so both are accepted (see `_parse_signed`).
_RATE_PATTERNS = (re.compile(r"([−-]?\d+(?:\.\d+)?)\s*(?:lbs?|pounds?)\s*(?:per|/)\s*(?:week|wk)\b", re.IGNORECASE),)
_RATE_DOMAIN = (-20.0, 20.0)


def _parse_signed(token: str) -> float:
    """A number that may carry a Unicode minus (−) instead of a hyphen."""
    return float(token.replace("−", "-"))


def _rate_claims(prose: str) -> list[float]:
    """Every loss-rate figure (lb/week, signed or not) `prose` states as current.
    Dated/target-framed sentences are excluded — the same rule every other
    extractor here uses (`_sentences`/`_DATED_SENTENCE`/`_VITALS_TARGET_SENTENCE`)."""
    out = []
    for sentence in _sentences(prose):
        if _VITALS_TARGET_SENTENCE.search(sentence) or _DATED_SENTENCE.search(sentence):
            continue
        for pat in _RATE_PATTERNS:
            for m in pat.finditer(sentence):
                try:
                    v = _parse_signed(m.group(1))
                except ValueError:
                    continue
                if _RATE_DOMAIN[0] <= v <= _RATE_DOMAIN[1]:
                    out.append(v)
    return out


# "14 logged days", "from 19 logged days" (a POSITIVE claim: this many days carry a
# log) vs "six days without logs", "the log went dark ... six days" (a GAP claim:
# this many days carry NO log — the engine's own `lag_days`, not its `days_logged`).
# Two different engine facts, so two different quantities — conflating them would
# compare a coach's "20 good days" against the engine's "0 days since the last one"
# and call it a match. Small English number-words are accepted because the live
# specimen ("Six days without logs") spells it out rather than using a digit.
_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
    "eighteen": 18, "nineteen": 19, "twenty": 20,
}  # fmt: skip
_NUM_TOKEN = r"(?:\d{1,3}|" + "|".join(_NUMBER_WORDS) + r")"
_DAYS_LOGGED_PATTERN = re.compile(rf"\b({_NUM_TOKEN})\s+logged\s+days?\b", re.IGNORECASE)
_LOG_GAP_PATTERN = re.compile(
    rf"\b({_NUM_TOKEN})\s+days?\s+(?:without\s+(?:a\s+)?logs?|dark|since\s+(?:a|the\s+last)\s+log)\b", re.IGNORECASE
)


def _num_token(token: str) -> float:
    try:
        return float(token)
    except ValueError:
        return float(_NUMBER_WORDS.get(token.lower(), float("nan")))


def _days_and_gap_claims(prose: str) -> list[tuple[str, float]]:
    """``[("days_logged"|"log_gap_days", value)]`` — see the module comment above
    for why these are two quantities, never one."""
    out = []
    for sentence in _sentences(prose):
        if _VITALS_TARGET_SENTENCE.search(sentence) or _DATED_SENTENCE.search(sentence):
            continue
        for m in _DAYS_LOGGED_PATTERN.finditer(sentence):
            v = _num_token(m.group(1))
            if 0 <= v <= 60:
                out.append(("days_logged", v))
        for m in _LOG_GAP_PATTERN.finditer(sentence):
            v = _num_token(m.group(1))
            if 0 <= v <= 60:
                out.append(("log_gap_days", v))
    return out


def coach_quantity_claims(coach: dict) -> dict:
    """Every numeric claim one coach's served prose makes, by quantity.

    Returns ``{quantity: [(value, "current"|"trend_end")]}`` — reuses #4180's
    `classify_claims` for the vitals four + protein (so a trend's start, or a
    dated/target-framed figure, is never in here at all — see that function's
    docstring), and appends weight/rate/days-logged/log-gap via their own
    extractors, all tagged ``"current"`` (none of the four fixtures behind
    #4186 need trend detection on those quantities).
    """
    prose = " ".join(str(coach.get(k) or "") for k in _PROSE_FIELDS)
    current, trend_end, _trend_start = classify_claims(prose, _CLAIM_PATTERNS, _CLAIM_DOMAIN)
    out: dict[str, list[tuple[float, str]]] = {}
    for quantity, values in current.items():
        out.setdefault(quantity, []).extend((v, "current") for v in values)
    for quantity, values in trend_end.items():
        out.setdefault(quantity, []).extend((v, "trend_end") for v in values)
    for v in weights_cited_in(prose):
        out.setdefault("weight", []).append((v, "current"))
    for v in _rate_claims(prose):
        out.setdefault("rate", []).append((v, "current"))
    for quantity, v in _days_and_gap_claims(prose):
        out.setdefault(quantity, []).append((v, "current"))
    return out


# Default tolerances for a quantity the engine may not always serve a CI for.
# `recovery`/`hrv`/`rhr`/`sleep` reuse `VITALS_TOL` (#2113 above) unchanged — same
# quantity, same reason, one number. `rate`'s tolerance is derived from the engine's
# own CI at call time (`_rate_tolerance`) and is never read from this dict.
COACH_CONSISTENCY_TOL: dict = {
    **VITALS_TOL,
    # g — rounding + ordinary day-to-day meal-logging variance. The live 2026-09-25
    # gap (106.9 vs 154, a 47g spread) sits more than 3x past this; an honest
    # same-window rounding difference does not.
    "protein": 15.0,
    "weight": CROSS_SURFACE_WEIGHT_TOL_LBS,
    # days — each coach names its OWN trailing window ("the last N logged days")
    # independently, and those windows commonly differ by nearly a week without
    # either coach being wrong about any single day's log status. A same-day
    # disagreement about whether logging has STOPPED is `log_gap_days`, below,
    # which stays tight because that is a same-day factual claim, not a window.
    "days_logged": 5.0,
    # days — a coach narrating "the log went dark" / "N days without logs" is
    # making a claim about right now, directly checkable against the engine's own
    # `lag_days` — no window latitude belongs here.
    "log_gap_days": 2.0,
    "rate": None,
}


def _rate_tolerance(rate_ci: tuple | None) -> float:
    """The loss-rate tolerance: half the engine's own CI width when the engine
    serves one (`journey.weekly_rate_ci_low/high`), per #4186's acceptance
    ("tolerance derived from the engine's own CI... where one is served").
    Falls back to a documented default when no CI is available: a coach's own
    rounding of the rate to one decimal place is the only source of disagreement
    the fallback needs to absorb.
    """
    if rate_ci and rate_ci[0] is not None and rate_ci[1] is not None:
        return abs(float(rate_ci[1]) - float(rate_ci[0])) / 2.0
    return 1.0


# #4186's chosen rule for `rate`, stated once here rather than at each call site:
# coach prose states the loss rate in plain, usually-unsigned terms ("3.7 pounds
# per week"), while the engine's `weekly_rate_lbs` is SIGNED negative-for-loss.
# Requiring sign agreement would fail ordinary correct writing ("losing 3.7
# lb/week") — the exact #1985 anti-pattern this whole file exists to avoid — so
# every rate comparison here is by MAGNITUDE. The documented limit: a coach who
# reports a rate of GAIN using the same unsigned phrasing a loss would use is
# invisible to this rule; nothing here reads direction, only size.
def _rate_value(v: float) -> float:
    return abs(v)


def _claims_by_quantity(coaches) -> tuple[dict, int]:
    """``({quantity: [(value, cls, coach_name)]}, skipped_count)`` across every
    served coach — `skipped_count` is `classify_claims`'s `trend_start` figures,
    which never reach `coach_quantity_claims`'s return at all (they are never a
    claim about anything comparable — see `classify_claims`) and so would
    otherwise vanish from both legs' emitted counts."""
    out: dict = {}
    skipped = 0
    for c in coaches or []:
        if not isinstance(c, dict):
            continue
        name = c.get("name") or c.get("persona_id") or "coach"
        for quantity, entries in coach_quantity_claims(c).items():
            for value, cls in entries:
                out.setdefault(quantity, []).append((value, cls, name))
        prose = " ".join(str(c.get(k) or "") for k in _PROSE_FIELDS)
        _cur, _te, trend_start = classify_claims(prose, _CLAIM_PATTERNS, _CLAIM_DOMAIN)
        skipped += len(trend_start)
    return out, skipped


def assess_cross_surface_coach_consistency(coaches, rate_ci: tuple | None = None):
    """Two coach texts served on ONE page must not state the same quantity with
    different values — protein, weight, loss rate, recovery, HRV, RHR, sleep
    hours, days logged (#4186).

    The rule: two `current`/`trend_end` claims for the SAME quantity from
    DIFFERENT coaches are compared unconditionally, beyond the quantity's own
    tolerance (`COACH_CONSISTENCY_TOL`) — a differently-named window is NOT an
    excuse (the live specimen: 106.9g matches no served field for ANY window, so
    "the coaches meant different spans" cannot be the answer). The one exception
    is `rate`, judged by magnitude (see `_rate_value`) — a signed/unsigned
    mismatch is not a content disagreement. A `trend_start` figure never reaches
    here at all (see `classify_claims`) — it is not a claim, so it cannot
    disagree with one.

    Returns (ok, message) — the message ALWAYS carries the claim count (extracted
    / compared / skipped), pass or fail, per #4186's dead-man requirement.
    """
    claims, trend_start_skipped = _claims_by_quantity(coaches)
    extracted = sum(len(v) for v in claims.values()) + trend_start_skipped
    disagreements = []
    compared = 0
    for quantity, entries in claims.items():
        tol = _rate_tolerance(rate_ci) if quantity == "rate" else COACH_CONSISTENCY_TOL.get(quantity)
        if tol is None:
            continue
        for i in range(len(entries)):
            for j in range(i + 1, len(entries)):
                v1, _c1, n1 = entries[i]
                v2, _c2, n2 = entries[j]
                if n1 == n2:
                    continue  # the same coach citing itself twice is not a disagreement
                compared += 1
                a, b = (_rate_value(v1), _rate_value(v2)) if quantity == "rate" else (v1, v2)
                if abs(a - b) > tol:
                    unit = _CLAIM_UNIT.get(quantity, "")
                    disagreements.append(f"{quantity}: {n1} cites {v1:g}{unit} vs {n2} cites {v2:g}{unit}")

    note = f" (claims: {extracted} extracted, {compared} compared, {trend_start_skipped} skipped as trend-start)"
    if disagreements:
        return False, "coach texts disagree with each other — " + "; ".join(sorted(set(disagreements))[:6]) + note
    return True, "coach texts agree with each other on every shared quantity" + note


def assess_cross_surface_coach_vs_engine(coaches, nutrition=None, journey=None):
    """Every protein / loss-rate / log-gap figure a coach states must agree with
    the engine's own served fact for the window the sentence names (#4186) —
    `nutrition_overview`'s `avg_protein_g`/`lag_days`, `journey`'s
    `weekly_rate_lbs` + its CI.

    `days_logged` (a coach's "N logged days") is deliberately NOT checked here,
    only in `assess_cross_surface_coach_consistency` — documented limit: a
    coach's stated day-count is ambiguous between "the trailing window my
    average was computed over" and "the total days logged this cycle", and only
    the second reading is comparable to `nutrition_overview.days_logged`
    (`len(items)` over ITS OWN query window, not necessarily the coach's). Two
    coaches both using the first reading with different window sizes is not an
    engine disagreement; `log_gap_days` carries no such ambiguity (a claimed
    logging GAP is a same-day fact, checked against `lag_days` below) and stays.

    Reuses the SAME classifier as `assess_cross_surface_coach_consistency` (a
    `trend_end` figure — an EWMA/rolling protein claim — is judged against the
    engine's own served average exactly like a `current` one, because
    `avg_protein_g` already IS the engine's rolling/aggregate figure; a
    `trend_start` never reaches here).

    Returns (ok, message) — always carries the claim count, per #4186's
    dead-man requirement.
    """
    claims, trend_start_skipped = _claims_by_quantity(coaches)
    extracted = sum(len(v) for v in claims.values()) + trend_start_skipped

    engine_facts: dict = {}
    if isinstance(nutrition, dict):
        if nutrition.get("avg_protein_g") is not None:
            engine_facts["protein"] = nutrition["avg_protein_g"]
        if nutrition.get("lag_days") is not None:
            engine_facts["log_gap_days"] = nutrition["lag_days"]
    rate_ci = None
    if isinstance(journey, dict) and journey.get("weekly_rate_lbs") is not None:
        engine_facts["rate"] = journey["weekly_rate_lbs"]
        lo, hi = journey.get("weekly_rate_ci_low"), journey.get("weekly_rate_ci_high")
        if lo is not None and hi is not None:
            rate_ci = (lo, hi)

    disagreements = []
    compared = 0
    for quantity, entries in claims.items():
        truth = engine_facts.get(quantity)
        if truth is None:
            continue
        try:
            truth = float(truth)
        except (TypeError, ValueError):
            continue
        tol = _rate_tolerance(rate_ci) if quantity == "rate" else COACH_CONSISTENCY_TOL.get(quantity)
        if tol is None:
            continue
        for value, _cls, name in entries:
            compared += 1
            a, b = (_rate_value(value), _rate_value(truth)) if quantity == "rate" else (value, truth)
            if abs(a - b) > tol:
                unit = _CLAIM_UNIT.get(quantity, "")
                disagreements.append(f"{quantity}: {name} cites {value:g}{unit} vs engine {truth:g}{unit}")

    no_field = extracted - compared - trend_start_skipped
    note = (
        f" (claims: {extracted} extracted, {compared} compared, "
        f"{trend_start_skipped} skipped as trend-start, {no_field} skipped — no served engine field for that quantity)"
    )
    if disagreements:
        return False, "coach text disagrees with the engine's own served fact — " + "; ".join(sorted(set(disagreements))[:6]) + note
    return True, "coach texts agree with the engine's own served facts" + note


def checks(check_cls, site_base_url, partition, timeout=15, table=None):
    """The qa_smoke-facing entrypoint: fetch both surfaces and return [Check].

    `check_cls` is injected rather than imported so this module stays a leaf —
    qa_smoke_lambda imports us, never the reverse. Fail-soft on fetch, matching
    check_hero_weight_arithmetic: a network blip must never red the nightly.

    `partition` (#1921) is likewise injected, not defaulted: this module cannot
    import qa_smoke_lambda's PARTITIONS, and a literal here would be a second
    copy of that vocabulary free to drift. The caller decides — and because the
    parameter is required, a Check built here can never slip through
    unpartitioned.

    `table` (#4025, optional): the caller's already-instantiated DDB Table resource
    (the same one qa_smoke_lambda reads elsewhere) — reused here, read-only, to
    resolve the trailing Whoop history `assess_cross_surface_vitals` judges a dated
    citation against. Omitted or erroring resolves to `history=None`, which is the
    documented strict fallback, never a silent skip of the whole check.
    """
    import json
    import urllib.request

    check = check_cls("cross_surface:weight", "Reader Truth", partition)
    # #2113: the vitals leg rides the SAME fetch — one pair of requests, two Checks.
    # Reported separately so a recovery/HRV contradiction is named as one, rather
    # than folded into a check whose title says "weight".
    vitals_check = check_cls("cross_surface:vitals", "Reader Truth", partition)
    # #3451: a third leg, a third surface (/api/sleep_detail) — fetched
    # independently below so a /sleep-only outage never blanks the weight/vitals
    # legs, and vice versa.
    sleep_check = check_cls("cross_surface:sleep_disclosure", "Reader Truth", partition)
    # #4186: two more legs riding the SAME coaching-dashboard fetch, plus two new
    # surfaces (nutrition_overview / journey) fetched independently below so their
    # absence never blanks anything the weight/vitals/sleep legs already cover.
    consistency_check = check_cls("cross_surface:coach_consistency", "Reader Truth", partition)
    vs_engine_check = check_cls("cross_surface:coach_vs_engine", "Reader Truth", partition)

    payloads, fetch_errors = {}, {}
    for path in ("/api/vitals", "/api/coaching-dashboard", "/api/sleep_detail", "/api/nutrition_overview", "/api/journey"):
        try:
            req = urllib.request.Request(site_base_url + path, headers={"User-Agent": "life-platform-qa-smoke"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                payloads[path] = json.loads(r.read().decode("utf-8", "replace"))
        except Exception as e:
            fetch_errors[path] = str(e)[:120]

    if "/api/vitals" in fetch_errors or "/api/coaching-dashboard" in fetch_errors:
        msg = "cross-surface fetch failed (fail-soft): " + "; ".join(
            f"{p} — {e}" for p, e in fetch_errors.items() if p in ("/api/vitals", "/api/coaching-dashboard")
        )
        weight_vitals_checks = [check.warn(msg), vitals_check.warn(msg)]
    else:
        served_vitals = payloads.get("/api/vitals", {}).get("vitals", {})
        served_coaches = payloads.get("/api/coaching-dashboard", {}).get("coaches", [])
        ok, msg = assess_cross_surface_weight(served_vitals, served_coaches)
        v_ok, v_msg = assess_cross_surface_vitals(served_vitals, served_coaches, history=resolve_vitals_history(table))
        weight_vitals_checks = [
            check.ok(msg) if ok else check.fail(msg),
            vitals_check.ok(v_msg) if v_ok else vitals_check.fail(v_msg),
        ]

    if "/api/coaching-dashboard" in fetch_errors:
        msg = f"cross-surface fetch failed (fail-soft): /api/coaching-dashboard — {fetch_errors['/api/coaching-dashboard']}"
        coach_agreement_checks = [consistency_check.warn(msg), vs_engine_check.warn(msg)]
    else:
        served_coaches = payloads.get("/api/coaching-dashboard", {}).get("coaches", [])
        served_nutrition = payloads.get("/api/nutrition_overview", {}).get("nutrition")
        served_journey = payloads.get("/api/journey", {}).get("journey")
        _rate_ci = None
        if isinstance(served_journey, dict):
            _lo, _hi = served_journey.get("weekly_rate_ci_low"), served_journey.get("weekly_rate_ci_high")
            if _lo is not None and _hi is not None:
                _rate_ci = (_lo, _hi)
        c_ok, c_msg = assess_cross_surface_coach_consistency(served_coaches, rate_ci=_rate_ci)
        e_ok, e_msg = assess_cross_surface_coach_vs_engine(served_coaches, nutrition=served_nutrition, journey=served_journey)
        coach_agreement_checks = [
            consistency_check.ok(c_msg) if c_ok else consistency_check.fail(c_msg),
            vs_engine_check.ok(e_msg) if e_ok else vs_engine_check.fail(e_msg),
        ]

    if "/api/vitals" in fetch_errors or "/api/sleep_detail" in fetch_errors:
        sleep_result = sleep_check.warn(
            "cross-surface fetch failed (fail-soft): "
            + "; ".join(f"{p} — {e}" for p, e in fetch_errors.items() if p in ("/api/vitals", "/api/sleep_detail"))
        )
    else:
        served_vitals = payloads.get("/api/vitals", {}).get("vitals", {})
        served_sleep_detail = payloads.get("/api/sleep_detail", {}).get("sleep_detail", {})
        s_ok, s_msg = assess_cross_surface_sleep_disclosure(served_vitals, served_sleep_detail)
        sleep_result = sleep_check.ok(s_msg) if s_ok else sleep_check.fail(s_msg)

    return weight_vitals_checks + [sleep_result] + coach_agreement_checks


# ── #1225: single-surface hero-weight arithmetic. Moved here from
# qa_smoke_lambda so both weight-truth assessors live together (the module was at
# 1196/1200 and #1894 pushed it over — the size gate asks for a cohesive split, not
# a grandfather entry). Re-exported from qa_smoke_lambda, so the public surface and
# tests/test_hero_weight_arithmetic.py are unchanged.

WEIGHT_RECONCILE_TOL = 0.05


def hero_weight_applicable(journey) -> bool:
    """Is there a weight claim on the page for `assess_hero_weight` to reconcile?

    #2640: `assess_hero_weight` returns (True, "no weight claim to reconcile") when there
    is nothing to check, and the caller rendered that as a GREEN CHECK. A green from a
    check that examined nothing is indistinguishable from a green from a check that
    examined something and liked it — the ADR-104 class this whole surface exists to
    police, sitting inside the police.

    The window is real, not theoretical. It opens at every genesis (#931/#939 stage the
    countdown with weight fields nulled by design) and re-opens for as long as Matthew
    does not weigh in. Measured 2026-08-15, five days into cycle 13: the live payload IS
    applicable (2 weigh-ins, span 1d) and the check IS armed — feeding it an impossible
    `lost_lbs` reds it with a specific message. So the branch is not suppressing anything
    today; it is that when it does suppress, nobody can tell.

    Split out rather than folded into the return value so every existing caller keeps its
    `ok, msg = assess_hero_weight(...)` shape.
    """
    return not (journey.get("pre_start") or journey.get("current_weight_lbs") is None)


def assess_hero_weight(journey):
    """Validate the /api/journey weight row reconciles + is trend-honest.

    Returns (ok: bool, message: str). Pure — no network, no clock. A pre-start
    payload (weight fields nulled by design, #931) is a clean pass.
    """
    if not isinstance(journey, dict):
        return False, "journey payload is not an object"
    if not hero_weight_applicable(journey):
        return True, "pre-start / no weigh-in — no weight claim to reconcile"

    now = journey.get("current_weight_lbs")
    start = journey.get("start_weight_lbs")
    lost = journey.get("lost_lbs")
    if start is None or lost is None:
        return False, f"weight row incomplete — current={now}, start={start}, lost={lost}"

    # (a) Arithmetic: DISPLAYED now − DISPLAYED start must equal the DISPLAYED delta.
    #     lost_lbs is start − now, so (now − start) must equal −lost_lbs.
    residual = float(now) - float(start) + float(lost)
    if abs(residual) > WEIGHT_RECONCILE_TOL:
        return False, (
            f"stat row fails arithmetic: now {now} − start {start} = {round(float(now) - float(start), 2)} "
            f"but the delta shows {lost} (residual {round(residual, 2)}) — a numerate reader can't reconcile it (#1225)"
        )

    # (b) Trend honesty: "up/down X in N days" needs >= 2 weigh-ins. The payload must
    #     carry the count, and a single weigh-in must span 0 days (story.js gates the
    #     elapsed-days copy on exactly this).
    n = journey.get("weighin_count")
    if n is None:
        return False, "journey payload is missing weighin_count — story.js can't gate the 'in N days' trend claim (#1225)"
    span = journey.get("weighin_span_days") or 0
    if int(n) < 2 and float(span) > 0:
        return False, (
            f"single weigh-in (count={n}) but weighin_span_days={span} > 0 — that would let story.js claim an "
            f"N-day trend off one reading (#1225)"
        )
    return True, f"stat row reconciles (now {now} − start {start} → {lost} delta) · {n} weigh-in(s), span {span}d"


# ── #1985: a superseded weight on a FROZEN artifact must carry its reconciliation ──
#
# Distinct from assess_cross_surface_weight above. That check asks "do two live
# surfaces agree?". This one asks a question no live-vs-live comparison can:
# a frozen document is *allowed* to quote a superseded figure — that is what
# "frozen" means, and editing it would be the defect — but it must carry an
# editor's note reconciling the number with the one the experiment runs on.
#
# The live failure (#1985): Prologue Part III, whose own text reads "Nothing
# here can be quietly revised later", asserted 317.61 lbs with no note, while
# the cockpit served 321.09. Part I already carried the reconciliation pattern.
# The asymmetry was the defect, not the number.
#
# Guarded as a SET, not an instance: nothing here hardcodes 317.61. Any
# bodyweight figure on a frozen artifact that diverges from the current
# baseline by more than the tolerance needs an annotation, so the NEXT
# supersede is caught without anyone remembering to add a literal.
_EDITORS_NOTE_MARKERS = ("editor's note", "editor’s note", "editors note")

# A frozen artifact reconciles by NAMING the governing figure near its note, so
# the presence of the baseline anywhere in the prose is what clears the check.
SUPERSEDED_ANNOTATION_TOL_LBS = CROSS_SURFACE_WEIGHT_TOL_LBS


def is_annotated(prose: str) -> bool:
    """True when the artifact carries an editor's-note reconciliation."""
    low = (prose or "").lower()
    return any(m in low for m in _EDITORS_NOTE_MARKERS)


def assess_frozen_artifact_weights(surfaces, baseline_lbs, tol: float = SUPERSEDED_ANNOTATION_TOL_LBS):
    """Frozen story artifacts quoting a superseded START weight must be annotated.

    Deliberately narrow, and the narrowness is the point. A plan document is FULL
    of legitimate bodyweights that are not the start: the 185 lb target, the
    275/250/225/200 waypoints, a goal-weight aside. An earlier draft of this check
    flagged all of them — firing on correct writing is how a gate teaches people to
    ignore it (the #1924 lesson, one class over). So a figure counts only when the
    prose presents it AS the starting weight, within a short window of the number.

    ``surfaces`` is the qa-smoke shape: ``[{"name", "path", "prose"}, ...]``.
    Returns a list of finding dicts (empty == clean). Pure — no network, no clock,
    no AWS — so the rule is unit-testable offline and the fetching stays in
    qa_check_reader_truth, matching this module's existing split.
    """
    findings = []
    for s in surfaces or []:
        prose = s.get("prose") or ""
        cited = sorted({w for w in _start_weights_cited_in(prose) if abs(w - float(baseline_lbs)) > tol})
        if not cited or is_annotated(prose):
            continue
        findings.append(
            {
                "page": s.get("path") or s.get("name"),
                "category": "superseded_weight_unannotated",
                "detail": (
                    f"{s.get('name')} presents {', '.join(f'{w} lbs' for w in cited)} as the starting weight, but the "
                    f"experiment runs on {baseline_lbs} lbs, and the page carries no editor's note reconciling them. A "
                    f"frozen artifact may keep its original figure — it must not present it un-reconciled (#1985)."
                ),
            }
        )
    return findings


# A bodyweight counts for #1985 only when the prose presents it AS the start.
# Everything else on a plan page — targets, waypoints, goal asides — is correct
# writing and must not trip the gate.
#
# Proximity alone is NOT enough, and the live page proves it: the stats line reads
# "317.61 lbs at the start · 185 lbs the target", so any window wide enough to bind
# "at the start" to 317.61 also reaches 185. So the test is NEAREST MARKER WINS —
# a figure is a start claim only when a start marker sits closer to it than any
# target marker does. That is what distinguishes the two numbers in one line.
#
# NB "destination" is deliberately NOT a target marker: the live prose reads
# "The destination. 317.61 pounds on the morning of Day 1. 185 pounds twelve
# months later." — there it is a section heading for the whole journey, and
# counting it suppressed the very finding this check exists for.
_START_CLAIM = re.compile(
    r"(start(?:ing)?\s+weight|at\s+the\s+start|on\s+the\s+morning\s+of\s+day\s*1|"
    r"day\s*1\s+weight|began\s+at|started\s+at|weight\s+at\s+day\s*1)",
    re.IGNORECASE,
)
_TARGET_CLAIM = re.compile(
    r"(target|goal|months?\s+later|by\s+month|twelve\s+months)",
    re.IGNORECASE,
)
_START_WINDOW_CHARS = 60


def _nearest(pattern, prose: str, at: int, window: int):
    """Distance from `at` to the closest match of `pattern` within `window`, or None."""
    lo = max(0, at - window)
    hi = min(len(prose), at + window)
    best = None
    for m in pattern.finditer(prose[lo:hi]):
        d = abs((lo + m.start()) - at)
        if best is None or d < best:
            best = d
    return best


def _start_weights_cited_in(prose: str) -> list[float]:
    """Bodyweights the prose presents as the STARTING weight (see the note above)."""
    prose = prose or ""
    out = []
    for m in _WEIGHT_IN_PROSE.finditer(prose):
        try:
            val = float(m.group(1))
        except ValueError:
            continue
        if val < _BODYWEIGHT_FLOOR_LBS:
            continue
        at = m.start()
        d_start = _nearest(_START_CLAIM, prose, at, _START_WINDOW_CHARS)
        if d_start is None:
            continue
        d_target = _nearest(_TARGET_CLAIM, prose, at, _START_WINDOW_CHARS)
        if d_target is not None and d_target <= d_start:
            continue  # reads as a target/waypoint, not a start claim
        out.append(val)
    return out
