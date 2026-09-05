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

# S3 error codes that mean "no canary record for that date", per-date and never fatal.
# 403 belongs here for a reason worth stating: without s3:ListBucket on the prefix S3
# refuses to confirm or deny a key's existence, so a MISSING object answers 403
# AccessDenied rather than 404 NoSuchKey (#3502). The canary runs 3x/week and this
# check walks 14 trailing dates, so 8+ absences per run are normal — treating one as
# fatal took the whole check down.
_ABSENT_CODES = {"NoSuchKey", "404", "403", "AccessDenied"}
_DENIED_CODES = {"403", "AccessDenied"}

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
    denied = 0
    window = CANARY_PRECISION_WINDOW_DAYS
    try:
        for i in range(1, window + 1):
            d = (today - timedelta(days=i)).strftime("%Y-%m-%d")
            try:
                obj = s3.get_object(Bucket=S3_BUCKET, Key=f"{CANARY_LOG_PREFIX}/{d}.json")
            except getattr(s3, "exceptions", None).NoSuchKey:  # the documented botocore shape, kept first
                continue
            except Exception as exc:  # noqa: BLE001 — classified below, never blanket-swallowed
                code = _s3_error_code(exc)
                if code in _DENIED_CODES:
                    denied += 1
                    continue
                if code in _ABSENT_CODES:
                    continue
                raise  # a genuine transport/parse fault still reaches the outer handler
            rec = json.loads(obj["Body"].read())
            if rec.get("skipped") or rec.get("blind"):
                continue  # no grounded verdict exists for these runs
            runs += 1
            if any(str(a).endswith(":grounded") for a in rec.get("alarms") or []):
                alarmed_dates.append(d)
    except Exception as e:
        # A fault that is NOT a per-date absence/denial: keep the old fail-soft shape,
        # but it is no longer the chronic-muted branch the grant gap used to land in.
        return [c.warn(f"canary precision unreadable ({e}) — fail-soft; needs s3:GetObject on {CANARY_LOG_PREFIX}/* (#1956)")]
    if denied == window:
        # EVERY date denied means the prefix itself is unreadable — the #3502 grant gap,
        # not missing records. Loud and NOT chronic: a muted warning is how this sat
        # dark for 30 days (249 events, zero rate lines).
        return [
            c.warn(
                f"canary precision unreadable — all {window} trailing dates returned AccessDenied; "
                f"the role needs s3:ListBucket on {CANARY_LOG_PREFIX}/* as well as s3:GetObject "
                f"(without List, a MISSING key answers 403 not 404) — #3502"
            )
        ]
    if runs == 0:
        extra = f" ({denied} date(s) denied)" if denied else ""
        return [c.warn(f"no sighted canary runs in trailing {window}d{extra} — grounded precision unmeasurable")]
    rate = len(alarmed_dates) / runs
    line = f"grounded-ALARM rate {len(alarmed_dates)}/{runs} ({rate:.0%}) over trailing {window}d"
    if denied:
        line += f" ({denied} date(s) unreadable — partial grant)"
    if runs >= CANARY_PRECISION_MIN_RUNS and rate > CANARY_PRECISION_WARN_RATE:
        return [c.warn(f"{line} — chronic firing, precision suspect (#1956 cried-wolf signature): {', '.join(alarmed_dates)}")]
    return [c.ok(line)]


def _s3_error_code(exc) -> str:
    """The error code from a botocore ClientError (or a bare NoSuchKey class), as a string.

    Kept tiny and defensive: the check must classify an S3 error without importing
    botocore (the lambda bundle has it, the offline tests stub it), and an exception
    shaped unlike either form falls through to the caller's re-raise.
    """
    resp = getattr(exc, "response", None)
    if isinstance(resp, dict):
        err = resp.get("Error") or {}
        code = err.get("Code")
        if code is not None:
            return str(code)
        status = (resp.get("ResponseMetadata") or {}).get("HTTPStatusCode")
        if status is not None:
            return str(status)
    return type(exc).__name__
