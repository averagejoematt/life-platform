#!/usr/bin/env python3
"""
restart_verify.py — Post-pivot health check. Run this Monday morning (or any
time) to confirm the restart pipeline produced a healthy, consistent state.

Checks (each pass/fail):
  1. lambdas/common/constants.py genesis matches config/user_goals.json
  2. No function references the retired shared layer (#781)
  3. DDB PROFILE#v1 matches lambdas/common/constants.py baseline
  4. Live /api/journey returns started_date == genesis
  5. Live /api/journey returns start_weight == baseline (rounded)
  6. day_n(today) is >= 1 (we are at or past genesis)
  7. Withings record exists for genesis date
  8. Character sheet exists for at least one post-genesis day
  9. No habit streak > day_n (would indicate leak from pre-genesis data)
 10. pytest layer-retirement test passes (i2)
 11. Baked static/no-JS + OG proof (Home + Coaching) is fresh post-genesis (#1815)
 12. Plan literals (protein floor et al.) reconcile with config/user_goals.json (#1898)
 13. /api/predict_week is active once the genesis week begins (#1952 — the
     cycle-11 seed carried the wall-clock pre-genesis week_id and the #1198
     guard hid the opening-week hook; pre-genesis countdown => dark is correct)
 14. Countdown-gap sweep (#1947): no un-tombstoned EXPERIMENT_SCOPED row was
     written in [wipe run, genesis) — the wipe is a point-in-time snapshot and
     the daily writers keep running through a future-genesis countdown window;
     cycle 11 leaked ~397 rows this way. Partition list derived from the wipe
     registries (guard-the-set); repairs via deploy/reconcile_countdown_gap.py.
 15. Pre-registration completion gate (#1979): every cycle in CYCLE_GENESES
     (lambdas/web/site_api_data.py) is either sealed (live S3 artifact whose
     SHA-256 matches its published stamp) or explicitly, dated-ly grandfathered
     (deploy/prereg_seal_gate.py) — derived from the artifacts themselves, never
     a hardcoded per-reset list. A fresh cycle fails here until the attended
     seed -> publish -> genesis_prereg_stamp.py --apply sequence actually lands
     a real artifact (#1092 posture: never auto-folded into the pipeline).
 16. Cross-surface weight honesty (#2104): no coach card on
     /api/coaching-dashboard cites a bodyweight the cockpit disagrees with. The
     reset is precisely when a weekly-regenerating narrative surface goes stale
     against a daily one — cycle 12's physical coach ran before the Day-1 weigh-in
     ingested and published the previous cycle's figure as current. Reuses
     lambdas/operational/weight_truth_qa.assess_cross_surface_weight, the same
     assessor the nightly qa-smoke runs, so the rule cannot fork.
 17. Genesis rebuild token-alarm window (#1961): lambdas/common/token_alarm_window.py
     is stamped for the CURRENT genesis, and no un-suppressed (i.e. actually
     dispatched/paged) remediation-dispatcher marker exists for the platform-total
     token alarm inside that window — the literal "no urgent page fired for a
     predicted condition" assertion the story's acceptance criteria ask for.
     NOTE: this only proves the automated-triage layer behaved; the raw CloudWatch
     alarm's SNS routing to the urgent topic (and its direct human email
     subscription) was unchanged by #1961 alone — closed by #2116's composite
     alarm below (a CDK-owner-gated deploy; this check tolerates it not being
     deployed yet — see the #2116 sub-checks appended right after this one).
 17b. #2116 (completes #1961): the composite-alarm half. Read-only
     `cloudwatch.describe_alarms` — if `ai-tokens-platform-daily-total-urgent` /
     `-genesis-window` don't exist yet, this is a benign SKIP (the CDK deploy is
     owner-gated and this check must never fail before that window). Once
     deployed: the raw `ai-tokens-platform-daily-total` alarm must carry NO
     `AlarmActions` of its own (only the composites route anywhere), and if it's
     currently in ALARM, exactly one of the two composites — the one matching
     today's in/out-of-window status — must also be in ALARM.

 18. Reset-predictable alarm check (#1962): the compute-pipeline-stale alarm is
     either not in ALARM, or it IS in ALARM but restart_pipeline.py's
     stamp_compute_staleness_window() declared a genesis suppression window
     that is still active (an expected, dated, auto-clearing red) — an ALARM
     with no active declared window is a real, unpredicted problem and fails.
 20. Pre-genesis prediction provenance (#3511): the live prediction ledger must
     AGREE with the frozen pre-registration. Check 15 asserts a seal EXISTS; nothing
     asserted the rows match it. Two directions, both blocking post-genesis: a season
     PREDICTION# row that presents as pre-genesis (written at/before the PT-midnight
     genesis boundary, or dated strictly before genesis) whose prediction_id is not in
     the frozen artifact; and a sealed id with no live season row at all. The second
     is not hypothetical — on 2026-09-17 all 16 cycle-17 sealed bets were stamped
     phase=pilot/cycle=16 by an attended seed that ran the evening before Day 1, so the
     whole pre-registration was invisible and ungradeable. Shares one PURE predicate
     with the CI half (deploy/prereg_provenance_gate.py); repairs via
     deploy/reconcile_prereg_season_3511.py.

 21. Pre-genesis provenance census (#3513 box 3): no EXPERIMENT_SCOPED row dated
     before genesis may lack phase=pilot. Row-side and family-derived (pk_census +
     phase_taxonomy.classify), never a writer list — insight_writer wrote 109 bare
     INSIGHT# rows across four cycles that PHASE_FILTER_EXPRESSION served as CURRENT on
     Day 1, and no writer enumeration could see it because its pk is a runtime value.

 22. Tombstone-provenance census (#3621 box 1): every non-null `tombstoned_reason`
     names a genesis that RESOLVES — to a cycle in CYCLE_GENESES or to the
     ABANDONED_GENESES alias map beside it (a genesis a reset actually ran on before
     the anchor moved; the wipe's if_not_exists writes mean an in-place registry
     correction can never reach rows an earlier run already stamped, #1202). The
     resolution is then compared against the row's own `cycle` stamp and every
     agreement/disagreement class is printed by name. Red on the 328 rows the
     2026-09-04 re-anchor left unreadable.

 19. Cross-surface VITALS honesty (#2113): no coach card on
     /api/coaching-dashboard cites a recovery score, HRV, resting HR or sleep
     duration the cockpit disagrees with. The sibling of the weight check —
     cycle 12's sleep and training coaches narrated the previous cycle's 59%
     recovery and 42 ms HRV under a "day one" frame while /api/vitals served
     44% and 35 ms, and no gate compared those columns at all. Reuses
     lambdas/operational/weight_truth_qa.assess_cross_surface_vitals, the same
     assessor the nightly qa-smoke runs, so the rule cannot fork.

Returns 0 if all checks pass, 1 if any fail.

Usage:
    python3 deploy/restart_verify.py
"""

import json
import re
import subprocess
import sys
import urllib.request
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import boto3

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "deploy"))

from lambdas.common.constants import (
    EXPERIMENT_BASELINE_WEIGHT_LBS,
    EXPERIMENT_START_DATE,
    day_n,
)

REGION = "us-west-2"
TABLE = "life-platform"
USER = "matthew"
LAYER = "life-platform-shared-utils"
API = "https://averagejoematt.com"

PASS = "\033[32m✓\033[0m"  # noqa: S105 — ANSI green-checkmark constant, not a secret
FAIL = "\033[31m✗\033[0m"


checks = []  # list of (name, passed, detail)


def served_genesis(payload) -> str | None:
    """The genesis the PUBLIC API is answering with, or None if it does not say (#3396).

    Pure, so the served-plane check below can be tested in both directions without a
    network. A missing/!dict/incomplete payload returns None — which never compares equal
    to a real genesis string, so an unreadable answer fails the check rather than passing
    it. That direction matters: this check exists because a reset can leave the serving
    path on the previous cycle, and "could not tell" is not "fine".
    """
    if not isinstance(payload, dict):
        return None
    experiment = payload.get("experiment")
    if not isinstance(experiment, dict):
        return None
    value = experiment.get("genesis")
    return value if isinstance(value, str) and value else None


def pre_genesis_unstamped(pages, genesis: str, exempt_keys=()) -> tuple[list, int]:
    """#3513 box 3 — the pure predicate behind check 21: every EXPERIMENT_SCOPED row whose own
    date is strictly before `genesis` must carry phase=pilot. Returns (violations, rows_scanned).

    Family and class are DERIVED per row (`phase_taxonomy.classify`, via the shared
    `pre_genesis_scoped_violation` predicate), so a new scoped family is audited the reset it
    appears; rows the taxonomy cannot classify are skipped here — the totality census is the
    instrument that rules on those. Date comes from the row itself
    (`restart_phase_tag.extract_date`: explicit `date` attr, then the sk, then a timestamp
    attr); an undated row cannot be pre-genesis by this predicate and is not guessed at.

    #4040: `exempt_keys` is a set of `(pk, sk)` this predicate must NOT flag however it is
    stamped — a chronicle row the live journal manifest still serves
    (`chronicle_manifest_qa.served_chronicle_keys`), whose `sk` can predate genesis by
    design (a reset-re-dated lead-in) while the row is CURRENT. Defaults to `()`, so a
    caller that doesn't pass one gets the pre-#4040 behaviour unchanged."""
    sys.path.insert(0, str(REPO_ROOT / "lambdas"))
    from experiment import phase_taxonomy as taxonomy  # noqa: E402
    from restart_phase_tag import extract_date  # noqa: E402

    exempt = set(exempt_keys)
    bad: list = []
    scanned = 0
    for page in pages:
        for it in page:
            scanned += 1
            pk, sk = it.get("pk", ""), str(it.get("sk", ""))
            if (pk, sk) in exempt:
                continue
            d = extract_date(it)
            if taxonomy.pre_genesis_scoped_violation(pk, sk, it.get("phase"), d, genesis):
                bad.append(f"{pk}/{sk}[phase={it.get('phase')}]")
    return bad, scanned


_REASON_GENESIS_RE = re.compile(r"_(\d{4}-\d{2}-\d{2})$")

# The census's classes, in the order the detail line prints them.
TOMB_UNRESOLVED = "unresolved_genesis"
TOMB_MATCHED = "stamp_is_closing_cycle"
TOMB_EARLIER = "stamp_is_an_earlier_cycle"
TOMB_LATER = "stamp_is_a_later_cycle"
TOMB_NO_STAMP = "no_cycle_stamp"
TOMB_CYCLE_ONE = "genesis_of_cycle_1"
TOMB_UNDATED = "reason_names_no_genesis"


def genesis_in_reason(reason) -> str | None:
    """The genesis date a tombstone reason names, or None when it names none.

    DELIBERATELY WIDER than phase_taxonomy.closing_genesis_of, which matches
    `experiment_restart_<date>` only — correctly, because the pre-registered-bet ledger it
    feeds must not read a reconcile row as a reset, and it falls back to `tombstoned_at`
    when the reason is unreadable. The census asks the other question ("does every dated
    reason in the table resolve?"), so it takes ANY reason whose trailing token is an ISO
    date — `countdown_gap_reconcile_2026-09-05` is one, and 438 live rows carry that family
    — and never falls back to a write timestamp, which is not a genesis. A reason with no
    trailing date (`legacy_daily_aggregate_superseded_by_per_workout`) names no genesis and
    is counted out of scope rather than guessed at (ADR-104).
    """
    m = _REASON_GENESIS_RE.search(str(reason or ""))
    return m.group(1) if m else None


def tombstone_provenance_census(pages, cycle_geneses: dict, abandoned_geneses: dict | None = None):
    """#3621 box 1 — the pure predicate behind check 22: every non-null `tombstoned_reason`
    in the table resolves, and its resolution is compared against the row's OWN cycle stamp.

    Returns (counts, examples, scanned). `counts` is keyed by the TOMB_* classes above.

    THE BLOCKING CLAUSE is `unresolved_genesis == 0`: a reason naming a genesis that is in
    NEITHER registry (CYCLE_GENESES nor ABANDONED_GENESES) means the archive carries a
    provenance nothing in the repo can read back. That is red today on the 328 rows the
    2026-09-04 re-anchor left behind and green once the alias map ships — the free positive
    control this check was built around.

    THE STAMP COMPARISON IS REPORTED, NOT BLOCKING, and that is a deliberate call. Three
    disagreement shapes exist in live data and only one of them is a defect:

      * `stamp_is_closing_cycle` — the wipe stamped `cycle = closing run` on a row that had
        no cycle attribute. The intended shape.
      * `stamp_is_an_earlier_cycle` — the row already carried the cycle it was WRITTEN in,
        so the wipe's `if_not_exists` left it alone (#1202, by design: the archive stays
        navigable by the generation a record was born in). Not a defect; ~8,400 live rows.
      * `stamp_is_a_later_cycle` — the stamp is the cycle the reset OPENED, not the one it
        closed, so two conventions coexist in the archive. That IS a finding, but it is a
        DIFFERENT finding from this box, its repair is an attended DynamoDB write, and a
        check that can only be made green by one is a check nobody can act on. It is
        counted and printed by name on every run so it cannot go quiet.
    """
    sys.path.insert(0, str(REPO_ROOT / "lambdas"))
    from experiment import phase_taxonomy as taxonomy  # noqa: E402

    counts: dict[str, int] = {}
    examples: dict[str, list] = {}
    scanned = 0

    def record(klass: str, key: str):
        counts[klass] = counts.get(klass, 0) + 1
        if len(examples.setdefault(klass, [])) < 4:
            examples[klass].append(key)

    for page in pages:
        for it in page:
            scanned += 1
            reason = it.get("tombstoned_reason")
            if reason in (None, ""):
                continue
            key = f"{it.get('pk', '')}/{it.get('sk', '')}[{reason}|cycle={it.get('cycle')}]"
            genesis = genesis_in_reason(reason)
            if genesis is None:
                record(TOMB_UNDATED, key)
                continue
            opening = taxonomy.opening_cycle_for_genesis(genesis, cycle_geneses, abandoned_geneses)
            if opening is None:
                record(TOMB_UNRESOLVED, key)
                continue
            if opening <= 1:
                record(TOMB_CYCLE_ONE, key)
                continue
            closing = opening - 1
            stamp = it.get("cycle")
            try:
                stamp_int = int(stamp)
            except (TypeError, ValueError):
                record(TOMB_NO_STAMP, key)
                continue
            if stamp_int == closing:
                record(TOMB_MATCHED, key)
            elif stamp_int < closing:
                record(TOMB_EARLIER, key)
            else:
                record(TOMB_LATER, key)
    return counts, examples, scanned


def check(name: str, ok: bool, detail: str = ""):
    checks.append((name, ok, detail))
    icon = PASS if ok else FAIL
    print(f"  {icon}  {name}{('  — ' + detail) if detail else ''}")


def main():
    print(f"\nrestart_verify — checking pipeline state against genesis={EXPERIMENT_START_DATE}\n")

    # 1. constants ↔ config consistency
    cfg = json.loads((REPO_ROOT / "config" / "user_goals.json").read_text())
    cfg_start = cfg["timeline"]["start_date"]
    cfg_w = float(cfg["timeline"]["start_weight_lbs"])
    check(
        "constants.py genesis matches config", cfg_start == EXPERIMENT_START_DATE, f"config={cfg_start} constants={EXPERIMENT_START_DATE}"
    )
    check(
        "constants.py baseline matches config",
        abs(cfg_w - EXPERIMENT_BASELINE_WEIGHT_LBS) < 0.01,
        f"config={cfg_w} constants={EXPERIMENT_BASELINE_WEIGHT_LBS}",
    )

    # 2. layer retirement (#781): nothing may reference the retired shared layer
    lam = boto3.client("lambda", region_name=REGION)
    attached = []
    for page in lam.get_paginator("list_functions").paginate():
        for fn in page["Functions"]:
            if any(LAYER in l.get("Arn", "") for l in fn.get("Layers", [])):
                attached.append(fn["FunctionName"])
    check("No function references the retired shared layer", not attached, f"attached={attached[:5]}")

    # 3. DDB profile consistency
    ddb = boto3.resource("dynamodb", region_name=REGION)
    t = ddb.Table(TABLE)
    p = t.get_item(Key={"pk": f"USER#{USER}", "sk": "PROFILE#v1"}).get("Item", {})
    profile_date = p.get("journey_start_date", "")
    profile_w = float(p.get("journey_start_weight_lbs", 0))
    check("DDB profile date matches genesis", profile_date == EXPERIMENT_START_DATE, f"profile={profile_date}")
    check(
        "DDB profile weight matches baseline",
        abs(profile_w - EXPERIMENT_BASELINE_WEIGHT_LBS) < 0.01,
        f"profile={profile_w} constants={EXPERIMENT_BASELINE_WEIGHT_LBS}",
    )

    # 4 + 5. Live /api/journey
    try:
        with urllib.request.urlopen(f"{API}/api/journey?cb=verify", timeout=10) as r:
            j = json.loads(r.read())["journey"]
        check("/api/journey started_date matches genesis", j.get("started_date") == EXPERIMENT_START_DATE, f"api={j.get('started_date')}")
        api_w = float(j.get("start_weight_lbs") or 0)
        check(
            "/api/journey start_weight matches baseline",
            abs(api_w - EXPERIMENT_BASELINE_WEIGHT_LBS) < 1.5,
            f"api={api_w} constants={EXPERIMENT_BASELINE_WEIGHT_LBS}",
        )
    except Exception as e:
        check("/api/journey reachable", False, f"error: {e}")

    # 6. day_n
    today = date.today().isoformat()
    d = day_n(today)
    check("day_n(today) >= 1 (past genesis)", d >= 1, f"day_n({today}) = {d}")

    # 7. Withings record for genesis
    w_record = t.get_item(Key={"pk": f"USER#{USER}#SOURCE#withings", "sk": f"DATE#{EXPERIMENT_START_DATE}"}).get("Item")
    check(
        f"Withings record exists for genesis ({EXPERIMENT_START_DATE})",
        w_record is not None,
        f"weight_lbs={w_record.get('weight_lbs') if w_record else '(missing)'}",
    )

    # 8. Post-genesis character sheet exists
    cs = t.query(
        KeyConditionExpression="pk = :p AND sk >= :s",
        ExpressionAttributeValues={
            ":p": f"USER#{USER}#SOURCE#character_sheet",
            ":s": f"DATE#{EXPERIMENT_START_DATE}",
        },
    )
    fresh_sheets = [it for it in cs.get("Items", []) if not it.get("tombstone")]
    check(
        "At least 1 post-genesis character sheet exists (untombstoned)", len(fresh_sheets) >= 1, f"found {len(fresh_sheets)} fresh sheet(s)"
    )

    # 9. No habit streak > day_n (would be a pre-genesis leak)
    # Quick check via DDB rather than MCP (avoids MCP scope issues).
    hs = t.query(
        KeyConditionExpression="pk = :p AND sk >= :s",
        ExpressionAttributeValues={
            ":p": f"USER#{USER}#SOURCE#habit_scores",
            ":s": f"DATE#{EXPERIMENT_START_DATE}",
        },
    )
    fresh_habits = [it for it in hs.get("Items", []) if not it.get("tombstone")]
    max_streak = 0
    for h in fresh_habits:
        for k, v in h.items():
            if isinstance(v, dict) and "streak" in str(k).lower():
                continue
            if "streak" in str(k).lower() and isinstance(v, (int, float)) and v > max_streak:
                max_streak = int(v)
    check("No habit streak > day_n (no pre-genesis leak)", max_streak <= max(d, 1), f"max_streak_in_habit_scores={max_streak} day_n={d}")

    # 10. Layer-consistency pytest
    proc = subprocess.run(
        [
            "python3",
            "-m",
            "pytest",
            "tests/test_integration_aws.py::test_i2_shared_layer_retired",
            "-q",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    pytest_ok = proc.returncode == 0
    check("pytest layer-retirement test passes", pytest_ok, proc.stdout.strip().splitlines()[-1] if proc.stdout else "no output")

    # 11. Static/no-JS + OG proof rebake (#1815, extended #3515). Home's <noscript>
    # core + OG tags, /coaching/'s OG title, and the Data/Protocols hubs' #1395 baked
    # core are BAKED (scripts/v4_build_home_proof.py, v4_build_coaching.py,
    # v4_build_evidence.py) and only regenerate as a side effect of
    # `deploy/sync_site_to_s3.sh` — which only runs on a site/** push. If genesis has
    # passed (or a generator was silently missing from that builder list, #3515) with
    # no incidental site/** merge since, the crawler/social/no-JS layer is still
    # serving pre-start or stale-dated copy. Re-run the generators here (offline-safe:
    # they fall back to the committed proof_snapshot.json if the live API is
    # unreachable) and diff the result — any change means the baked layer WAS stale
    # and has now been rebaked in the working tree; commit + push (touches site/**, so
    # the standing site-deploy.yml auto-deploys it) to actually publish the fix.
    watched = ["site/index.html", "site/coaching/index.html", "site/data/index.html", "site/protocols/index.html"]
    before = {}
    for rel in watched:
        p = REPO_ROOT / rel
        before[rel] = p.read_text(encoding="utf-8") if p.exists() else None
    rebake_errors = []
    # v4_apply_chrome.py MUST run last (same order as sync_site_to_s3.sh) — it
    # re-flattens the doors nav/footer/head-chrome to the single source, so a
    # generator alone would otherwise leave the page on its own stale inline
    # chrome and manufacture a false "changed" diff below.
    for script in (
        "scripts/v4_build_home_proof.py",
        "scripts/v4_build_coaching.py",
        "scripts/v4_build_evidence.py",
        "scripts/v4_apply_chrome.py",
    ):
        r = subprocess.run(["python3", script], cwd=REPO_ROOT, capture_output=True, text=True)
        if r.returncode != 0:
            rebake_errors.append(f"{script}: exit {r.returncode}: {r.stderr.strip().splitlines()[-1] if r.stderr else ''}")
    changed = [rel for rel in watched if (REPO_ROOT / rel).exists() and (REPO_ROOT / rel).read_text(encoding="utf-8") != before[rel]]
    if rebake_errors:
        check("Static/OG proof rebake ran cleanly", False, "; ".join(rebake_errors))
    else:
        check(
            "Baked static/OG proof was already fresh (no rebake needed)",
            not changed,
            f"rebaked (now dirty in the working tree, commit+push to deploy): {changed}" if changed else "up to date",
        )

    # 12. #1898 — plan literals reconcile against config/user_goals.json.
    # A reset rewrites user_goals + the character_sheet BASELINE, but nothing swept
    # the plan FIGURES scattered through prompt-feeding and page-generating configs.
    # Cycle 11 shipped the wiped pilot's 190 g protein target: the character engine
    # graded against it, /method/game/ published "target grams 190", and
    # board_of_directors fed "(190g target)" into coach prompts — while the sealed
    # prereg said 170. Same class as the #1219 kept-chronicle figure check, hence the
    # same WARN-shaped surfacing here; the hard gate is
    # tests/test_plan_literal_reconciliation.py, which reds CI on divergence.
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/test_plan_literal_reconciliation.py", "-q"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        tail = (proc.stdout or proc.stderr).strip().splitlines()
        check(
            "Plan literals reconcile with config/user_goals.json (#1898)",
            proc.returncode == 0,
            tail[-1] if tail else "no output",
        )
    except Exception as e:  # never let the verifier itself crash the post-reset check
        check("Plan literals reconcile with config/user_goals.json (#1898)", False, f"check could not run: {e}")

    # 13. #1952 — predict-the-week must be LIVE once the genesis week begins.
    # Cycle 11 ran its whole opening week dark: the Sunday prep run stamped the
    # wall-clock (pre-genesis) ISO week and the #1198 fail-closed guard hid the
    # challenge for Days 1-6. Pre-genesis, dark is the correct countdown state.
    try:
        from build_genesis_predict_week import evaluate_predict_week_state

        try:
            with urllib.request.urlopen(f"{API}/api/predict_week?cb=verify", timeout=10) as r:
                active = bool(json.loads(r.read()).get("active"))
        except Exception:
            active = None
        today_pt = datetime.now(ZoneInfo("America/Los_Angeles")).date()
        ok, detail = evaluate_predict_week_state(EXPERIMENT_START_DATE, today_pt, active)
        check("/api/predict_week live once the genesis week begins (#1952)", ok, detail)
    except Exception as e:  # never let the verifier itself crash the post-reset check
        check("/api/predict_week live once the genesis week begins (#1952)", False, f"check could not run: {e}")

    # 14. #1947 — the wipe-to-genesis countdown-gap sweep. The wipe is a
    # point-in-time snapshot; on a future-genesis reset the daily writers keep
    # running between the wipe run and the genesis boundary, and everything they
    # write in that window passes PHASE_FILTER_EXPRESSION un-tombstoned forever
    # (cycle 11: ~397 escapees consumed as live coach state). Fails loudly on
    # any determinate escapee; flagged rows (no timestamp anywhere / date-only
    # ambiguity / pre-window stamps) are surfaced in the detail, never hidden.
    try:
        from countdown_gap_sweep import FLAG_CATEGORIES, run_sweep

        res = run_sweep(t)
        esc = res["totals"].get("escapee", 0)
        flags = sum(res["totals"].get(c, 0) for c in FLAG_CATEGORIES)
        by_part = {k: v.get("escapee", 0) for k, v in res["per_partition"].items() if v.get("escapee", 0)}
        detail = (
            f"escapees={esc} flagged={flags} in window [{res['window_start'].isoformat()} → "
            f"{res['window_end'].isoformat()}) ({res['wipe_ts_source']})"
            + (f"; per-partition {by_part}" if by_part else "")
            + ("; repair: python3 deploy/reconcile_countdown_gap.py (dry-run first)" if esc else "")
        )
        check("No countdown-gap escapees (wipe→genesis swept, #1947)", esc == 0, detail)
    except Exception as e:  # never let the verifier itself crash the post-reset check
        check("No countdown-gap escapees (wipe→genesis swept, #1947)", False, f"check could not run: {e}")

    # 21. #3513 box 3 — pre-genesis provenance census. Check 14 sweeps the wipe->genesis
    # countdown window for un-tombstoned rows; this asks the older question it cannot: is
    # there ANY experiment-scoped row dated before genesis that is not `pilot`? A writer that
    # stamps nothing (insight_writer until #3890; the MCP save_insight tool until the same
    # PR as this check) leaves rows PHASE_FILTER_EXPRESSION serves as current on Day 1.
    # One projected full scan (pk_census.scan_provenance_pages — the totality census's RCU).
    # #4040: a chronicle row the live journal manifest still serves is exempted first — its
    # `sk` can predate genesis by design (a reset-re-dated lead-in) while it is CURRENT.
    try:
        sys.path.insert(0, str(REPO_ROOT / "lambdas"))
        from experiment.pk_census import scan_provenance_pages  # noqa: E402
        from operational.chronicle_manifest_qa import served_chronicle_keys  # noqa: E402

        try:
            exempt_keys = served_chronicle_keys(t, boto3.client("s3", region_name=REGION), "matthew-life-platform")
        except Exception:  # noqa: BLE001 — #4040: an unreadable manifest exempts nothing; stays conservative
            exempt_keys = set()
        bad, scanned = pre_genesis_unstamped(scan_provenance_pages(t), EXPERIMENT_START_DATE, exempt_keys=exempt_keys)
        detail = f"{len(bad)} pre-genesis scoped row(s) not pilot over {scanned} scanned" + (
            f"; e.g. {', '.join(bad[:4])}; repair: python3 deploy/phase_stamp_sweep.py (dry-run first)" if bad else ""
        )
        check("No pre-genesis EXPERIMENT_SCOPED row without phase=pilot (#3513)", not bad and scanned > 0, detail)
    except Exception as e:  # never let the verifier itself crash the post-reset check
        check("No pre-genesis EXPERIMENT_SCOPED row without phase=pilot (#3513)", False, f"check could not run: {e}")

    # 22. #3621 box 1 — tombstone-provenance census. Check 21 asks whether a pre-genesis
    # row is stamped; this asks whether the ARCHIVE's own provenance can be read back:
    # every non-null `tombstoned_reason` names a genesis, and that genesis must resolve to
    # a cycle in CYCLE_GENESES or the ABANDONED_GENESES alias beside it. Red on 328 rows
    # before #3621's alias (the 2026-09-04 Friday re-anchor), green after — and the stamp
    # comparison prints beside it (see `tombstone_provenance_census` for why one of its
    # three disagreement classes is a finding and two are the intended shape).
    # A second projected full scan, same RCU class as check 21 — this is an attended script.
    try:
        sys.path.insert(0, str(REPO_ROOT / "lambdas"))
        from experiment.pk_census import scan_provenance_pages  # noqa: E402
        from web.site_api_data import ABANDONED_GENESES, CYCLE_GENESES  # noqa: E402

        counts, examples, scanned = tombstone_provenance_census(scan_provenance_pages(t), CYCLE_GENESES, ABANDONED_GENESES)
        unresolved = counts.get(TOMB_UNRESOLVED, 0)
        breakdown = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
        detail = f"{breakdown} over {scanned} scanned" + (
            f"; e.g. {', '.join(examples.get(TOMB_UNRESOLVED, [])[:3])}; repair: add the genesis to "
            "ABANDONED_GENESES in lambdas/web/site_api_data.py (NEVER re-put the reason strings — that "
            "destroys the record that the genesis was written)"
            if unresolved
            else ""
        )
        check("Every dated tombstoned_reason resolves to a known cycle (#3621)", unresolved == 0 and scanned > 0, detail)
    except Exception as e:  # never let the verifier itself crash the post-reset check
        check("Every dated tombstoned_reason resolves to a known cycle (#3621)", False, f"check could not run: {e}")

    # 15. #1979 — pre-registration completion gate. "Pre-registered" is the
    # platform's central credibility claim; nothing previously asserted a cycle's
    # seal was actually published, and 3 of the last 6 cycles slipped through
    # unsealed with nothing failing. Every genesis in CYCLE_GENESES must have a
    # live S3 artifact + hash-matching stamp, OR an explicit dated grandfather
    # record (deploy/prereg_seal_gate.py::GRANDFATHERED_UNSEALED_CYCLES) — so a
    # reset is not "verified" until the new cycle is sealed or the gap is an
    # owned, dated decision, never a silent one.
    try:
        sys.path.insert(0, str(REPO_ROOT / "lambdas"))
        import prereg_seal_gate  # noqa: E402  (REPO_ROOT/deploy already on sys.path)
        from web.site_api_data import CYCLE_GENESES  # noqa: E402  (needs lambdas/ on sys.path, see above)

        s3_for_seal = boto3.client("s3", region_name=REGION)
        problems = prereg_seal_gate.audit_seal_coverage(CYCLE_GENESES, prereg_seal_gate.make_s3_sealed_check(s3_for_seal))
        check(
            "Every cycle has a published prereg seal or a dated grandfather record (#1979)",
            not problems,
            "; ".join(problems) if problems else f"{len(CYCLE_GENESES)} cycles in CYCLE_GENESES, all covered",
        )
    except Exception as e:  # never let the verifier itself crash the post-reset check
        check("Every cycle has a published prereg seal or a dated grandfather record (#1979)", False, f"check could not run: {e}")

    # 20. #3511 — the live prediction ledger must AGREE with the frozen seal.
    # Check 15 above proves a seal was PUBLISHED. It says nothing about the rows: on
    # cycle-16 Day 0 two gradeable directional bets with 14-day windows were written at
    # 17:09Z before genesis, carried no `pre_registered`, were absent from the frozen
    # artifact, and were on course to be machine-graded into the cycle scorecard beside
    # the sealed ones. The mirror direction turned out to be live too — see the module
    # docstring of deploy/prereg_provenance_gate.py, which holds the PURE predicate this
    # check and the CI test (tests/test_prereg_pregenesis_contract_3511.py) both call.
    try:
        import prereg_provenance_gate  # noqa: E402  (REPO_ROOT/deploy already on sys.path)

        _frozen = prereg_provenance_gate.load_frozen()
        # as_of defaults to today (PT) inside audit_live — the missing-seal clause is
        # only applicable from genesis onward, and this check runs post-genesis.
        _findings, _rows = prereg_provenance_gate.audit_live(frozen=_frozen)
        _blocking = prereg_provenance_gate.blocking(_findings)
        _detail = (
            f"{len(_rows)} PREDICTION# rows read, {len(prereg_provenance_gate.frozen_prediction_ids(_frozen))} sealed ids, "
            f"findings {prereg_provenance_gate.summarize(_findings)}"
        )
        if _blocking:
            _detail += "; " + " | ".join(str(f) for f in _blocking[:5]) + ("" if len(_blocking) <= 5 else f" | +{len(_blocking) - 5} more")
        check("Live prediction ledger agrees with the frozen pre-registration (#3511)", not _blocking, _detail)
    except Exception as e:  # never let the verifier itself crash the post-reset check
        check("Live prediction ledger agrees with the frozen pre-registration (#3511)", False, f"check could not run: {e}")

    # 16. #2104 — coach cards must not narrate a pre-genesis body. The reset is the
    # exact moment a slow-regenerating narrative surface goes stale against a fast
    # one: on cycle 12's genesis the physical coach ran before the Day-1 weigh-in had
    # ingested, was handed the previous cycle's 316.97 (exactly at the age tolerance,
    # so not "stale"), and published "I have one weight reading: 317.0 lbs" against a
    # cockpit serving 322. Nothing in restart_verify looked at the coaching door at
    # all, so the reset was "verified" with the contradiction already live and only
    # the nightly qa-smoke found it, hours later.
    #
    # Reuses the nightly's OWN assessor rather than re-deriving the rule — one
    # definition, now three hooks (qa_smoke, this, and the analyzer's fact assembly).
    try:
        sys.path.insert(0, str(REPO_ROOT / "lambdas"))
        from operational.weight_truth_qa import assess_cross_surface_weight  # noqa: E402

        def _get(path):
            with urllib.request.urlopen(f"{API}{path}?cb=verify", timeout=15) as r:
                return json.loads(r.read())

        ok, msg = assess_cross_surface_weight(
            _get("/api/vitals").get("vitals", {}),
            _get("/api/coaching-dashboard").get("coaches", []),
        )
        check(
            "No coach card cites a weight the cockpit disagrees with (#2104)",
            ok,
            msg + ("" if ok else '  — regen that coach once the Day-1 weigh-in has ingested (ai-expert-analyzer, {"expert": "<domain>"})'),
        )
    except Exception as e:  # never let the verifier itself crash the post-reset check
        check("No coach card cites a weight the cockpit disagrees with (#2104)", False, f"check could not run: {e}")
    # 19. #2113 — the vitals sibling of the weight check. A reset is the one moment a
    # weekly-regenerating coach card and a daily cockpit are guaranteed to disagree,
    # and weight is not the only number they disagree about: on cycle 12's genesis the
    # sleep and training coaches published "a recovery score of 59% ... and HRV of 42
    # ms" and "Day one of this experiment ... Your Whoop recovery came in at 59%, HRV
    # at 42 ms" while /api/vitals served 44% and 35 ms. Every per-surface guard passed
    # — the defect existed only in the comparison, and nothing compared those columns.
    #
    # Reuses the nightly's OWN assessor rather than re-deriving the rule.
    try:
        sys.path.insert(0, str(REPO_ROOT / "lambdas"))
        from operational.weight_truth_qa import assess_cross_surface_vitals  # noqa: E402

        def _get_v(path):
            with urllib.request.urlopen(f"{API}{path}?cb=verify", timeout=15) as r:
                return json.loads(r.read())

        ok, msg = assess_cross_surface_vitals(
            _get_v("/api/vitals").get("vitals", {}),
            _get_v("/api/coaching-dashboard").get("coaches", []),
        )
        check(
            "No coach card cites a vital the cockpit disagrees with (#2113)",
            ok,
            msg
            + (
                ""
                if ok
                else '  — regen that coach once the genesis day\'s metrics have computed (ai-expert-analyzer, {"expert": "<domain>"})'
            ),
        )
    except Exception as e:  # never let the verifier itself crash the post-reset check
        check("No coach card cites a vital the cockpit disagrees with (#2113)", False, f"check could not run: {e}")

    # 17. #1961 — the genesis rebuild token-alarm suppression window. Two parts:
    # (a) structural — the stamped window actually matches what window_for_genesis
    # would derive for the CURRENT genesis (catches "forgot to re-run the pipeline
    # stamp step" and hand-edits alike); (b) live/read-only — no un-suppressed
    # remediation-dispatcher dedupe marker exists for the platform-total token
    # alarm inside the window, i.e. the literal "no urgent page fired for a
    # predicted condition" acceptance criterion. A breach with NO marker at all is
    # fine (nothing observed to have paged); a marker with suppressed=False means
    # the dispatcher actually fired repository_dispatch — the thing this story
    # exists to prevent.
    try:
        from lambdas.common.token_alarm_window import TOKEN_ALARM_GENESIS_WINDOW, window_for_genesis

        expected_window = window_for_genesis(EXPERIMENT_START_DATE)
        check(
            "Token-alarm genesis window is stamped for the current genesis (#1961)",
            tuple(TOKEN_ALARM_GENESIS_WINDOW) == expected_window,
            f"stamped={TOKEN_ALARM_GENESIS_WINDOW} expected={expected_window} for genesis={EXPERIMENT_START_DATE} "
            "(re-run: python3 deploy/restart_pipeline.py --apply to re-stamp)",
        )

        s3_tok = boto3.client("s3", region_name=REGION)
        win_start_compact = expected_window[0].replace("-", "")
        win_end_compact = expected_window[1].replace("-", "")
        prefix = "remediation-log/dispatch-dedupe/ai-tokens-platform-daily-total-"
        unsuppressed = []
        scanned = 0
        for page in s3_tok.get_paginator("list_objects_v2").paginate(Bucket="matthew-life-platform", Prefix=prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                stamp = key[len(prefix) :].split(".")[0]  # YYYYMMDDHHmm bucket
                day = stamp[:8]
                if not (win_start_compact <= day < win_end_compact):
                    continue
                scanned += 1
                try:
                    body = json.loads(s3_tok.get_object(Bucket="matthew-life-platform", Key=key)["Body"].read())
                except Exception:
                    continue
                if not body.get("suppressed", False):
                    unsuppressed.append(key)
        check(
            "No urgent page fired for the platform-total token alarm inside the genesis window (#1961)",
            not unsuppressed,
            (
                f"{scanned} marker(s) in-window, {len(unsuppressed)} NOT suppressed (paged): {unsuppressed[:3]}"
                if scanned
                else "no dispatch-dedupe markers in-window (nothing breached, or dispatcher never saw it — either way, no observed page)"
            ),
        )
    except Exception as e:  # never let the verifier itself crash the post-reset check
        check("Token-alarm genesis window checks (#1961)", False, f"check could not run: {e}")

    # 17b. #2116 (completes #1961) — the composite-alarm half. Read-only
    # cloudwatch.describe_alarms only; never mutates AWS. Deliberately tolerant
    # of the composites not existing yet (the CDK deploy is owner-gated) — this
    # check must be able to run clean BEFORE that deploy, same as every other
    # check in this file.
    try:
        from lambdas.common.token_alarm_window import TOKEN_ALARM_GENESIS_WINDOW as _TAW

        cw_tok = boto3.client("cloudwatch", region_name=REGION)
        # AlarmTypes IS REQUIRED (#3390, 2026-09-04). `describe_alarms` returns ONLY metric
        # alarms when AlarmTypes is omitted — asking for names that happen to be composites
        # yields an empty CompositeAlarms list, indistinguishable from "not deployed".
        # Measured: without AlarmTypes -> 0 composites; with it -> 2, both OK. So this check
        # reported "not deployed yet" from the moment #2116 actually deployed, and because
        # that verdict takes the tolerant branch it silently SKIPPED the four assertions
        # below it — the absence-read-as-success class, in the post-reset verifier itself.
        composite = cw_tok.describe_alarms(
            AlarmNames=["ai-tokens-platform-daily-total-urgent", "ai-tokens-platform-daily-total-genesis-window"],
            AlarmTypes=["CompositeAlarm"],
        ).get("CompositeAlarms", [])
        by_name = {a["AlarmName"]: a for a in composite}
        urgent = by_name.get("ai-tokens-platform-daily-total-urgent")
        in_window_composite = by_name.get("ai-tokens-platform-daily-total-genesis-window")

        if not urgent or not in_window_composite:
            check(
                "Token-alarm composite (#2116) is deployed",
                True,
                "not deployed yet — needs `cdk deploy LifePlatformMonitoring` (owner-gated); "
                "the raw alarm's direct urgent-topic routing is unchanged from #1961's pre-fix state until then",
            )
        else:
            raw = cw_tok.describe_alarms(AlarmNames=["ai-tokens-platform-daily-total"], AlarmTypes=["MetricAlarm"]).get("MetricAlarms", [])
            raw_actions = raw[0].get("AlarmActions", []) if raw else None
            # #3390: the detail branched on `if raw_actions`, so the PASSING state (an
            # empty action list — exactly what #2116 wants) rendered as "raw alarm
            # missing: [...]". Branch on the alarm's presence, not on the truthiness of
            # the thing whose emptiness is the success condition.
            check(
                "Raw ai-tokens-platform-daily-total alarm carries no SNS action of its own (#2116)",
                raw_actions == [],
                (
                    "raw alarm not found — cannot confirm its routing"
                    if not raw
                    else f"AlarmActions={raw_actions} — only the two composites should route anywhere"
                ),
            )

            raw_state = raw[0].get("StateValue") if raw else "MISSING"
            in_window_today = date.fromisoformat(_TAW[0]) <= date.today() < date.fromisoformat(_TAW[1])
            if raw_state != "ALARM":
                check(
                    "Composite routing matches genesis-window status when the raw alarm breaches (#2116)",
                    True,
                    f"raw alarm state={raw_state} (not ALARM) — nothing to route, composites correctly quiet",
                )
            else:
                expected_urgent_alarm = not in_window_today
                actual = {"urgent": urgent["StateValue"] == "ALARM", "in_window": in_window_composite["StateValue"] == "ALARM"}
                ok = actual["urgent"] == expected_urgent_alarm and actual["in_window"] == in_window_today
                check(
                    "Composite routing matches genesis-window status when the raw alarm breaches (#2116)",
                    ok,
                    f"today_in_window={in_window_today} expected_urgent_alarm={expected_urgent_alarm} actual={actual}",
                )
    except Exception as e:  # never let the verifier itself crash the post-reset check
        check("Token-alarm composite checks (#2116)", False, f"check could not run: {e}")

    # 18. #1962 — the compute-pipeline-stale alarm is a reset-predictable false
    # red (the cutover sequence tombstones "yesterday" before the new cycle's
    # compute has had a cron cycle to write a fresh row — cycle 11 fired it red
    # on BOTH 07-26 and 07-27). restart_pipeline.py's
    # stamp_compute_staleness_window() declares a dated suppress_until when it
    # runs; an ALARM state with no active declared window is a real problem,
    # not the known reset artifact, and fails loudly.
    try:
        cw = boto3.client("cloudwatch", region_name=REGION)
        alarms = cw.describe_alarms(AlarmNames=["compute-pipeline-stale"], AlarmTypes=["MetricAlarm"])["MetricAlarms"]
        alarm_state = alarms[0]["StateValue"] if alarms else "MISSING"
        if alarm_state != "ALARM":
            check("compute-pipeline-stale is not a reset-predictable false red (#1962)", True, f"state={alarm_state}")
        else:
            marker = t.get_item(Key={"pk": "SYSTEM#alarm-windows", "sk": "GENESIS#compute-pipeline-stale"}).get("Item")
            suppress_until = marker.get("suppress_until") if marker else None
            in_window = bool(suppress_until) and today <= suppress_until
            check(
                "compute-pipeline-stale is not a reset-predictable false red (#1962)",
                in_window,
                (
                    f"ALARM, but expected — declared genesis window through {suppress_until}, auto-clears then"
                    if in_window
                    else f"ALARM with no active declared genesis window (suppress_until={suppress_until}) — investigate for real"
                ),
            )
    except Exception as e:  # never let the verifier itself crash the post-reset check
        check("compute-pipeline-stale is not a reset-predictable false red (#1962)", False, f"check could not run: {e}")

    # 20. #3396 — the SERVED genesis must equal the staged genesis.
    #
    # Launch eve 2026-08-31: the reset staged genesis 2026-09-01 and `cdk deploy --all`
    # updated every function (CFN: SiteApiLambdaA5C2FE08 UPDATE_COMPLETE 20:13:43Z), yet
    # the public API still answered with the OLD anchor hours later — the nightly QA
    # sweep read cycle-14 residue off 14 pages, the #2878 weight-arbitration smoke check
    # tripped on the disagreement, and the scope-blind rollback reverted wanted prose.
    #
    # Every check above this one reads the CONTROL plane — constants.py, DynamoDB, the
    # config files, CloudWatch. Not one of them reads what a reader actually receives, so
    # a fleet that is correct everywhere except at the edge passed the whole battery. This
    # check is deliberately CAUSE-AGNOSTIC: it does not care whether a bundle missed a
    # function, an asset hash failed to move, a cache held, or a later deploy reasserted
    # an older tree — it asserts the one fact the reset exists to establish, on the plane
    # the public reads it from. `?cb=verify` matches the cache-buster the other served
    # checks use, so a CloudFront hit cannot answer for the origin.
    try:
        with urllib.request.urlopen(f"{API}/api/source_freshness?cb=verify", timeout=15) as r:
            served = json.loads(r.read().decode())
        live = served_genesis(served)
        check(
            "served /api/source_freshness genesis == staged genesis (#3396)",
            live == EXPERIMENT_START_DATE,
            (
                f"served={live} staged={EXPERIMENT_START_DATE}"
                if live == EXPERIMENT_START_DATE
                else (
                    f"served={live} but staged={EXPERIMENT_START_DATE} — the public API is on a "
                    "different cycle than the fleet. Redeploy the serving path "
                    "(bash deploy/deploy_site_api.sh) and re-run; do NOT let a site deploy gate on it first."
                )
            ),
        )
    except Exception as e:  # never let the verifier itself crash the post-reset check
        check("served /api/source_freshness genesis == staged genesis (#3396)", False, f"check could not run: {e}")

    # Summary
    total = len(checks)
    passed = sum(1 for _, ok, _ in checks if ok)
    failed = total - passed
    print("\n══ summary ══")
    print(f"  {passed}/{total} checks passed")
    if failed:
        print("\nFailures:")
        for name, ok, detail in checks:
            if not ok:
                print(f"  ✗  {name}  — {detail}")
        sys.exit(1)
    print(f"\n  GENESIS = {EXPERIMENT_START_DATE} · Day {d} · baseline {EXPERIMENT_BASELINE_WEIGHT_LBS} lbs · all healthy.\n")
    sys.exit(0)


if __name__ == "__main__":
    main()
