#!/usr/bin/env python3
"""
scripts/surface_drift_gate.py — PR-time surface-drift gate (#1454).

THE PROBLEM: nothing stopped a PR from adding a page/route/cron/JS module with
zero QA registration — exactly how 44 pages and ~118-vs-documented-60 endpoints
drifted uncovered before #1426. This is the "did you also update the tests?"
question, asked by a machine on every PR, diff-aware: it compares the merge-base
of --base (origin/main) against HEAD and only ever blocks on surface the PR
itself ADDS. Pre-existing drift is reported as advisory (its enforcing gates
live elsewhere: tests/test_qa_manifest.py, deploy/sync_doc_metadata.py --check).

FOUR LEGS (one per surface type):

  PAGE   a new site/**/*.html (non-legacy) must be registered in
         tests/qa_manifest.py (or carry an EXEMPT reason there). Registration
         truth comes from qa_manifest.self_check() — reused, NOT reimplemented.

  ROUTE  a new route in lambdas/web/site_api_lambda.py's dispatcher (the
         three-mechanism union AST-discovered by
         deploy/sync_doc_metadata.discover_endpoint_paths — reused, NOT
         reimplemented) must have a schema baseline in tests/api_schemas/ or a
         dated ledger exemption. DEGRADES GRACEFULLY: while tests/api_schemas/
         does not exist (#1436 not yet landed), this leg is ADVISORY — it flips
         to blocking automatically the moment the baselines directory appears.

  CRON   a new EventBridge schedule under cdk/stacks/ (net count increase of
         Schedule.cron/rate/expression calls per file — an edited cadence alone
         does not trigger) requires EITHER a monitoring change in the same diff
         (cdk/stacks/monitoring_stack.py touched, or an alarm-constructor count
         increase in any changed stack file) OR a dated entry in
         docs/qa/SURFACE_DRIFT_EXEMPTIONS.md.

  JS     new files directly under site/assets/js/ are covered BY CONSTRUCTION —
         the #1432 import gate (scripts/import_site_js_graph.mjs) directory-
         scans that dir — so this leg (a) asserts that scan is still in place,
         and (b) fails any new site/ JS file OUTSIDE the scanned directory
         (the scan is non-recursive; such a file gets no full-parse coverage).

EXEMPTIONS are dated ledger entries in docs/qa/SURFACE_DRIFT_EXEMPTIONS.md —
explicit and reviewable, never silent. Pages may alternatively use the
qa_manifest EXEMPT dict (its reasons live next to the registry itself).

Every FAIL names the exact missing registration and the file to add it to.

USAGE:
  python3 scripts/surface_drift_gate.py                     # vs origin/main
  python3 scripts/surface_drift_gate.py --base origin/main  # explicit
  python3 scripts/surface_drift_gate.py --repo /path/to/clone

Exit 0 = clean (advisories allowed), exit 1 = at least one blocking finding.
Runs in .github/workflows/surface-drift.yml on every PR touching a surface
path. No AWS, no browser, stdlib only — seconds, not minutes.
"""
from __future__ import annotations

import argparse
import ast
import importlib.util
import os
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

SITE_API = "lambdas/web/site_api_lambda.py"
QA_MANIFEST = "tests/qa_manifest.py"
SCHEMA_DIR = "tests/api_schemas"
LEDGER = "docs/qa/SURFACE_DRIFT_EXEMPTIONS.md"
JS_SCAN_DIR = "site/assets/js"
IMPORT_GATE = "scripts/import_site_js_graph.mjs"
CDK_STACKS_DIR = "cdk/stacks"
MONITORING_STACK = "cdk/stacks/monitoring_stack.py"

_SCHEDULE_METHODS = {"cron", "rate", "expression"}  # events.Schedule.<method>(...)


@dataclass
class Finding:
    leg: str  # PAGE | ROUTE | CRON | JS
    severity: str  # "fail" | "advisory" | "ok"
    surface: str  # the specific page path / route / schedule / file
    message: str
    fix: str = ""  # the exact registration to add, and where


# ══════════════════════════════════════════════════════════════════════════════
# git + module plumbing (monkeypatch surface for tests — keep these module-level)
# ══════════════════════════════════════════════════════════════════════════════


def _git(repo: str, *args: str) -> str:
    return subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True, text=True).stdout


def merge_base(repo: str, base: str) -> str:
    return _git(repo, "merge-base", base, "HEAD").strip()


def changed_files(repo: str, mb: str) -> list:
    """[(status_letter, path)] for mb..HEAD; renames/copies report the NEW path."""
    rows = []
    for line in _git(repo, "diff", "--name-status", mb, "HEAD").splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        rows.append((parts[0][0], parts[-1]))
    return rows


def read_at(repo: str, rev: str, path: str) -> str | None:
    """File content at a git revision, or None if it does not exist there."""
    try:
        return _git(repo, "show", f"{rev}:{path}")
    except subprocess.CalledProcessError:
        return None


def read_worktree(repo: str, path: str) -> str | None:
    p = os.path.join(repo, path)
    if not os.path.isfile(p):
        return None
    with open(p, encoding="utf-8") as f:
        return f.read()


_MODULE_CACHE: dict = {}


def _load_module(repo: str, rel_path: str, alias: str):
    """Import a repo module by file path (works for scratch clones, not just this checkout)."""
    key = (repo, rel_path)
    if key not in _MODULE_CACHE:
        spec = importlib.util.spec_from_file_location(alias, os.path.join(repo, rel_path))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _MODULE_CACHE[key] = mod
    return _MODULE_CACHE[key]


def _load_qa_manifest(repo: str):
    return _load_module(repo, QA_MANIFEST, "qa_manifest_for_surface_drift")


def _load_sync_doc_metadata(repo: str):
    return _load_module(repo, "deploy/sync_doc_metadata.py", "sync_doc_metadata_for_surface_drift")


# ══════════════════════════════════════════════════════════════════════════════
# Exemptions ledger — dated entries, never silent
# ══════════════════════════════════════════════════════════════════════════════

_LEDGER_LINE = re.compile(
    r"^\s*-\s*(?P<date>\d{4}-\d{2}-\d{2})\s*\|\s*(?P<kind>page|route|cron|js)\s*\|\s*(?P<token>\S+)\s*\|\s*(?P<reason>\S.*?)\s*$"
)


def parse_exemptions(text: str) -> list:
    """Dated `- YYYY-MM-DD | kind | token | reason` lines; anything else is prose, ignored."""
    return [m.groupdict() for m in (_LEDGER_LINE.match(line) for line in (text or "").splitlines()) if m]


def exemption_for(exemptions: list, kind: str, key: str):
    """Exact-or-prefix token match (a token of `cdk/stacks/x.py` covers `cdk/stacks/x.py:<sig>`)."""
    for e in exemptions:
        if e["kind"] == kind and (key == e["token"] or key.startswith(e["token"])):
            return e
    return None


# ══════════════════════════════════════════════════════════════════════════════
# Pure decision legs (unit-tested with fabricated inputs — no git, no filesystem)
# ══════════════════════════════════════════════════════════════════════════════


def page_path_for(file_path: str) -> str | None:
    """site/x/y/index.html → /x/y/ · site/foo.html → /foo.html (qa_manifest.site_files normalization)."""
    if not file_path.startswith("site/") or not file_path.endswith(".html"):
        return None
    rel = file_path.removeprefix("site/")
    if rel.split("/")[0] == "legacy":
        return None
    if rel == "index.html" or rel.endswith("/index.html"):
        return "/" + rel.removesuffix("index.html")
    return "/" + rel


def page_leg(added_pages: set, unregistered: set, ghosts: set, exemptions: list) -> list:
    findings = []
    for p in sorted(added_pages):
        if p not in unregistered:
            findings.append(Finding("PAGE", "ok", p, "registered in tests/qa_manifest.py (or EXEMPT there)"))
            continue
        ex = exemption_for(exemptions, "page", p)
        if ex:
            findings.append(Finding("PAGE", "ok", p, f"ledger-exempted {ex['date']}: {ex['reason']}"))
            continue
        findings.append(
            Finding(
                "PAGE",
                "fail",
                p,
                f"new site page {p} is not registered in {QA_MANIFEST}",
                f"add a manifest entry for {p!r} to _CURATED in {QA_MANIFEST} (path/name/tier/api_deps/visual), "
                f"or an EXEMPT[{p!r}] reason there if it is deliberately outside the QA sweep, "
                f"or a dated 'page' entry in {LEDGER}",
            )
        )
    for p in sorted(unregistered - added_pages):
        findings.append(
            Finding(
                "PAGE",
                "advisory",
                p,
                "pre-existing unregistered page (not added by this PR) — "
                "tests/test_qa_manifest.py::test_no_unregistered_pages is the enforcing gate for it",
            )
        )
    for p in sorted(ghosts):
        findings.append(Finding("PAGE", "advisory", p, f"ghost manifest entry (no file under site/) — clean up {QA_MANIFEST}"))
    return findings


def route_slug(route: str) -> str:
    return route.strip("/").replace("/", "_")


def schema_candidates(route: str) -> set:
    """Schema-file stems accepted as this route's baseline: 'api_foo_bar' and 'foo_bar'.

    #1436 (PR #1502) has not merged at time of writing, so the exact naming
    convention of tests/api_schemas/ is not yet pinned — accept both obvious
    spellings; tighten here (one place) once the baselines land.
    """
    slug = route_slug(route)
    cands = {slug}
    if slug.startswith("api_"):
        cands.add(slug.removeprefix("api_"))
    return cands


def route_leg(new_routes: set, schema_stems, exemptions: list) -> list:
    """schema_stems: set of tests/api_schemas/ file stems, or None if the dir does not exist yet."""
    findings = []
    for r in sorted(new_routes):
        ex = exemption_for(exemptions, "route", r)
        if ex:
            findings.append(Finding("ROUTE", "ok", r, f"ledger-exempted {ex['date']}: {ex['reason']}"))
        elif schema_stems is None:
            findings.append(
                Finding(
                    "ROUTE",
                    "advisory",
                    r,
                    f"new site-api route {r} — schema-baseline enforcement is pending #1436 "
                    f"({SCHEMA_DIR}/ does not exist yet); this leg flips to BLOCKING automatically once it lands",
                    f"when #1436 lands, add {SCHEMA_DIR}/{route_slug(r)}.json, or a dated 'route' entry in {LEDGER}",
                )
            )
        elif schema_candidates(r) & schema_stems:
            findings.append(Finding("ROUTE", "ok", r, f"schema baseline present under {SCHEMA_DIR}/"))
        else:
            findings.append(
                Finding(
                    "ROUTE",
                    "fail",
                    r,
                    f"new site-api route {r} has no schema baseline under {SCHEMA_DIR}/",
                    f"add {SCHEMA_DIR}/{route_slug(r)}.json (#1436 baseline), or a dated 'route' entry in {LEDGER}",
                )
            )
    return findings


def schedule_signatures(source: str) -> Counter:
    """Multiset of Schedule.cron/rate/expression call signatures in a CDK stack source."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return Counter()
    sigs: Counter = Counter()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in _SCHEDULE_METHODS):
            continue
        owner = node.func.value
        owner_name = owner.attr if isinstance(owner, ast.Attribute) else (owner.id if isinstance(owner, ast.Name) else None)
        if owner_name == "Schedule":
            sigs[ast.unparse(node)] += 1
    return sigs


def cron_leg(new_schedules: dict, monitoring_changed: bool, exemptions: list) -> list:
    """new_schedules: {stack_file: [new schedule signature, ...]} (net additions only)."""
    findings = []
    for path in sorted(new_schedules):
        for sig in new_schedules[path]:
            key = f"{path}:{sig}"
            ex = exemption_for(exemptions, "cron", key)
            if ex:
                findings.append(Finding("CRON", "ok", key, f"ledger-exempted {ex['date']}: {ex['reason']}"))
            elif monitoring_changed:
                findings.append(Finding("CRON", "ok", key, "new schedule ships with a monitoring change in the same diff"))
            else:
                findings.append(
                    Finding(
                        "CRON",
                        "fail",
                        key,
                        f"new EventBridge schedule in {path} ({sig}) with no monitoring change in this PR",
                        f"add a heartbeat/alarm for it in the same PR (e.g. {MONITORING_STACK}, or an "
                        f"alarm on the scheduled lambda in {path} itself), or a dated 'cron' entry in "
                        f"{LEDGER} (token: {path})",
                    )
                )
    return findings


def import_gate_scans_directory(source: str) -> bool:
    """The #1432 gate's coverage-by-construction contract: it still readdir-scans site/assets/js/."""
    return "readdirSync(JS_DIR)" in source and '"site", "assets", "js"' in source


def js_leg(added_js: set, scan_intact: bool, exemptions: list) -> list:
    findings = []
    if not scan_intact:
        findings.append(
            Finding(
                "JS",
                "fail",
                IMPORT_GATE,
                f"the #1432 import gate no longer directory-scans {JS_SCAN_DIR}/ — new JS modules "
                "would silently escape full-parse coverage (the JS leg's coverage-by-construction contract)",
                f"restore the readdirSync(JS_DIR) scan over {JS_SCAN_DIR}/ in {IMPORT_GATE}",
            )
        )
    for p in sorted(added_js):
        if os.path.dirname(p) == JS_SCAN_DIR:
            findings.append(Finding("JS", "ok", p, f"covered by construction — the #1432 import gate scans {JS_SCAN_DIR}/"))
            continue
        ex = exemption_for(exemptions, "js", p)
        if ex:
            findings.append(Finding("JS", "ok", p, f"ledger-exempted {ex['date']}: {ex['reason']}"))
            continue
        findings.append(
            Finding(
                "JS",
                "fail",
                p,
                f"new site JS file {p} is OUTSIDE {JS_SCAN_DIR}/ — the #1432 import-graph gate scans "
                "only that directory (non-recursively), so this file gets no full-parse coverage",
                f"move it under {JS_SCAN_DIR}/, or add a dated 'js' entry in {LEDGER} (token: {p})",
            )
        )
    return findings


# ══════════════════════════════════════════════════════════════════════════════
# Collectors — git/filesystem in, pure-leg inputs out
# ══════════════════════════════════════════════════════════════════════════════


def collect_page_findings(repo: str, changed: list, exemptions: list) -> list:
    added_pages = {pp for s, p in changed if s == "A" and (pp := page_path_for(p))}
    page_relevant = bool(added_pages) or any(p == QA_MANIFEST or (p.startswith("site/") and p.endswith(".html")) for _, p in changed)
    if not page_relevant:
        return []
    try:
        qa = _load_qa_manifest(repo)
        unregistered, ghosts = qa.self_check()
    except Exception as e:  # a broken manifest must be loud, not skipped
        return [
            Finding(
                "PAGE",
                "fail",
                QA_MANIFEST,
                f"could not load/self-check the page manifest: {type(e).__name__}: {e}",
                f"fix {QA_MANIFEST} — the PAGE leg (and every QA sweep that derives from it) needs it importable",
            )
        ]
    return page_leg(added_pages, set(unregistered), set(ghosts), exemptions)


def _schema_stems(repo: str):
    d = os.path.join(repo, SCHEMA_DIR)
    if not os.path.isdir(d):
        return None
    stems = set()
    for root, _dirs, files in os.walk(d):
        stems.update(f[: -len(".json")] for f in files if f.endswith(".json"))
    return stems


def collect_route_findings(repo: str, mb: str, changed: list, exemptions: list) -> list:
    if SITE_API not in {p for _, p in changed}:
        return []
    discover = _load_sync_doc_metadata(repo).discover_endpoint_paths
    head_routes = discover(read_worktree(repo, SITE_API) or "")
    if head_routes is None:
        return [
            Finding(
                "ROUTE",
                "advisory",
                SITE_API,
                "route discoverer returned None on HEAD (dispatcher restructured or unparseable) — "
                "ROUTE leg skipped; deploy/sync_doc_metadata.py --check is the count gate",
            )
        ]
    base_src = read_at(repo, mb, SITE_API)
    base_routes = (discover(base_src) or set()) if base_src is not None else set()
    return route_leg(head_routes - base_routes, _schema_stems(repo), exemptions)


def _alarm_count(repo: str, source: str) -> int:
    """Alarm-constructor calls in a stack source — attr list single-sourced from sync_doc_metadata."""
    attrs = getattr(_load_sync_doc_metadata(repo), "_ALARM_CONSTRUCTOR_ATTRS", ("Alarm", "create_alarm"))
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return 0
    return sum(1 for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in attrs)


def monitoring_change_present(repo: str, mb: str, changed: list) -> bool:
    if MONITORING_STACK in {p for _, p in changed}:
        return True
    for s, p in changed:
        if s != "D" and p.startswith(CDK_STACKS_DIR + "/") and p.endswith(".py"):
            if _alarm_count(repo, read_worktree(repo, p) or "") > _alarm_count(repo, read_at(repo, mb, p) or ""):
                return True
    return False


def collect_cron_findings(repo: str, mb: str, changed: list, exemptions: list) -> list:
    stack_changes = [(s, p) for s, p in changed if p.startswith(CDK_STACKS_DIR + "/") and p.endswith(".py") and s != "D"]
    if not stack_changes:
        return []
    new_by_file = {}
    for _s, p in stack_changes:
        head_sigs = schedule_signatures(read_worktree(repo, p) or "")
        base_sigs = schedule_signatures(read_at(repo, mb, p) or "")
        if sum(head_sigs.values()) > sum(base_sigs.values()):
            new_by_file[p] = sorted((head_sigs - base_sigs).elements()) or ["<new schedule — signature not isolated>"]
    if not new_by_file:
        return []
    return cron_leg(new_by_file, monitoring_change_present(repo, mb, changed), exemptions)


def collect_js_findings(repo: str, changed: list, exemptions: list) -> list:
    added_js = {p for s, p in changed if s == "A" and p.startswith("site/") and p.endswith(".js")}
    gate_src = read_worktree(repo, IMPORT_GATE)
    scan_intact = bool(gate_src) and import_gate_scans_directory(gate_src)
    return js_leg(added_js, scan_intact, exemptions)


def run_gate(repo: str = REPO, base: str = "origin/main"):
    mb = merge_base(repo, base)
    changed = changed_files(repo, mb)
    exemptions = parse_exemptions(read_worktree(repo, LEDGER) or "")
    findings = []
    findings += collect_page_findings(repo, changed, exemptions)
    findings += collect_route_findings(repo, mb, changed, exemptions)
    findings += collect_cron_findings(repo, mb, changed, exemptions)
    findings += collect_js_findings(repo, changed, exemptions)
    return findings, changed, mb


# ══════════════════════════════════════════════════════════════════════════════
# Report
# ══════════════════════════════════════════════════════════════════════════════

_SEV_MARK = {"fail": "FAIL", "advisory": "note", "ok": "ok  "}


def format_report(findings: list, base: str, mb: str, n_changed: int) -> str:
    lines = [f"── surface-drift gate (#1454) ── base={base} merge-base={mb[:8]} changed_files={n_changed}"]
    if not findings:
        lines.append("no QA-relevant surface added by this diff — nothing to check.")
    for f in sorted(findings, key=lambda f: ({"fail": 0, "advisory": 1, "ok": 2}[f.severity], f.leg, f.surface)):
        lines.append(f"[{f.leg:<5}] {_SEV_MARK[f.severity]}  {f.surface} — {f.message}")
        if f.fix and f.severity != "ok":
            lines.append(f"          fix → {f.fix}")
    n_fail = sum(1 for f in findings if f.severity == "fail")
    n_adv = sum(1 for f in findings if f.severity == "advisory")
    if n_fail:
        lines.append(f"RESULT: FAIL — {n_fail} blocking finding(s), {n_adv} advisory. New surface lands registered or doesn't land.")
    else:
        lines.append(f"RESULT: PASS — 0 blocking findings, {n_adv} advisory.")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="PR-time surface-drift gate (#1454): new pages/routes/crons/JS land registered.")
    ap.add_argument("--base", default="origin/main", help="base ref to diff against (merge-base with HEAD; default origin/main)")
    ap.add_argument("--repo", default=REPO, help="repo root (default: this checkout)")
    args = ap.parse_args(argv)
    findings, changed, mb = run_gate(args.repo, args.base)
    print(format_report(findings, args.base, mb, len(changed)))
    return 1 if any(f.severity == "fail" for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
