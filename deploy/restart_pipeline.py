#!/usr/bin/env python3
"""
restart_pipeline.py — ADR-058: One-command orchestrator that re-anchors the
experiment to a new genesis date and converges every surface (DDB, layer,
Lambdas, S3 chronicle, site copy, docs).

Usage:
    # Re-target the experiment to a new date:
    python3 deploy/restart_pipeline.py --genesis 2026-05-25 --dry-run
    python3 deploy/restart_pipeline.py --genesis 2026-05-25 --apply

    # Re-converge the current genesis without changing the date:
    python3 deploy/restart_pipeline.py --apply

Every sub-script is idempotent; the orchestrator can be safely re-run.

Steps (each can be skipped with --skip-<name>):
    1. fetch Withings reading for the target date (or fail)
    2. write config/user_goals.json + config/character_sheet.json
    2b. --close-cycle (default ON): append the new genesis to CYCLE_GENESES
        in lambdas/web/site_api_data.py (drives /api/cycle_compare + /api/timeline)
    3. regenerate lambdas/constants.py via sync_constants_from_config.py
    4. cdk deploy --all (full-tree bundles carry constants + CYCLE_GENESES)
    5. restart_phase_tag.py
    6. restart_intelligence_wipe.py   (stamps the CLOSING cycle onto the archive;
       --close-cycle then bumps SSM /life-platform/experiment-cycle to N+1)
    6b. restart_ledger_reset.py --closing-cycle <closing>  (zero the ledger → $0;
       the cycle is passed EXPLICITLY because SSM already holds N+1 here — #951)
    7. restart_chronicle_handler.py  (re-dates the PRELAUNCH_CALENDAR chronicle
       lead-ins to genesis − days_before)
    8. restart_media_reset.py     (archive + blank panelcast/debrief audio feeds,
       then resurrect the calendar's podcast prequel dated genesis − days_before)
    8b. restart_leadin_pages.py   (rebuild the public journal pages + posts.json
       for every visible chronicle record — the lead-ins' pages)
    9. restart_character_rebuild.py
   10. restart_site_copy_sync.py --old-genesis <outgoing>  (JS/HTML literal sweep)
   11. restart_docs_update.py
   11b. --sync-site (opt-in): bash deploy/sync_site_to_s3.sh — the full-site
       content-hashed sync + rss.xml regen. Deliberately NOT default (#1092):
       too heavy + interactive for an unattended sub-step; without the flag it
       stays a printed next command.
   12. restart_verify_rendered.py --old-genesis <outgoing>  (hard gate, apply only)
   12b. restart_verify_semantic.py  (hard gate, apply only — #1093): deterministic
       assertions on what the LIVE site SAYS pre-start (pre_start flags, zeroed
       character, no current-cycle findings, dispute null-or-current-cycle,
       prologue-only journal manifest) + ZERO pre-genesis phase=experiment rows
       across raw-timeseries sources (the ingestion-poisoning class, 2026-07-12).
   12c. restart_verify_truth.py  (hard gate, apply only — #1097): the AI
       reader-truth pass (the SAME #1140 rubric as CI --reader-truth + the
       nightly qa_smoke, lambdas/reader_truth_qa.py) over the reset-critical
       surfaces. A HIGH finding blocks exactly like the render gate; a budget
       pause (tier >= 1, ADR-125) or Bedrock outage SKIPS LOUDLY, never a
       silent green. Standalone-runnable for the #1094 reset drill.
   13. post-verify hooks (#1092 — the former manual Sunday-queue steps, now inside
       the one command; each respects --apply vs dry-run + fail-fast):
       a. fix_prologue_cycle_and_subscribe_ttl.py — default ON (issue-sanctioned);
          it reads SSM /life-platform/experiment-cycle, so it MUST run after the
          step-6 cycle bump (post-verify satisfies that). --skip-prologue-fix to skip.
       b. seed_genesis_preregistration.py — opt-in --with-preregistration (re-lands
          the FROZEN #976 pre-registration after the wipe).
       c. dedup_source_records.py --source <name> per --dedup-source (repeatable) —
          raw-timeseries duplicate DATE# rows (the eightsleep UTC-rollover class).
   14. --close-cycle: append one line to docs/restart/RESET_LOG.md

DELIBERATELY NOT FOLDED (#1092 — each exclusion verified, not an omission):
  - publish_genesis_preregistration.py — a PERMANENT PUBLIC AI artifact; stays
    attended under the prereg/frozen-artifact dry-run-review posture. The pipeline
    prints it as a clearly-labeled attended next step instead.
  - deploy/restart_verify.py — the POST-genesis Monday health check (asserts
    day_n >= 1, a genesis weigh-in, a post-genesis character sheet); folding it
    would structurally fail at reset time. Run it Monday morning.
  - deploy/sync_site_to_s3.sh — opt-in --sync-site only (see 11b).

FAIL-FAST (2026-07-10): any sub-step exiting nonzero ABORTS the pipeline and
prints exactly what already ran vs. what didn't; --continue-on-error is the
escape hatch. By default --dry-run runs every sub-script in dry-run mode so
the operator sees the total surface area before committing. --apply commits
writes at every step.
"""
import argparse
import json
import re
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import boto3

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

REGION = "us-west-2"
TABLE = "life-platform"
USER = "matthew"
LAYER_NAME = "life-platform-shared-utils"

USER_GOALS = REPO_ROOT / "config" / "user_goals.json"
CHAR_SHEET = REPO_ROOT / "config" / "character_sheet.json"
CDK_CONSTANTS = REPO_ROOT / "cdk" / "stacks" / "constants.py"
LAMBDA_CONSTANTS = REPO_ROOT / "lambdas" / "constants.py"
SITE_API_DATA = REPO_ROOT / "lambdas" / "web" / "site_api_data.py"
RESET_LOG = REPO_ROOT / "docs" / "restart" / "RESET_LOG.md"
SSM_CYCLE_PARAM = "/life-platform/experiment-cycle"

RESET_LOG_SEED = """# RESET_LOG — the durable record of experiment resets (ADR-058/077)

One line per reset, appended by `deploy/restart_pipeline.py --close-cycle` (the
default). The SSM parameter `/life-platform/experiment-cycle` holds only the
CURRENT cycle number; `CYCLE_GENESES` in `lambdas/web/site_api_data.py` drives
/api/cycle_compare + /api/timeline — this file is the human-readable ledger
that ties them together (genesis, cycle, baseline, pipeline report).

| cycle | genesis | baseline (lbs) | report |
|-------|---------|----------------|--------|
| 1 | 2026-04-01 | 307.0 | original launch (Day 1) |
| 2 | 2026-06-01 | — | first reset (ADR-077 tooling) |
| 3 | 2026-06-08 | 311.62 | docs/restart/_pipeline_report.txt (overwritten per run) |
| 4 | 2026-06-14 | 306.87 | Sunday-anchored routine reset |
"""


def snapshot_outgoing_genesis() -> str:
    """Read the OUTGOING genesis from lambdas/constants.py by text (not import —
    the file is regenerated mid-pipeline and module caching would lie). This is
    the literal the site JS/HTML sweep + the rendered-surface verifier hunt for."""
    m = re.search(r"EXPERIMENT_START_DATE\s*=\s*[\"'](\d{4}-\d{2}-\d{2})[\"']", LAMBDA_CONSTANTS.read_text())
    if not m:
        raise RuntimeError("Could not parse EXPERIMENT_START_DATE from lambdas/constants.py")
    return m.group(1)


def read_cycle_from_ssm() -> int | None:
    try:
        ssm = boto3.client("ssm", region_name=REGION)
        return int(ssm.get_parameter(Name=SSM_CYCLE_PARAM)["Parameter"]["Value"])
    except Exception:
        return None


def read_max_cycle_from_registry() -> int:
    """Fallback when SSM is unreadable: the highest key in CYCLE_GENESES."""
    text = SITE_API_DATA.read_text()
    block = re.search(r"CYCLE_GENESES\s*=\s*\{(.*?)\}", text, re.DOTALL)
    if not block:
        raise RuntimeError("Could not locate CYCLE_GENESES in lambdas/web/site_api_data.py")
    keys = [int(k) for k in re.findall(r"^\s*(\d+)\s*:", block.group(1), re.MULTILINE)]
    if not keys:
        raise RuntimeError("CYCLE_GENESES parsed empty")
    return max(keys)


def append_cycle_genesis(new_cycle: int, genesis: str, apply: bool) -> str:
    """Append `new_cycle: "genesis"` to CYCLE_GENESES in site_api_data.py (drives
    /api/cycle_compare + /api/timeline). Idempotent: no-op when the genesis (or
    the cycle number) is already registered. Runs BEFORE the CDK deploy so the
    full-tree bundle ships the updated registry."""
    text = SITE_API_DATA.read_text()
    block_m = re.search(r"CYCLE_GENESES\s*=\s*\{(.*?)\}", text, re.DOTALL)
    if not block_m:
        raise RuntimeError("Could not locate CYCLE_GENESES in lambdas/web/site_api_data.py")
    body = block_m.group(1)
    if f'"{genesis}"' in body:
        return "already-registered"
    if re.search(rf"^\s*{new_cycle}\s*:", body, re.MULTILINE):
        return f"CONFLICT: cycle {new_cycle} already present with a different genesis — resolve by hand"
    lines = body.rstrip().splitlines()
    indent = re.match(r"\s*", lines[-1]).group(0) if lines else "    "
    new_line = f'{indent}{new_cycle}: "{genesis}",  # appended by restart_pipeline --close-cycle'
    new_body = body.rstrip() + "\n" + new_line + "\n"
    if apply:
        SITE_API_DATA.write_text(text[: block_m.start(1)] + new_body + text[block_m.end(1) :])
    return "appended" if apply else "would-append"


def bump_cycle_ssm(new_cycle: int, apply: bool) -> str:
    """Write the incremented cycle to SSM. MUST run AFTER the intelligence wipe —
    the wipe stamps `cycle=<closing run>` onto archived records, so bumping first
    would mislabel the whole archive generation."""
    if not apply:
        return f"would-set {SSM_CYCLE_PARAM}={new_cycle}"
    ssm = boto3.client("ssm", region_name=REGION)
    ssm.put_parameter(Name=SSM_CYCLE_PARAM, Value=str(new_cycle), Type="String", Overwrite=True)
    return f"set {SSM_CYCLE_PARAM}={new_cycle}"


def append_reset_log(cycle: int, genesis: str, weight_lbs: float, apply: bool) -> str:
    """Append one line to docs/restart/RESET_LOG.md (created + seeded with the
    cycle 1-4 history if absent). Idempotent per (cycle, genesis)."""
    if not RESET_LOG.exists():
        if apply:
            RESET_LOG.parent.mkdir(parents=True, exist_ok=True)
            RESET_LOG.write_text(RESET_LOG_SEED)
        existing = RESET_LOG_SEED
    else:
        existing = RESET_LOG.read_text()
    line = f"| {cycle} | {genesis} | {weight_lbs} | docs/restart/_pipeline_report.txt @ {datetime.now(timezone.utc).date().isoformat()} |"
    if f"| {cycle} | {genesis} |" in existing:
        return "already-logged"
    if apply:
        RESET_LOG.write_text(existing.rstrip() + "\n" + line + "\n")
    return "appended" if apply else "would-append"


def fetch_withings_for(target_date: str) -> dict:
    ddb = boto3.resource("dynamodb", region_name=REGION)
    t = ddb.Table(TABLE)
    r = t.get_item(Key={"pk": f"USER#{USER}#SOURCE#withings", "sk": f"DATE#{target_date}"})
    item = r.get("Item")
    if not item:
        raise RuntimeError(
            f"No Withings reading found for {target_date}. " f"Either wait for the morning sync or pass --override-weight-lbs."
        )
    return {
        "weight_lbs": float(item["weight_lbs"]),
        "weight_kg": float(item["weight_kg"]),
        "measurement_utc": item.get("measurement_time_utc"),
    }


def update_ddb_profile(target_date: str, weight_lbs: float, apply: bool):
    """Update the DDB profile record (USER#matthew / PROFILE#v1) — the runtime
    source of truth that site_api_lambda etc. read from. The config JSON files
    are static; the DDB profile is what Lambdas actually see at request time.
    """
    if not apply:
        return
    from decimal import Decimal

    ddb = boto3.resource("dynamodb", region_name=REGION)
    t = ddb.Table(TABLE)
    t.update_item(
        Key={"pk": f"USER#{USER}", "sk": "PROFILE#v1"},
        UpdateExpression="SET journey_start_weight_lbs = :w, journey_start_date = :d, " "baseline_weight_lbs = :w, baseline_date = :d",
        ExpressionAttributeValues={
            ":w": Decimal(str(weight_lbs)),
            ":d": target_date,
        },
    )


def seed_grading_liveness_marker(target_date: str, apply: bool):
    """#1196: seed the coach-prediction grading-liveness watermark to genesis.

    coach_prediction_evaluator.emit_grading_liveness() reads the singleton marker
    (pk=EVALUATOR#coach_prediction, sk=STATE#last_decided) and emits
    DaysSinceLastDecided = days between today and the marker's date (or the 999
    "never" sentinel when the marker is absent). monitoring_stack.GradingStalled
    alarms at >= 14.

    The EVALUATOR# partition is SYSTEM_STATE (phase_taxonomy.py) — the restart
    tooling deliberately never touches it — so across a cycle reset the marker
    otherwise carries the OUTGOING cycle's last-decided date (or, on a first-ever
    cycle, is absent → the 999 sentinel). Either way it fires a false
    grading-stalled ALARM for the first ~14 days of every new cycle, before any
    fresh prediction in the new cycle has had a window to mature and grade.

    Re-stamping date=genesis at reset restarts the grading clock at 0 on Day 1,
    so the alarm only fires if 14 real days elapse in the NEW cycle with nothing
    graded — the intended liveness semantic. Idempotent: put_item overwrites.
    """
    if not apply:
        return
    ddb = boto3.resource("dynamodb", region_name=REGION)
    t = ddb.Table(TABLE)
    t.put_item(
        Item={
            "pk": "EVALUATOR#coach_prediction",
            "sk": "STATE#last_decided",
            "date": target_date,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    )


def bust_lambda_warm_cache(apply: bool):
    """Toggle an env var on site-api-style Lambdas to force a cold start.
    Required because they cache the DDB profile in-memory for the warm
    container lifetime — after a profile update, warm containers still
    return stale data until they cycle.
    """
    if not apply:
        return
    from datetime import datetime as _dt

    bust_val = _dt.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    targets = ["life-platform-site-api", "life-platform-site-api-ai", "site-stats-refresh"]
    lam = boto3.client("lambda", region_name=REGION)
    for fn in targets:
        try:
            cur = lam.get_function_configuration(FunctionName=fn)
            env = cur.get("Environment", {}).get("Variables", {})
            env["RESTART_CACHE_BUST"] = bust_val
            lam.update_function_configuration(FunctionName=fn, Environment={"Variables": env})
        except Exception:
            pass  # function may not exist; harmless


def update_configs(target_date: str, weight_lbs: float, weight_kg: float, measurement_utc: str, apply: bool):
    # user_goals.json
    cfg = json.loads(USER_GOALS.read_text())
    today_iso = date.today().isoformat()
    end_date = (date.fromisoformat(target_date) + (date.fromisoformat("2027-05-17") - date.fromisoformat("2026-05-18"))).isoformat()
    cfg["last_updated"] = today_iso
    cfg["timeline"]["start_date"] = target_date
    cfg["timeline"]["end_date"] = end_date
    cfg["timeline"]["start_weight_lbs"] = weight_lbs
    cfg["timeline"]["start_weight_kg"] = weight_kg
    cfg["timeline"]["baseline_source"] = "withings"
    # Always assign — a conditional here let the PREVIOUS cycle's timestamp
    # survive a restart whose genesis date had no weigh-in yet (None clears it).
    cfg["timeline"]["baseline_measurement_utc"] = measurement_utc
    if apply:
        USER_GOALS.write_text(json.dumps(cfg, indent=2) + "\n")

    # character_sheet.json
    cs = json.loads(CHAR_SHEET.read_text())
    cs["_meta"]["last_updated"] = today_iso
    cs["baseline"]["start_date"] = target_date
    cs["baseline"]["start_weight_lbs"] = weight_lbs
    cs["baseline"]["start_weight_kg"] = weight_kg
    cs["baseline"]["baseline_source"] = "withings"
    if apply:
        CHAR_SHEET.write_text(json.dumps(cs, indent=2) + "\n")


def build_sub_scripts(
    skip_chronicle: bool, keep_chronicle: list[str], old_genesis: str, closing_cycle: int | None = None
) -> list[tuple[str, list[str]]]:
    """The restart sub-script sequence. Order matters (pre-launch content
    calendar, 2026-07-11): chronicle handler (untombstones + re-dates the
    calendar's chronicle lead-ins) → media reset (archives ALL audio, then
    resurrects the calendar's podcast prequel + writes episodes.json/feed.xml)
    → leadin pages (rebuilds the public journal pages + posts.json from the
    now-visible records) → character rebuild → site copy sync → docs update.

    #951: the ledger reset receives the CLOSING cycle explicitly — the SSM bump
    fires right after the wipe (before the ledger reset), so an SSM read inside
    restart_ledger_reset.py would mislabel the closing totals with the NEW cycle
    (the CYCLE_TOTALS#005/cycle=5-for-a-cycle-4-close off-by-one)."""
    ledger_cmd = ["python3", "deploy/restart_ledger_reset.py", "--apply"]
    if closing_cycle is not None:
        ledger_cmd += ["--closing-cycle", str(closing_cycle)]
    sub_scripts = [
        ("restart_phase_tag", ["python3", "deploy/restart_phase_tag.py", "--apply"]),
        ("restart_intelligence_wipe", ["python3", "deploy/restart_intelligence_wipe.py", "--apply"]),
        ("restart_ledger_reset", ledger_cmd),
        ("restart_character_rebuild", ["python3", "deploy/restart_character_rebuild.py", "--apply"]),
        ("restart_site_copy_sync", ["python3", "deploy/restart_site_copy_sync.py", "--apply", "--old-genesis", old_genesis]),
        ("restart_docs_update", ["python3", "deploy/restart_docs_update.py", "--apply"]),
    ]
    sub_scripts.insert(3, ("restart_leadin_pages", ["python3", "deploy/restart_leadin_pages.py", "--apply"]))
    sub_scripts.insert(3, ("restart_media_reset", ["python3", "deploy/restart_media_reset.py", "--apply"]))
    if not skip_chronicle:
        chron_cmd = ["python3", "deploy/restart_chronicle_handler.py", "--apply"]
        for sk in keep_chronicle:  # ADR-077: explicit carry-forward override (else PRELAUNCH_CALENDAR)
            chron_cmd += ["--resurrect-sk", sk]
        sub_scripts.insert(3, ("restart_chronicle_handler", chron_cmd))
    return sub_scripts


def build_post_verify_hooks(
    with_preregistration: bool = False, dedup_sources: list[str] | None = None, skip_prologue_fix: bool = False
) -> list[tuple[str, list[str]]]:
    """The #1092 post-verify hook sequence — the former manual Sunday-queue steps.

    Ordering constraint (verified): fix_prologue_cycle_and_subscribe_ttl reads SSM
    /life-platform/experiment-cycle, so it must run AFTER bump_cycle_ssm (which fires
    right after the intelligence wipe) — every post-verify position satisfies that.
    fix_prologue is default-ON (issue-sanctioned change to default behavior); the
    other two hooks only run when their flags are passed, keeping the pipeline
    byte-compatible when the new flags are absent."""
    hooks: list[tuple[str, list[str]]] = []
    if not skip_prologue_fix:
        hooks.append(("fix_prologue_cycle_and_subscribe_ttl", ["python3", "deploy/fix_prologue_cycle_and_subscribe_ttl.py", "--apply"]))
    if with_preregistration:
        hooks.append(("seed_genesis_preregistration", ["python3", "deploy/seed_genesis_preregistration.py", "--apply"]))
    for src in dedup_sources or []:
        hooks.append((f"dedup_{src}", ["python3", "deploy/dedup_source_records.py", "--source", src, "--apply"]))
    return hooks


def run_step(name: str, cmd: list[str], apply: bool, log: list[str]) -> int:
    print(f"\n──[ {name} ]──")
    print(f"    $ {' '.join(cmd)}")
    if not apply:
        # Inject --dry-run / drop --apply for sub-scripts
        cmd = [c for c in cmd if c != "--apply"]
    proc = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
    log.append(f"=== {name} === (exit {proc.returncode})")
    log.append(proc.stdout[-1500:] if proc.stdout else "")
    if proc.returncode != 0:
        log.append(f"STDERR: {proc.stderr[-800:]}")
    print(proc.stdout[-400:] if proc.stdout else "(no stdout)")
    return proc.returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--genesis", help="Target genesis date YYYY-MM-DD. Default: current genesis.")
    parser.add_argument("--apply", action="store_true", help="Commit writes (default: dry-run for every sub-step)")
    parser.add_argument("--override-weight-lbs", type=float, help="Skip Withings fetch, use this weight")
    parser.add_argument("--override-weight-kg", type=float, help="Override kg too (computed from lbs if absent)")
    parser.add_argument("--skip-deploy", action="store_true", help="Skip CDK deploy step (use if you just deployed)")
    parser.add_argument("--skip-chronicle", action="store_true", help="Skip chronicle handler (rerunning is generally fine)")
    parser.add_argument(
        "--keep-chronicle",
        action="append",
        default=[],
        help="Chronicle DDB sk to keep across the restart, re-dated as a pre-genesis "
        "lead-in (repeatable, max 2). e.g. --keep-chronicle DATE#2026-02-28",
    )
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Escape hatch: keep running later steps after a sub-step fails (default: "
        "any nonzero rc ABORTS the pipeline — a silent partial reset is worse than a loud stop)",
    )
    parser.add_argument(
        "--no-close-cycle",
        action="store_true",
        help="Skip the cycle bookkeeping (CYCLE_GENESES append, SSM cycle bump, RESET_LOG line). Default: ON.",
    )
    parser.add_argument(
        "--with-preregistration",
        action="store_true",
        help="#1092 hook (b): re-land the frozen genesis pre-registration after the wipe "
        "(deploy/seed_genesis_preregistration.py). The PUBLIC publish step stays attended.",
    )
    parser.add_argument(
        "--dedup-source",
        action="append",
        default=[],
        metavar="SOURCE",
        help="#1092 hook (c): run the raw-timeseries duplicate-DATE# dedup pass for this "
        "source (repeatable; e.g. --dedup-source eightsleep — the UTC-rollover class).",
    )
    parser.add_argument(
        "--skip-prologue-fix",
        action="store_true",
        help="Skip #1092 hook (a) fix_prologue_cycle_and_subscribe_ttl (default: runs after the verify gates).",
    )
    parser.add_argument(
        "--sync-site",
        action="store_true",
        help="Run bash deploy/sync_site_to_s3.sh as a pipeline step (default OFF — heavy/interactive; "
        "without the flag it stays a printed next command).",
    )
    args = parser.parse_args()
    close_cycle = not args.no_close_cycle

    # Snapshot the OUTGOING genesis + closing cycle BEFORE anything regenerates
    # constants — the site sweep + verifier need the old literal, and the wipe
    # stamps the closing cycle number onto the archive.
    old_genesis = snapshot_outgoing_genesis()
    closing_cycle = read_cycle_from_ssm()
    cycle_source = "ssm"
    if closing_cycle is None:
        closing_cycle = read_max_cycle_from_registry()
        cycle_source = "CYCLE_GENESES fallback (SSM unreadable)"

    # Resolve target genesis
    if args.genesis:
        target = args.genesis
    else:
        target = old_genesis
    new_cycle = closing_cycle + 1 if target != old_genesis else closing_cycle
    print("\n╔══ restart_pipeline ══╗")
    print(f"║ target genesis: {target}")
    print(f"║ outgoing genesis: {old_genesis}")
    print(f"║ closing cycle: {closing_cycle} ({cycle_source}) → new cycle: {new_cycle}")
    print(f"║ close-cycle bookkeeping: {'ON' if close_cycle else 'off'}")
    print(f"║ mode: {'APPLY' if args.apply else 'DRY-RUN'}")
    print("╚══════════════════════╝")

    # Step 1: fetch Withings reading
    if args.override_weight_lbs:
        wt = {
            "weight_lbs": args.override_weight_lbs,
            "weight_kg": args.override_weight_kg or round(args.override_weight_lbs / 2.20462, 3),
            "measurement_utc": None,
        }
        print(f"\n[1] Withings override: {wt['weight_lbs']} lbs / {wt['weight_kg']} kg")
    else:
        print(f"\n[1] Fetching Withings reading for {target}...")
        try:
            wt = fetch_withings_for(target)
            print(f"    weight_lbs={wt['weight_lbs']} weight_kg={wt['weight_kg']} measurement={wt['measurement_utc']}")
        except RuntimeError as e:
            print(f"    ERROR: {e}")
            sys.exit(2)

    # Step 2: update configs + DDB profile
    print("\n[2] Updating config/user_goals.json + config/character_sheet.json + DDB PROFILE#v1")
    update_configs(target, wt["weight_lbs"], wt["weight_kg"], wt.get("measurement_utc"), args.apply)
    update_ddb_profile(target, wt["weight_lbs"], args.apply)
    print(f"    ({'wrote' if args.apply else 'would write'} configs + DDB profile)")

    # Step 2c (#1196): re-stamp the grading-liveness watermark to genesis so the
    # GradingStalled alarm's DaysSinceLastDecided gauge restarts at 0 on Day 1
    # instead of inheriting the outgoing cycle's stale date (or the 999 sentinel)
    # and firing a false 14-day ALARM every new cycle. EVALUATOR# is SYSTEM_STATE,
    # untouched by the wipe, so this seed is the only thing that resets its clock.
    seed_grading_liveness_marker(target, args.apply)
    print(f"    ({'seeded' if args.apply else 'would seed'} EVALUATOR#coach_prediction/STATE#last_decided = {target})")

    # Step 2b (--close-cycle, default ON): register the new cycle's genesis in
    # CYCLE_GENESES (drives /api/cycle_compare + /api/timeline). Must happen
    # BEFORE the CDK deploy so the site-api bundle ships with it. The SSM cycle
    # bump happens AFTER the wipe (which stamps the closing cycle onto the archive).
    if close_cycle:
        status = append_cycle_genesis(new_cycle, target, args.apply)
        print(f"\n[2b] CYCLE_GENESES registry (lambdas/web/site_api_data.py): {status}")
        if status.startswith("CONFLICT"):
            print("    ABORT: fix CYCLE_GENESES by hand, then re-run.")
            sys.exit(3)

    # Step 3: regenerate constants
    log = []
    rc = run_step("sync_constants_from_config", ["python3", "deploy/sync_constants_from_config.py", "--apply"], args.apply, log)
    if rc and not args.continue_on_error:
        print(f"\n✗ ABORT: sync_constants_from_config failed (exit {rc}).")
        sys.exit(rc)

    # Step 4: CDK deploy (#781: no layer to bump/build — constants.py ships
    # inside every function bundle, so a full-stack deploy converges the fleet)
    if not args.skip_deploy:
        if args.apply:
            print("\n[4] CDK deploy (full-tree bundles carry the new constants)")
            cdk_proc = subprocess.run(
                ["npx", "cdk", "deploy", "--all", "--require-approval", "never"],
                cwd=REPO_ROOT / "cdk",
                capture_output=True,
                text=True,
            )
            log.append(f"=== cdk_deploy === (exit {cdk_proc.returncode})")
            log.append(cdk_proc.stdout[-2000:] if cdk_proc.stdout else "")
            if cdk_proc.returncode != 0:
                log.append(f"STDERR: {cdk_proc.stderr[-1000:]}")
            print(cdk_proc.stdout[-500:] if cdk_proc.stdout else "(no stdout)")
            if cdk_proc.returncode != 0 and not args.continue_on_error:
                print(f"\n✗ ABORT: CDK deploy failed (exit {cdk_proc.returncode}). Nothing after it ran.")
                print("   Fix the deploy, then re-run (the pipeline is idempotent).")
                print(f"   STDERR tail: {(cdk_proc.stderr or '')[-500:]}")
                sys.exit(cdk_proc.returncode)
        else:
            print("\n[5] (dry-run) skipping CDK deploy")
    else:
        print("\n[4-5] CDK deploy skipped (--skip-deploy)")

    # Step 6-11: all the restart sub-scripts (ordering built + unit-tested in
    # build_sub_scripts).
    sub_scripts = build_sub_scripts(args.skip_chronicle, args.keep_chronicle, old_genesis, closing_cycle)

    # Fail-fast (2026-07-10 audit): a nonzero rc used to be silently discarded,
    # so one broken sub-script produced a PARTIAL reset that looked complete.
    completed: list[str] = []
    for i, (name, cmd) in enumerate(sub_scripts):
        rc = run_step(name, cmd, args.apply, log)
        if rc != 0:
            remaining = [n for n, _ in sub_scripts[i + 1 :]]
            print(f"\n✗ step FAILED: {name} (exit {rc})")
            print(f"   already ran: {completed or ['(none)']}")
            print(f"   did NOT run: {remaining or ['(none)']}")
            if args.continue_on_error:
                print("   --continue-on-error: proceeding anyway.")
            else:
                print("   ABORTING (pass --continue-on-error to override). The pipeline is idempotent — fix and re-run.")
                sys.exit(rc)
        else:
            completed.append(name)
            # Cycle bump belongs immediately after a SUCCESSFUL wipe: the wipe
            # stamped cycle=<closing> onto the archive; from here on the platform
            # is cycle N+1.
            if name == "restart_intelligence_wipe" and close_cycle:
                print(f"    [close-cycle] {bump_cycle_ssm(new_cycle, args.apply)}")

    # Step 11b (opt-in --sync-site, #1092): the full-site sync. Runs BEFORE the
    # verify gates so they check the freshly-synced surface. Apply-only — the
    # shell script has no dry-run mode.
    if args.sync_site:
        if args.apply:
            print("\n[11b] Full site sync (--sync-site): bash deploy/sync_site_to_s3.sh")
            sync_proc = subprocess.run(["bash", "deploy/sync_site_to_s3.sh"], cwd=REPO_ROOT, capture_output=True, text=True)
            log.append(f"=== sync_site_to_s3 === (exit {sync_proc.returncode})")
            log.append(sync_proc.stdout[-1500:] if sync_proc.stdout else "")
            if sync_proc.returncode != 0:
                log.append(f"STDERR: {sync_proc.stderr[-800:]}")
            print(sync_proc.stdout[-400:] if sync_proc.stdout else "(no stdout)")
            if sync_proc.returncode != 0 and not args.continue_on_error:
                print(f"\n✗ ABORT: sync_site_to_s3.sh failed (exit {sync_proc.returncode}).")
                sys.exit(sync_proc.returncode)
        else:
            print("\n[11b] (dry-run) would run: bash deploy/sync_site_to_s3.sh (--sync-site)")

    # Final: bust warm-container caches on read-path Lambdas
    print("\n[final] Busting warm-container caches on public-facing Lambdas")
    bust_lambda_warm_cache(args.apply)
    print(f"    ({'forced cold start' if args.apply else 'would force cold start'} on site-api / site-api-ai / site-stats-refresh)")

    # ADR-058 launch-eve audit: hard gate on rendered-surface verification.
    # Catches the class of bug where clean backend still produces a stale-
    # looking public site (hardcoded client JS, cached S3 JSON, missed
    # DDB partitions, etc.). Pass the verify only if apply is true — in
    # dry-run we don't expect the live site to reflect the pivot yet.
    verify_rc = 0
    if args.apply:
        print("\n[verify] restart_verify_rendered.py (hard gate)")
        import time

        time.sleep(30)  # let CloudFront invalidation propagate before we curl
        verify_rc = run_step(
            "restart_verify_rendered", ["python3", "deploy/restart_verify_rendered.py", "--old-genesis", old_genesis], True, log
        )
        if verify_rc != 0:
            print("\n⚠ VERIFY GATE FAILED — public surfaces still show stale tokens.")
            print("   Check docs/restart/_verify_rendered_report.txt for the failing URLs.")
            print("   Common causes: CloudFront cache not yet purged, Lambda warm-cache,")
            print("   newly-missed JS/HTML/JSON surface. Re-run after fixing.")

        # #1093: the SEMANTIC gate — what the site SAYS, not just that it renders.
        # Runs even when the rendered gate failed (one pass = the full picture).
        print("\n[verify] restart_verify_semantic.py (hard gate)")
        semantic_rc = run_step("restart_verify_semantic", ["python3", "deploy/restart_verify_semantic.py"], True, log)
        if semantic_rc != 0:
            print("\n⚠ SEMANTIC VERIFY GATE FAILED — the site contradicts its own timeline.")
            print("   Check docs/restart/_verify_semantic_report.txt for the failing assertions.")
            verify_rc = verify_rc or semantic_rc

        # #1097: the READER-TRUTH gate — the AI read of the rendered prose, AFTER
        # the deterministic semantic assertions (same #1140 rubric as CI
        # --reader-truth + the nightly qa_smoke). A HIGH finding blocks like the
        # render gate; a budget pause / Bedrock outage skips LOUDLY inside the
        # script (exit 0 with an explicit SKIP report), never a silent green.
        print("\n[verify] restart_verify_truth.py (hard gate — AI reader-truth pass)")
        truth_rc = run_step("restart_verify_truth", ["python3", "deploy/restart_verify_truth.py"], True, log)
        if truth_rc != 0:
            print("\n⚠ READER-TRUTH GATE FAILED — high-severity truth finding(s) on the reset surface.")
            print("   Check docs/restart/_verify_truth_report.txt for the findings.")
            verify_rc = verify_rc or truth_rc

    # Post-verify hooks (#1092): the former manual Sunday-queue steps. Fail-fast
    # like the sub-scripts; skipped (loudly) when a verify gate failed, since the
    # pipeline is idempotent — fix, re-run, and the hooks run then.
    hooks = build_post_verify_hooks(args.with_preregistration, args.dedup_source, args.skip_prologue_fix)
    if hooks and args.apply and verify_rc != 0 and not args.continue_on_error:
        print(f"\n⚠ post-verify hooks NOT run (verify gate failed): {[n for n, _ in hooks]}")
        print("   They run automatically on the next successful --apply re-run.")
    else:
        for i, (name, cmd) in enumerate(hooks):
            rc = run_step(name, cmd, args.apply, log)
            if rc != 0:
                remaining = [n for n, _ in hooks[i + 1 :]]
                print(f"\n✗ post-verify hook FAILED: {name} (exit {rc})")
                print(f"   hooks did NOT run: {remaining or ['(none)']}")
                if args.continue_on_error:
                    print("   --continue-on-error: proceeding anyway.")
                else:
                    print("   ABORTING (pass --continue-on-error to override). The pipeline is idempotent — fix and re-run.")
                    sys.exit(rc)

    # Close-cycle part (d): the durable one-line-per-reset ledger.
    if close_cycle:
        print(f"\n[close-cycle] RESET_LOG: {append_reset_log(new_cycle, target, wt['weight_lbs'], args.apply)}")

    # Final report
    report = REPO_ROOT / "docs" / "restart" / "_pipeline_report.txt"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(
        f"restart_pipeline report — target={target} — mode={'APPLY' if args.apply else 'DRY-RUN'}\n"
        f"generated={datetime.now(timezone.utc).isoformat()}\n"
        f"old_genesis={old_genesis} closing_cycle={closing_cycle} new_cycle={new_cycle}\n\n"
        f"baseline_weight_lbs = {wt['weight_lbs']}\n"
        f"baseline_weight_kg  = {wt['weight_kg']}\n\n" + "\n".join(log)
    )
    print(f"\n══ pipeline {'COMPLETE' if args.apply else 'DRY-RUN COMPLETE'} ══")
    print("Report: docs/restart/_pipeline_report.txt")

    # Required follow-ups the pipeline deliberately does NOT run itself (#1092:
    # each exclusion is verified — see the DELIBERATELY NOT FOLDED docstring block).
    print("\n══ REQUIRED NEXT COMMANDS ══")
    if not args.sync_site:
        print(
            "  1. bash deploy/sync_site_to_s3.sh        # full site sync — regenerates rss.xml, hashes the module graph (or re-run with --sync-site)"
        )
    if args.skip_deploy:
        print("  2. bash deploy/deploy_site_api.sh        # --skip-deploy was used: CYCLE_GENESES + constants are NOT live yet")
    if not args.with_preregistration:
        print("  •  python3 deploy/seed_genesis_preregistration.py --apply   # NOT run (pass --with-preregistration to fold it in)")
    print("  •  ATTENDED (deliberately never folded — permanent public AI artifact, dry-run-review posture):")
    print("     python3 deploy/publish_genesis_preregistration.py           # review the dry-run output, THEN --apply")
    print("  •  git status / commit the regenerated files (constants, configs, CYCLE_GENESES, RESET_LOG.md) from MAIN")
    print(
        "  •  Monday morning (post-genesis): python3 deploy/restart_verify.py   # deliberately not folded — it asserts post-genesis state"
    )
    if args.apply and verify_rc != 0:
        print("\n(exiting nonzero: a verify gate failed — rendered and/or semantic, see above)")
        if not args.continue_on_error:
            sys.exit(verify_rc)
    if not args.apply:
        print("\nRe-run with --apply to commit.")


if __name__ == "__main__":
    main()
