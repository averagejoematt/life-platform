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
from datetime import date as _date

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
_DATED_SENTENCE = re.compile(
    r"""(?:
          \d{4}-\d{2}-\d{2}                        # an explicit ISO date in the sentence
        | \b(?:on|since)\s+day\s+\d+\b             # "on Day 3"
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
    for text in _SENTENCE_SPLIT.split(prose or ""):
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

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?;])\s+|\n+")


def vitals_cited_in(prose: str) -> dict:
    """Every vital a blob of prose asserts **as a current reading**, by metric.

    Returns ``{metric: [values]}``. Excluded, by design: figures the prose anchors to
    a past point (`_HISTORICAL_ANCHOR`, shared with the weight assessor so the dated
    escape hatch is ONE seam), figures in a sentence that frames a target or goal,
    and figures outside the metric's real domain.
    """
    out: dict[str, list[float]] = {}
    for sentence in _SENTENCE_SPLIT.split(prose or ""):
        if _VITALS_TARGET_SENTENCE.search(sentence) or _DATED_SENTENCE.search(sentence):
            continue
        for metric, patterns in _VITALS_PATTERNS.items():
            lo, hi = _VITALS_DOMAIN[metric]
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
                    out.setdefault(metric, []).append(v)
    return out


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


def assess_cross_surface_vitals(vitals, coaches, tol: dict | None = None):
    """Every recovery / HRV / resting-HR / sleep figure a coach asserts as current
    must match the reading that surface was published against.

    Returns (ok, message). Absence is a clean pass (ADR-104) on BOTH sides: a null
    cockpit field has nothing to contradict, and a coach that cites nothing is silent,
    not wrong. Pure — no network, no clock — so the rule is unit-testable offline.
    """
    if not isinstance(vitals, dict):
        return True, "no vitals payload — nothing to compare"
    tol = tol or VITALS_TOL

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
    for c in coaches or []:
        if not isinstance(c, dict):
            continue
        name = c.get("name") or c.get("persona_id") or "coach"
        prose = " ".join(str(c.get(k) or "") for k in _PROSE_FIELDS)
        for metric, values in vitals_cited_in(prose).items():
            if metric not in truth:
                continue
            unit = _VITALS_UNIT[metric]
            baseline, provenance = publication_baseline(vitals, c, metric)
            if baseline is None:
                continue
            for cited in values:
                if abs(cited - baseline) > tol[metric]:
                    disagreements.append(f"{name} cites {metric} {cited:g}{unit} vs {provenance} {baseline:g}{unit}")

    if disagreements:
        return False, "coach-cited vitals disagree with the reading they were published against — " + "; ".join(
            sorted(set(disagreements))[:4]
        )
    return True, "coach narratives agree with the cockpit vitals (" + ", ".join(f"{k} {v:g}" for k, v in sorted(truth.items())) + ")"


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


def checks(check_cls, site_base_url, partition, timeout=15):
    """The qa_smoke-facing entrypoint: fetch both surfaces and return [Check].

    `check_cls` is injected rather than imported so this module stays a leaf —
    qa_smoke_lambda imports us, never the reverse. Fail-soft on fetch, matching
    check_hero_weight_arithmetic: a network blip must never red the nightly.

    `partition` (#1921) is likewise injected, not defaulted: this module cannot
    import qa_smoke_lambda's PARTITIONS, and a literal here would be a second
    copy of that vocabulary free to drift. The caller decides — and because the
    parameter is required, a Check built here can never slip through
    unpartitioned.
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

    payloads, fetch_errors = {}, {}
    for path in ("/api/vitals", "/api/coaching-dashboard", "/api/sleep_detail"):
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
        v_ok, v_msg = assess_cross_surface_vitals(served_vitals, served_coaches)
        weight_vitals_checks = [
            check.ok(msg) if ok else check.fail(msg),
            vitals_check.ok(v_msg) if v_ok else vitals_check.fail(v_msg),
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

    return weight_vitals_checks + [sleep_result]


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
