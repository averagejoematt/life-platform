#!/usr/bin/env python3
"""build_genesis_predict_week.py — the genesis-week predict-the-week subject,
derived from the FROZEN pre-registration (#1378, criterion 3).

Readers should be able to place their own predictions AGAINST the frozen targets —
not against ad-hoc picks. This script derives the week's `predict_metrics` from the
pre-registered hypotheses' deterministic test_specs (the levers and outcomes the
freeze itself names: e.g. the kcal adherence line, the daily-step floor), stamps the
challenge with the freeze's SHA-256 for provenance, and emits the exact
`site/config/current_challenge.json` payload the predict-the-week widget reads
(lambdas/web/site_api_social._predict_subject — week_id must be the CURRENT Pacific
ISO week or the widget fails closed, #1198).

week_id is the GENESIS week (#1952): the ISO week containing experiment Day 1,
derived from `--genesis` / the frozen record's own `genesis` /
lambdas.common.constants.EXPERIMENT_START_DATE — never from the wall clock. The
cycle-11 Sunday prep run (2026-07-26, ISO week W30) stamped its own run-time week
onto a challenge built FOR the W31 genesis week, and the #1198 fail-closed guard
then correctly hid the flagship engagement hook for the entire opening week. The
challenge can therefore be seeded any time before (or during) the genesis week; it
goes live exactly when that week becomes the current Pacific ISO week.

Grounding (ADR-104/105): every number in a label comes from the frozen file's own
test_specs — nothing invented. Weight is excluded as a subject by the standing
predict-the-week rule (levers and leading signals, never the outcome scale —
see deploy/current_challenge.sample.json). The freeze must verify (hash match)
before anything is emitted — entries are only "against the frozen targets" if the
targets provably ARE the frozen ones.

Usage:
    python3 deploy/build_genesis_predict_week.py            # dry-run: print the payload + upload cmd
    python3 deploy/build_genesis_predict_week.py --apply    # upload to s3://…/site/config/current_challenge.json
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "deploy"))

import genesis_prereg_stamp  # noqa: E402

REGION = "us-west-2"
S3_BUCKET = "matthew-life-platform"
CHALLENGE_KEY = "site/config/current_challenge.json"

# The presentation rule (#976) — the challenge is a public artifact too.
BANNED_TOKENS = ("cycle", "reset", "restart", "attempt", "last time", "previous", "this time", "once more", "back on")

# The predict-the-week house rule: levers/leading signals only, never the outcome scale.
EXCLUDED_METRICS = {"weight_lbs", "weight"}

# Reader-facing labels, grounded in the frozen test_spec's own threshold where one exists.
_LABELS = {
    "calories": lambda thr: f"logged daily calories against the {int(thr):,} kcal pre-registered line",
    "steps": lambda thr: f"daily steps against the {int(thr):,}-step pre-registered floor",
    "recovery": lambda thr: "next-day recovery — the pre-registered outcome signal",
}


def genesis_iso_week(genesis: str) -> str:
    """The ISO week id (e.g. '2026-W31') of the week containing experiment Day 1.

    #1952: derived from the genesis DATE, never `now()`. A genesis date is a plain
    calendar date, so no timezone enters here; the #1198 guard's PT wall-clock
    comparison happens serve-side, against this stamped value.
    """
    iso = date.fromisoformat(genesis).isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def evaluate_predict_week_state(genesis: str, today_pt: date, active) -> tuple:
    """Restart-verify semantics for GET /api/predict_week (#1952). Returns (ok, detail).

    - `active` is None (endpoint unreachable/unparseable) -> FAIL: the verifier
      never read the surface, so no verdict was earned.
    - today before genesis -> the pre-start countdown: dark is CORRECT (#931), pass.
    - today inside the genesis ISO week -> the opening-week hook must be live:
      active must be true, else FAIL (the exact cycle-11 dark-week regression).
    - after the genesis week -> pass: weekly re-seeds are a standing manual step,
      outside the reset verifier's scope.
    """
    week = genesis_iso_week(genesis)
    t_iso = today_pt.isocalendar()
    today_week = f"{t_iso[0]}-W{t_iso[1]:02d}"
    if active is None:
        return False, "/api/predict_week unreachable or unparseable — no verdict earned"
    if today_pt < date.fromisoformat(genesis):
        note = " (note: a challenge is unexpectedly live pre-genesis)" if active else ""
        return True, f"pre-genesis countdown (genesis {genesis}) — dark is correct{note}"
    if today_week == week:
        if active:
            return True, f"genesis week {week} and the challenge is live"
        return False, f"genesis week {week} but /api/predict_week is dark (active:false) — the opening-week hook is hidden (#1952)"
    return True, f"genesis week {week} has ended (today is {today_week}) — weekly re-seeding is outside the reset verifier"


def derive_predict_metrics(frozen: dict, cap: int = 2) -> list:
    """Levers/signals straight from the frozen hypotheses' test_specs, in freeze
    order, deduped, weight excluded, capped at the house 1-2 per week."""
    out, seen = [], set()
    for hyp in frozen.get("hypotheses", []):
        spec = hyp.get("test_spec") or {}
        candidates = [
            (spec.get("condition_metric"), spec.get("condition_threshold")),
            (spec.get("outcome_metric"), None),
        ]
        for metric, thr in candidates:
            m = (metric or "").strip().lower()
            if not m or m in seen or m in EXCLUDED_METRICS:
                continue
            seen.add(m)
            label_fn = _LABELS.get(m)
            label = label_fn(thr) if (label_fn and thr is not None) else (label_fn(0) if label_fn else f"daily {m} (pre-registered signal)")
            out.append({"key": m, "label": label})
            if len(out) >= cap:
                return out
    return out


def build_challenge(frozen: dict, stamp: dict, genesis: str = None) -> dict:
    frozen_genesis = (frozen.get("genesis") or "").strip() or None
    genesis = (genesis or "").strip() or frozen_genesis
    if not genesis:
        raise SystemExit("No genesis date: pass --genesis (or freeze one into the pre-registration's 'genesis' field).")
    if frozen_genesis and genesis != frozen_genesis:
        raise SystemExit(
            f"--genesis {genesis} disagrees with the frozen pre-registration's own genesis {frozen_genesis} — "
            "refusing to stamp a challenge for a week the freeze does not cover."
        )
    metrics = derive_predict_metrics(frozen)
    if not metrics:
        raise SystemExit("No usable predict_metrics could be derived from the frozen hypotheses — refusing to emit an empty subject.")
    challenge = {
        "week_id": genesis_iso_week(genesis),
        "title": "The opening week — the board is on the record",
        "predict_metrics": metrics,
        "result": None,
        # #1378 provenance: readers' entries are placed against THE frozen record.
        "prereg_sha256": stamp["sha256"],
        "prereg_url": stamp["public_artifact_url"],
        "note": "Subjects derive from the pre-registered hypotheses' own test specs — verify the freeze via prereg_url + prereg_sha256.",
    }
    low = json.dumps(challenge).lower()
    hits = sorted({tok for tok in BANNED_TOKENS if tok in low})
    if hits:
        raise SystemExit(f"presentation rule violation in the challenge payload: {hits}")
    return challenge


def main():
    ap = argparse.ArgumentParser(description="Emit/upload the genesis-week predict-the-week subject from the frozen pre-registration")
    ap.add_argument("--apply", action="store_true", help="upload to S3 (default: dry-run print)")
    ap.add_argument(
        "--genesis",
        default=None,
        help="Experiment Day 1 (YYYY-MM-DD). Default: the frozen pre-registration's own genesis, "
        "falling back to lambdas.common.constants.EXPERIMENT_START_DATE. week_id is the ISO week of THIS date, never the run time (#1952).",
    )
    args = ap.parse_args()

    frozen = json.loads(genesis_prereg_stamp.FROZEN_PATH.read_text())
    stamp = genesis_prereg_stamp.require_valid_stamp(frozen)
    genesis = args.genesis
    if not genesis and not (frozen.get("genesis") or "").strip():
        sys.path.insert(0, str(REPO_ROOT))
        from lambdas.common.constants import EXPERIMENT_START_DATE  # noqa: E402

        genesis = EXPERIMENT_START_DATE
    challenge = build_challenge(frozen, stamp, genesis=genesis)
    payload = json.dumps(challenge, indent=2) + "\n"
    print(payload)

    if not args.apply:
        print(f"DRY RUN — nothing uploaded. Re-run with --apply to write s3://{S3_BUCKET}/{CHALLENGE_KEY}")
        print(
            f"NB: week_id {challenge['week_id']} is the GENESIS week (#1952) — safe to upload any time before or during it; "
            "the widget serves it only while that week is the current Pacific ISO week (#1198)."
        )
        return 0

    import boto3

    s3 = boto3.client("s3", region_name=REGION)
    s3.put_object(Bucket=S3_BUCKET, Key=CHALLENGE_KEY, Body=payload.encode(), ContentType="application/json")
    print(f"WROTE s3://{S3_BUCKET}/{CHALLENGE_KEY} (week {challenge['week_id']}, {len(challenge['predict_metrics'])} subjects)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
