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


def weights_cited_in(prose: str) -> list[float]:
    """Every bodyweight-scale figure asserted **as current** in a blob of prose.

    Figures the prose explicitly anchors to a past point are excluded — see
    `_HISTORICAL_ANCHOR`. A citation is a contradiction only if it presents itself
    as today's number.
    """
    text = prose or ""
    out = []
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
    try:
        payloads = {}
        for path in ("/api/vitals", "/api/coaching-dashboard"):
            req = urllib.request.Request(site_base_url + path, headers={"User-Agent": "life-platform-qa-smoke"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                payloads[path] = json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:
        return [check.warn(f"cross-surface weight fetch failed (fail-soft): {str(e)[:120]}")]

    ok, msg = assess_cross_surface_weight(
        payloads.get("/api/vitals", {}).get("vitals", {}),
        payloads.get("/api/coaching-dashboard", {}).get("coaches", []),
    )
    return [check.ok(msg) if ok else check.fail(msg)]


# ── #1225: single-surface hero-weight arithmetic. Moved here from
# qa_smoke_lambda so both weight-truth assessors live together (the module was at
# 1196/1200 and #1894 pushed it over — the size gate asks for a cohesive split, not
# a grandfather entry). Re-exported from qa_smoke_lambda, so the public surface and
# tests/test_hero_weight_arithmetic.py are unchanged.

WEIGHT_RECONCILE_TOL = 0.05


def assess_hero_weight(journey):
    """Validate the /api/journey weight row reconciles + is trend-honest.

    Returns (ok: bool, message: str). Pure — no network, no clock. A pre-start
    payload (weight fields nulled by design, #931) is a clean pass.
    """
    if not isinstance(journey, dict):
        return False, "journey payload is not an object"
    if journey.get("pre_start") or journey.get("current_weight_lbs") is None:
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
