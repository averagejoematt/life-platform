"""qa_check_coach_labs.py — the coach-labs-truth check (#1993), own module.

The labs coach's served card publicly narrated "zero results … a total sync
failure" while /api/labs simultaneously served 8 draws / 152 biomarkers (the
analyzer's fact extractor hunted top-level *_flag keys that never existed in
the labs schema, and each daily regeneration re-fabricated the scandal fresh).
The extraction itself is fixed in intelligence/labs_facts.py; this nightly
tripwire catches the CLASS at the serving edge: any served coach text claiming
zero results/draws while /api/labs serves total_draws > 0 is a
self-contradiction between two public surfaces — an ALARMED content-truth FAIL
(novel defect, never chronic; the #2025 taxonomy).

Lives outside qa_smoke_lambda because that module sits over the 1200-line hard
ceiling (#1665) — same cohesive-split idiom as qa_check_reader_truth (#1944)
and weight_truth_qa (#1894). No contract change: qa_smoke_lambda re-exports
`assess_coach_labs_truth` and `check_coach_labs_truth`.
"""

import json
import re
import urllib.error
import urllib.request

from operational.qa_check import CONTENT_TRUTH, Check
from operational.qa_check_reader_truth import SITE_BASE_URL

# "zero results" / "zero draws" / "zero lab results" — the empty-store claim.
_ZERO_LABS_CLAIM = re.compile(r"\bzero\s+(?:lab\s+|blood\s+)?(?:results|draws)\b", re.IGNORECASE)

# #3728: a zero-claim that NAMES ITS WINDOW is not a contradiction. `/api/labs` counts
# lifetime draws (labs is CROSS_PHASE — no restart trims it); a coach saying "zero draws
# THIS CYCLE" beside a lifetime 8 is two true statements about two windows, and a reader
# can hold both. Only an unqualified zero — which a reader can only read as "there are
# none" — contradicts the served count. Scanned within the claim's OWN SENTENCE: a
# qualifier one sentence away frames that sentence, not this one, and reading across the
# boundary let "Zero draws this cycle. And I have zero results at all." pass whole.
_WINDOW_QUALIFIER = re.compile(
    r"\b(?:this|the current|the present)\s+(?:cycle|experiment|phase|restart|round)\b"
    r"|\bsince\s+(?:the\s+)?(?:restart|reset|genesis|day\s*1|this\s+cycle\s+began)\b"
    r"|\b(?:in|during|within)\s+(?:this|the current)\s+(?:cycle|experiment|phase|window)\b"
    r"|\bthis\s+cycle\b",
    re.IGNORECASE,
)
_SENTENCE_SPLIT = re.compile(r"[.!?;\n]+")

# The opposite direction (#3728): a served text asserting a POSITIVE draw count while
# /api/labs serves an empty store. The original check returned True unconditionally
# whenever the store was empty, so the honest-looking half of the same class — a coach
# inventing bloodwork that does not exist — was never guarded at all. A numeric claim is
# the tight, non-fuzzy half of that and the only half worth asserting on.
_POSITIVE_LABS_CLAIM = re.compile(r"\b(\d{1,3})\s+(?:total\s+)?(?:lab|blood)\s+(?:draws|panels|results)\b", re.IGNORECASE)


def _zero_claim_is_framed(text):
    """True when EVERY zero claim in `text` names its window in its own sentence.

    All-or-nothing on purpose: one unframed zero is the sentence a reader takes
    away, however carefully the sentence beside it was hedged.
    """
    for sentence in _SENTENCE_SPLIT.split(text or ""):
        if _ZERO_LABS_CLAIM.search(sentence) and not _WINDOW_QUALIFIER.search(sentence):
            return False
    return True


def assess_coach_labs_truth(labs, coaches, weekly_priority_text=""):
    """Pure assessor (#1993): (ok, message) for the served-coach-text vs
    /api/labs contradiction. `labs` is the /api/labs labs object ({} when the
    endpoint 404s, i.e. a genuinely empty store); `coaches` is
    /api/coaching-dashboard's coaches list."""
    total_draws = labs.get("total_draws") if isinstance(labs, dict) else None
    try:
        total_draws = int(float(total_draws)) if total_draws is not None else None
    except (TypeError, ValueError):
        total_draws = None

    texts = []
    for coach in coaches or []:
        if isinstance(coach, dict) and coach.get("position_summary"):
            texts.append((str(coach.get("coach_id") or coach.get("name") or "?"), str(coach["position_summary"])))
    if weekly_priority_text:
        texts.append(("weekly_priority", str(weekly_priority_text)))

    if total_draws is None:
        # Endpoint dark or unparseable: there is no count to compare against. Not a
        # pass about the coaches — a statement that the comparison could not be made.
        return True, "/api/labs served no readable total_draws — nothing to compare the served coach text against"

    if not total_draws:
        # #3728: the store is genuinely empty. The old code returned here
        # unconditionally, which left the opposite direction — a coach narrating
        # bloodwork that does not exist — unguarded. Assert it.
        inventors = sorted(
            {f"{cid}:{m.group(1)}" for cid, text in texts for m in _POSITIVE_LABS_CLAIM.finditer(text) if int(m.group(1)) > 0}
        )
        if inventors:
            return False, (
                f"served coach text ({', '.join(inventors)}) claims a positive lab-draw count while /api/labs serves "
                "an empty store — bloodwork narrated that the platform holds no record of (#3728)"
            )
        return True, "labs store serves no draws and no served text claims otherwise"

    # #3728: `total_draws` is LIFETIME (labs is CROSS_PHASE). A coach narrating its own
    # shorter window is not lying, so only an UNFRAMED zero contradicts it. The original
    # check compared the two directly and so fired on honest prose whenever the cycle was
    # young — and its stated remedy, "regenerate the coach analysis", was inert against
    # the real cause: regeneration reproduces the same unframed inputs.
    offenders = sorted({cid for cid, text in texts if _ZERO_LABS_CLAIM.search(text) and not _zero_claim_is_framed(text)})
    if offenders:
        return False, (
            f"served coach text ({', '.join(offenders)}) narrates 'zero results/draws' with no window named, while "
            f"/api/labs serves total_draws={total_draws} for all cycles — a reader sees zero beside {total_draws}. "
            "Fix the frame, not the wording: check that build_data_inventory reports labs present (it is EPISODIC — "
            "a rolling window is the wrong denominator) and that the claim names its window if it has one (#1993, #3728)"
        )
    return True, f"no served coach text contradicts the labs store (total_draws={total_draws} all cycles, {len(texts)} texts scanned)"


def _fetch_site_json(path, timeout=15):
    req = urllib.request.Request(SITE_BASE_URL + path, headers={"User-Agent": "life-platform-qa-smoke"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def check_coach_labs_truth():
    check = Check("coach_labs:truth", "Reader Truth", CONTENT_TRUTH)
    try:
        labs = _fetch_site_json("/api/labs").get("labs") or {}
    except urllib.error.HTTPError as e:
        if e.code == 404:
            labs = {}  # shaped empty: the store genuinely serves no draws
        else:
            return [check.warn(f"/api/labs fetch failed (fail-soft): HTTP {e.code}")]
    except Exception as e:
        # Fail-soft: a fetch/parse blip must never red the nightly.
        return [check.warn(f"/api/labs fetch failed (fail-soft): {str(e)[:120]}")]
    try:
        dash = _fetch_site_json("/api/coaching-dashboard")
    except Exception as e:
        return [check.warn(f"/api/coaching-dashboard fetch failed (fail-soft): {str(e)[:120]}")]
    coaches = dash.get("coaches") or []
    priority_text = (dash.get("weekly_priority") or {}).get("text") or ""
    ok, msg = assess_coach_labs_truth(labs, coaches, priority_text)
    return [check.ok(msg) if ok else check.fail(msg)]
