#!/usr/bin/env python3
"""qa_audit.py — /qa audit (#1450): recompute the QA coverage map and report drift.

The 2026-07-18 QA review needed a three-agent survey to answer "what does QA
actually cover?" (site/ vs manifest vs each sweep vs alarms). This script makes
that a deterministic, repeatable ritual: everything derives at run time from
tests/qa_manifest.py (THE page registry, #1426) + the repo's own sweep/workflow/
CDK sources — no hand lists, no cached numbers.

What it computes
  registry   site/ files vs manifest: unregistered pages, ghost entries, the
             EXEMPT ledger (every exemption carries its reason)
  sweeps     per-layer page coverage, each derived from a manifest facet:
             smoke / structural / static-core / leak-scan / visual (Playwright)
             / AI-vision (deploy tier-1 + weekly full, #1428) / WebKit weekly
             (tier<=2, #1434)
  uncovered  surface with NO check: pages without a visual def, manifest-declared
             /api endpoints no smoke status-check covers — enumerated, not counted
  silent_skips  every state where a page is skipped without failing anything:
             weekly-only AI vision, leak-scan exclusions, policy exemptions,
             budget-tier pauses (#1440), the #1452 QA-depth dial
  consumers  the derive-don't-relist contract: each sweep consumer must
             reference qa_manifest (a hand list re-growing is drift)
  workflows  the QA workflow inventory: cron, gating vs advisory (computed from
             rollback steps / pull_request triggers, not a hand list), failure
             surface, #1452 dial sensitivity
  alarms     QA-relevant CloudWatch alarms declared in cdk/stacks/*.py (#1445)
  drift      the hard-failure rollup (non-zero exit): unregistered/ghost pages,
             a consumer that stopped deriving, zero QA alarms found

Usage
  python3 scripts/qa_audit.py            # human report; exits 1 on hard drift
  python3 scripts/qa_audit.py --json     # machine-readable audit dict
  python3 scripts/qa_audit.py --live     # + read-only AWS reads (qa-level dial,
                                         #   budget tier, live alarm states);
                                         #   skipped gracefully without creds

Offline by default (repo-only, runs in seconds — the #1450 "~10 minutes
standalone" bar with room to spare). No Playwright, no Bedrock, no writes ever.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
for _p in (os.path.join(_REPO, "tests"), _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import qa_manifest  # noqa: E402

QA_LEVEL_PARAM = "/life-platform/qa-level"
BUDGET_TIER_PARAM = "/life-platform/budget-tier"

# The derive-don't-relist contract (#1426): every sweep consumer must read the
# manifest, never re-list pages. file → marker that proves derivation.
CONSUMER_CONTRACT = {
    os.path.join(_REPO, "tests", "visual_qa.py"): "qa_manifest",
    os.path.join(_REPO, "deploy", "smoke_test_site.sh"): "qa_manifest",
    os.path.join(_REPO, "deploy", "restart_verify_rendered.py"): "qa_manifest",
    os.path.join(_REPO, "tests", "site_review_bindings.py"): "qa_manifest",
    os.path.join(_REPO, ".claude", "commands", "qa.md"): "qa_manifest",
}

# QA workflow inventory surface (which files to characterize, not what they mean —
# gating/advisory/dial facts are computed from each file's own text below).
QA_WORKFLOWS = ["ci-cd.yml", "site-deploy.yml", "v4-gate.yml", "surface-drift.yml", "visual-qa.yml", "webkit-mobile-qa.yml"]

_QA_ALARM_TOKENS = ("qa", "smoke", "reader", "visual", "accuracy")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


# ── registry: site/ vs manifest ──────────────────────────────────────────────
def registry_section():
    unregistered, ghosts = qa_manifest.self_check()
    return {
        "pages_total": len(qa_manifest.MANIFEST),
        "unregistered": sorted(unregistered),
        "ghosts": sorted(ghosts),
        "exempt": dict(qa_manifest.EXEMPT),
    }


# ── sweeps: per-layer coverage, straight from the manifest facets ────────────
def sweeps_section():
    m = qa_manifest.MANIFEST
    total = len(m)
    visual = [p for p in m if p.get("visual")]
    tier1_visual = [p for p in visual if p["tier"] == 1]
    webkit = qa_manifest.visual_pages()
    webkit_sel = [p for p in webkit if (p.get("tier") or 0) <= 2]

    def row(pages, runs_at, gating):
        return {"pages": len(pages), "of": total, "runs_at": runs_at, "gating": gating}

    return {
        "smoke": row(qa_manifest.smoke_rows(), "every deploy + nightly qa_smoke_lambda", True),
        "structural": row(qa_manifest.structural_rows(), "every smoke run (#1429)", True),
        "static_core": row(qa_manifest.static_core_paths(), "every smoke run (#1395)", True),
        "leak_scan": row(qa_manifest.leak_scan_paths(), "restart_verify_rendered (reset verification)", False),
        "visual": row(visual, "every deploy (ci-cd/site-deploy) + daily standalone (#749)", True),
        "ai_vision_deploy": row(tier1_visual, "every deploy — --ai-qa-max-tier 1 (#1428)", True),
        "ai_vision_weekly": row(visual, "Sunday/manual standalone fire — full surface (#1428)", False),
        "webkit_weekly": row(webkit_sel, "Tuesdays 21:37 UTC — tier<=2, advisory (#1434)", False),
    }


# ── uncovered surface ────────────────────────────────────────────────────────
def smoke_checked_endpoints():
    """The /api endpoints the smoke script actually status-checks (parsed live —
    this is smoke's one remaining hand list, so the audit diffs it)."""
    text = _read(os.path.join(_REPO, "deploy", "smoke_test_site.sh"))
    return sorted(
        set(re.findall(r'check_status\s+"(/api/[^"|]+)"', text)) | set(re.findall(r'check_status\s+"[^"]*"\s+"\$BASE(/api/[^"]+)"', text))
    )


def uncovered_section():
    no_visual = sorted(p["path"] for p in qa_manifest.MANIFEST if not p.get("visual") and not p.get("visual_variants"))
    declared = sorted({d for p in qa_manifest.MANIFEST for d in (p.get("api_deps") or []) if d.startswith("/api/")})
    checked = set(smoke_checked_endpoints())
    return {
        "no_visual_def": no_visual,
        "api_deps_declared": len(declared),
        "api_deps_unchecked": [d for d in declared if d not in checked],
        "note": (
            "api_deps_unchecked = endpoints the manifest declares pages render from but no smoke status-check "
            "covers directly (they ARE exercised indirectly by the Playwright sweep loading the pages)"
        ),
    }


# ── silent skips ─────────────────────────────────────────────────────────────
def silent_skips_section(live=None):
    live = live or {}
    m = qa_manifest.MANIFEST
    weekly_only = [p["path"] for p in m if p.get("visual") and p["tier"] > 1]
    no_leak = [p["path"] for p in m if not p.get("leak_scan")]
    skips = [
        {
            "kind": "ai_vision_weekly_only",
            "detail": (
                f"{len(weekly_only)} tier>1 pages get AI-vision ONLY on the Sunday/manual standalone fire (#1428): "
                "deploy-time AI is tier-1 only"
            ),
            "pages": weekly_only,
        },
        {
            "kind": "leak_scan_excluded",
            "detail": f"{len(no_leak)} pages excluded from the reset leak scan (redirect stubs — targets are scanned)",
            "pages": no_leak,
        },
        {
            "kind": "exempt_by_policy",
            "detail": "; ".join(f"{k}: {v}" for k, v in qa_manifest.EXEMPT.items()),
            "pages": sorted(qa_manifest.EXEMPT),
        },
        {
            "kind": "budget_pause",
            "detail": (
                "budget tier >= 1 pauses the AI-vision + reader-truth layers (internal-QA band, ADR-125/#1440) — "
                "renders SKIPPED-BY-BUDGET + the QAPausedByBudget metric, deterministic sweeps unaffected"
                + (f"; live tier now: {live['budget_tier']}" if "budget_tier" in live else "")
            ),
        },
        {
            "kind": "qa_level_dial",
            "detail": (
                f"SSM {QA_LEVEL_PARAM} (#1452): lean strips AI/reader-truth from the standalone sweeps, off skips them; "
                "deploy-gating QA is structurally exempt; unreadable = fail-open standard"
                + (f"; live value now: {live['qa_level']}" if "qa_level" in live else "; live value not read (offline — pass --live)")
            ),
        },
        {
            "kind": "webkit_tier_cap",
            "detail": "the weekly WebKit run sweeps tier<=2 only (#1434) — tier-3/4 pages never see the iOS-Safari engine",
        },
    ]
    return skips


# ── consumers: the derive-don't-relist contract ──────────────────────────────
def consumer_drift(contract=None):
    drift = []
    for path, marker in (contract or CONSUMER_CONTRACT).items():
        if not os.path.exists(path):
            drift.append(f"{path}: MISSING (sweep consumer gone?)")
        elif marker not in _read(path):
            drift.append(f"{path}: no longer references {marker} — a hand list has re-grown (#1426 drift)")
    return drift


# ── workflows: gating vs advisory, failure surface, dial sensitivity ─────────
def workflows_section():
    out = []
    for name in QA_WORKFLOWS:
        path = os.path.join(_REPO, ".github", "workflows", name)
        if not os.path.exists(path):
            out.append({"file": name, "missing": True, "gating": None, "dial_sensitive": None})
            continue
        text = _read(path)
        gating = bool(re.search(r"rollback_(site|lambda)\.sh|cdk deploy", text)) or "pull_request:" in text
        surfaces = [
            s for s, tok in (("sns", "sns publish"), ("advisory-issue", "advisory-failure-issue"), ("rollback", "rollback_")) if tok in text
        ]
        out.append(
            {
                "file": name,
                "crons": re.findall(r"cron:\s*'([^']+)'", text),
                "invokes_visual_qa": "tests/visual_qa.py" in text,
                "invokes_smoke": "smoke_test_site.sh" in text,
                "gating": gating,
                "failure_surface": surfaces,
                "dial_sensitive": QA_LEVEL_PARAM in text,
            }
        )
    return out


# ── alarms: QA-relevant CloudWatch alarms declared in CDK ────────────────────
def alarms_section():
    stacks_dir = os.path.join(_REPO, "cdk", "stacks")
    all_alarms = []
    for fn in sorted(os.listdir(stacks_dir)):
        if not fn.endswith(".py"):
            continue
        text = _read(os.path.join(stacks_dir, fn))
        names = set(re.findall(r'alarm_name\s*=\s*f?"([^"]+)"', text))
        # the monitoring stack's local helpers take (alarm_id, alarm_name, ...) positionally
        names |= set(re.findall(r'_alarm\(\s*"[^"]+",\s*"([^"{}]+)"', text))
        for name in sorted(names):
            all_alarms.append({"name": name, "stack": fn})
    qa_alarms = [a for a in all_alarms if any(tok in a["name"].lower() for tok in _QA_ALARM_TOKENS)]
    return {"declared_total": len(all_alarms), "qa_alarms": qa_alarms}


# ── optional read-only live reads (--live) ───────────────────────────────────
def live_reads():
    out = {}
    try:
        import boto3

        ssm = boto3.client("ssm", region_name="us-west-2")
        for key, param, default in (
            ("qa_level", QA_LEVEL_PARAM, "standard (param unset — fail-open default)"),
            ("budget_tier", BUDGET_TIER_PARAM, None),
        ):
            try:
                out[key] = ssm.get_parameter(Name=param)["Parameter"]["Value"]
            except Exception as e:
                if default is not None and "ParameterNotFound" in str(e):
                    out[key] = default
                else:
                    out[f"{key}_error"] = str(e)[:120]
        cw = boto3.client("cloudwatch", region_name="us-west-2")
        alarms = cw.describe_alarms(AlarmNamePrefix="qa-", MaxRecords=50).get("MetricAlarms", [])
        out["qa_alarm_states"] = {a["AlarmName"]: a["StateValue"] for a in alarms}
    except Exception as e:
        out["error"] = f"live reads unavailable ({str(e)[:120]}) — offline audit is complete without them"
    return out


# ── rollup ───────────────────────────────────────────────────────────────────
def build_audit(live=False):
    live_data = live_reads() if live else {}
    reg = registry_section()
    consumers = consumer_drift()
    alarms = alarms_section()
    audit = {
        "pages": [{"path": p["path"], "tier": p["tier"], "content_class": p["content_class"]} for p in qa_manifest.MANIFEST],
        "registry": reg,
        "sweeps": sweeps_section(),
        "uncovered": uncovered_section(),
        "silent_skips": silent_skips_section(live_data),
        "consumers": {"contract": sorted(os.path.relpath(p, _REPO) for p in CONSUMER_CONTRACT), "drift": consumers},
        "workflows": workflows_section(),
        "alarms": alarms,
        "live": live_data,
    }
    audit["drift"] = hard_drift(audit)
    return audit


def hard_drift(audit):
    """The non-zero-exit class: real registry/derivation breaks, not judgement calls."""
    drift = []
    reg = audit["registry"]
    for p in reg["unregistered"]:
        drift.append(f"UNREGISTERED page under site/: {p} — add a qa_manifest entry or an EXEMPT reason")
    for p in reg["ghosts"]:
        drift.append(f"GHOST manifest entry (no file under site/): {p}")
    drift.extend(audit["consumers"]["drift"])
    if not audit["alarms"]["qa_alarms"]:
        drift.append("zero QA-relevant alarms declared in cdk/stacks/ — the #1445 qa-smoke alarms are gone")
    for w in audit["workflows"]:
        if w.get("missing"):
            drift.append(f"QA workflow missing: {w['file']}")
    return drift


def render(audit):
    L = []
    reg, sw, unc = audit["registry"], audit["sweeps"], audit["uncovered"]
    L.append("QA COVERAGE MAP — derived live from tests/qa_manifest.py + repo sources (#1450)")
    L.append(f"  pages registered: {reg['pages_total']} · unregistered: {len(reg['unregistered'])} · ghosts: {len(reg['ghosts'])}")
    for k, v in reg["exempt"].items():
        L.append(f"  exempt {k} — {v}")
    L.append("")
    L.append("  layer              pages   gating  runs at")
    for name, rowd in sw.items():
        L.append(f"  {name:<18} {rowd['pages']:>3}/{rowd['of']:<4} {'GATE  ' if rowd['gating'] else 'advis.'}  {rowd['runs_at']}")
    L.append("")
    L.append(f"UNCOVERED SURFACE (enumerated — {len(unc['no_visual_def'])} pages, {len(unc['api_deps_unchecked'])} endpoints)")
    for p in unc["no_visual_def"]:
        L.append(f"  no visual def: {p}")
    for d in unc["api_deps_unchecked"]:
        L.append(f"  api dep never status-checked by smoke: {d}")
    L.append(f"  ({unc['note']})")
    L.append("")
    L.append("SILENT-SKIP STATES")
    for s in audit["silent_skips"]:
        L.append(f"  [{s['kind']}] {s['detail']}")
    L.append("")
    L.append("QA WORKFLOWS")
    for w in audit["workflows"]:
        if w.get("missing"):
            L.append(f"  {w['file']}: MISSING")
            continue
        L.append(
            f"  {w['file']:<22} {'GATING  ' if w['gating'] else 'advisory'} crons={w['crons'] or ['-']} "
            f"fail-surface={w['failure_surface'] or ['none']} dial={'yes' if w['dial_sensitive'] else 'exempt'}"
        )
    L.append("")
    cons = audit["consumers"]
    L.append("CONSUMER DERIVATION (#1426 — every sweep consumer must read the manifest)")
    for c in cons["contract"]:
        L.append(f"  {c}: {'DRIFT' if any(c in d for d in cons['drift']) else 'derives from qa_manifest'}")
    L.append("")
    al = audit["alarms"]
    L.append(f"ALARM COVERAGE — {len(al['qa_alarms'])} QA-relevant of {al['declared_total']} declared in cdk/stacks/")
    for a in al["qa_alarms"]:
        L.append(f"  {a['name']}  ({a['stack']})")
    if audit.get("live"):
        L.append("")
        L.append(f"LIVE READS: {json.dumps(audit['live'], default=str)}")
    L.append("")
    drift = audit["drift"]
    L.append(f"DRIFT: {len(drift)} hard finding(s)" if drift else "DRIFT: none — registry, consumers, and alarms all hold")
    for d in drift:
        L.append(f"  !! {d}")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description="Recompute the QA coverage map + drift report (#1450)")
    ap.add_argument("--json", action="store_true", help="emit the audit dict as JSON")
    ap.add_argument("--live", action="store_true", help="add read-only AWS reads (dial, budget tier, alarm states)")
    args = ap.parse_args()
    audit = build_audit(live=args.live)
    print(json.dumps(audit, indent=2, default=str) if args.json else render(audit))
    sys.exit(1 if audit["drift"] else 0)


if __name__ == "__main__":
    main()
