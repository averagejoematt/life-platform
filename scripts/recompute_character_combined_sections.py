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


def preflights(out: str, plan_path: str, public_plan_id: str) -> dict:
    """The read-only backup preconditions of both tools. PRIVATE: the private tool's own ``--preflight`` (ListObjectsV2
    on its backup prefix, GetBucketVersioning — no write). PUBLIC: the public tool's own ``preflight``
    (``backfill_public_variant_backup``) on this run's public plan id — the same two reads, no write."""
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
    import backfill_public_variant_backup as BK
    import boto3

    try:  # the public tool's own preflight (read-only: ListObjectsV2 + GetBucketVersioning), on this run's public plan id
        region = os.environ.get("AWS_DEFAULT_REGION", "us-west-2")
        store = BK.S3Backups(boto3.client("s3", region_name=region), os.environ.get("S3_BUCKET", "matthew-life-platform"))
        public = BK.preflight(store, public_plan_id)
    except Exception as exc:  # noqa: BLE001 — reported, and the run fails on it
        public = {"ok": False, "error": str(exc)[-400:], "unverifiable_without_a_write": BK.UNVERIFIABLE}
    return {"private": private, "public": public}


def preflight_lines(c: dict) -> list:
    pf = c.get("preflight") or {}
    pv, pb = pf.get("private") or {}, pf.get("public") or {}
    return [
        f"- PRIVATE preflight (`recompute_character_private.py --preflight`, read-only): ok={pv.get('ok')}; "
        f"{pv.get('verified_read_only') or pv.get('error')}.",
        "  - What a read cannot prove (verbatim): " + "; ".join(pv.get("unverifiable_without_a_write") or ["(not reported)"]),
        f"- PUBLIC preflight (`backfill_public_variant.py --preflight`'s function, read-only): ok={pb.get('ok')}; "
        f"{pb.get('verified_read_only') or pb.get('error')}.",
        "  - What a read cannot prove (verbatim): " + "; ".join(pb.get("unverifiable_without_a_write") or ["(not reported)"]),
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
    if (c.get("unplanned_public") or {}).get("servable"):
        out.append(f"{c['unplanned_public']['servable']} stored public block(s) outside both plans would be served")
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
            f"mood, pillars, events): {len(fs.get('mismatches') or []) == 0}; composite verified on {fs.get('composite_verified')} "
            f"of {fs.get('dates')} dates. `planned_states` is computed by the tool from the planned items, not copied from "
            "the ladder. The independent site-API second opinion cannot be taken on the PRIVATE composite: the rule is "
            "inline in `web.site_api_character.character()` (no callable function) and that route serves only the public "
            "variant (`character_privacy.public_sheets` fails closed on a private record) — computing it would need a "
            "site-API change (extracting the rule), not done. The private composite is therefore verified through the "
            "supported reader (the tool's own calculation from the planned items, which the tool also self-checks against its "
            "last ladder step); no independent re-implementation of the rule was made."
        )
    return [
        priv,
        f"- PUBLIC: composite verified on {pc.get('verified')} of {pc.get('dates')} dates — each planned v3 block's composite "
        f"as this recompute reports it equals what `/api/character` serves for that block. Rule: {pc.get('rule')}. Exact "
        "equality after the route's own rounding (one decimal). No independent re-implementation of the rule was made.",
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
        *deploy_meaning_lines(c),
        "",
        "**When a public score is served — two independent conditions.** A public character number (overall level, tier, "
        "XP, XP debt, composite, mood, effects, level events, pillar levels) is served only when (1) the stored block is "
        "CURRENT-method (`character_privacy.older_method` is false: v3) AND (2) the global containment switch "
        '`PUBLIC_CHARACTER_SCORES_PENDING_RECOMPUTE` is off. Either one alone serves "being recalculated"; an '
        "older-method block also credits no level, badge, milestone or event. So a sheet the recompute missed, or a "
        'ROLLBACK of the public apply (which restores the older blocks), returns every affected date to "being '
        'recalculated", never to the old numbers — tested with the switch forced off '
        "(tests/test_recompute_combined_6224.py end-to-end; tests/test_tombstoned_public_blocks_6224.py, incl. the route "
        "walk's `--older-method` case).",
        "",
        "**Not changed (flagged):** `web/site_api_rollups.py` reads a method-1 field (`overall_score`) from raw sheets; "
        "no stored sheet carries it (0 of 177), so it serves nothing from the character partition.",
        "",
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
        f"- PRIVATE: `s3://<bucket>/backups/character-private-recompute/{p['plan_id']}/<phase>-<ts>/export.json` (conditional put, "
        "never overwrites) + a local `export.json` (+ `.sha256`); each entry is the FULL stored item of every row the phase "
        "writes, with its digest.",
        f"- PUBLIC: `s3://<bucket>/backups/character-public-recompute/{pub['public_plan_id']}/export_<phase>.json` (+ "
        "`.sha256`), conditional put (IfNoneMatch='*'), read back and hashed BEFORE the first write — a failure aborts with "
        "zero writes; a refused put continues only when the existing backup's content equals this export (a resumed apply). "
        "The local copy is kept in the public --out. Each entry is the item's previous `public` attribute (or its absence) "
        "and its method-1 fingerprint, for every item the phase writes, plus the ledger item's pre-image.",
        "- Neither backup is anonymously readable: `deploy/bucket_policy.json` grants public GetObject only on `site/*` and "
        "named `generated/*` paths; no statement names `backups/` (tested: "
        "tests/test_recompute_combined_6224.py::test_backups_are_not_anonymously_readable).",
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


def tradeoff_lines(c: dict) -> list:
    """The planned-rest trade-off for the owner's pending decision: counts and ranges only (sick-day dates stay private)."""
    t = (c.get("verification") or {}).get("rest_tradeoff") or {}
    f = t.get("fields") or {}
    lvl = (f.get("overall level") or {}).get("dates", 0)
    mv = f.get("movement raw") or {}
    worst = max((abs(x) for x in (mv.get("range") or [0])), default=0)
    affected = max((v.get("dates", 0) for v in f.values()), default=0)
    lines = [
        f"As built, the public score does not apply the rest allowance (sick days are owner-only; the public day is "
        f"restored as scored). In this window {t.get('dates_with_planned_rest', 0)} planned date(s) carry the private "
        f"allowance; applying it publicly (a what-if, computed here only, NOT shipped) would change {affected} date(s), "
        f"Movement raw by at most {worst}; "
        + ("no public overall level differs" if not lvl else f"the public overall level differs on {lvl} date(s)")
        + f"; level events added, removed or re-dated: {t.get('events_differ_dates', 0)} date(s)"
        + (
            f" (on {t.get('events_detail_only_dates')} date(s) the same event records a different detail)."
            if t.get("events_detail_only_dates")
            else "."
        ),
        "",
        "| public quantity | dates that differ, (a) as built vs (b) with the allowance | range (b − a) |",
        "|---|---|---|",
    ]
    for label, v in f.items():
        lines.append(f"| {label} | {v.get('dates')} | {v.get('range')} |")
    lines.append(
        f"| level events added, removed or re-dated | {t.get('events_differ_dates', 0)} | by pillar: {t.get('events_differ_by_pillar') or {}} |"
    )
    lines.append(
        f"| level events identical but a recorded detail differs (e.g. the event's level_score) | {t.get('events_detail_only_dates', 0)} | — |"
    )
    return lines


def interrupted_apply_lines() -> list:
    return [
        "| | PRIVATE (`recompute_character_private.py`) | PUBLIC (`backfill_public_variant.py`) |",
        "|---|---|---|",
        "| pre-image | ONE per plan: `backups/character-private-recompute/<plan_id>/export.json` + local + sha256, written "
        "once (IfNoneMatch) | one per phase: `backups/character-public-recompute/<public_plan_id>/export_<phase>.json` + "
        "`.sha256` + local, written once (IfNoneMatch) |",
        "| a second `--apply` of the same plan | re-verifies the existing pre-image, takes no second one, and COMPLETES only "
        "if every exported row is exactly its pre-image or exactly its planned value; otherwise writes nothing and points "
        "to rollback | continues only if the existing backup's content equals the export it is about to use — after any "
        "partial write the live pre-images differ, so a resumed partial apply always STOPS (zero writes): roll back from "
        "the S3 backup, then re-apply |",
        "| rollback | `--rollback <export> --apply` (its local export) | `--rollback s3://…/export_<phase>.json --apply` "
        "(sha256 verified first), post-merge phase before pre-merge |",
    ]


def mood_lines(c: dict) -> list:
    m = (c.get("verification") or {}).get("mood") or {}
    return [
        f"- PRIVATE (stored → planned, the supported state readers): {m.get('private_rewritten')} label(s) rewritten — "
        + ", ".join(f"{k}: {v}" for k, v in sorted((m.get("private_moves") or {}).items()))
        + ".",
        "- PUBLIC label on those dates after the recompute (v3 chain): "
        + ", ".join(f"{k}: {v}" for k, v in sorted((m.get("public_label_on_those_dates") or {}).items()))
        + f". Labels the public chain produces over the window: {', '.join(m.get('public_labels_produced') or [])}; "
        f"'dormant' produced publicly: {m.get('dormant_public')}.",
        f"- While the scores are pending, `/api/character` serves mood = {m.get('served_while_pending')} (the route's own "
        "code on the planned records: suppressed with the rest of the headline).",
    ]


# ── every stored item with a `public` block that neither plan covers (owner, 2026-11-27) ─────────────────────────────

PUBLIC_PARTITIONS = ("character_sheet", "character_receipt", "day_grade")


def publicly_servable(source: str, item: dict) -> bool:
    """Would the code on THIS tree serve anything public from ``item`` once the scores are live? (The public readers
    themselves: ``character_privacy.public_sheet``, the receipt route's ``_public_receipt``, ``day_grade_public``.)"""
    from common.numeric import decimals_to_float
    from health import character_privacy as CP, day_grade_public
    from web import site_api_character as ch

    rec = decimals_to_float(item)
    saved = CP.PUBLIC_CHARACTER_SCORES_PENDING_RECOMPUTE
    CP.PUBLIC_CHARACTER_SCORES_PENDING_RECOMPUTE = False
    try:
        if source == "character_sheet":
            return CP.public_sheet(rec, pending=False) is not None
        if source == "character_receipt":
            return ch._public_receipt({k: v for k, v in rec.items() if k not in ("pk", "sk")}) is not None
        return day_grade_public.public_grade(rec) is not None
    finally:
        CP.PUBLIC_CHARACTER_SCORES_PENDING_RECOMPUTE = saved


def why_skipped(item: dict) -> str:
    from experiment.phase_filter import singleton_visible

    if item.get("tombstone"):
        return "tombstoned"
    if not singleton_visible(item):
        return f"phase {item.get('phase')}"
    return "not in either plan"


def unplanned_public_items(items: dict, accounted: set) -> dict:
    """``items``: {source: [stored items]}; ``accounted``: {(source, sk)} every key a plan writes or the public dry run
    recomputed and found unchanged. Returns each stored item with a ``public`` block outside that set, why, and whether
    the public routes would serve it (the run FAILS on any servable one)."""
    rows = []
    for source, its in items.items():
        for it in its:
            if "public" not in it or (source, it["sk"]) in accounted:
                continue
            rows.append({"source": source, "date": it["sk"][5:], "why": why_skipped(it), "servable": publicly_servable(source, it)})
    return {"count": len(rows), "servable": sum(1 for r in rows if r["servable"]), "rows": rows}


def read_public_items() -> dict:
    """Read-only: every stored item of the three public-carrying partitions (DynamoDB Query, no write)."""
    import boto3
    from boto3.dynamodb.conditions import Key

    table = boto3.resource("dynamodb", region_name=os.environ.get("AWS_DEFAULT_REGION", "us-west-2")).Table(
        os.environ.get("TABLE_NAME", "life-platform")
    )
    out = {}
    for source in PUBLIC_PARTITIONS:
        items, kw = [], {"KeyConditionExpression": Key("pk").eq(f"USER#matthew#SOURCE#{source}")}
        while True:
            r = table.query(**kw)
            items += r["Items"]
            if "LastEvaluatedKey" not in r:
                break
            kw["ExclusiveStartKey"] = r["LastEvaluatedKey"]
        out[source] = items
    return out


def accounted_keys(out: str) -> set:
    import json

    priv = json.load(open(os.path.join(out, "private", "plan.json"), encoding="utf-8"))
    pman = json.load(open(os.path.join(out, "public", "manifest.json"), encoding="utf-8"))
    pub = json.load(open(os.path.join(out, "public", "plan.json"), encoding="utf-8"))
    keys = {(r["pk"].split("#SOURCE#")[-1], r["sk"]) for r in priv["rows"]}
    keys |= {(w["pk"].split("#SOURCE#")[-1], w["sk"]) for w in pub}
    keys |= {tuple(s.split(" ", 1)) for s in pman["plan"]["skipped_unchanged"]}
    return keys


def unplanned_lines(c: dict) -> list:
    u = c.get("unplanned_public") or {}
    lines = [
        f"- Stored items with a `public` block that NEITHER plan covers (not written, not recomputed-and-unchanged): "
        f"{u.get('count')}; publicly servable under this tree once the switch flips: {u.get('servable')} (the run FAILS on any)."
    ]
    for r in u.get("rows") or []:
        lines.append(
            f"  - {r['source']} {r['date']}: {r['why']} — the public routes will serve {'IT (FAIL)' if r['servable'] else 'nothing'}"
        )
    return lines


def version_counts(items: dict) -> dict:
    """{source: {public_method_version: count}} of the stored public blocks (read-only, from ``read_public_items``)."""
    out: dict = {}
    for source, its in items.items():
        for it in its:
            pub = it.get("public")
            if isinstance(pub, dict):
                v = str(pub.get("public_method_version"))
                out.setdefault(source, {})[v] = out.setdefault(source, {}).get(v, 0) + 1
    return out


def deploy_meaning_lines(c: dict) -> list:
    sv = c.get("stored_versions") or {}
    return [
        "**What changes at deploy (before the public apply).** Stored public blocks today: "
        + "; ".join(f"`{src}` " + ", ".join(f"{v} {n}" for v, n in sorted(vs.items())) for src, vs in sorted(sv.items()))
        + ". Every character serving path — the routes, `public_stats.json`, `character_stats.json`, `buddy/data.json`, "
        "the og card, the Ask context and the daily brief's published character block — reads through "
        '`character_privacy.public_sheet` / `public_headline`, which today serve every one of these blocks as "being '
        'recalculated" because the global switch is on. The only other readers of a stored character `public` block '
        "(`milestone_ledger`, `achievement_rules`) ask only whether it is the corrected chain (v3). So no surface shows a "
        "number from a v1/v2 block today, and nothing visible changes at deploy: the per-block rule adds a second, "
        "independent condition, not a new state.",
    ]
