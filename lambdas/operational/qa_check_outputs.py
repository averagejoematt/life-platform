"""qa_check_outputs.py — the AWS-surface sweeps, extracted from qa_smoke_lambda (#1665).

Split out when concurrent merges (#2025 chronic split + #2027 HAE liveness) pushed
qa_smoke_lambda back over the 1200-line hard ceiling. No contract change:
qa_smoke_lambda re-exports every check here, and the run list calls them exactly
as before.

The four checks are one concern: everything qa-smoke validates by listing or
reading AWS resources directly (S3 outputs, the dashboard JSON's value sanity,
Lambda→Secrets references, avatar sprites) — as opposed to the site-fetch, MCP,
and content-truth passes that stay in the main module.

#2307 removed a fifth, ``check_blog_links``: qa_smoke_lambda imported it but its
run list appended a hand-built PAUSED Check instead of calling it (the blog moved
to /story/ in v4), so it was an orphan with tests but no caller. The paused
``blog:links`` Check stays in the sweep as the honest "surface retired" signal.
"""

import json
from datetime import date, datetime, timedelta, timezone

import boto3

from operational.qa_check import CONTENT_TRUTH, DEPLOY_HEALTH, Check

try:
    from common.constants import EXPERIMENT_START_DATE
except ImportError:
    EXPERIMENT_START_DATE = None

import os

REGION = os.environ.get("AWS_REGION", "us-west-2")
S3_BUCKET = os.environ["S3_BUCKET"]

s3 = boto3.client("s3", region_name=REGION)


def _yesterday_str():
    from common.pacific_time import pacific_now  # #1964: the one Pacific frame (DST-aware)

    return (pacific_now() - timedelta(days=1)).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# CHECK 2 — S3 output freshness
# ---------------------------------------------------------------------------


def check_s3_freshness():
    checks = []

    # (s3_key, label, max_age_hours, non_critical)
    # 2026-05-03: paths corrected from dashboard/{file} → dashboard/matthew/{file}.
    # The canonical writer (output_writers.py) uses dashboard/{user_id}/data.json
    # for multi-user prep. qa-smoke had been checking the OLD pre-refactor path
    # since 2026-03-08, generating false S3-stale failures continuously.
    # 2026-06-03: buddy/data.json moved to a PAUSED check below (not freshness-checked
    # while the buddy surface is dormant; last written 2026-03-09). Kept visible so it
    # can be returned to.
    FILES = [
        # data.json's ONLY writer is the daily-brief (cron 17:00 UTC, 1x/day) — a
        # 4h max-age was stale-by-design for ~20h of every day and only looked
        # green because the nightly qa-smoke cron lands a few hours after the
        # brief. CI smoke invokes at arbitrary times inherited a guaranteed FAIL
        # (the 2026-07-27 16:15Z firing rolled back 98 functions on it). 26h =
        # red only when the daily writer actually missed a cycle.
        ("dashboard/matthew/data.json", "Dashboard JSON", 26, False),
        ("dashboard/matthew/clinical.json", "Clinical JSON", 26, True),
    ]

    for key, label, max_hours, non_critical in FILES:
        c = Check(f"S3:{key}", "Output Files", CONTENT_TRUTH)
        try:
            head = s3.head_object(Bucket=S3_BUCKET, Key=key)
            age_h = (datetime.now(timezone.utc) - head["LastModified"]).total_seconds() / 3600
            if age_h <= max_hours:
                c.ok(f"{label} is current ({age_h:.1f}h ago)")
            elif non_critical:
                c.warn(f"{label} is stale ({age_h:.1f}h ago, max {max_hours}h) — non-critical")
            else:
                c.fail(f"{label} is STALE — last written {age_h:.1f}h ago (max {max_hours}h)")
        except Exception as e:
            if non_critical:
                c.warn(f"{label} — error (non-critical): {e}")
            else:
                c.fail(f"{label} — error: {e}")
        checks.append(c)

    checks.append(
        Check("S3:buddy/data.json", "Output Files", CONTENT_TRUTH).pause("Buddy JSON — paused (buddy surface dormant); will return")
    )
    return checks


# ---------------------------------------------------------------------------
# CHECK 3 — Score sanity (read dashboard/data.json, validate value ranges)
# ---------------------------------------------------------------------------


def check_score_sanity():
    checks = []

    try:
        resp = s3.get_object(Bucket=S3_BUCKET, Key="dashboard/matthew/data.json")
        data = json.loads(resp["Body"].read())
    except Exception as e:
        return [Check("dashboard:parse", "Score Sanity", CONTENT_TRUTH).fail(f"Cannot load dashboard/matthew/data.json: {e}")]

    # Pre-start/Day-1 grace window (shared by three checks below — the 39f01e88
    # class): before genesis, and on Day 1 before the first computes/syncs land,
    # several zero/odd states are the HONEST state (ADR-104), not data loss.
    # From Day 2 every one of them is a real FAIL again.
    try:
        from common.constants import EXPERIMENT_START_DATE as _genesis
        from common.pacific_time import pacific_today as _pt_today

        _genesis_grace = (date.fromisoformat(_pt_today()) - date.fromisoformat(_genesis)).days < 1
    except Exception:  # noqa: BLE001 — grace derivation must never break the sweep
        _genesis_grace = False

    expected_date = _yesterday_str()
    actual_date = data.get("date", "")
    c = Check("dashboard:date", "Score Sanity", CONTENT_TRUTH)
    if actual_date == expected_date:
        c.ok(f"Date = {actual_date}")
    elif actual_date and actual_date > expected_date and _genesis_grace:
        # AHEAD of expected (e.g. a manual pre-genesis regen computed "today"
        # early) is never data loss; self-heals at the next scheduled brief.
        c.warn(f"Dashboard dated {actual_date}, ahead of expected {expected_date} — pre-start/Day-1 regen artifact, self-heals")
    elif actual_date:
        c.fail(f"Stale date — expected {expected_date}, got {actual_date}")
    else:
        c.fail("Date field missing from dashboard JSON")
    checks.append(c)

    def _range_check(name, value, lo, hi, unit="", optional=False):
        c = Check(f"value:{name}", "Score Sanity", CONTENT_TRUTH)
        if value is None:
            # #2378: a null on an OPTIONAL metric is the sweep-hour timing class
            # (#1958) — the source is event-driven/sync-lagged by nature, and the
            # 30-day measured record shows these nulls recur on a healthy
            # platform (they were 4 of the 5-8 warns holding qa-smoke-warnings
            # structurally red 21+ days). Chronic: reported + counted in
            # ChronicWarnCount, never alarmed. A null on a REQUIRED metric and
            # an out-of-range value both stay hard FAILs below.
            return c.warn(f"{name} is null (may not have synced)", chronic=True) if optional else c.fail(f"{name} is null — expected data")
        if lo <= float(value) <= hi:
            return c.ok(f"{name} = {value}{unit}")
        return c.fail(f"{name} = {value}{unit} — outside plausible range [{lo},{hi}]")

    readiness = (data.get("readiness") or {}).get("score")
    sleep_s = (data.get("sleep") or {}).get("score")
    weight = (data.get("weight") or {}).get("current")
    hrv = (data.get("hrv") or {}).get("value")
    glucose = (data.get("glucose") or {}).get("avg")
    grade_l = (data.get("day_grade") or {}).get("letter")
    grade_s = (data.get("day_grade") or {}).get("score")
    hydration = ((data.get("day_grade") or {}).get("components") or {}).get("hydration")

    # Pre-start/Day-1 weight grace (2026-07-26, first live catch of the #1831
    # strict oracle): a null weight before the first Withings sync IS the honest
    # state — see the shared _genesis_grace derivation above.
    _weight_grace = _genesis_grace

    checks += [
        _range_check("readiness", readiness, 0, 100, "%", optional=True),
        _range_check("sleep", sleep_s, 0, 100, "", optional=True),
        _range_check("weight", weight, 150, 450, " lbs", optional=_weight_grace),
        _range_check("hrv", hrv, 5, 250, " ms", optional=True),
        _range_check("glucose", glucose, 50, 300, " mg/dL", optional=True),
    ]

    c = Check("score:day_grade", "Score Sanity", CONTENT_TRUTH)
    if grade_l and grade_s is not None:
        c.ok(f"Day grade = {grade_l} ({grade_s}/100)")
    elif EXPERIMENT_START_DATE and actual_date and actual_date < EXPERIMENT_START_DATE:
        c.ok(f"Day grade absent for pre-genesis day {actual_date} (experiment starts {EXPERIMENT_START_DATE}) — expected")
    else:
        c.fail(f"Day grade missing — grade={grade_l}, score={grade_s}")
    checks.append(c)

    c = Check("score:hydration", "Score Sanity", CONTENT_TRUTH)
    if hydration is None:
        # #2378: same timing class as the optional nulls above — HAE water is a
        # webhook source that often hasn't synced by the sweep. Chronic; the
        # low-but-present branch below stays alarmed (a real anomaly signal).
        c.warn("Hydration null — Apple Health water likely didn't sync", chronic=True)
    elif hydration < 30:
        c.warn(f"Hydration = {hydration} — low, possible HAE sync gap (may be valid if <1L consumed)")
    else:
        c.ok(f"Hydration = {hydration}")
    checks.append(c)

    cs = data.get("character_sheet") or {}
    c = Check("character_sheet", "Score Sanity", CONTENT_TRUTH)
    lvl, tier = cs.get("level"), cs.get("tier")
    if lvl and tier:
        xp = cs.get("xp", 0)
        c.ok(f"Level {lvl} {tier} ({xp:,} XP)")
    elif _genesis_grace:
        # The reset wipes the character; the first sheet computes after genesis.
        # Its absence tonight is the honest zero state (ADR-104).
        c.warn("Character sheet absent — wiped at reset, first compute lands after genesis (pre-start/Day-1 grace)")
    else:
        c.fail(f"Character sheet missing — level={lvl}, tier={tier}")
    checks.append(c)

    return checks


# ---------------------------------------------------------------------------
# CHECK 4 — Lambda secret health
# ---------------------------------------------------------------------------


def check_lambda_secrets():
    """Verify every Lambda's SECRET_NAME env var points to an existing secret."""
    lm = boto3.client("lambda", region_name=REGION)
    sm = boto3.client("secretsmanager", region_name=REGION)

    # Build set of existing (non-deleted) secrets
    existing = set()
    try:
        paginator = sm.get_paginator("list_secrets")
        for page in paginator.paginate():
            for s in page["SecretList"]:
                if s.get("DeletedDate") is None:
                    existing.add(s["Name"])
    except Exception as e:
        return [Check("secrets:inventory", "Lambda Secrets", DEPLOY_HEALTH).fail(f"Cannot list secrets: {e}")]

    stale = []
    try:
        paginator = lm.get_paginator("list_functions")
        for page in paginator.paginate():
            for fn in page["Functions"]:
                secret_name = fn.get("Environment", {}).get("Variables", {}).get("SECRET_NAME")
                if secret_name and secret_name not in existing:
                    stale.append(f"{fn['FunctionName']} → {secret_name}")
    except Exception as e:
        return [Check("secrets:sweep", "Lambda Secrets", DEPLOY_HEALTH).fail(f"Cannot list functions: {e}")]

    c = Check("secrets:lambda_refs", "Lambda Secrets", DEPLOY_HEALTH)
    if stale:
        c.fail(f"{len(stale)} stale SECRET_NAME(s): " + "; ".join(stale))
    else:
        c.ok(f"All Lambda SECRET_NAME references resolve ({len(existing)} secrets in inventory)")
    return [c]


# ---------------------------------------------------------------------------
# CHECK 5 — Avatar PNG assets
# ---------------------------------------------------------------------------


def check_avatar_assets():
    TIERS = ["foundation", "momentum", "discipline", "mastery", "elite"]
    FRAMES = [1, 2, 3]

    try:
        paginator = s3.get_paginator("list_objects_v2")
        existing = set()
        for page in paginator.paginate(Bucket=S3_BUCKET, Prefix="dashboard/avatar/base/"):
            for obj in page.get("Contents", []):
                existing.add(obj["Key"])
    except Exception as e:
        # ListBucket permission may be missing — non-critical (IAM least-privilege)
        return [Check("avatar:sprites", "Avatar Assets", CONTENT_TRUTH).warn(f"Cannot list avatar assets (non-critical): {e}")]

    missing = [
        f"{tier}-frame{frame}.png" for tier in TIERS for frame in FRAMES if f"dashboard/avatar/base/{tier}-frame{frame}.png" not in existing
    ]

    c = Check("avatar:sprites", "Avatar Assets", CONTENT_TRUTH)
    total = len(TIERS) * len(FRAMES)
    if missing:
        c.fail(f"Missing {len(missing)}/{total} sprites: {', '.join(missing)}")
    else:
        c.ok(f"All {total} avatar sprites present")
    return [c]


def check_chronicle_sk_date_invariant(table, check_cls=Check, partition=CONTENT_TRUTH):
    """#2367: sk is the chronicle row's IDENTITY; `date` is display/as-of.

    The ADR-077 --keep-chronicle carry-forward deliberately rewrites `date`
    while keeping the sk, and stamps `redated_from_sk` when it does — so a
    date/sk mismatch is legal ONLY on a row carrying that marker. Anything
    else is drift of the kind that made #2352's freshness build accuse an
    already-indexed week. Exemption is BY MARKER, never by hand-listed sks,
    so the next reset's carried lead-ins are born compliant.
    """
    name = "data:chronicle_sk_date_invariant"
    try:
        rows = []
        kwargs = {
            "KeyConditionExpression": "pk = :pk AND begins_with(sk, :skp)",
            "ExpressionAttributeValues": {":pk": "USER#matthew#SOURCE#chronicle", ":skp": "DATE#"},
        }
        while True:
            resp = table.query(**kwargs)
            rows.extend(resp.get("Items", []))
            lek = resp.get("LastEvaluatedKey")
            if not lek:
                break
            kwargs["ExclusiveStartKey"] = lek
    except Exception as e:
        return [check_cls(name, "Schema Invariants", partition).warn(f"chronicle sk/date invariant unreadable ({e}) — fail-soft")]
    offenders = []
    for it in rows:
        if it.get("tombstone"):
            continue  # archived rows carry the closing cycle's history, not the live surface
        sk_date = str(it.get("sk", ""))[len("DATE#") :]
        attr_date = str(it.get("date", "")) or None
        if attr_date and attr_date != sk_date and not it.get("redated_from_sk"):
            offenders.append(f"{it.get('sk')} (date={attr_date})")
    c = check_cls(name, "Schema Invariants", partition)
    if offenders:
        return [
            c.fail(
                f"{len(offenders)} live chronicle row(s) contradict their sk without the carry-forward marker: " + "; ".join(offenders[:4])
            )
        ]
    return [c.ok(f"{len(rows)} chronicle DATE# rows: date==sk or carried (redated_from_sk) — invariant holds")]
