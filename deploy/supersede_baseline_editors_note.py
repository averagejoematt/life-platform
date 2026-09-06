#!/usr/bin/env python3
"""supersede_baseline_editors_note.py — the reusable editor's-note leg of the
SUPERSEDE REFLEX (#3390), generalised from the cycle-11 one-shot.

WHAT THE REFLEX IS
------------------
A reset that lands before the genesis-morning weigh-in has synced anchors the cycle
on `--override-weight-lbs` — the last real Withings reading. When the real Day-1
reading arrives, the served baseline is superseded everywhere the platform computes
it (DDB `PROFILE#v1` → `config/user_goals.json` → `constants.py` → the fleet).

The frozen pre-registration is deliberately NOT rewritten. It is SHA-256 stamped and
publicly verifiable; editing it is the edit-laundering the seal exists to prevent.
So `lambdas/operational/weight_truth_qa.assess_frozen_artifact_weights` (#1985)
enforces the other path: a frozen artifact may keep its original figure, it may not
present it un-reconciled. The reconciliation is an editor's note.

WHY THIS EXISTS RATHER THAN A SECOND ONE-SHOT
---------------------------------------------
`deploy/fix_prologue_part3_editors_note.py` repaired exactly one instance: 317.61 →
321.09 on `week-03`, `DATE#2026-07-26`, with the page key, the DDB sk, both figures
and three hand-patched S3 surfaces all hardcoded. Every reset can produce this
situation again, and cycle 16 did. Copying the one-shot per cycle is how a literal
goes stale behind a green check.

This module hardcodes NO weight, NO slug and NO DDB key. It:

  1. asks the GATE which artifacts are unreconciled — the same
     `FROZEN_ARTIFACT_SURFACES` list and the same `assess_frozen_artifact_weights`
     assessor qa-smoke runs, against the live site and the deployed-source
     `EXPERIMENT_BASELINE_WEIGHT_LBS`. Whatever reds is what gets repaired, so the
     repair set can never drift from the failing set (guard the SET, not the
     instance);
  2. resolves each flagged slug to its chronicle DDB record through the live
     `generated/journal/posts.json` manifest (`url` → `date` → `DATE#<date>`);
  3. splices a Margaret-Calloway editor's note into `content_html` /
     `content_markdown` and re-anchors the `stats_line` start figure — the DDB
     record ONLY.

WHY DDB-ONLY, WHEN THE ONE-SHOT PATCHED THREE SURFACES
-------------------------------------------------------
`deploy/restart_leadin_pages.py` already renders `generated/journal/posts/<slug>/
index.html` AND `generated/journal/posts.json` from these records, idempotently, with
the CloudFront invalidation. The one-shot hand-patched both because it predated that
wiring; doing it again would be a second renderer to keep in parity with the first
(the stored-artifact class in SITE_UPLEVEL_PLAYBOOK cuts both ways). So this script
writes the record and prints the one command that converges the served surfaces.

IDEMPOTENT AND STALENESS-AWARE
------------------------------
The note is wrapped in sentinel comments carrying a stamp of everything it asserts
(`supersede-note:start cycle-16|324.64->326.2`). A re-run with the SAME stamp is a
no-op; a re-run whose figures moved REPLACES the block instead of skipping it. Without
that, the second supersede in a cycle would leave a note quoting a now-superseded
baseline while `is_annotated()` stayed True — a silently-wrong page behind a green
check, which is the #3512 lesson one surface over.

ATTENDED BY DESIGN
------------------
Dry-run is the default and prints the exact prose. The note is permanent public
editorial copy in a named persona's voice: read it before `--apply`, exactly as the
cycle-11 note was read before it shipped.

Usage:
    python3 deploy/supersede_baseline_editors_note.py            # dry-run
    python3 deploy/supersede_baseline_editors_note.py --apply    # write DDB
    python3 deploy/restart_leadin_pages.py --apply               # then re-render
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (str(REPO_ROOT), str(REPO_ROOT / "lambdas")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

REGION = "us-west-2"
TABLE = "life-platform"
BUCKET = "matthew-life-platform"
CHRONICLE_PK = "USER#matthew#SOURCE#chronicle"
MANIFEST_KEY = "generated/journal/posts.json"
SITE_BASE_URL = "https://averagejoematt.com"

# Sentinel pair — identical in HTML and markdown, so ONE regex governs both forms and
# the stamp is machine-readable in each. Everything the note ASSERTS is in the stamp.
NOTE_START = "<!-- supersede-note:start {stamp} -->"
NOTE_END = "<!-- supersede-note:end -->"
# NB the stamp itself contains '->', so the id group cannot be `[^>]*` — it is bounded
# by the ' -->' terminator, non-greedily.
_NOTE_BLOCK_RE = re.compile(r"<!-- supersede-note:start (.*?) -->.*?<!-- supersede-note:end -->\n*", re.DOTALL)

# "324.64 lbs at the start" — the stats-line start figure, the one number in the
# header chrome that is a live claim rather than frozen prose.
_STATS_START_RE = re.compile(r"(\d+(?:\.\d+)?)(\s+lbs\s+at\s+the\s+start)", re.IGNORECASE)


def fmt(v: float) -> str:
    """326.2 → '326.2', 326.0 → '326'. Matches how the figures read in prose."""
    s = f"{float(v):.2f}".rstrip("0").rstrip(".")
    return s or "0"


def stamp_for(cycle: int | None, superseded: list[float], actual: float) -> str:
    """The idempotency + staleness stamp. Changing any asserted figure changes it."""
    cyc = f"cycle-{cycle}" if cycle is not None else "cycle-?"
    return f"{cyc}|{'/'.join(fmt(s) for s in sorted(superseded))}->{fmt(actual)}"


def note_text(superseded: list[float], actual: float, measured_on: str | None) -> str:
    """The reconciliation prose. Mirrors the cycle-11 note's approved voice and
    structure; every figure in it is passed in, none is written here."""
    was = " / ".join(f"{fmt(s)} lbs" for s in sorted(superseded))
    morning = f"On the morning of {measured_on}" if measured_on else "On the morning of Day 1"
    return (
        f"Filed before the genesis-morning weigh-in had synced, when {was} — the scale's last reading on record — "
        f"was the honest number to plan against. {morning} the scale read {fmt(actual)}, and that is the figure the "
        f"experiment actually runs on: the waypoints below re-anchor from it, and every live surface has carried it "
        f"since Day 1. The plan is preserved exactly as filed, its predictions included — they are graded against the "
        f"numbers they were written with, and the pre-registration they cite stays sealed and publicly verifiable. A "
        f"commitment device that could be quietly re-baselined would not be one."
    )


def render_note(text: str, stamp: str) -> tuple[str, str]:
    """(html, markdown) for the stamped Margaret-Calloway editor's note.

    The inner device is `restart_leadin_repair.render_editors_note` — imported, not
    re-typed, so the blockquote class and the byline stay one definition."""
    from restart_leadin_repair import render_editors_note

    inner_html, inner_md = render_editors_note(text)
    start, end = NOTE_START.format(stamp=stamp), NOTE_END
    return (f"{start}\n{inner_html}{end}\n", f"{start}\n{inner_md}{end}\n\n")


def splice(body: str, block: str, stamp: str) -> tuple[str, str]:
    """Insert/replace/keep the stamped note at the TOP of `body`.

    → (new_body, action) where action is 'added' | 'replaced' | 'unchanged'. A reader
    meets the reconciliation before the superseded figure, and a stale stamp is
    REPLACED rather than skipped."""
    m = _NOTE_BLOCK_RE.search(body)
    if m is None:
        return block + body, "added"
    if m.group(1).strip() == stamp:
        return body, "unchanged"
    return body[: m.start()] + block + body[m.end() :], "replaced"


def reanchor_stats_line(stats: str, superseded: list[float], actual: float) -> str:
    """Re-point 'N lbs at the start' at the live baseline — but ONLY when N is one of
    the figures the assessor actually flagged. Header chrome is a live claim; the
    article prose below it is frozen and never touched."""
    flagged = {fmt(s) for s in superseded}

    def sub(m: re.Match) -> str:
        return f"{fmt(actual)}{m.group(2)}" if fmt(float(m.group(1))) in flagged else m.group(0)

    return _STATS_START_RE.sub(sub, stats or "")


def sk_for_url(manifest: dict, url: str) -> str | None:
    """Chronicle sk for a journal permalink, via the manifest the site itself serves."""
    for post in manifest.get("posts", []) if isinstance(manifest, dict) else (manifest or []):
        if (post.get("url") or "").rstrip("/") == (url or "").rstrip("/"):
            d = post.get("date")
            return f"DATE#{d}" if d else None
    return None


def plan_repairs(surfaces: list[dict], baseline: float, manifest: dict, cycle: int | None) -> tuple[list[dict], list[str]]:
    """PURE. → (repairs, problems). The gate's own assessor decides the set."""
    from operational import weight_truth_qa

    findings = weight_truth_qa.assess_frozen_artifact_weights(surfaces, baseline)
    by_path = {s.get("path"): s for s in surfaces}
    repairs, problems = [], []
    for f in findings:
        path = f["page"]
        prose = (by_path.get(path) or {}).get("prose", "")
        cited = sorted(
            {w for w in weight_truth_qa._start_weights_cited_in(prose) if abs(w - baseline) > weight_truth_qa.SUPERSEDED_ANNOTATION_TOL_LBS}
        )
        sk = sk_for_url(manifest, path)
        if not sk:
            problems.append(f"{path}: no manifest entry — cannot resolve the chronicle record (ABORT rather than guess)")
            continue
        repairs.append({"path": path, "sk": sk, "superseded": cited, "stamp": stamp_for(cycle, cited, baseline)})
    return repairs, problems


# ── I/O ───────────────────────────────────────────────────────────────────────


def fetch_frozen_surfaces() -> tuple[list[dict], list[str]]:
    from operational import reader_truth_qa
    from operational.qa_check_reader_truth import FROZEN_ARTIFACT_SURFACES

    out, warns = [], []
    for path, name in FROZEN_ARTIFACT_SURFACES:
        try:
            req = urllib.request.Request(SITE_BASE_URL + path, headers={"User-Agent": "life-platform-supersede"})
            with urllib.request.urlopen(req, timeout=20) as r:
                body = r.read().decode("utf-8", "replace")
            out.append({"name": name, "path": path, "prose": reader_truth_qa.html_to_text(body), "frozen": True})
        except Exception as e:  # a fetch miss must never be read as "clean"
            warns.append(f"{name} ({path}) — fetch failed: {str(e)[:120]}")
    return out, warns


def fetch_manifest(s3) -> dict:
    return json.loads(s3.get_object(Bucket=BUCKET, Key=MANIFEST_KEY)["Body"].read().decode("utf-8"))


def apply_repair(ddb, repair: dict, actual: float, measured_on: str | None, dry: bool) -> bool:
    item = ddb.get_item(TableName=TABLE, Key={"pk": {"S": CHRONICLE_PK}, "sk": {"S": repair["sk"]}}).get("Item")
    if not item:
        print(f"  ✗ {repair['sk']} not found — aborting, nothing partial is written")
        return False

    text = note_text(repair["superseded"], actual, measured_on)
    note_html, note_md = render_note(text, repair["stamp"])
    html, act_h = splice(item["content_html"]["S"], note_html, repair["stamp"])
    md, act_m = splice(item["content_markdown"]["S"], note_md, repair["stamp"])
    stats_old = item.get("stats_line", {}).get("S", "")
    stats_new = reanchor_stats_line(stats_old, repair["superseded"], actual)

    print(f"  {repair['path']}  (chronicle {repair['sk']})")
    print(f"    note        {act_h} (html) / {act_m} (markdown) · stamp {repair['stamp']}")
    print(f"    stats_line  {stats_old!r}")
    print(f"            →   {stats_new!r}")
    if act_h == "unchanged" and act_m == "unchanged" and stats_new == stats_old:
        print("    ✓ already reconciled (no-op)")
        return True
    print(f"\n    ── the note, verbatim ──\n    {text}\n")
    if dry:
        return True
    ddb.update_item(
        TableName=TABLE,
        Key={"pk": {"S": CHRONICLE_PK}, "sk": {"S": repair["sk"]}},
        UpdateExpression="SET content_html = :h, content_markdown = :m, stats_line = :s",
        ExpressionAttributeValues={":h": {"S": html}, ":m": {"S": md}, ":s": {"S": stats_new}},
    )
    print("    ✓ record updated")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="write the DDB record (default: dry-run)")
    ap.add_argument("--measured-on", help="date the superseding reading was taken (default: the genesis date)")
    args = ap.parse_args()
    dry = not args.apply

    import boto3
    from common import constants

    baseline = float(constants.EXPERIMENT_BASELINE_WEIGHT_LBS)
    measured_on = args.measured_on or constants.EXPERIMENT_START_DATE

    s3 = boto3.client("s3", region_name=REGION)
    ddb = boto3.client("dynamodb", region_name=REGION)
    ssm = boto3.client("ssm", region_name=REGION)
    try:
        cycle = int(ssm.get_parameter(Name="/life-platform/experiment-cycle")["Parameter"]["Value"])
    except Exception:
        cycle = None

    print(f"{'DRY RUN' if dry else 'APPLYING'} — supersede editor's note · baseline {fmt(baseline)} lbs · cycle {cycle}\n")

    surfaces, warns = fetch_frozen_surfaces()
    for w in warns:
        print(f"  ! {w}")
    if warns:
        print("\nABORTED — a frozen surface could not be fetched. An unfetched page is unknown, not clean.")
        return 1

    repairs, problems = plan_repairs(surfaces, baseline, fetch_manifest(s3), cycle)
    for p in problems:
        print(f"  ! {p}")
    if problems:
        print("\nABORTED — see above.")
        return 1
    if not repairs:
        print(f"  ✓ {len(surfaces)} frozen artifact(s) already reconcile against {fmt(baseline)} lbs — nothing to do.")
        return 0

    ok = all(apply_repair(ddb, r, baseline, measured_on, dry) for r in repairs)
    print()
    if not ok:
        print("ABORTED — a record did not match its expected shape; nothing partial was written.")
        return 1
    if dry:
        print("Dry run only. Read the note above, then re-run with --apply.")
    else:
        print("Done. Re-render the served surfaces from the records:")
        print("    python3 deploy/restart_leadin_pages.py --apply")
    return 0


if __name__ == "__main__":
    sys.exit(main())
