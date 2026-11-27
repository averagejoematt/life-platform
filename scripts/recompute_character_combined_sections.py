"""scripts/recompute_character_combined_sections.py — the owner-condition sections of COMBINED_SUMMARY.md (#6224).

Owner conditions (2026-11-27), each a section the combined runner (``recompute_character_combined.py``) renders and,
where it is a safety property, a check that FAILS the run:

  * the complete planned final state, composite included: last ladder step == ``planned_states`` on every field; the
    public composite of every planned block == what ``/api/character`` serves for it (``recompute_character_verify``);
  * the 57 / 58 reconciliation as a checked equation, no duplicates, every served event's disposition, the level
    badges and milestone rungs before → after;
  * what still responds to a poor measured day once XP debt is 0 (live counts);
  * exact write counts, live baselines, backups, rollback coverage, the silent outbound paths with their tests re-run on
    this tree, and the apply commands that refuse without the exact approved plan id.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from typing import Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SILENT_TESTS = "tests/test_reconstructed_events_silent_6224.py"
# outbound path → the test (in SILENT_TESTS) that proves a reconstructed or re-dated event stays silent on it
SILENT_PATHS = (
    (
        "every public route's view (no provenance, no reconstructed event)",
        "test_a_public_view_carries_no_provenance_and_no_reconstructed_event",
    ),
    ("the buddy file", "test_the_buddy_file_serialises_no_provenance_and_no_reconstructed_event"),
    ("the digest recipients and the coach triggers (re-dated rung)", "test_a_redated_level_rung_reaches_no_digest_recipient_and_no_coach"),
    (
        "  control: a genuinely new rung still mails and triggers",
        "test_must_fail_control_a_genuinely_new_level_rung_still_mails_and_triggers",
    ),
    ("the milestone sweep (historical crossing written unannounced)", "test_the_sweep_writes_a_historical_level_crossing_unannounced"),
    ("the chronicle packet", "test_the_chronicle_packet_lists_no_reconstructed_event_as_this_weeks"),
    ("the story dossier", "test_the_story_dossier_lists_no_reconstructed_event"),
    ("/api/character_stats timeline", "test_character_stats_timeline_lists_no_reconstructed_event"),
    ("the owner's emails (method 1)", "test_the_owners_emails_read_method_one_which_holds_no_reconstructed_event"),
    ("idempotence: a second dry run after an apply", "test_a_second_dry_run_after_an_apply_plans_no_write_and_doubles_no_event"),
    ("the route walk (no provenance key on any public route)", "test_no_public_route_carries_reconstructed_provenance"),
)
ROLLBACK_COVERAGE_TEST = (
    "tests/test_recompute_combined_6224.py::test_end_to_end_apply_verify_and_rollback_restore_every_item_byte_identically"
)


def preflights(out: str, plan_path: str) -> dict:
    """The read-only backup preconditions of both tools. PRIVATE: the private tool's own ``--preflight`` (ListObjectsV2
    on its backup prefix, GetBucketVersioning — no write). PUBLIC: the public tool writes its pre-image export as a LOCAL
    file in its ``--out`` directory; the check is that the directory exists, is writable (an access check, not a write)
    and lies outside the repo."""
    import json

    cp = subprocess.run(
        [
            sys.executable,
            "scripts/recompute_character_private.py",
            "--out",
            os.path.join(out, "preflight"),
            "--preflight",
            "--plan-in",
            plan_path,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    try:
        private = json.loads(cp.stdout)
    except ValueError:
        private = {"ok": False, "error": (cp.stderr or cp.stdout)[-800:]}
    pub_dir = os.path.realpath(os.path.join(out, "public"))
    root = os.path.realpath(ROOT)
    public = {
        "location": f"local file {pub_dir}/export_<phase>_<ts>.json (not S3)",
        "directory_exists": os.path.isdir(pub_dir),
        "writable": os.access(pub_dir, os.W_OK),
        "outside_repo": not (pub_dir == root or pub_dir.startswith(root + os.sep)),
        "copy_to": "after each phase, copy the export (and SUMMARY/manifest) beside the private backup or another durable "
        "private store — not automated; the rollback reads the local file",
    }
    public["ok"] = public["directory_exists"] and public["writable"] and public["outside_repo"]
    return {"private": private, "public": public}


def preflight_lines(c: dict) -> list:
    pf = c.get("preflight") or {}
    pv, pb = pf.get("private") or {}, pf.get("public") or {}
    return [
        f"- PRIVATE preflight (`recompute_character_private.py --preflight`, read-only): ok={pv.get('ok')}; "
        f"{pv.get('verified_read_only') or pv.get('error')}.",
        "  - What a read cannot prove (verbatim): " + "; ".join(pv.get("unverifiable_without_a_write") or ["(not reported)"]),
        f"- PUBLIC preflight: ok={pb.get('ok')}; the pre-image is a {pb.get('location')}; directory exists "
        f"{pb.get('directory_exists')}, writable {pb.get('writable')}, outside the repo {pb.get('outside_repo')}. "
        f"Copy: {pb.get('copy_to')}.",
    ]


def run_silent_tests() -> dict:
    """Re-run the silent-path tests on this tree: {test name: PASSED | FAILED | missing}."""
    cp = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-rA", "-p", "no:cacheprovider", SILENT_TESTS], cwd=ROOT, capture_output=True, text=True
    )
    got: dict = {}
    for status, name in re.findall(r"^(PASSED|FAILED|ERROR) \S+::(\w+)", cp.stdout, flags=re.M):
        got[name] = status
    return {name: got.get(name, "missing") for _label, name in SILENT_PATHS}


def failures(c: dict, preliminary: bool) -> list:
    """The verification failures that fail the combined run (on top of the attribution's)."""
    v, fs = c.get("verification") or {}, c.get("final_state") or {}
    out = list((v.get("reconciliation") or {}).get("failures") or [])
    pc = v.get("public_composite") or {}
    if pc.get("mismatches"):
        out.append(f"public composite differs from /api/character on {len(pc['mismatches'])} date(s)")
    if fs.get("mismatches"):
        out.append(f"last ladder step differs from planned_states on {len(fs['mismatches'])} field(s)")
    pf = c.get("preflight") or {}
    if pf and not ((pf.get("private") or {}).get("ok") and (pf.get("public") or {}).get("ok")):
        out.append("a backup preflight did not pass")
    if fs.get("status") == "pending" and not preliminary:
        out.append("planned_states (the private final-state reader) is missing: the private composite is unverified")
    bad = [n for n, s in (c.get("silent_tests") or {}).items() if s != "PASSED"]
    if c.get("silent_tests") is not None and bad:
        out.append(f"{len(bad)} silent-path test(s) did not pass")
    return out


def final_state_lines(c: dict) -> list:
    fs, pc = c.get("final_state") or {}, (c.get("verification") or {}).get("public_composite") or {}
    if fs.get("status") == "pending":
        priv = (
            f"- PRIVATE: **PENDING** — the private tool's `planned_states(path)` reader has not landed, so the last ladder "
            f"step is not yet compared on every field (composite and events included) across the {fs.get('dates')} dates. "
            "A final (non-preliminary) run FAILS on this. The site API cannot stand in for it: the composite rule is inline "
            "in `web.site_api_character.character()` (no callable function) and that route serves only the PUBLIC variant "
            "(`character_privacy.public_sheets` fails closed on a private record), so the private composite of a planned "
            "sheet cannot be computed by the route without changing the site API. Not approximated."
        )
    else:
        priv = (
            f"- PRIVATE (supported reader): last ladder step == `planned_states` on every field (level, XP, composite, "
            f"pillars, events): {len(fs.get('mismatches') or []) == 0}; composite verified on {fs.get('composite_verified')} "
            f"of {fs.get('dates')} dates. `planned_states` is computed by the tool from the planned items, not copied from "
            "the ladder. The independent site-API second opinion cannot be taken on the PRIVATE composite: the rule is "
            "inline in `web.site_api_character.character()` (no callable function) and that route serves only the public "
            "variant (`character_privacy.public_sheets` fails closed on a private record) — computing it would need a "
            "site-API change (extracting the rule), not done and not approximated."
        )
    return [
        priv,
        f"- PUBLIC: composite verified on {pc.get('verified')} of {pc.get('dates')} dates — each planned v3 block's composite "
        f"as this recompute reports it equals what `/api/character` serves for that block. Rule: {pc.get('rule')}. Exact "
        "equality after the route's own rounding (one decimal).",
    ]


def reconciliation_lines(c: dict) -> list:
    r = (c.get("verification") or {}).get("reconciliation") or {}
    eq, sb = r.get("equation") or {}, r.get("served_before") or {}
    lines = [
        f"- Checked equation: reconstructed ({eq.get('reconstructed')}) == added ({eq.get('added')}) + moved ({eq.get('moved')}): "
        f"{eq.get('holds')}. The run fails if it does not hold.",
        "- Marked reconstructed without being ADDED (each is a MOVED event, marked with its served date as `redated_from`): "
        + (
            "; ".join(
                f"{m['key'][0]} {m['key'][1]} {m['key'][2]} {m['redated_from']} → {m['date']}" for m in r.get("marked_not_added") or []
            )
            or "none"
        )
        + ".",
        "- No ADDED or MOVED event lacks the marker, no KEPT event carries it, and every MOVED event's `redated_from` is its "
        "served date (each is a checked failure).",
        f"- Duplicates in the final public event set (one (who, type, level) on two dates): {len(r.get('duplicates') or {})}; "
        f"events both KEPT and ADDED: {len(r.get('kept_and_added') or [])}. The run fails on either.",
        f"- Events served before the containment switch: {sb.get('count')}; dispositions: "
        + ", ".join(f"{k} {v}" for k, v in sorted((sb.get("by_disposition") or {}).items()))
        + ". A served event with no disposition fails the run (per-event detail and the corrected per-date values: the "
        "private public/manifest.json `verification.reconciliation` and `level_credit.events`).",
        "- Level badges, first crossing before → after:",
    ]
    for k, v in sorted((r.get("level_badges") or {}).items()):
        lines.append(f"  - {k}: {v.get('before')} → {v.get('after')} ({v.get('status')})")
    lines.append("- Level-milestone rungs, first crossing before → after:")
    for k, v in sorted((r.get("level_milestones") or {}).items(), key=lambda kv: int(kv[0].split("_")[-1])):
        lines.append(f"  - {k}: {v.get('before')} → {v.get('after')} ({v.get('status')})")
    return lines


def responsiveness_lines(c: dict) -> list:
    rs = (c.get("verification") or {}).get("responsiveness") or {}
    return [
        "The amended rule (character_engine v1.10.0, #6293): XP never falls and carries no debt — a measured low day earns 0 "
        "XP instead of a negative balance. Nothing else is suppressed: a pillar's raw score is the day's measurement; its "
        "level follows the EMA target and FALLS after `level_down_streak_days` (7; per-tier overrides 5 / 7 / 10 / 14 / 21) "
        "consecutive measured days below it, once the level-down shield (`xp_buffer`, drained by measured low days, never by "
        "silence) is below its threshold, with the longer tier-boundary streak to cross a tier; a held day (no signal) holds "
        "both streaks. The composite is the mean of the scored pillars' raw scores; Consistency is recomputed from the "
        "public pillars' history.",
        "- Synthetic chain (tests/test_public_responds_6224.py, with a must-fail flat variant): under v3 a poor measured day "
        "lowers the pillar raw score, the composite and Consistency at once; sustained poor days lower the pillar level; "
        "XP never falls and debt stays 0.",
        f"- Live preliminary run, after the recompute, {rs.get('dates')} dates: a public pillar level goes DOWN day-over-day on "
        f"{rs.get('level_down_dates')} dates; a public pillar raw score on {rs.get('raw_down_dates')}; the composite on "
        f"{rs.get('composite_down_dates')}. XP falls on {rs.get('xp_falls')} dates; XP debt non-zero on {rs.get('xp_debt_nonzero')}.",
        "  - per pillar (level down / raw down): "
        + ", ".join(f"{p} {v['level_down']} / {v['raw_down']}" for p, v in (rs.get("by_pillar") or {}).items()),
    ]


def operations_lines(c: dict) -> list:
    p, pub, bl = c["private"], c["public"], c.get("baselines") or {}
    pc = p["counts"]
    silent = c.get("silent_tests")
    lines = [
        "**Write counts (exact).** Private plan `"
        + str(p["plan_id"])
        + "`: "
        + "; ".join(f"`{k}` {v.get('rows_to_write')}" for k, v in sorted(pc.items()) if isinstance(v, dict))
        + f". Public plan `{pub['public_plan_id']}`: "
        + "; ".join(f"`{k.split('#SOURCE#')[-1]}` {v}" for k, v in sorted(pub["by_partition"].items()))
        + " (only the `public` attribute) + 1 correction-ledger item.",
        "",
        "**Live baselines.** PRIVATE compares against the stored private rows: "
        + "; ".join(f"`{k}` {v.get('rows_read')} rows read" for k, v in sorted(pc.items()) if isinstance(v, dict))
        + f". PUBLIC compares against the stored `public` block as served before the containment switch: {bl.get('public_dates_with_stored_block')} "
        f"of {bl.get('public_dates')} dates carry one (the rest serve nothing today).",
        "",
        "**Backups (pre-images, written and re-read before the first write).**",
        "- PRIVATE: a local `export.json` (+ `.sha256`) and `s3://…/backups/character-private-recompute/<plan_id>/<phase>-<ts>/export.json` "
        "(conditional put, never overwrites); each entry is the FULL stored item of every row the phase writes, with its digest.",
        "- PUBLIC: `export_<phase>_<ts>.json` in the public --out; each entry is the item's previous `public` attribute (or its "
        "absence) and its method-1 fingerprint, for every item the phase writes, plus the ledger item's pre-image.",
        *preflight_lines(c),
        f"- Rollback coverage: each tool's export covers exactly its write set (asserted: {ROLLBACK_COVERAGE_TEST}); rollback "
        "order PUBLIC first, then PRIVATE; every item byte-identical after both.",
        "",
        "**Historical-notification suppression (outbound paths proven silent for reconstructed / re-dated events), re-run on "
        "this tree:**",
    ]
    for label, name in SILENT_PATHS:
        lines.append(f"- {label}: `{name}` — {(silent or {}).get(name, 'not run (--skip-tests)')}")
    lines += [
        "",
        "**Exact-plan approval before any production write.**",
        f"1. `python3 scripts/recompute_character_private.py --apply --plan-in <out>/private/plan.json --phase sheets` (then "
        f"`--phase receipts`), each with `--approved-plan-id {p['plan_id']}` — REFUSES (exit 4, before any backup or write) "
        "unless the id equals the plan file's and the id re-derived from the live rows (tested through the CLI: "
        "tests/test_recompute_combined_6224.py::test_the_private_apply_refuses_without_the_exact_approved_plan_id).",
        f"2. `python3 scripts/backfill_public_variant.py --apply --plan-in <out>/private/plan.json --approved-public-plan-id "
        f"{pub['public_plan_id']} --phase pre-merge` (then `--phase post-merge`) — REFUSES unless the approved id equals the "
        "recomputed one AND every live row is exactly the approved private plan's planned row (tested: "
        "tests/test_recompute_combined_6224.py::test_the_public_apply_refusal_names_the_approval_and_the_live_rows).",
        "3. Both `--verify` at 0 planned writes.",
    ]
    return lines


def baselines(pman: dict) -> dict:
    rows = pman.get("character") or []
    return {
        "public_dates": len(rows),
        "public_dates_with_stored_block": sum(1 for r in rows if str(r.get("before_basis", "")).startswith("stored public block")),
    }


def final_state(pman: dict) -> Optional[dict]:
    return ((pman.get("attribution") or {}).get("method") or {}).get("final_state")
