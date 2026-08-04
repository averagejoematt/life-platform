#!/usr/bin/env python3
"""scripts/doc_facts_ops.py — the OPERATIONAL-claim half of the wiki drift gate (#1957).

WHY THIS EXISTS
  `check_doc_facts.py` already policies stale *numbers* (counts, budget ceilings) and,
  since #1205, stale *crons*. But the #1205 scan is deliberately narrow: it only compares
  lines that quote a literal `cron(...)`. The 2026-07-28 panel found six materially false
  operational claims in ARCHITECTURE.md that all sailed through it, because none of them
  is a bare count and none quotes a cron:

    • a budget-TIER MAPPING that was the pre-ADR-125 inverse of the live ladder
      ("1=coaches, 2=website AI" — an incident responder misdiagnoses which surfaces are
      legitimately paused);
    • a LAMBDA TABLE ROW for a function retired months earlier (`apple-health-ingestion`
      → ResourceNotFoundException);
    • a SECRET INVENTORY claiming 21 secrets while listing 12 and marking a live secret
      SOFT-DELETED, with the count re-stamped on every doc-sync (manufactured freshness
      on a fact nobody had verified since 2026-07-10);
    • an ALARM count of "~50" on the same page whose header said "~81".

  Fixing the six instances (the 2026-07-16 pass did exactly that) does not stop the
  seventh. THE GATE EXTENSION IS THE FIX. Each check below derives its ground truth from
  machine-readable source — the `_FEATURE_CUTOFF` map, the CDK `function_name=` set, the
  `_secret_arn(...)` grants — never from an enumerated list of prose strings, so a NEW
  false claim of the same class is caught without anyone updating this file (the
  "guard the SET, not the instance" rule).

STRUCTURE
  Pure functions. Every scan takes the files/values to check plus an `exempt` predicate
  (check_doc_facts owns the single HISTORICAL/drift-ok definition and passes it in), and
  returns a list of human-readable hit strings. Nothing here reads argv, exits, or
  touches the network — so `tests/test_doc_facts_ops_1957.py` can plant a synthetic
  drifted claim of each class in a scratch file and prove the rule bites (#1189).

  Lives in its own module rather than in check_doc_facts.py (890 lines) or
  sync_doc_metadata.py (1754, already baselined over the module-size ceiling) — the
  four checks are one cohesive concern with one reason to change.
"""

import ast
import datetime as _dt
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

BUDGET_GUARD_PATH = ROOT / "lambdas" / "ai" / "budget_guard.py"
CDK_STACKS_DIR = ROOT / "cdk" / "stacks"
ROLE_POLICIES_PATH = CDK_STACKS_DIR / "role_policies.py"
SYNC_META_PATH = ROOT / "deploy" / "sync_doc_metadata.py"
ARCHITECTURE_PATH = ROOT / "docs" / "ARCHITECTURE.md"
INGESTION_STACK_PATH = CDK_STACKS_DIR / "ingestion_stack.py"
SOURCE_REGISTRY_PATH = ROOT / "lambdas" / "ingestion" / "source_registry.py"


# ══════════════════════════════════════════════════════════════════════════════
# GROUND-TRUTH DISCOVERERS (AST / source parse — never an import, never live AWS)
# ══════════════════════════════════════════════════════════════════════════════
def budget_tier_cutoffs(path: Path = BUDGET_GUARD_PATH) -> dict:
    """feature key -> tier at which it is DISABLED, AST-read from `_FEATURE_CUTOFF`.

    Parsed, not imported: budget_guard imports boto3 and would drag an AWS client into
    a doc gate. Returns {} if the map can't be found, and the caller then skips the
    check rather than guessing (a silently vacuous gate is worse than no gate).
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if "_FEATURE_CUTOFF" not in names or not isinstance(node.value, ast.Dict):
            continue
        out = {}
        for k, v in zip(node.value.keys, node.value.values):
            if isinstance(k, ast.Constant) and isinstance(v, ast.Constant):
                if isinstance(k.value, str) and isinstance(v.value, int):
                    out[k.value] = v.value
        return out
    return {}


def ingestion_paused_sources(path: Path = SOURCE_REGISTRY_PATH) -> dict:
    """{key: label} for every `SOURCE_REGISTRY` entry carrying `"paused": True`
    (#2003). AST-read, not imported — source_registry.py has no external deps, but
    this keeps the "parse, don't import" rule uniform across this module.

    Ground truth for the ingest-bullet check: a doc must never describe a paused
    source's schedule as if it were a live EventBridge pull (the Garmin/ADR-074
    defect this issue fixes).
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if "SOURCE_REGISTRY" not in names or not isinstance(node.value, ast.Dict):
            continue
        out = {}
        for k, v in zip(node.value.keys, node.value.values):
            if not (isinstance(k, ast.Constant) and isinstance(k.value, str) and isinstance(v, ast.Dict)):
                continue
            paused, label = False, k.value
            for fk, fv in zip(v.keys, v.values):
                if not isinstance(fk, ast.Constant):
                    continue
                if fk.value == "paused" and isinstance(fv, ast.Constant) and fv.value is True:
                    paused = True
                elif fk.value == "label" and isinstance(fv, ast.Constant) and isinstance(fv.value, str):
                    label = fv.value
            if paused:
                out[k.value] = label
        return out
    return {}


def ingestion_scheduled_lambda_count(path: Path = INGESTION_STACK_PATH) -> int | None:
    """Count `create_platform_lambda(...)` calls in ingestion_stack.py that carry a
    `schedule=` kwarg — the live EventBridge-scheduled ingestion fleet (#2003).

    AST-parsed, not imported: the stack module drags in aws_cdk at import time. This
    deliberately EXCLUDES:
      * S3-triggered Lambdas (macrofactor / food_delivery / measurements — no
        `schedule=` kwarg, an `add_permission` S3 invoke grant instead);
      * the API-Gateway-triggered HAE webhook (a raw `_lambda.Function(...)`, not
        `create_platform_lambda`);
      * garmin — PAUSED (ADR-074): its `create_platform_lambda` call carries no
        `schedule=` kwarg at all while paused, which is exactly the #2003 root
        cause (CLAUDE.md counted it as scheduled anyway, two months after the
        rule was removed).

    Returns None if the file can't be parsed or no matching calls are found — the
    caller must treat that as "ground truth unavailable", never trust a silent 0.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return None
    total = scheduled = 0
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "create_platform_lambda"):
            continue
        total += 1
        for kw in node.keywords:
            if kw.arg == "schedule" and not (isinstance(kw.value, ast.Constant) and kw.value.value is None):
                scheduled += 1
                break
    if total == 0:
        return None
    return scheduled


_CDK_FUNC_RE = re.compile(r'function_name\s*=\s*["\']([a-z0-9_-]+)["\']')
# mcp_stack passes `function_name=MCP_FUNCTION_NAME`; harvest those module constants too,
# or a doc correctly naming `life-platform-mcp-warmer` would be reported as a ghost.
_CDK_FUNC_CONST_RE = re.compile(r'^[A-Z0-9_]*FUNCTION_NAME\s*=\s*["\']([a-z0-9_-]+)["\']', re.M)


def cdk_function_names(stacks_dir: Path = CDK_STACKS_DIR) -> set:
    """Every Lambda function name declared in cdk/stacks/*.py.

    Same `function_name=` idiom `sync_doc_metadata._auto_discover_lambda_count()` counts
    with — this returns the NAMES so a doc can be checked against the set, not the size.
    """
    names: set = set()
    if not stacks_dir.exists():
        return names
    for f in sorted(stacks_dir.glob("*.py")):
        try:
            src = f.read_text(encoding="utf-8")
        except OSError:
            continue
        names |= set(_CDK_FUNC_RE.findall(src))
        names |= set(_CDK_FUNC_CONST_RE.findall(src))
    return names


_SECRET_ARN_RE = re.compile(r'_secret_arn\(\s*["\']([^"\']+)["\']')


def cdk_granted_secrets(path: Path = ROLE_POLICIES_PATH) -> set:
    """Secret names a live IAM role is granted access to (`_secret_arn("…")` literals).

    A secret that a deployed role reads cannot honestly be documented as deleted — that
    is either a doc lie or a dangling grant, and both want a human.
    """
    try:
        return set(_SECRET_ARN_RE.findall(path.read_text(encoding="utf-8")))
    except OSError:
        return set()


_SECRET_LITERAL_RE = re.compile(r'"secret_count":\s*(\d+),\s*#\s*live-verified\s*(\d{4}-\d{2}-\d{2})')


def stamped_secret_fact(path: Path = SYNC_META_PATH):
    """(count, live-verified date) from sync_doc_metadata's `secret_count` literal.

    The literal is not auto-discoverable from the repo (secrets live only in AWS), so its
    freshness is the fact: `python3 deploy/sync_doc_metadata.py --refresh-secrets` reads
    the live inventory and rewrites BOTH the number and the date. This parse is what lets
    the staleness rule below be deterministic — no AWS call in CI.
    """
    try:
        mo = _SECRET_LITERAL_RE.search(path.read_text(encoding="utf-8"))
    except OSError:
        return None, None
    if not mo:
        return None, None
    return int(mo.group(1)), _dt.date.fromisoformat(mo.group(2))


# ══════════════════════════════════════════════════════════════════════════════
# CHECK A — budget TIER SEMANTICS vs budget_guard._FEATURE_CUTOFF
# ══════════════════════════════════════════════════════════════════════════════
# The drift shape: a doc states the ladder inline — "(1=coaches, 2=website AI, 3=hard
# cutoff)". Only lines that NAME the gate (budget_guard / budget-tier / cost governor)
# are read, and only `N = phrase` / `tier N: phrase` pairs are extracted, so ordinary
# prose containing an equals sign is never touched.
#
# The phrase→feature map below is the only prose glue in this module: it says which
# GATE KEY a doc phrase refers to. The tier itself is NEVER hardcoded — it is read from
# `_FEATURE_CUTOFF`, so when a feature is rebanded (as ADR-125 rebanded coach_narrative
# 1→2) every doc that states the old ladder reds immediately.
_TIER_PHRASE_FEATURE = [
    (re.compile(r"internal\s*/?\s*dev\s+ai|internal ai|dev ai", re.I), "ensemble"),
    (re.compile(r"coach narratives?|coach commentary|\bcoaches\b", re.I), "coach_narrative"),
    (re.compile(r"reader narratives?|narrative content", re.I), "coach_narrative"),
    (re.compile(r"website ai|public ask|ask endpoints?", re.I), "website_ai"),
    (re.compile(r"hard cutoff|hard stop", re.I), "website_ai"),
    (re.compile(r"daily[- ]brief ai|brief's ai", re.I), "daily_brief_ai"),
]
_TIER_GATE_LINE = re.compile(r"budget_guard|budget-tier|budget tier|cost[_ ]governor", re.I)
_TIER_PAIR = re.compile(r"(?:tier\s*)?\*{0,2}(\d)\*{0,2}\s*[=:]\s*([^,;|]{3,70})", re.I)


def tier_semantics_hits(files, cutoffs: dict, exempt) -> list:
    """Doc lines mapping a budget tier to a surface that the live ladder puts elsewhere."""
    if not cutoffs:
        return []
    hits = []
    for doc in files:
        rel = _rel(doc)
        for lineno, line in enumerate(_lines(doc), 1):
            if exempt(line) or not _TIER_GATE_LINE.search(line):
                continue
            for mo in _TIER_PAIR.finditer(line):
                claimed = int(mo.group(1))
                phrase = mo.group(2)
                for rx, feature in _TIER_PHRASE_FEATURE:
                    if not rx.search(phrase):
                        continue
                    live = cutoffs.get(feature)
                    if live is None or live == claimed:
                        continue
                    hits.append(
                        f"{rel}:{lineno}: budget ladder puts '{phrase.strip()[:40]}' at tier {claimed}, "
                        f"but budget_guard._FEATURE_CUTOFF['{feature}'] = {live} (ADR-125, #1957)\n"
                        f"      | {line.strip()[:120]}"
                    )
    return hits


# ══════════════════════════════════════════════════════════════════════════════
# CHECK B — a doc table naming a Lambda that no CDK stack declares
# ══════════════════════════════════════════════════════════════════════════════
# Scope is deliberately the markdown TABLE cell under a "Lambda"/"Function" header —
# that is where the operational registries live (the S3-trigger table, the cadence
# table, the secret-consumer table), and it keeps prose mentions out of the blast radius.
#
# The candidate filter is DERIVED, not enumerated: a backticked hyphenated token is only
# judged if its last segment is a suffix some real CDK function uses (`-ingestion`,
# `-compute`, `-digest`, …). So `life-platform-trail` (CloudTrail) and `insight-capture`
# (an SES rule) are never candidates, while a retired-but-still-documented
# `apple-health-ingestion` is. New suffixes arrive with new Lambdas — nothing to update.
_TABLE_TOKEN = re.compile(r"`([a-z][a-z0-9]*(?:-[a-z0-9]+)+)`")
_LAMBDA_COLUMN = re.compile(r"lambda|function", re.I)


def _table_cells(lines):
    """Yield (lineno, cell_text) for cells sitting under a Lambda/Function header."""
    cols = None
    for lineno, line in enumerate(lines, 1):
        s = line.strip()
        if not (s.startswith("|") and s.endswith("|")):
            cols = None
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if set("".join(cells).replace(" ", "")) <= set("-:"):
            continue  # markdown header separator row
        if cols is None:  # first row of this table = its header
            cols = [j for j, c in enumerate(cells) if _LAMBDA_COLUMN.search(c)]
            continue
        for j in cols:
            if j < len(cells):
                yield lineno, cells[j], s


def lambda_name_hits(files, cdk_names: set, exempt) -> list:
    """Doc table cells naming a Lambda-shaped function that the CDK does not declare."""
    if not cdk_names:
        return []
    suffixes = {n.rsplit("-", 1)[-1] for n in cdk_names if "-" in n}
    hits = []
    for doc in files:
        rel = _rel(doc)
        for lineno, cell, raw in _table_cells(_lines(doc)):
            if exempt(raw):
                continue
            for mo in _TABLE_TOKEN.finditer(cell):
                name = mo.group(1)
                if name in cdk_names or name.rsplit("-", 1)[-1] not in suffixes:
                    continue
                hits.append(
                    f"{rel}:{lineno}: table names Lambda `{name}`, which no cdk/stacks/*.py declares "
                    f"(retired? renamed? — #1957)\n"
                    f"      | {raw.strip()[:120]}"
                )
    return hits


# ══════════════════════════════════════════════════════════════════════════════
# CHECK C — CloudWatch alarm-inventory claims
# ══════════════════════════════════════════════════════════════════════════════
# `alarm_count` was in check_doc_facts' ground-truth dict but had no FACT_SPEC pattern,
# so "~50 alarms" sat two lines from an auto-stamped "81 alarms" on the same page. The
# ≥20 floor keeps incident prose ("3 alarms sat red 9 days") out of a platform-inventory
# rule; ±10% honours the "~" the doc rightly uses.
_ALARM_CLAIM = re.compile(r"(?<![\w.$])(\d+)\s+(?:metric\s+)?alarms?\b")
_ALARM_INVENTORY_FLOOR = 20


def alarm_count_hits(files, truth: int, exempt, tol: float = 0.10) -> list:
    """Doc lines claiming a platform-wide alarm count that disagrees with the CDK."""
    if not truth:
        return []
    hits = []
    for doc in files:
        rel = _rel(doc)
        for lineno, line in enumerate(_lines(doc), 1):
            if exempt(line):
                continue
            for mo in _ALARM_CLAIM.finditer(line):
                claim = int(mo.group(1))
                if claim < _ALARM_INVENTORY_FLOOR or abs(claim - truth) <= round(truth * tol):
                    continue
                hits.append(
                    f"{rel}:{lineno}: alarm inventory claims {claim}, CDK declares {truth} (±{round(tol*100)}%, #1957)\n"
                    f"      | {line.strip()[:120]}"
                )
    return hits


# ══════════════════════════════════════════════════════════════════════════════
# CHECK D — secret inventory: count, table, deleted-but-granted, and freshness
# ══════════════════════════════════════════════════════════════════════════════
# Three independent failures produced the 2026-07-28 finding, so there are three rules:
#   D1 the stamped count must equal the number of LIVE rows the inventory table lists
#      (21 claimed / 12 listed passed every gate for months);
#   D2 no secret an IAM role is granted may be listed as deleted (`life-platform/notion`
#      was marked SOFT-DELETED while a role read it and AWS served it);
#   D3 the `live-verified` stamp on the literal must be inside the freshness window —
#      the count cannot be discovered from the repo, so its VERIFICATION DATE is the
#      thing CI can hold. Without D3 the doc-sync re-stamps "Last updated" over a fact
#      last checked months ago: manufactured freshness, the root cause in the finding.
SECRET_VERIFY_MAX_AGE_DAYS = 90
_SECRET_ROW = re.compile(r"`(life-platform/[a-z0-9-]+)`")
_STRUCK = re.compile(r"~~")


def secret_table_rows(lines):
    """(live, deleted) secret-name sets read from a markdown inventory table.

    A row is DELETED when the doc strikes the name through (`~~name~~`) — the convention
    the Secrets Manager section already uses for its deletion ledger.
    """
    live, deleted = set(), set()
    for line in lines:
        s = line.strip()
        if not (s.startswith("|") and s.endswith("|")):
            continue
        first = s.strip("|").split("|")[0]
        for mo in _SECRET_ROW.finditer(first):
            (deleted if _STRUCK.search(first) else live).add(mo.group(1))
    return live, deleted


def secret_inventory_hits(doc_path, count, verified, granted: set, today=None) -> list:
    """Inventory-consistency + freshness hits for the stamped secret count."""
    hits = []
    rel = _rel(doc_path)
    if count is None:
        return [
            f"{rel}: could not read the `secret_count` literal + `live-verified` date from "
            f"deploy/sync_doc_metadata.py — the secret-inventory gate would be vacuous (#1957)"
        ]
    live, deleted = secret_table_rows(_lines(doc_path))
    if live and len(live) != count:
        hits.append(
            f"{rel}: secret inventory lists {len(live)} live secrets but the stamped count is {count} "
            f"— refresh with `python3 deploy/sync_doc_metadata.py --refresh-secrets` and fix the table (#1957)"
        )
    for name in sorted(deleted & granted):
        hits.append(
            f"{rel}: `{name}` is documented as deleted but an IAM role in cdk/stacks/role_policies.py "
            f"is granted it — one of the two is wrong (#1957)"
        )
    age = ((today or _dt.date.today()) - verified).days
    if age > SECRET_VERIFY_MAX_AGE_DAYS:
        hits.append(
            f"deploy/sync_doc_metadata.py: `secret_count` live-verified {verified} — {age}d old "
            f"(ceiling {SECRET_VERIFY_MAX_AGE_DAYS}d). Re-verify: "
            f"`python3 deploy/sync_doc_metadata.py --refresh-secrets` (#1957)"
        )
    return hits


# ══════════════════════════════════════════════════════════════════════════════
# CHECK E — ingestion cadence claims: paused sources + the scheduled-Lambda count
# ══════════════════════════════════════════════════════════════════════════════
# The drift shape (#2003): CLAUDE.md's ingest bullet hand-stated Garmin as a live
# "4x daily" EventBridge pull two months after ADR-074 paused it and the rule was
# removed — while `lambdas/ingestion/source_registry.py` (`paused: True`, method
# facet "…paused (ADR-074)") and `cdk/stacks/ingestion_stack.py` (no `schedule=`
# on the garmin Lambda, with a comment explaining why) both already told the truth.
# Two rules, both ground-truthed from source, never from an enumerated doc string:
#   E1 no doc line names a PAUSED source next to live-cadence language ("4x daily",
#      "hourly") without also saying so is paused;
#   E2 no doc line hand-states a "N scheduled ingestion Lambda functions" count that
#      disagrees with the live `schedule=` count in the CDK stack.
_CADENCE_LANGUAGE = re.compile(r"\b\d+x\s*(?:daily|/\s*day|\s*a\s*day)\b|\bhourly\b", re.I)


def ingestion_paused_cadence_hits(files, paused: dict, exempt) -> list:
    """Doc lines naming a paused ingestion source next to live-cadence language."""
    if not paused:
        return []
    needles = {v.lower() for v in paused.values()} | {k.lower() for k in paused}
    hits = []
    for doc in files:
        rel = _rel(doc)
        for lineno, line in enumerate(_lines(doc), 1):
            if exempt(line):
                continue
            low = line.lower()
            if "paused" in low or not _CADENCE_LANGUAGE.search(line):
                continue
            for needle in needles:
                if needle in low:
                    hits.append(
                        f"{rel}:{lineno}: names paused source '{needle}' next to live cadence language, but "
                        f"source_registry.py marks it paused — state the pause or drop the cadence claim (#2003)\n"
                        f"      | {line.strip()[:120]}"
                    )
                    break
    return hits


_SCHEDULED_INGESTION_COUNT = re.compile(r"(?<![\w.])(\d+)\s+scheduled ingestion Lambda functions?\b", re.I)


def ingestion_scheduled_count_hits(files, truth, exempt) -> list:
    """Doc lines hand-stating a scheduled-ingestion-Lambda count that disagrees with
    the live `schedule=` count in cdk/stacks/ingestion_stack.py. Exact match — this
    is a registry-derived hard count, not an approximate prose figure."""
    if truth is None:
        return []
    hits = []
    for doc in files:
        rel = _rel(doc)
        for lineno, line in enumerate(_lines(doc), 1):
            if exempt(line):
                continue
            for mo in _SCHEDULED_INGESTION_COUNT.finditer(line):
                claim = int(mo.group(1))
                if claim != truth:
                    hits.append(
                        f"{rel}:{lineno}: claims {claim} scheduled ingestion Lambda functions, but "
                        f"cdk/stacks/ingestion_stack.py's live schedule= count is {truth} (#2003)\n"
                        f"      | {line.strip()[:120]}"
                    )
    return hits


# ── small shared helpers ──────────────────────────────────────────────────────
def _rel(p: Path):
    try:
        return p.relative_to(ROOT)
    except ValueError:
        return p  # scratch file outside the repo (the non-vacuous regression tests)


def _lines(p: Path):
    return p.read_text(encoding="utf-8").splitlines()
