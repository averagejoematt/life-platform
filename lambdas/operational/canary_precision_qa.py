"""canary_precision_qa — #1956: the false-positive-rate line for the AI quality canary's
grounded-digits check. Extracted from qa_smoke_lambda (#3485 size-split, the
acwr_liveness_qa / raw_archive_qa pattern): that file owns the AWS clients and the
nightly wiring; this module owns the logic and takes its collaborators as arguments.
The constants stay importable from qa_smoke_lambda (re-exported) for the tests and
the canary log writer that cite them.
"""

from __future__ import annotations

import json
from datetime import timedelta

CANARY_LOG_PREFIX = "ai-canary-log"
CANARY_PRECISION_WINDOW_DAYS = 14
CANARY_PRECISION_WARN_RATE = 0.2  # >20% of runs alarming grounded = chronic
CANARY_PRECISION_MIN_RUNS = 5  # below this, a rate is noise — report, don't judge


def check_canary_precision(s3, S3_BUCKET, Check, CONTENT_TRUTH, pt_now):
    """#1956: a false-positive-rate line for the AI quality canary's
    grounded-digits check. The canary's 07-03→07-31 era fired grounded ALARMs on
    provably TRUE numbers (its fact universe was narrower than the ask
    pipeline's serving context) — and nothing measured that precision decay, so
    the alarm quietly became the boy who cried wolf. This line makes the rate a
    nightly, queryable fact: read the trailing dated ai-canary-log records and
    report how often the grounded check alarmed. Post-fix a grounded ALARM
    should be a rare, true fabrication — a chronic rate (> 20% across >= 5
    sighted runs) is the cried-wolf signature, surfaced as WARN (ground truth
    for any single firing is not deterministically knowable here, so never
    FAIL). Budget-paused and transport-BLIND runs carry no grounded verdict and
    are excluded from the denominator. Fail-soft: an unreadable log prefix
    degrades to WARN naming the missing grant, never a crash."""
    c = Check("canary:grounded_precision", "AI Canary", CONTENT_TRUTH)
    today = pt_now().date()
    runs, alarmed_dates = 0, []
    try:
        for i in range(1, CANARY_PRECISION_WINDOW_DAYS + 1):
            d = (today - timedelta(days=i)).strftime("%Y-%m-%d")
            try:
                obj = s3.get_object(Bucket=S3_BUCKET, Key=f"{CANARY_LOG_PREFIX}/{d}.json")
            except s3.exceptions.NoSuchKey:
                continue
            rec = json.loads(obj["Body"].read())
            if rec.get("skipped") or rec.get("blind"):
                continue  # no grounded verdict exists for these runs
            runs += 1
            if any(str(a).endswith(":grounded") for a in rec.get("alarms") or []):
                alarmed_dates.append(d)
    except Exception as e:
        # #2378: chronic while the #1956 grant gap is open; branches below stay ALARMED.
        return [c.warn(f"canary precision unreadable ({e}) — fail-soft; needs s3:GetObject on {CANARY_LOG_PREFIX}/* (#1956)", chronic=True)]
    if runs == 0:
        return [c.warn(f"no sighted canary runs in trailing {CANARY_PRECISION_WINDOW_DAYS}d — grounded precision unmeasurable")]
    rate = len(alarmed_dates) / runs
    line = f"grounded-ALARM rate {len(alarmed_dates)}/{runs} ({rate:.0%}) over trailing {CANARY_PRECISION_WINDOW_DAYS}d"
    if runs >= CANARY_PRECISION_MIN_RUNS and rate > CANARY_PRECISION_WARN_RATE:
        return [c.warn(f"{line} — chronic firing, precision suspect (#1956 cried-wolf signature): {', '.join(alarmed_dates)}")]
    return [c.ok(line)]
