#!/usr/bin/env python3
"""scripts/review_estate.py — the ESTATE SWEEP: what each review row must enumerate before it grades (owner ruling 2026-11-14).

THE DEFECT. Three full reviews in a row had sound verifiers and poor recall: 2026-10-31 uncalibrated on the withheld
control, 2026-11-13 0 of 1 blind, 2026-11-14 0 of 4 — on the stronger grader. Each missed issue sat in a corner its
row never reached: one read grant among ~100 roles, a missing grant visible only by crossing emitters with policies,
an over-budget census the cost row did not run, a scheduled workflow red for four days. The graders sampled their
sealed clauses and the prior path-to-A list well, and did not sweep the estate their area owns. A stronger model did
not fix that, because it is not a reasoning failure: it is a coverage failure.

THE RULE. Before a row grades a clause, it runs its ESTATE SWEEPS: a short, fixed list of enumerations over the
registries, configurations, production evidence and execution results that ARE its area — every role, every alarm,
every scheduled workflow, every source, every public route — never a sample chosen by familiarity. Each sweep states
what set it walks and how to walk it. The grader reports, per sweep, how many members it examined and every anomaly
it found ("none" is a result only beside a count). A sweep that was not run is recorded as `not_run` with its reason,
and the row is then INCOMPLETE: it cannot be graded A and it does not stand as a from-scratch grading of its area.

WHAT THIS IS NOT. It is not the answer key. A sweep names a set to walk, not a defect to find; no sweep names an
issue, and the withheld controls stay out of every brief (.claude/skills/review/SKILL.md, Phase 2). The sweeps are
bounded on purpose — two to five per row, each one command or one read — so a row's sweep costs minutes, not a
second review (ADR-103: this is a list and a checker, no new standing machinery).

USAGE
    python3 scripts/review_estate.py --lens security      # the sweeps a grader's brief carries, verbatim
    python3 scripts/review_estate.py --json               # the whole registry
    python3 scripts/review_estate.py --check <grades.json> # every row carries every sweep; exit 1 names the gaps
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@dataclass(frozen=True)
class Sweep:
    id: str
    estate: str  # the SET that is walked — every member, not a sample
    how: str  # the command or read that enumerates it (read-only)
    report: str  # what the grader returns for it
    paths: tuple = ()  # repo files the sweep depends on (must exist — tests/test_review_estate.py)


_N = "the count examined, and every anomaly with its member named"

ESTATE: dict = {
    "cto": (
        Sweep(
            "cto.E1",
            "every alarm currently in ALARM",
            "aws cloudwatch describe-alarms --state-value ALARM, then python3 scripts/check_alarm_citations.py",
            f"{_N}: an alarm lit with no cited cause or owner, or a citation the live state contradicts",
            ("scripts/check_alarm_citations.py",),
        ),
        Sweep(
            "cto.E2",
            "every CloudFormation stack",
            "aws cloudformation describe-stacks --query 'Stacks[].[StackName,StackStatus,DriftInformation.StackDriftStatus]' (us-west-2 and us-east-1)",
            f"{_N}: a stack not in a *_COMPLETE state, or DRIFTED with no owner",
        ),
        Sweep(
            "cto.E3",
            "every row of the complexity ledger",
            "docs/PROPORTIONALITY.md read against python3 scripts/boot_brief.py",
            f"{_N}: a ledger row whose resource no longer exists, or a standing resource with no row",
            ("docs/PROPORTIONALITY.md", "scripts/boot_brief.py"),
        ),
    ),
    "principal": (
        Sweep(
            "principal.E1",
            "every gate in the census",
            "python3 scripts/gate_census.py",
            f"{_N}: unproven gates by family, and any flag the census prints",
            ("scripts/gate_census.py",),
        ),
        Sweep(
            "principal.E2",
            "the last 30 runs of each required check on main and on PRs",
            "gh run list --workflow ci-cd.yml --branch main --limit 30 --json conclusion,headSha,createdAt; the same for pr-checks.yml",
            f"{_N}: a red or cancelled run nobody re-ran, a flake seen twice",
        ),
        Sweep(
            "principal.E3",
            "every module and function over the size ratchets",
            "python3 -m pytest tests/test_module_size_guard.py tests/test_function_length_guard_4880.py -q, then the two recorded ledgers they read",
            f"{_N}: entries at their ceiling, entries that grew",
            ("tests/test_module_size_guard.py", "tests/test_function_length_guard_4880.py"),
        ),
    ),
    "aiq": (
        Sweep(
            "aiq.E1",
            "every caller of the inference chokepoint",
            "git grep -n 'bedrock_client.invoke\\|ai_calls\\.' -- lambdas mcp",
            f"{_N}: for each caller that reaches a reader — its grounding gate, and what it serves when that gate raises (open or closed)",
            ("lambdas/ai/bedrock_client.py",),
        ),
        Sweep(
            "aiq.E2",
            "every number in the live AI-written payloads",
            "GET /api/edition, /api/pulse, /api/coaching-dashboard, /api/chapters; each stated figure checked against the series or record it names",
            f"{_N}: a figure the source does not carry, or a partial day stated as a whole one",
        ),
        Sweep(
            "aiq.E3",
            "every prompt-cache caller record",
            "lambdas/ai/prompt_cache.py and the PromptCacheNoOp metric (aws cloudwatch get-metric-statistics)",
            f"{_N}: a caller below its cacheable floor still marked cached",
            ("lambdas/ai/prompt_cache.py",),
        ),
    ),
    "cpo": (
        Sweep(
            "cpo.E1",
            "every page the site owns",
            "www/owned_paths.json and qa/qa_manifest.py visual_pages(), each against docs/SITE_MAP_AND_INTENT.md",
            f"{_N}: a page with no stated intent, or an intent no page serves",
            ("www/owned_paths.json", "qa/qa_manifest.py", "docs/SITE_MAP_AND_INTENT.md"),
        ),
        Sweep(
            "cpo.E2",
            "every link on the front page",
            "www/reach.json depth1, each followed live",
            f"{_N}: a link that dead-ends, or lands on a page that does not answer the question that led there",
            ("www/reach.json",),
        ),
    ),
    "designer": (
        Sweep(
            "designer.E1",
            "every stylesheet and token",
            "python3 scripts/check_css_tokens.py, then the same reading of www/src/styles/*.css",
            f"{_N}: hard-coded colours, sizes or breakpoints outside the tokens",
            ("scripts/check_css_tokens.py",),
        ),
        Sweep(
            "designer.E2",
            "every top-level v9 route at 390 px and 1280 px",
            "python3 tests/web_preview_gate.py over a fresh build, and a look at each top-level page at both widths",
            f"{_N}: overflow, type under the floor, an empty state that reads as broken",
            ("tests/web_preview_gate.py",),
        ),
    ),
    "dataviz": (
        Sweep(
            "dataviz.E1",
            "every function that draws a figure",
            "git grep -ln '<svg' -- www/src/lib www/src/components",
            f"{_N}: for each — its baseline, whether a nonzero scale is labelled, and whether n or an interval is shown where one exists",
        ),
        Sweep(
            "dataviz.E2",
            "every measurement drawn on more than one page",
            "python3 scripts/check_www_build.py (spark_agreement), then each shared metric's value read on each page that shows it",
            f"{_N}: one series drawn two ways, or two values for one reading",
            ("scripts/check_www_build.py",),
        ),
    ),
    "qs": (
        Sweep(
            "qs.E1",
            "every pre-registered test and every weekly finding",
            "the publication snapshot's lab.json (python3 scripts/publish_snapshot.py --mode live --out <tmp>), every test and finding",
            f"{_N}: a test with no pre-registration date, n or decision rule; a finding stated beyond its interval",
            ("scripts/publish_snapshot.py",),
        ),
        Sweep(
            "qs.E2",
            "every causal word on the public pages",
            "the built pages (www/dist after a live build) searched for: causes, because of, leads to, drives, thanks to, results in",
            f"{_N}: each hit, and whether the sentence is the platform's claim or a quoted coach",
        ),
    ),
    "narrative": (
        Sweep(
            "narrative.E1",
            "every published chapter",
            "GET /api/chapters; each chapter's quotations checked against the record it quotes, and its dates against its covered days",
            f"{_N}: a quotation that is not exact, a date that is not the day it names",
        ),
        Sweep(
            "narrative.E2",
            "every coach's public page",
            "each /system/coaches/<id>/ page read against that coach's record on /api/predictions",
            f"{_N}: a lead figure the record does not carry, a voice that contradicts the persona",
        ),
        Sweep(
            "narrative.E3",
            "every held or skipped week",
            "GET /api/chapters, the weeks whose status is not published",
            f"{_N}: any text, title or figure of a held week reachable on a public page",
        ),
    ),
    "security": (
        Sweep(
            "security.E1",
            "every IAM policy statement of every role",
            "python3 scripts/review_estate.py --statements (every statement: actions, resources, conditions), then python3 deploy/verify_oidc_iam.py for the CI roles",
            f"{_N}: every statement whose Resource is a whole table, bucket or '*' with no Condition narrowing it — reads included, not only writes",
            ("deploy/verify_oidc_iam.py",),
        ),
        Sweep(
            "security.E2",
            "every public route's payload",
            "python3 deploy/pii_surface_guard.py --endpoints, then python3 tests/age_inversion_lib.py --live",
            f"{_N}: every violation, and every route the sweep could not scan",
            ("deploy/pii_surface_guard.py", "tests/age_inversion_lib.py"),
        ),
        Sweep(
            "security.E3",
            "every sensitive S3 prefix at the origin",
            "an unsigned GET and an unsigned list against raw/, config/, uploads/, dashboard/ and one real key under each",
            f"{_N}: any response that is not 403 or 404",
        ),
        Sweep(
            "security.E4",
            "every authentication door",
            "lambdas/operational/qa_check_oauth_door.py and qa_check_edge_429.py read, then each probe's last result in the qa-smoke log",
            f"{_N}: a bypass a probe does not attempt, a probe that has not run",
            ("lambdas/operational/qa_check_oauth_door.py", "lambdas/operational/qa_check_edge_429.py"),
        ),
    ),
    "a11y": (
        Sweep(
            "a11y.E1",
            "every page in the manifest, both themes",
            "python3 qa/a11y_audit.py",
            f"{_N}: every violation by page and rule, and every page the audit skipped",
            ("qa/a11y_audit.py",),
        ),
        Sweep(
            "a11y.E2",
            "every interactive island",
            "www/src/islands/*.js, each operated by keyboard on the page that mounts it",
            f"{_N}: a control with no visible focus, no name, or no keyboard path",
        ),
    ),
    "reader": (
        Sweep(
            "reader.E1",
            "every top-level route, cold",
            "each route in www/owned_paths.json one level deep, rendered live at 390 px and 1280 px",
            f"{_N}: where a stranger cannot tell what the page is, what a number means, or what to do next",
            ("www/owned_paths.json",),
        ),
    ),
    "observability": (
        Sweep(
            "observability.E1",
            "every alarm",
            "aws cloudwatch describe-alarms (both regions), then python3 scripts/check_alarm_census.py",
            f"{_N}: alarms that cannot clear, cannot fire, or route nowhere; the census's own drift",
            ("scripts/check_alarm_census.py",),
        ),
        Sweep(
            "observability.E2",
            "every role against every metric its code can emit",
            "python3 scripts/review_estate.py --emitters (every handler that can reach a put_metric_data call, beside its role's grant)",
            f"{_N}: an emitter with no grant (a metric silently dark), a grant with no emitter",
            ("tests/test_put_metric_data_grant_lockstep.py",),
        ),
        Sweep(
            "observability.E3",
            "every scheduled workflow and every dead-man",
            "for each file in .github/workflows/ with a schedule: gh run list --workflow <file> --limit 10 --json conclusion,createdAt",
            f"{_N}: a workflow red on three or more consecutive scheduled runs, with or without an owner",
        ),
        Sweep(
            "observability.E4",
            "every metric namespace",
            "python3 deploy/emf_series_census.py --strict",
            f"{_N}: namespaces over budget, unregistered or orphaned",
            ("deploy/emf_series_census.py",),
        ),
    ),
    "cost": (
        Sweep(
            "cost.E1",
            "the month's spend by service and by usage type",
            "aws ce get-cost-and-usage for the current and the last closed month, grouped by SERVICE and by USAGE_TYPE",
            f"{_N}: every line that moved by more than a tenth, and its cause",
        ),
        Sweep(
            "cost.E2",
            "every priced counter the platform budgets",
            "python3 deploy/emf_series_census.py --strict, then model/cost_surface_baseline.json against the live counts (alarms, secrets, log groups)",
            f"{_N}: every counter over its budget or off its baseline",
            ("deploy/emf_series_census.py", "model/cost_surface_baseline.json"),
        ),
        Sweep(
            "cost.E3",
            "every budget-tier transition this month",
            "aws ssm get-parameter-history --name /life-platform/budget-tier and /life-platform/budget-breakdown",
            f"{_N}: each transition, what triggered it, and whether the tier's pauses took effect",
        ),
    ),
    "data-architect": (
        Sweep(
            "data-architect.E1",
            "every partition-key family in the table",
            "deploy/generated/pk_family_census.json, each family through experiment.phase_taxonomy.classify",
            f"{_N}: a family the taxonomy cannot classify, a census older than its refresh rule",
            ("deploy/generated/pk_family_census.json",),
        ),
        Sweep(
            "data-architect.E2",
            "every documented partition against a live item",
            "docs/SCHEMA.md partitions, one recent live item read per partition",
            f"{_N}: attributes live but undocumented, documented but absent, or typed otherwise",
            ("docs/SCHEMA.md",),
        ),
        Sweep(
            "data-architect.E3",
            "every source's raw layout",
            "python3 scripts/check_raw_zone_drift.py",
            f"{_N}: every drift it reports",
            ("scripts/check_raw_zone_drift.py",),
        ),
    ),
    "integrations": (
        Sweep(
            "integrations.E1",
            "every source in the registry",
            "lambdas/ingestion/source_registry.py, each source's newest stored record against its stale_hours and paused facets",
            f"{_N}: a live source past its threshold, a paused source still described as live",
            ("lambdas/ingestion/source_registry.py",),
        ),
        Sweep(
            "integrations.E2",
            "every source on both status surfaces",
            "GET /api/status and /api/source_freshness, source by source",
            f"{_N}: two surfaces that disagree about one source",
        ),
        Sweep(
            "integrations.E3",
            "every ingestion function's last seven days",
            "aws cloudwatch get-metric-statistics Errors and Invocations per ingestion function, and the ingestion DLQ depth",
            f"{_N}: a function erroring, or not invoked on its cadence",
        ),
    ),
    "devex": (
        Sweep(
            "devex.E1",
            "every workflow file",
            "for each file in .github/workflows/: gh run list --workflow <file> --limit 10 --json conclusion,event,createdAt",
            f"{_N}: a workflow red on three or more consecutive runs, a workflow that has never run",
        ),
        Sweep(
            "devex.E2",
            "every skill and agent definition",
            "python3 scripts/skill_lint.py --offline, then python3 scripts/check_synced_skill_drift.py",
            f"{_N}: every lint finding and every drifted copy",
            ("scripts/skill_lint.py", "scripts/check_synced_skill_drift.py"),
        ),
        Sweep(
            "devex.E3",
            "every first-contact doc fact",
            "python3 scripts/check_doc_facts.py, then python3 scripts/check_doc_index.py",
            f"{_N}: every stale fact or stamp it prints, gating or advisory",
            ("scripts/check_doc_facts.py", "scripts/check_doc_index.py"),
        ),
        Sweep(
            "devex.E4",
            "main's head",
            "python3 scripts/check_main_green.py",
            f"{_N}: whether the head commit's required checks ran and passed, and how a zero-run head is classified",
            ("scripts/check_main_green.py",),
        ),
    ),
    "growth": (
        Sweep(
            "growth.E1",
            "every shareable page's card",
            "each URL in the live sitemap: its og:title, og:description and og:image, and one figure on the card against the page",
            f"{_N}: a missing or generic card, a card whose figure differs from its page",
        ),
        Sweep(
            "growth.E2",
            "every feed the site links",
            "each RSS or JSON feed the site links: validity, item dates against publication dates",
            f"{_N}: an invalid feed, an item dated by its reporting period",
        ),
        Sweep(
            "growth.E3",
            "the subscribe path",
            "the subscribe form and its confirm and unsubscribe pages fetched (no submission)",
            f"{_N}: a step that 404s, a promise the privacy policy does not make",
        ),
    ),
}


# ── two enumerators the sweeps had no command for ───────────────────────────────────────────────────────────────────
# Every other sweep already has a tool. These two did not, and they are the two estates the 2026-11-13 and 2026-11-14
# rows walked past: the policy statements (one by one, reads included) and the roles against what their code can emit.


def _load_role_policies():
    """The role-policy modules imported with a stub ``aws_cdk`` whose PolicyStatement keeps its arguments."""
    import importlib
    import types

    class _Statement:
        def __init__(self, sid="", actions=None, resources=None, conditions=None, effect=None, **_kw):
            self.sid, self.actions, self.resources, self.conditions = sid, list(actions or []), list(resources or []), conditions

    iam = types.ModuleType("aws_cdk.aws_iam")
    iam.PolicyStatement = _Statement
    iam.Effect = types.SimpleNamespace(ALLOW="Allow", DENY="Deny")
    cdk = types.ModuleType("aws_cdk")
    cdk.aws_iam = iam
    saved = {k: sys.modules.get(k) for k in ("aws_cdk", "aws_cdk.aws_iam")}
    sys.modules["aws_cdk"], sys.modules["aws_cdk.aws_iam"] = cdk, iam
    stacks = os.path.join(REPO, "cdk", "stacks")
    for path in (os.path.join(REPO, "cdk"), stacks):
        if path not in sys.path:
            sys.path.insert(0, path)
    names = sorted(f[:-3] for f in os.listdir(stacks) if f.startswith("role_policies") and f.endswith(".py"))
    # Every role-policy module is imported FRESH under this stub, as a set: they import one another (as
    # `stacks.role_policies_*`), and a copy another caller imported earlier under a thinner stub would hand back
    # statements that carry no conditions — every conditioned grant would then read as unconditioned. Both spellings
    # of each name are set aside first and put back afterwards, so this never changes what another caller holds.
    spellings = [n for name in names for n in (name, f"stacks.{name}")]
    kept = {n: sys.modules.pop(n) for n in spellings if n in sys.modules}
    mods = []
    try:
        mods = [importlib.import_module(f"stacks.{n}") for n in names]
    finally:
        for n in spellings:
            sys.modules.pop(n, None)
        sys.modules.update(kept)
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
    return mods


def _broad(resource) -> bool:
    """A whole table (not one index of it), a whole bucket, or everything."""
    r = str(resource)
    if r == "*":
        return True
    if ":table/" in r:
        return "/index/" not in r and "/stream/" not in r
    if r.startswith("arn:aws:s3:::"):
        rest = r[len("arn:aws:s3:::") :]
        return "/" not in rest or rest.endswith("/*") and rest.count("/") == 1
    return False


def iam_statements() -> list:
    """Every PolicyStatement every role-policy function builds: where it is, what it allows, on what, under which
    condition — and ``unconditioned_broad`` when it reaches a whole table, a whole bucket or ``*`` with no condition."""
    import inspect

    out = []
    for mod in _load_role_policies():
        for fn_name, fn in sorted(vars(mod).items()):
            if fn_name.startswith("_") or not inspect.isfunction(fn) or fn.__module__ != mod.__name__:
                continue
            params = inspect.signature(fn).parameters.values()
            if any(p.default is inspect.Parameter.empty and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD) for p in params):
                continue
            where = f"{mod.__name__.rsplit('.', 1)[-1]}.{fn_name}"
            try:
                stmts = fn()
            except Exception:  # noqa: BLE001 — a builder that cannot be evaluated here is listed, not hidden
                out.append(
                    {
                        "where": where,
                        "sid": "",
                        "actions": [],
                        "resources": [],
                        "conditioned": False,
                        "unconditioned_broad": False,
                        "unreadable": True,
                    }
                )
                continue
            for st in stmts if isinstance(stmts, (list, tuple)) else []:
                if not hasattr(st, "actions"):
                    continue
                broad = any(_broad(r) for r in st.resources)
                out.append(
                    {
                        "where": where,
                        "sid": st.sid,
                        "actions": st.actions,
                        "resources": [str(r) for r in st.resources],
                        "conditioned": bool(st.conditions),
                        "unconditioned_broad": broad and not st.conditions,
                    }
                )
    return out


_IMPORTS_MEMO: dict = {}


def _local_imports(path: str) -> set:
    """The repo modules a file imports, as paths under lambdas/ (``from ai import bedrock_client`` → ai/bedrock_client.py).
    Memoised per (path, mtime): the closure of every handler re-reads the same few hundred shared modules, and re-parsing
    them per handler was minutes of ast work (#5514). A changed file changes its mtime, so a stale answer is not served."""
    try:
        key = (path, os.stat(path).st_mtime_ns)
    except OSError:
        return set()
    if key not in _IMPORTS_MEMO:
        _IMPORTS_MEMO[key] = _parse_local_imports(path)
    return set(_IMPORTS_MEMO[key])


def _parse_local_imports(path: str) -> set:
    import ast

    root = os.path.join(REPO, "lambdas")
    try:
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
    except (OSError, SyntaxError):
        return set()
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names.add(node.module)
            names |= {f"{node.module}.{a.name}" for a in node.names}
    return {c for c in (os.path.join(root, *n.split(".")) + ".py" for n in names) if os.path.isfile(c)}


def emitter_reach() -> list:
    """Every wired handler whose code can reach a ``put_metric_data`` call (itself or through what it imports) beside
    whether its role holds ``cloudwatch:PutMetricData``. ``dark`` = it can emit and has no grant: the emit is denied
    and swallowed, so the metric never lands. An import-closure over-approximation — a reach is a lead, not a verdict."""
    tests = os.path.join(REPO, "tests")
    if tests not in sys.path:
        sys.path.insert(0, tests)
    import test_put_metric_data_grant_lockstep as lock  # the ONE derivation of handler → role-policy function

    emits: dict = {}

    def _emits(path: str) -> bool:
        if path not in emits:
            try:
                with open(path, encoding="utf-8") as fh:
                    emits[path] = ".put_metric_data(" in fh.read()
            except OSError:
                emits[path] = False
        return emits[path]

    out = []
    for source, fns in sorted(lock._build_source_to_rp_map().items()):
        start = os.path.join(REPO, source)
        seen, stack, hits = {start}, [start], []
        while stack:
            cur = stack.pop()
            if _emits(cur):
                hits.append(os.path.relpath(cur, REPO))
            for nxt in _local_imports(cur):
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        if not hits:
            continue
        fn_list = sorted(fns) if isinstance(fns, (set, list, tuple)) else [fns]
        granted = any(lock._rp_grants_put_metric_data(fn) for fn in fn_list)
        out.append({"handler": source, "role_policy": fn_list, "emitters_reached": sorted(hits), "granted": granted, "dark": not granted})
    return out


#: The first day a full-review artifact must carry the sweeps. Earlier runs could not have (the instrument did not ask).
REQUIRED_FROM = "2026-11-15"


def required(grades: dict) -> bool:
    return str(grades.get("date") or "") >= REQUIRED_FROM


def sweeps_for(lens: str) -> tuple:
    if lens not in ESTATE:
        raise SystemExit(f"unknown lens {lens!r} — one of: {', '.join(sorted(ESTATE))}")
    return ESTATE[lens]


def brief(lens: str) -> str:
    """The block a grader's brief carries verbatim."""
    out = [
        f"ESTATE SWEEP — {lens} (scripts/review_estate.py). Run EVERY sweep below BEFORE grading a clause. Each walks a whole",
        "set — every member, never a sample. Return `estate_sweep`: one entry per sweep id, with `examined` (a count),",
        "`anomalies` (each with its member named; an empty list is a result only beside a count) and `evidence` (the command",
        "and the lines that show it). A sweep you could not run is `status: not_run` with the reason — the row is then",
        "INCOMPLETE and cannot be graded A. Findings come from the sweeps as well as from the clauses.",
        "",
    ]
    for s in sweeps_for(lens):
        out += [f"  [{s.id}] {s.estate}", f"      how:    {s.how}", f"      report: {s.report}", ""]
    return "\n".join(out)


def check_artifact(grades: dict) -> list[str]:
    """Rows of a grades artifact whose estate sweep is missing or incomplete (the artifact's own `lenses` only)."""
    problems = []
    for lens, row in sorted((grades.get("lenses") or {}).items()):
        if lens not in ESTATE or not isinstance(row, dict):
            continue
        got = {str(e.get("sweep_id")): e for e in (row.get("estate_sweep") or []) if isinstance(e, dict)}
        for s in ESTATE[lens]:
            e = got.get(s.id)
            if e is None:
                problems.append(f"{lens}: sweep {s.id} is absent ({s.estate})")
            elif e.get("status") == "not_run":
                problems.append(f"{lens}: sweep {s.id} was not run — {e.get('reason') or 'no reason given'}")
            elif not isinstance(e.get("examined"), int) or e["examined"] < 1:
                problems.append(f"{lens}: sweep {s.id} states no count of what it examined")
    return problems


def incomplete_lenses(grades: dict) -> set:
    """The rows of a run that did not complete their estate sweep — empty for a run dated before the rule."""
    return {p.split(":", 1)[0] for p in check_artifact(grades)} if required(grades) else set()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--lens")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--check", metavar="GRADES_JSON")
    ap.add_argument(
        "--statements", action="store_true", help="every IAM policy statement, broad-and-unconditioned ones marked (security.E1)"
    )
    ap.add_argument("--emitters", action="store_true", help="every handler that can emit a metric, beside its grant (observability.E2)")
    a = ap.parse_args()
    if a.statements:
        rows = iam_statements()
        for r in rows:
            mark = "BROAD, NO CONDITION" if r["unconditioned_broad"] else ("unreadable" if r.get("unreadable") else "")
            print(f"{r['where']:55} {r['sid'][:34]:34} {','.join(r['actions'])[:70]:70} {mark}")
        print(
            f"{len(rows)} statements · {sum(r['unconditioned_broad'] for r in rows)} reach a whole table, a whole bucket or * with no condition"
        )
        return 0
    if a.emitters:
        rows = emitter_reach()
        for r in rows:
            print(f"{'DARK' if r['dark'] else 'ok  '}  {r['handler']:58} via {', '.join(r['emitters_reached'])[:90]}")
        print(f"{len(rows)} handlers can reach an emitter · {sum(r['dark'] for r in rows)} hold no cloudwatch:PutMetricData grant")
        return 0
    if a.check:
        with open(a.check, encoding="utf-8") as fh:
            grades = json.load(fh)
        problems = check_artifact(grades)
        for p in problems:
            print(p)
        if not required(grades):
            print(f"(informational: this artifact is dated before {REQUIRED_FROM}, when the estate sweep became part of the instrument)")
            return 0
        print(
            f"{'❌' if problems else '✅'} estate sweep: {len(problems)} gap(s) across {len({p.split(':', 1)[0] for p in problems})} row(s)"
        )
        return 1 if problems else 0
    if a.json:
        print(json.dumps({k: [asdict(s) for s in v] for k, v in ESTATE.items()}, indent=1))
        return 0
    for lens in [a.lens] if a.lens else sorted(ESTATE):
        print(brief(lens))
    return 0


if __name__ == "__main__":
    sys.exit(main())
