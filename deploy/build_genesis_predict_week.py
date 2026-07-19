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
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "deploy"))

import genesis_prereg_stamp  # noqa: E402

REGION = "us-west-2"
S3_BUCKET = "matthew-life-platform"
CHALLENGE_KEY = "site/config/current_challenge.json"
PT = ZoneInfo("America/Los_Angeles")

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


def current_iso_week(now: datetime = None) -> str:
    """Same PT ISO-week rule as site_api_social._current_iso_week (#1198 fail-closed)."""
    iso = (now or datetime.now(PT)).isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


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


def build_challenge(frozen: dict, stamp: dict, now: datetime = None) -> dict:
    metrics = derive_predict_metrics(frozen)
    if not metrics:
        raise SystemExit("No usable predict_metrics could be derived from the frozen hypotheses — refusing to emit an empty subject.")
    challenge = {
        "week_id": current_iso_week(now),
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
    args = ap.parse_args()

    frozen = json.loads(genesis_prereg_stamp.FROZEN_PATH.read_text())
    stamp = genesis_prereg_stamp.require_valid_stamp(frozen)
    challenge = build_challenge(frozen, stamp)
    payload = json.dumps(challenge, indent=2) + "\n"
    print(payload)

    if not args.apply:
        print(f"DRY RUN — nothing uploaded. Re-run with --apply to write s3://{S3_BUCKET}/{CHALLENGE_KEY}")
        print(
            "NB: the widget only serves this while week_id matches the CURRENT Pacific ISO week (#1198) — upload during the genesis week."
        )
        return 0

    import boto3

    s3 = boto3.client("s3", region_name=REGION)
    s3.put_object(Bucket=S3_BUCKET, Key=CHALLENGE_KEY, Body=payload.encode(), ContentType="application/json")
    print(f"WROTE s3://{S3_BUCKET}/{CHALLENGE_KEY} (week {challenge['week_id']}, {len(challenge['predict_metrics'])} subjects)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
