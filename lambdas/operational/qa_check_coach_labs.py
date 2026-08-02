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

    offenders = sorted({cid for cid, text in texts if _ZERO_LABS_CLAIM.search(text)})
    if not total_draws:
        # Store empty (or endpoint dark): a zero-results narration has nothing to
        # contradict tonight — the extraction-side honesty lives in labs_facts.
        return True, "labs store serves no draws — no served text can contradict it tonight"
    if offenders:
        return False, (
            f"served coach text ({', '.join(offenders)}) narrates 'zero results/draws' while /api/labs serves "
            f"total_draws={total_draws} — a fabricated data-integrity claim between two public surfaces "
            "(regenerate the coach analysis; #1993)"
        )
    return True, f"no served coach text contradicts the labs store (total_draws={total_draws}, {len(texts)} texts scanned)"


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
