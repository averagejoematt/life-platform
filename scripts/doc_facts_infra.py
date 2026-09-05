#!/usr/bin/env python3
"""scripts/doc_facts_infra.py — the #3509 infrastructure-fact rules for check_doc_facts.py.

WHY THIS MODULE EXISTS
  The 2026-09-05 `/review full` (CTO-4, INT-4) found four operational claims an incident
  responder reads, all wrong, and `grep -n -i 'canary|eventbridge|async lambda|dlq'
  scripts/check_doc_facts.py` returned nothing — no rule owned any of them:

    docs/ARCHITECTURE.md  "Canary Lambda (synthetic health check every 30 min)"
                          -> `life-platform-canary` is `rate(4 hours)` in operational_stack
    docs/ARCHITECTURE.md  "~50 EventBridge rules"        -> 88 CDK-defined schedule rules
    docs/ARCHITECTURE.md  "DLQ coverage: all async ..."  -> five async Lambdas have none
    source_registry.py    "the PAGING slo-source-freshness alarm"
                          -> `to_digest=True` in monitoring_stack.py; it digests

  The canary line is the sharpest instrument defect of the four: the #1205 cron rule that
  exists precisely to diff a doc's schedule against the CDK's could never see it, because
  `CRON_RE`/`_cdk_cron_map()` match `cron(...)` ONLY. Every `rate(...)` schedule on the
  platform was invisible to the gate that was supposed to police schedules.

PRECISION over recall, same as the parent module. Every rule here is forward-phrased and
narrow, and each was measured against the live corpus before landing (hit counts in the
per-rule notes below). Ground truth is always derived — from the #2845 model generator's
AST walk (`extract_lambdas`, `extract_alarms`) or from `model/platform_model.json` — never
hand-typed here.
"""

import ast
import importlib.util
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ARCHITECTURE_PATH = ROOT / "docs" / "ARCHITECTURE.md"
SOURCE_REGISTRY_PATH = ROOT / "lambdas" / "ingestion" / "source_registry.py"
MODEL_PATH = ROOT / "model" / "platform_model.json"
CDK_STACKS_DIR = ROOT / "cdk" / "stacks"
FRESHNESS_ALARM = "slo-source-freshness"


def _load_model_gen():
    """generate_platform_model.py, loaded by path — the same convention check_doc_facts.py
    uses for its own siblings (this file is spec-loaded, so `scripts/` is not importable
    as a package)."""
    spec = importlib.util.spec_from_file_location("_platformmodelgen_infra", ROOT / "scripts" / "generate_platform_model.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# ── ground truth 1: the CDK schedule map, cron AND rate ───────────────────────
def cdk_schedule_map() -> dict:
    """function_name -> sorted list of every resolvable schedule expression.

    Deliberately the SUPERSET of `check_doc_facts._cdk_cron_map()`: that map filters to
    `expr.startswith("cron(")`, which is the blind spot #3509 is about. Dynamic /
    unresolved schedules carry no expression and are dropped (there is nothing to diff a
    doc value against); a function with no resolvable schedule is omitted entirely.
    """
    out: dict[str, list[str]] = {}
    try:
        lambdas = _load_model_gen().extract_lambdas()
    except Exception:
        return out
    for name, record in lambdas.items():
        exprs = sorted({s["expr"] for s in record["schedules"] if s.get("resolution") != "dynamic" and s.get("expr")})
        if exprs:
            out[name] = exprs
    return out


# ── ground truth 2: the EventBridge rule count ────────────────────────────────
def eventbridge_rule_count() -> int | None:
    """CDK-defined EventBridge schedule rules — `meta.counts.schedules` in the #2845 system
    model (`model/platform_model.json`), which is the flattened lambdas-plane schedule list.

    Why the model and not `aws events list-rules` (95 on 2026-09-04): a doc gate must not
    need AWS credentials, and the sentence being policed is "CDK owns ... N EventBridge
    rules" — a claim about what the IaC declares. The live 95 also counts rules CDK does
    not own (e.g. the hand-made `life-platform-mcp-canary-15min`) and non-schedule rules,
    so it is the wrong number for that sentence even where creds exist.

    Returns None when the model is missing/unreadable; the caller's `missing` check in
    check_doc_facts.main() then fails loud rather than silently skipping the fact.
    """
    try:
        counts = json.loads(MODEL_PATH.read_text(encoding="utf-8"))["meta"]["counts"]
    except Exception:
        return None
    value = counts.get("schedules")
    return value if isinstance(value, int) else None


# ── rule 1: `rate(...)` cadence — the #1205 cron rule's blind spot ────────────
# Two halves, both anchored on "the line names EXACTLY ONE known CDK function", the same
# unambiguity requirement `_cron_hits` uses:
#   LITERAL — the line quotes exactly one `rate(...)` that is none of that function's real
#             schedules (the direct analogue of the cron diff).
#   PROSE   — the function's schedules are ALL `rate(N <unit>)` and the line states exactly
#             one "every N <unit>" interval that equals none of them. This is the half that
#             owns the founding defect: "synthetic health check every 30 min" quotes no
#             schedule expression at all, so a literal-only rule can never see it.
# Mixed cron+rate functions are skipped by the PROSE half (a human interval cannot be
# compared against a cron without re-implementing a cron parser — out of scope, and the
# cron half of the family is already policed by #1205).
# Measured on the live corpus (docs + lambdas + mcp + cdk/stacks + scripts): 0 hits.
RATE_RE = re.compile(r"rate\([^)]*\)")
_RATE_EXPR_RE = re.compile(r"rate\((\d+)\s+(\w+)\)")
_INTERVAL_UNITS = {
    "minute": 1,
    "minutes": 1,
    "min": 1,
    "mins": 1,
    "hour": 60,
    "hours": 60,
    "hr": 60,
    "hrs": 60,
    "day": 1440,
    "days": 1440,
}
_INTERVAL_CLAIM_RE = re.compile(r"\bevery\s+(\d+)\s*(minutes|minute|mins|min|hours|hour|hrs|hr|days|day)\b", re.I)


def _rate_minutes(expr: str) -> int | None:
    mo = _RATE_EXPR_RE.fullmatch(expr.strip())
    if not mo or mo.group(2) not in _INTERVAL_UNITS:
        return None
    return int(mo.group(1)) * _INTERVAL_UNITS[mo.group(2)]


def rate_schedule_hits(files, schedule_map: dict, exempt) -> list[str]:
    """Lines quoting a `rate(...)` or a human interval that disagrees with the CDK schedule.

    `exempt` is check_doc_facts.line_is_exempt — the ONE historical/drift-ok predicate, passed
    in rather than redefined. Exposed (and `schedule_map` injectable) so the regression test can
    plant a violation in a scratch file and prove the rule bites — the #1189 non-vacuous-scan
    lesson: a rule nobody has watched fail is not known to be able to fail.
    """
    if not schedule_map:
        return []
    name_res = {n: re.compile(r"(?<![\w-])" + re.escape(n) + r"(?![\w-])") for n in schedule_map}
    hits = []
    for path in files:
        try:
            rel = path.relative_to(ROOT)
        except ValueError:
            rel = path  # scratch file outside the repo (the non-vacuous test)
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for lineno, line in enumerate(lines, 1):
            if exempt(line):
                continue
            named = [n for n, rx in name_res.items() if rx.search(line)]
            if len(named) != 1:
                continue  # no CDK function named, or ambiguous multi-function line
            name = named[0]
            exprs = schedule_map[name]
            quoted = RATE_RE.findall(line)
            if len(quoted) == 1 and quoted[0] not in exprs:
                hits.append(
                    f"{rel}:{lineno}: schedule for `{name}` claims {quoted[0]}, CDK schedules "
                    f"{' or '.join(exprs)} (#3509)\n      | {line.strip()[:140]}"
                )
            minutes = [_rate_minutes(e) for e in exprs]
            if None in minutes:
                continue  # a cron (or an unparseable rate) is in the set — PROSE half abstains
            claims = _INTERVAL_CLAIM_RE.findall(line)
            if len(claims) != 1:
                continue  # 0 intervals, or ambiguous multi-interval line
            claimed = int(claims[0][0]) * _INTERVAL_UNITS[claims[0][1].lower()]
            if claimed not in minutes:
                hits.append(
                    f"{rel}:{lineno}: cadence for `{name}` claims every {claims[0][0]} {claims[0][1]}, "
                    f"CDK schedules {' or '.join(exprs)} (#3509)\n      | {line.strip()[:140]}"
                )
    return hits


# ── rule 2: the DLQ exception set ────────────────────────────────────────────
# "DLQ coverage: all async Lambdas -> life-platform-ingestion-dlq" was simply false
# (`telegram-coach-worker` has `DeadLetterConfig: null`). Making it true by construction is
# #3500/CTO-5's story; this makes it HONEST AND CHECKABLE — the doc names the exception set
# and this rule derives that set from the CDK, so the sentence reds the moment the two
# disagree in EITHER direction (a new uncovered async Lambda, or a covered one still listed).
#
# "async-invoked" is derived from three CDK/source-visible wirings, all of which invoke a
# Lambda asynchronously (so a terminal failure is discarded unless a DLQ catches it):
#   1. `schedule=` on the construct              — EventBridge -> async
#   2. `sns_subs.LambdaSubscription(fn)`         — SNS -> async
#   3. `invoke(..., InvocationType="Event")` in lambdas/ or mcp/ naming the function
# Known limit, stated rather than hidden: a target #3 whose FunctionName is a runtime
# variable (dlq_consumer's replay of the ORIGINAL failed function) cannot be resolved and is
# not counted. The schedule/SNS legs are fully resolved.
_DLQ_SENTENCE_RE = re.compile(r"DLQ coverage:")
_BACKTICKED_RE = re.compile(r"`([a-z0-9][a-z0-9-]+)`")


def _dict_literals(tree: ast.Module) -> dict:
    """name -> {kwarg: <ast node>} for `name = dict(...)` / `name = {...}` assignments.

    The stacks build their per-Lambda kwargs as a shared dict spread into every call
    (`**shared`), so a scan that reads only explicit keywords sees `dlq` as absent on ~80
    functions that in fact have one — measured against live `aws lambda list-functions`,
    which reports exactly 11 functions with a null DeadLetterConfig.
    """
    out: dict[str, dict] = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)):
            continue
        value = node.value
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id == "dict":
            out[node.targets[0].id] = {kw.arg: kw.value for kw in value.keywords if kw.arg}
        elif isinstance(value, ast.Dict):
            keys = {k.value: v for k, v in zip(value.keys, value.values) if isinstance(k, ast.Constant) and isinstance(k.value, str)}
            if keys:
                out[node.targets[0].id] = keys
    return out


def _spread_kwargs(node: ast.Call, dicts: dict) -> tuple[dict, list[str]]:
    """Resolve a call's `**spread` arguments into {kwarg: <ast node>}, plus the list of
    spreads that could NOT be resolved.

    Three spread shapes exist in cdk/stacks: `**shared`, `**{**shared, "k": v}` and
    `**{k: v for k, v in shared.items() if k != "alerts_topic"}`. Anything else is reported
    unresolved and made loud by the caller — silently treating an unreadable spread as "no
    dlq" would invent exceptions, and treating it as "has dlq" would hide real ones.
    """
    merged: dict = {}
    unresolved: list[str] = []
    for kw in node.keywords:
        if kw.arg is not None:
            continue
        value = kw.value
        if isinstance(value, ast.Name):
            merged.update(dicts.get(value.id, {}))
        elif isinstance(value, ast.Dict):
            for k, v in zip(value.keys, value.values):
                if k is None and isinstance(v, ast.Name):
                    merged.update(dicts.get(v.id, {}))
                elif isinstance(k, ast.Constant) and isinstance(k.value, str):
                    merged[k.value] = v
        elif isinstance(value, ast.DictComp):
            base = next((n.id for n in ast.walk(value.generators[0].iter) if isinstance(n, ast.Name)), None)
            merged.update(dicts.get(base, {}))
            for cond in value.generators[0].ifs:  # `if k != "alerts_topic"` — a key REMOVAL
                for const in (n.value for n in ast.walk(cond) if isinstance(n, ast.Constant)):
                    merged.pop(const, None)
        else:
            unresolved.append(ast.unparse(value))
    return merged, unresolved


def cdk_constructs() -> tuple[dict, dict, list[str]]:
    """(name -> {'dlq': bool, 'scheduled': bool}, name -> variable it is bound to, unresolved spreads).

    Its own const-resolving walk rather than `extract_lambdas()` because the model generator
    requires a literal `function_name=`, so mcp_stack's two constant-named functions
    (`life-platform-mcp`, `life-platform-mcp-warmer`) are absent from the model — and the
    warmer is exactly one of the scheduled, DLQ-less functions this rule must not miss.
    """
    gen = _load_model_gen()
    records: dict[str, dict] = {}
    var_to_name: dict[str, str] = {}
    unresolved: list[str] = []
    for path in sorted(CDK_STACKS_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        consts = gen._module_str_consts(tree)
        dicts = _dict_literals(tree)
        for node in ast.walk(tree):
            call = node.value if isinstance(node, ast.Assign) and len(node.targets) == 1 else node
            if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "create_platform_lambda"):
                continue
            kwargs, bad = _spread_kwargs(call, dicts)
            unresolved += [f"{path.name}: **{u}" for u in bad]
            kwargs.update({kw.arg: kw.value for kw in call.keywords if kw.arg})
            name = gen._resolve_str(kwargs["function_name"], consts) if "function_name" in kwargs else None
            if not name:
                continue
            dlq, sched = kwargs.get("dlq"), kwargs.get("schedule")
            records[name] = {
                "dlq": dlq is not None and not (isinstance(dlq, ast.Constant) and dlq.value is None),
                "scheduled": sched is not None and not (isinstance(sched, ast.Constant) and sched.value is None),
            }
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
                var_to_name[f"{path.name}::{node.targets[0].id}"] = name
    return records, var_to_name, unresolved


def _module_consts(tree: ast.Module) -> dict:
    """Module-level string constants, including the `os.environ.get("X", "default")` idiom the
    coach/telegram callers use to name their async target."""
    consts = _load_model_gen()._module_str_consts(tree)
    for node in tree.body:
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)):
            continue
        call = node.value
        if isinstance(call, ast.Call) and len(call.args) == 2 and isinstance(call.args[1], ast.Constant):
            if ast.unparse(call.func).endswith("environ.get") and isinstance(call.args[1].value, str):
                consts.setdefault(node.targets[0].id, call.args[1].value)
    return consts


def _async_event_targets() -> set:
    """Function names invoked with `InvocationType="Event"` from lambdas/ or mcp/."""
    targets: set = set()
    for root in (ROOT / "lambdas", ROOT / "mcp"):
        for path in sorted(root.rglob("*.py")):
            src = path.read_text(encoding="utf-8", errors="ignore")
            if "InvocationType" not in src:
                continue
            try:
                tree = ast.parse(src)
            except SyntaxError:
                continue
            consts = _module_consts(tree)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                kwargs = {kw.arg: kw.value for kw in node.keywords if kw.arg}
                invocation = kwargs.get("InvocationType")
                if not (isinstance(invocation, ast.Constant) and invocation.value == "Event"):
                    continue
                fn = kwargs.get("FunctionName")
                name = None
                if isinstance(fn, ast.Constant) and isinstance(fn.value, str):
                    name = fn.value
                elif isinstance(fn, ast.Name):
                    name = consts.get(fn.id)
                elif isinstance(fn, ast.Call) and len(fn.args) == 2 and isinstance(fn.args[1], ast.Constant):
                    name = fn.args[1].value  # os.environ.get("X", "default-name")
                if isinstance(name, str) and name:
                    targets.add(name)
    return targets


def _sns_lambda_targets(var_to_name: dict) -> set:
    """Lambdas subscribed to an SNS topic — SNS invokes its Lambda targets asynchronously."""
    names: set = set()
    for path in sorted(CDK_STACKS_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and node.args):
                continue
            if (getattr(node.func, "attr", None) or getattr(node.func, "id", None)) != "LambdaSubscription":
                continue
            arg = node.args[0]
            if isinstance(arg, ast.Name):
                resolved = var_to_name.get(f"{path.name}::{arg.id}")
                if resolved:
                    names.add(resolved)
    return names


def async_invoked_names(records: dict = None, var_to_name: dict = None) -> set:
    """Every Lambda the platform invokes asynchronously (schedule | SNS | InvocationType=Event)."""
    if records is None:
        records, var_to_name, _ = cdk_constructs()
    names = {n for n, r in records.items() if r["scheduled"]}
    names |= set(cdk_schedule_map())  # + standalone events.Rule(...).add_target(...) wirings
    names |= _async_event_targets()
    names |= _sns_lambda_targets(var_to_name or {})
    return names


def dlq_exception_set() -> tuple[set, dict, list[str]]:
    """(async-invoked Lambdas whose CDK construct has NO DLQ, the construct records, spread notes)."""
    records, var_to_name, unresolved = cdk_constructs()
    async_names = async_invoked_names(records, var_to_name)
    return {n for n in async_names if records.get(n, {}).get("dlq") is False}, records, unresolved


def dlq_exception_hits(doc_path: Path = ARCHITECTURE_PATH, derived: set = None, records: dict = None, unresolved: list = None) -> list[str]:
    """The doc's stated DLQ exception set vs the CDK's. Injectable for the negative-control test.

    Blindness detector first (#2578's rule — a derivation that finds nothing must red, never
    silently pass): if the `DLQ coverage:` sentence has vanished, or a `**spread` in the CDK
    could not be resolved, that is a failure, not a green.
    """
    if derived is None:
        derived, records, unresolved = dlq_exception_set()
    hits = [
        f"cdk/stacks: unresolved create_platform_lambda spread {u} — the #3509 DLQ derivation went partly blind" for u in unresolved or []
    ]
    lines = doc_path.read_text(encoding="utf-8").splitlines() if doc_path.exists() else []
    stated, found = set(), False
    for line in lines:
        if not _DLQ_SENTENCE_RE.search(line):
            continue
        found = True
        stated |= {n for n in _BACKTICKED_RE.findall(line) if n in (records or {})}
    rel = doc_path.relative_to(ROOT) if doc_path.is_absolute() and str(doc_path).startswith(str(ROOT)) else doc_path
    if not found:
        return hits + [f"{rel}: the 'DLQ coverage:' sentence is gone — the #3509 DLQ-parity rule has nothing to check"]
    if stated != derived:
        hits.append(
            f"{rel}: DLQ exception set is stale — doc says {sorted(stated) or '[]'}, "
            f"CDK says {sorted(derived) or '[]'} (async-invoked constructs with no dlq=) (#3509)"
        )
    return hits


# ── rule 3: an alarm's documented ROUTE vs its `to_digest` flag ───────────────
# `source_registry.py` called `slo-source-freshness` "the paging ... alarm" — wrong when
# written (2026-08-09), three months after ADR-052's deliberate `to_digest=True`. The pager
# for that failure is `paging-pipeline-dead` at >=8. Ground truth is the routing class the
# #2845 alarm plane already derives by tracing `to_digest=` through the stack, so this rule
# adds no second parse of the flag.
#
# PRECISION: only the `digest` class is policed, and only for paging vocabulary. `urgent` is
# a second immediate-notification class, so "urgent-topic-routed, which is what pages" is a
# true sentence and must not be flagged. The window is +/-80 chars around the alarm NAME, over
# the alarm's own prose block (the anchor line, plus an adjacent line only when neither is a
# list/table/heading row — joining table rows produced 7 false positives from
# DEPENDENCY_GRAPH.md's generated alarm table, measured).
# Measured on the live corpus: 2 hits, both real (source_registry.py:1103 and
# PROPORTIONALITY.md:110's "Pages when the outbound privacy scrub fails CLOSED", whose alarm
# also routes to life-platform-alerts-digest — verified live, both fixed in #3509).
# The token guards are `(?<![\w-])`/`(?![\w-])`, not `\b`: `\b` matches inside the hyphenated
# alarm name `paging-pipeline-dead`, so a sentence correctly NAMING the real pager would
# flag itself. That is structural (a hyphen is part of an alarm identifier here), not a
# phrase-match suppressor — the class this repo has watched fail four times (#3379).
# `page`/`page.` alone is excluded: the corpus says "the /status/ page" and "the home
# page's protagonist", and a routing gate must not read the webpage sense of the word.
_PAGING_CLAIM_RE = re.compile(r"(?<![\w-])(?:paging|pager|page[sd]|page\s+(?:the|a|an|this))(?![\w-])", re.I)
_BLOCK_BREAK_RE = re.compile(r"^\s*(?:[|>*+#]|-\s|\d+[.)]\s)")
_ROUTE_WINDOW = 80


def alarm_routing() -> dict:
    """alarm_name -> routing class, from the #2845 alarm plane (`to_digest=` traced in AST)."""
    try:
        return {name: rec.get("routing") for name, rec in _load_model_gen().extract_alarms().items()}
    except Exception:
        return {}


def _prose_block(lines: list[str], i: int) -> str:
    """The anchor line plus each immediate neighbour that is a plain prose continuation."""
    if _BLOCK_BREAK_RE.match(lines[i]):
        return lines[i]
    parts = [lines[i]]
    if i and lines[i - 1].strip() and not _BLOCK_BREAK_RE.match(lines[i - 1]):
        parts.insert(0, lines[i - 1])
    if i + 1 < len(lines) and lines[i + 1].strip() and not _BLOCK_BREAK_RE.match(lines[i + 1]):
        parts.append(lines[i + 1])
    return " ".join(parts)


def alarm_route_hits(files, routing: dict, exempt) -> list[str]:
    """Lines claiming a digest-routed alarm pages. Injectable for the negative-control test."""
    digest = {n for n, r in routing.items() if r == "digest"}
    if not digest:
        return []
    name_res = {n: re.compile(r"(?<![\w-])" + re.escape(n) + r"(?![\w-])") for n in digest}
    hits = []
    for path in files:
        try:
            rel = path.relative_to(ROOT)
        except ValueError:
            rel = path  # scratch file outside the repo (the non-vacuous test)
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines):
            for name, rx in name_res.items():
                if not rx.search(line):
                    continue
                block = _prose_block(lines, i)
                if exempt(block):
                    continue
                mo = rx.search(block)
                window = block[max(0, mo.start() - _ROUTE_WINDOW) : mo.end() + _ROUTE_WINDOW]
                if _PAGING_CLAIM_RE.search(window):
                    hits.append(
                        f"{rel}:{i + 1}: `{name}` is documented as paging, but its CDK routing is "
                        f"digest (`to_digest=True`) (#3509)\n      | {line.strip()[:140]}"
                    )
                    break
    return hits


def registry_route_citation_hits(routing: dict, registry_path: Path = SOURCE_REGISTRY_PATH) -> list[str]:
    """`source_registry.py` must CITE the flag that decides the route, not restate the route.

    The registry is the file that is supposed to BE the freshness fact, and its header is the
    line an operator reads first — so every line there naming `slo-source-freshness` must name
    `to_digest`, the CDK keyword the routing class is derived from. That is what makes the
    prose re-checkable instead of re-assertable, and it closes the one shape the corpus rule
    above cannot see: the founding defect wrapped "the paging" and the alarm name onto two
    different lines.

    Reds in both directions, so it is also the dead-man for a future route change: if the
    alarm stops being digest-routed, a registry line still citing `to_digest` is now the lie.
    """
    route = routing.get(FRESHNESS_ALARM)
    if route is None:
        return [f"model: alarm `{FRESHNESS_ALARM}` is gone from the CDK alarm plane — the #3509 registry route rule is blind"]
    if not registry_path.exists():
        return []
    hits = []
    for lineno, line in enumerate(registry_path.read_text(encoding="utf-8").splitlines(), 1):
        if not re.search(r"(?<![\w-])" + re.escape(FRESHNESS_ALARM) + r"(?![\w-])", line) or "drift-ok" in line:
            continue
        cites = "to_digest" in line
        if route == "digest" and not cites:
            hits.append(
                f"lambdas/ingestion/source_registry.py:{lineno}: names `{FRESHNESS_ALARM}` without citing "
                f"`to_digest` — state the route by its CDK flag, not by assertion (#3509)\n      | {line.strip()[:140]}"
            )
        elif route != "digest" and cites:
            hits.append(
                f"lambdas/ingestion/source_registry.py:{lineno}: cites `to_digest` for `{FRESHNESS_ALARM}`, "
                f"whose CDK routing is now `{route}` (#3509)\n      | {line.strip()[:140]}"
            )
    return hits


def scan_infra_surface(docs) -> list[Path]:
    """`docs` (the parent gate's doc surface) + first-party Python that states these facts in
    comments — the registry header and the stack docstrings live there, not in `docs/`."""
    out = list(docs)
    for d in (ROOT / "lambdas", ROOT / "mcp", ROOT / "cdk" / "stacks"):
        if d.exists():
            out += sorted(d.rglob("*.py"))
    return out
