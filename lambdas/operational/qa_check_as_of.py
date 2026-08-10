"""qa_check_as_of.py — the nightly as_of sensor's fetch/wrap half, own module.

Two assertions over the same fetched reader payload, both deterministic (no LLM
verdict, so both keep working at budget tier 3 where the AI half pauses):

  * **#2414 — stamp vs the CLOCK.** No reader payload may stamp a document day
    AHEAD of the PT-expected day; the runtime sensor for the one-Pacific-frame
    invariant the premerge AST guard (tests/test_pacific_today_guard_2414.py)
    enforces in code.
  * **#2379 — stamp vs the DATA.** A stamp that satisfies the clock check can
    still disagree with the content the same document serves: stamped today
    while every dated field it carries is last week's. The LLM reader-truth
    judge found that class and it saturated `qa-smoke-failures`; this makes the
    deterministic canary own it.

Judging for both is pure (`operational/as_of_agreement_qa`); this module only
fetches and wraps. Lives outside qa_smoke_lambda because that module sits at the
1200-line hard ceiling (#1665) — same cohesive-split idiom as qa_check_coach_labs
(#1993) and weight_truth_qa (#1894). No contract change: qa_smoke_lambda
re-exports `check_as_of_agreement`.
"""

import json
import urllib.error
import urllib.request

from operational.as_of_agreement_qa import assess_as_of, assess_as_of_data_correspondence
from operational.qa_check import CONTENT_TRUTH, Check
from operational.qa_check_reader_truth import SITE_BASE_URL

_AS_OF_ENDPOINTS = (
    "/api/vitals",
    "/api/observatory_week?domain=sleep",  # #2392's original defect site
    "/api/habit_streaks",
    "/api/vice_streaks",
    "/api/journey",
)


def _pt_today():
    from common.pacific_time import pacific_now  # #1964: the one Pacific frame (DST-aware)

    return pacific_now().strftime("%Y-%m-%d")


def check_as_of_agreement():
    pt_today = _pt_today()
    checks_out = []
    for ep in _AS_OF_ENDPOINTS:
        label = ep.split("?")[0].rsplit("/", 1)[-1]
        check = Check(f"as_of:{label}", "Reader Truth", CONTENT_TRUTH)
        try:
            req = urllib.request.Request(SITE_BASE_URL + ep, headers={"User-Agent": "life-platform-qa-smoke"})
            with urllib.request.urlopen(req, timeout=15) as r:
                payload = json.loads(r.read().decode("utf-8", "replace"))
        except Exception as e:
            # Fail-soft: a fetch/parse blip must never red the nightly.
            checks_out.append(check.warn(f"{ep} fetch failed (fail-soft): {str(e)[:120]}"))
            continue

        verdict = assess_as_of(payload, pt_today)
        if verdict["violations"]:
            checks_out.append(check.fail(f"{ep}: " + "; ".join(verdict["violations"][:5])))
        else:
            checks_out.append(check.ok(f"{ep}: {verdict['stamps']} day-stamp(s) <= PT day {pt_today}"))

        # #2379: the complement — the stamp agrees with the CLOCK above; here it
        # must also agree with the DATA the same payload carries. Reuses the one
        # fetch; clock-free, so it cannot become a midnight time-bomb.
        corr_check = Check(f"as_of_data:{label}", "Reader Truth", CONTENT_TRUTH)
        corr = assess_as_of_data_correspondence(payload)
        if corr["violations"]:
            checks_out.append(corr_check.fail(f"{ep}: " + "; ".join(corr["violations"][:5])))
        else:
            served = corr["newest_data_day"] or "no dated data"
            checks_out.append(corr_check.ok(f"{ep}: {corr['stamps']} day-stamp(s) agree with newest served day ({served})"))
    return checks_out
