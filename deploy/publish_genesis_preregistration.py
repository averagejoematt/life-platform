#!/usr/bin/env python3
"""publish_genesis_preregistration.py — "Prologue · The Plan, On the Record" (#976).

The public half of the genesis pre-registration moment: a pre-genesis journal
installment (dated genesis − 1) that puts the plan and the board's frozen opening
predictions on the record, published the same way every other Prologue chapter is.

DESIGN — why this extends restart_leadin_pages rather than patching S3 directly:
the journal surface (article pages + /journal/posts.json) is DERIVED from the
chronicle DDB partition — both restart_leadin_pages.py and the Wednesday publish
rebuild it from the date-sorted installment list. An S3-only page would be dropped
from the manifest at the very next publish and its week-NN slot would collide with
the next real installment. So this script writes ONE chronicle DDB record
(sk DATE#{genesis-1}, phase=experiment) and then reuses restart_leadin_pages.run()
verbatim for the page render + manifest + CloudFront invalidation — render parity
and sequential-URL coherence by construction.

CONTENT SOURCES (ADR-104/105 — no fabricated numbers):
  - config/user_goals.json  → every target/protocol number in the plan section
  - deploy/generated/genesis_preregistration.json → the FROZEN board predictions
    (run deploy/seed_genesis_preregistration.py first; this script never generates)
No "model finish-line odds" number is stated anywhere — no endpoint computes one.

THE PRESENTATION RULE (hard rule, #976): the artifact never mentions resets,
cycles, or prior attempts — only /data/cycles/ may know. Enforced here at publish
time over the full rendered body AND every frozen claim; a violation aborts.

WIPE WARNING: chronicle records are EXPERIMENT_SCOPED — a restart_pipeline.py
re-run tombstones them and only resurrects PRELAUNCH_CALENDAR entries. Re-run this
script (with --apply) after any pipeline run; content is rebuilt deterministically
from the frozen JSON + goals config, so the artifact re-lands unchanged.

Usage:
    python3 deploy/publish_genesis_preregistration.py            # dry-run
    python3 deploy/publish_genesis_preregistration.py --apply    # DDB + S3 + CF
    python3 deploy/publish_genesis_preregistration.py --apply --no-invalidate
"""

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import boto3

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "deploy"))
sys.path.insert(0, str(REPO_ROOT / "lambdas"))

import restart_leadin_pages as leadin  # noqa: E402  (render/manifest machinery — reused, not copied)
from constants import EXPERIMENT_START_DATE  # noqa: E402

REGION = "us-west-2"
TABLE_NAME = "life-platform"
USER_ID = "matthew"

GOALS_PATH = REPO_ROOT / "config" / "user_goals.json"
FROZEN_PATH = REPO_ROOT / "deploy" / "generated" / "genesis_preregistration.json"

TITLE = "The Plan, On the Record"

# The presentation rule, enforced over the FULL rendered artifact.
BANNED_TOKENS = ("cycle", "reset", "restart", "attempt", "last time", "previous", "this time", "once more", "back on")

# Roster order + display domain for the board section (matches the seeder/API roster).
ROSTER = [
    ("training_coach", "training"),
    ("nutrition_coach", "nutrition"),
    ("physical_coach", "body composition"),
    ("sleep_coach", "sleep"),
    ("glucose_coach", "metabolic health"),
    ("labs_coach", "biomarkers"),
    ("mind_coach", "behavior"),
    ("explorer_coach", "the N=1 statistics"),
]

WIPE_REMINDER = (
    "REMINDER: the chronicle partition is EXPERIMENT_SCOPED — a restart_pipeline.py\n"
    "re-run tombstones this installment. Re-run\n"
    "  python3 deploy/seed_genesis_preregistration.py --apply\n"
    "  python3 deploy/publish_genesis_preregistration.py --apply\n"
    "after the pipeline to re-land the pre-registration unchanged (claims stay frozen)."
)


def banned_language_issues(text: str) -> list:
    low = (text or "").lower()
    return [tok for tok in BANNED_TOKENS if tok in low]


def _confidence_phrase(conf) -> str:
    return {"low": "low confidence", "medium": "moderate confidence", "high": "high confidence"}.get(str(conf).lower(), "stated confidence")


def _pretty_date(iso: str) -> str:
    return datetime.strptime(iso, "%Y-%m-%d").strftime("%B %-d, %Y")


def build_body_markdown(goals: dict, frozen: dict) -> str:
    """The installment body, in the exact markdown dialect markdown_to_html renders
    (paragraphs, blockquotes, ---, **bold**, *italics*, *signature* closer)."""
    t = goals["targets"]
    tl = goals["timeline"]
    day1 = _pretty_date(EXPERIMENT_START_DATE)
    start_lbs = tl["start_weight_lbs"]
    goal_lbs = t["weight"]["goal_lbs"]
    milestones = " · ".join(f'{m["lbs"]} by {m["label"].lower()}' for m in t["weight"]["interim_milestones"])
    nut = t["nutrition"]
    phase = t["training"]["phases"][0]
    slp = t["sleep"]

    lines = [
        (
            f"Tomorrow morning — {day1} — a scale in a quiet bathroom records the first number of a "
            "twelve-month experiment. Today, while that number is still a blank, we are doing the thing "
            "that separates a documented experiment from a highlight reel: writing the whole plan down, "
            "in public, before any data exists to flatter it."
        ),
        (
            "This page is a commitment device. Every target below comes from the plan file the platform "
            "itself runs on, and every prediction below has already been logged as a formal, dated record "
            "the grading engine will score without asking anyone's permission. Nothing here can be "
            "quietly revised later. That is the point."
        ),
        "---",
        f"**The destination.** {start_lbs} pounds on the morning of Day 1. {goal_lbs} pounds twelve months later. "
        f"The waypoints are already written: {milestones}. Body composition is the real target under the weight — "
        f"a DEXA-verified descent that protects lean mass the entire way down, with a hard floor of "
        f"{t['body_composition']['lean_mass_floor_lbs']} pounds of lean mass below which the deficit gives way, no argument.",
        f"**The fuel.** {nut['daily_calories_target']:,} calories a day as the working baseline — an aggressive, "
        f"deliberate deficit — with a protein floor of {nut['daily_protein_min_g']} grams and a fiber minimum of "
        f"{nut['daily_fiber_min_g']} grams, eaten inside an {nut['eating_window']['window']} window. Hungry-day "
        "flexibility is written into the plan; starvation theater is not.",
        f"**The work.** The opening months are the {phase['phase']} phase: {phase['gym_days_per_week']} strength "
        f"days a week, roughly three miles of walking every day, and {t['training']['zone2_minutes_per_week_target']} "
        f"minutes of zone-2 cardio a week. Sleep is a training input, not an afterthought: lights out near "
        f"{slp['target_bedtime']}, up at {slp['target_wake']}, chasing {slp['target_hours']} hours.",
        (
            "**The ramp discipline.** Week one is deliberately light — reduced volume, no sets to failure, "
            "and no personal records before day 21. Cardio holds at a conversational effort, zone 2 judged "
            "by feel, for the first two weeks. A body carrying three hundred pounds earns intensity by "
            "surviving consistency first; the plan protects the joints so the habit can compound."
        ),
        "---",
        (
            "That is the plan. Now the part most projects skip: the board goes on the record. Eight "
            "specialists have each filed opening predictions about what the first weeks of data will "
            "show — dated today, frozen, and wired straight into the platform's grading engine. Each "
            "carries its author's honest confidence and the window over which a deterministic evaluator "
            "— code, not the coach — will mark it right or wrong."
        ),
    ]

    for coach_id, domain in ROSTER:
        block = frozen["coaches"].get(coach_id)
        if not block:
            continue
        for pred in block["predictions"]:
            window = int(pred.get("window_days", 14))
            lines.append(
                f"> **{block['coach_name']}, on {domain}:** “{pred['claim_natural']}” "
                f"*({_confidence_phrase(pred.get('confidence'))} · graded over {window} days)*"
            )
            lines.append("")

    lines += [
        "---",
        (
            "Some of these calls will be wrong. That is not a flaw in the exercise — it is the exercise. "
            "A prediction you only publish after it comes true is a press release; these were filed before "
            "the first data point existed, and the scorecard will say so either way."
        ),
        (
            "So here is the standing invitation: come back and grade us. The live ledger — every call, its "
            'status, and each coach\'s hit rate — is public at <a href="/method/predictions/">the predictions '
            "board</a>, and it updates as each window closes. Check it at the two-week mark. Check it again "
            "at four. The numbers on that page, not this essay, are the record."
        ),
        "The first weigh-in is tomorrow. From here on, the data does the talking.",
        "*Elena Voss, the day before Day 1*",
    ]
    return "\n\n".join(lines)


def build_stats_line(goals: dict, n_predictions: int) -> str:
    tl = goals["timeline"]
    goal_lbs = goals["targets"]["weight"]["goal_lbs"]
    return (
        f"{tl['start_weight_lbs']} lbs at the start · {goal_lbs} lbs the target · "
        f"{n_predictions} board predictions filed | Prologue — the plan before Day 1"
    )


def _current_cycle():
    """Cycle stamp for the record (ADR-077 archive navigability) — fail-soft None."""
    try:
        ssm = boto3.client("ssm", region_name=REGION)
        return int(ssm.get_parameter(Name="/life-platform/experiment-cycle")["Parameter"]["Value"])
    except Exception as e:
        print(f"  (warn: could not read experiment-cycle from SSM — cycle stamp skipped: {e})")
        return None


def build_chronicle_record(goals: dict, frozen: dict, cycle=None) -> dict:
    """The chronicle DDB record — publish_to_journal/store_installment field shape,
    pre-genesis flavor (phase=experiment, week_number 0, no editorial image)."""
    body_md = build_body_markdown(goals, frozen)
    body_html = leadin.markdown_to_html(body_md)
    post_date = (date.fromisoformat(EXPERIMENT_START_DATE) - timedelta(days=1)).isoformat()
    n_preds = sum(len(b["predictions"]) for b in frozen["coaches"].values())
    item = {
        "pk": f"USER#{USER_ID}#SOURCE#chronicle",
        "sk": f"DATE#{post_date}",
        "date": post_date,
        "source": "chronicle",
        "week_number": 0,
        "title": TITLE,
        "subtitle": "Prologue · The Measured Life",
        "stats_line": build_stats_line(goals, n_preds),
        "content_markdown": body_md,
        "content_html": body_html,
        "word_count": len(body_md.split()),
        "has_board_interview": False,
        "series_title": "The Measured Life",
        "author": "Elena Voss",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "published",
        "phase": "experiment",  # visible through with_phase_filter (ADR-058)
        "pre_registration": True,  # #976 provenance
        "pre_registered_at": frozen["generated_at"],
    }
    if cycle is not None:
        item["cycle"] = cycle
    return item


def main():
    ap = argparse.ArgumentParser(description='Publish "Prologue · The Plan, On the Record" (#976)')
    ap.add_argument("--apply", action="store_true", help="write DDB + S3 + CloudFront (default: dry-run)")
    ap.add_argument("--no-invalidate", action="store_true", help="with --apply: skip the CloudFront invalidation")
    args = ap.parse_args()

    if not FROZEN_PATH.exists():
        raise SystemExit(f"No frozen pre-registration at {FROZEN_PATH} — run deploy/seed_genesis_preregistration.py first.")
    frozen = json.loads(FROZEN_PATH.read_text())
    if frozen.get("genesis") != EXPERIMENT_START_DATE:
        raise SystemExit(
            f"Frozen pre-registration is for genesis {frozen.get('genesis')} but constants say "
            f"{EXPERIMENT_START_DATE} — regenerate the seed deliberately before publishing."
        )
    goals = json.loads(GOALS_PATH.read_text())

    # The presentation rule — checked over every frozen claim AND the full body.
    for coach_id, block in frozen["coaches"].items():
        for pred in block["predictions"]:
            hits = banned_language_issues(pred["claim_natural"])
            if hits:
                raise SystemExit(f"presentation rule violation in {coach_id} claim ({hits}): {pred['claim_natural']!r}")
    record = build_chronicle_record(goals, frozen)
    hits = (
        banned_language_issues(record["content_markdown"])
        + banned_language_issues(record["title"])
        + banned_language_issues(record["stats_line"])
    )
    if hits:
        raise SystemExit(f"presentation rule violation in the rendered artifact: {sorted(set(hits))}")

    print(f'Installment: "{record["title"]}" · {record["date"]} · {record["word_count"]} words · sk {record["sk"]}')
    print(f"Stats line: {record['stats_line']}")
    print(
        f"Frozen predictions referenced: {sum(len(b['predictions']) for b in frozen['coaches'].values())} "
        f"(frozen {frozen['generated_at']})"
    )

    if not args.apply:
        print("\n--- body markdown ---\n")
        print(record["content_markdown"])
        print(
            "\nDRY RUN — nothing written. Re-run with --apply to write the DDB record, "
            "then render pages + manifest via restart_leadin_pages.run()."
        )
        print("\n" + WIPE_REMINDER)
        return 0

    table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE_NAME)
    cycle = _current_cycle()
    if cycle is not None:
        record["cycle"] = cycle
    table.put_item(Item=record)  # fixed sk → idempotent overwrite
    print(f"WROTE {record['pk']} / {record['sk']}")

    # Page + manifest + invalidation — the shared lead-in machinery, unmodified.
    rc = leadin.run(apply=True, no_invalidate=args.no_invalidate)
    print("\n" + WIPE_REMINDER)
    return rc


if __name__ == "__main__":
    sys.exit(main())
