#!/usr/bin/env python3
"""
coach_sim_replay.py — the $0 half of the coach-sim measure (#2539).

WHAT THIS IS. ``coach_chat_sim.py`` generates a corpus by talking to Bedrock: ~$3.73 and
~25 minutes a run. ``coach_sim_analyze.py`` then computes deterministic metrics AND runs
a three-judge blind panel over it. This script is the deterministic half alone, pointed
at a corpus that already exists on disk. It calls no model, spends nothing, and finishes
in under a second, which is what makes it something that can run unattended.

It exists because the expensive layer cannot be a gate. The AI ceiling is $85 base — an
$115 dated window for August 2026 only — and the month is already projecting over it
(ADR-063/133). Gating every PR on a $3.73 panel would spend more measuring the coaches
than running them, and would push the tier ladder into pausing reader-facing narratives
to pay for a dev metric, which is the audience ordering ADR-125 exists to forbid. So the
panel is on demand, and this — the part that costs nothing — is the part that repeats.

ADVISORY, AND IT HAS NEVER BEEN ARMED. Per the ADR-108 promotion pattern this reports and
exits 0. ``--strict`` exists so a future decision to promote it is a flag flip with a
measured flag-rate behind it, not a rewrite. Nothing in CI passes ``--strict`` today.

WHAT IT DOES NOT DO. It does not discover anything. The deterministic layer would have
missed the corpus's loudest finding — rhetorical symmetry was 25% of the judges' 2,404
free-text tells while the deterministic detector matched 9 times in 536 replies (#2537).
These metrics are a tripwire for regressions in signals already known. The panel is how
new tells are found, and dropping it because this is cheaper is the mistake this docstring
is here to prevent.

THE CORPUS IS PINNED BY MANIFEST, NOT BY CONTENT. Real run artifacts carry Matthew's
health facts (the AUTHORITATIVE FACTS block is real), and this repo is public, so no real
corpus is committed. What is committed is a small synthetic fixture — enough to prove the
metric code runs and to keep it honest in CI — plus, for a real run, a manifest of
sha256 + counts written into the scoreboard row. That is what lets a later run say "I
replayed the same bytes" without publishing them.

The metric functions are IMPORTED from ``coach_sim_analyze`` / ``coach_sim_shapes``, never
reimplemented. A harness that hand-rebuilds the thing it measures drifts from it silently
and then reports the drift as a finding — the failure this harness already hit twice.

USAGE
    # $0 deterministic pass over the committed fixture
    python3 scripts/coach_sim_replay.py

    # ...over a real (out-of-repo, private) run directory, printing the trend
    python3 scripts/coach_sim_replay.py --corpus ~/sim-runs/2026-08-20 --compare

    # one-time: put the 2026-08-10 baseline in the scoreboard partition
    python3 scripts/coach_sim_replay.py --seed-baseline

    # persist this run beside it
    python3 scripts/coach_sim_replay.py --corpus ~/sim-runs/2026-08-20 --run-date 2026-08-20 --write
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import statistics
import sys
from datetime import datetime, timezone

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "lambdas"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from coach import coach_sim_scoreboard as sb  # noqa: E402  (path set above)
from coach_sim_analyze import conversation_metrics  # noqa: E402
from coach_sim_shapes import structural_collapse  # noqa: E402

DEFAULT_CORPUS = os.path.join(_ROOT, "tests", "fixtures", "coach_sim_replay")


def corpus_files(path: str) -> list:
    """Every .jsonl in a directory, or the single file itself. Sorted, so the manifest
    hash is a property of the corpus and not of the filesystem's iteration order."""
    if os.path.isdir(path):
        return sorted(p for p in glob.glob(os.path.join(path, "*.jsonl")) if not os.path.basename(p).startswith("pilot"))
    return [path]


def load_corpus(path: str) -> list:
    convos = []
    for f in corpus_files(path):
        with open(f) as fh:
            for line in fh:
                line = line.strip()
                if line:
                    convos.append(json.loads(line))
    return convos


def manifest(path: str, convos: list) -> dict:
    """Identity of the corpus without its contents.

    sha256 over the concatenated file bytes in sorted-name order. A later run quoting
    this manifest has demonstrably replayed the same corpus; a corpus that was quietly
    regenerated shows up as a different digest instead of as a mysterious metric shift.
    """
    digest = hashlib.sha256()
    names = []
    for f in corpus_files(path):
        names.append(os.path.basename(f))
        with open(f, "rb") as fh:
            digest.update(fh.read())
    return {
        "files": names,
        "sha256": digest.hexdigest(),
        "conversations": len(convos),
        "replies": sum(len(c.get("turns") or []) for c in convos),
    }


def deterministic_metrics(convos: list) -> dict:
    """The LLM-free subset, on the same keys the stored baseline uses.

    Empty corpus returns ``{}`` rather than zeros: no replies measured is not a 0%
    em-dash rate (ADR-104 — behavioural absence is absence, never a flattering zero).
    """
    rows = [conversation_metrics(c) for c in convos]
    per_turn = [t for r in rows for t in (r.get("per_turn") or [])]
    if not per_turn:
        return {}

    n = len(per_turn)
    isms = [i for t in per_turn for i in t["assistant_isms"]]
    collapse = structural_collapse(convos)
    return {
        "em_dash_reply_rate": round(sum(1 for t in per_turn if t["em_dashes"] > 0) / n, 3),
        "closing_question_rate": round(sum(1 for t in per_turn if t["closes_on_question"]) / n, 3),
        "formatting_violations": sum(t["formatting_hits"] for t in per_turn),
        "median_reply_chars": int(statistics.median([t["chars"] for t in per_turn])),
        "median_reply_inbound_ratio": round(statistics.median([t["char_ratio"] for t in per_turn]), 2),
        "assistant_ism_hits": len(isms),
        "assistant_ism_replies": sum(1 for t in per_turn if t["assistant_isms"]),
        "assistant_ism_kinds": sorted(set(isms)),
        "balanced_clause_replies": sum(1 for t in per_turn if t["balanced_classes"]),
        "not_x_but_y": sum(t["not_x_but_y"] for t in per_turn),
        # Worst archetype only: the full table belongs in the analyze report, the
        # scoreboard wants the one number a trend can be read off.
        "max_structural_collapse_ratio": (max((float(r["collapse_ratio"]) for r in collapse), default=None)),
        "replies_measured": n,
    }


def honesty_gate_counts(convos: list) -> dict:
    counts: dict = {}
    for c in convos:
        for t in c.get("turns") or []:
            status = str(t.get("status") or "unknown")
            counts[status] = counts.get(status, 0) + 1
    return counts


def _print_report(det: dict, man: dict, trend: dict | None) -> None:
    print(f"corpus: {man['conversations']} conversations / {man['replies']} replies  sha256={man['sha256'][:16]}…")
    print("\ndeterministic subset (LLM-free, $0):")
    for key, value in det.items():
        print(f"  {key:34s} {value}")
    if trend:
        print(f"\ntrend vs stored run {trend['from_run']}:")
        for key, row in trend["metrics"].items():
            if row["status"] != "measured":
                print(f"  {key:34s} unmeasured (current={row['current']!r} previous={row['previous']!r})")
            else:
                print(f"  {key:34s} {row['previous']} -> {row['current']}  ({row['change']:+}, {row['direction']})")
    print("\nlimitations carried with every stored run:")
    for lim in sb.KNOWN_LIMITATIONS:
        print(f"  [{lim['severity']}] {lim['id']}")
    print("\nposture: ADVISORY (ADR-108 promotion pattern) — this run never fails a build.")


def main() -> int:
    ap = argparse.ArgumentParser(description="LLM-free deterministic replay of a coach-sim corpus (#2539)")
    ap.add_argument("--corpus", default=DEFAULT_CORPUS, help="jsonl file or directory (default: the committed synthetic fixture)")
    ap.add_argument("--run-date", default=None, help="YYYY-MM-DD to store this run under (default: today, UTC)")
    ap.add_argument("--compare", action="store_true", help="read the stored baseline back from the scoreboard and print the trend")
    ap.add_argument("--write", action="store_true", help="persist this run to COACHSIM#scoreboard (implies --compare)")
    ap.add_argument("--seed-baseline", action="store_true", help="one-time: store the 2026-08-10 baseline, then exit")
    ap.add_argument("--json", dest="as_json", action="store_true", help="emit the payload as JSON instead of a report")
    ap.add_argument("--strict", action="store_true", help="reserved for the ADR-108 promotion — NOT armed anywhere today")
    args = ap.parse_args()

    if args.seed_baseline:
        result = sb.seed_baseline()
        print(json.dumps(result, indent=2, default=str))
        return 0

    convos = load_corpus(args.corpus)
    det = deterministic_metrics(convos)
    man = manifest(args.corpus, convos)

    trend = None
    if args.compare or args.write:
        # The whole point of box 5: the previous number comes out of the stored
        # scoreboard, not out of a scratch file someone has to still have.
        previous = sb.read_latest()
        if previous:
            trend = sb.delta_vs({"run_date": args.run_date or "pending", "deterministic": det}, previous)
        else:
            print("no stored run in COACHSIM#scoreboard — run --seed-baseline first", file=sys.stderr)

    if args.write:
        run_date = args.run_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        record = sb.build_run_record(
            run_date,
            deterministic=det,
            honesty_gate=honesty_gate_counts(convos),
            conversations=man["conversations"],
            replies=man["replies"],
            coaches=len({c.get("coach") for c in convos if c.get("coach")}),
            cost_usd={"corpus": 0.0, "panel": 0.0, "total": 0.0},
            corpus_manifest=man,
            label="deterministic_replay",
            source=os.path.abspath(args.corpus),
        )
        sb.write_run(record)
        print(f"wrote {sb.SCOREBOARD_PK} / RUN#{run_date}")

    if args.as_json:
        print(
            json.dumps({"deterministic": det, "manifest": man, "trend": trend, "limitations": sb.KNOWN_LIMITATIONS}, indent=2, default=str)
        )
    else:
        _print_report(det, man, trend)

    return 0  # advisory: never fails a build (see --strict)


if __name__ == "__main__":
    sys.exit(main())
