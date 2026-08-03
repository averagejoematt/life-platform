#!/usr/bin/env python3
"""config_mirror_audit.py — every live `config/` object a Lambda reads has an OWNER (#2057).

Why this exists
---------------
#2019 gave bucket-root `config/` a deploy path and a drift check, both built on
**repo twins**: repo `config/x.json` must equal `s3://…/config/x.json`. That is
exactly right for repo-authored registries and structurally blind to every other
way an object can arrive in that prefix. An object written by something other
than a merge — a runtime Lambda, a one-time `aws s3 cp`, a reset script — is not
"clean" in that check; it is *absent from it*, and a stale one serves silently.

This audit closes that by inverting the direction. Instead of asking "does each
repo file match S3?", it asks, of every object that is **actually live and
actually read by deployed code**: *what asserts this?* An object nothing asserts
is the finding.

Owner classes, all derived
--------------------------
``repo_twin``    The #2019 twin set — repo `config/x` ↔ S3 `config/x`. Byte
                 equality is asserted by ``config_twin_sync``, which is strictly
                 stronger than freshness, so this audit does not re-check it.
``alias``        A second key for a repo twin's bytes (`config/{user}/…`),
                 expanded from an AST-derived pattern. Also covered by
                 ``config_twin_sync`` since #2057.
``repo_source``  A repo file OUTSIDE `config/` is its origin — e.g. a catalog
                 hand-copied once with `aws s3 cp`. Ownership is real but weaker
                 than a twin: someone can point at the source, nothing asserts
                 the bytes still match. Reported, never silently green.

                 As of #2084 this class has **no live members**: both `seeds/`
                 originals were promoted to `config/` twins after the audit's
                 first run found one of them drifted (see below). The class stays
                 because it is a *rule*, not a list — the next object someone
                 `aws s3 cp`s into `config/` from elsewhere in the repo joins it
                 on its own and warns, which is exactly what it is for. Its
                 negative proof lives in `tests/test_config_mirror_audit.py`
                 against a synthetic repo, so it cannot quietly stop working
                 just because the live population is currently zero.
``writer``       An AST-derived runtime write from `lambdas/`/`mcp/`. Freshness
                 IS asserted here, with max-age read from the writer's own
                 declared TTL constant — never a number picked in this file.
``unowned``      Nothing in the repo produces it and no deployed module writes
                 it. This is the class the issue is about.

What gates, and why it is the serving path rather than a cron
-------------------------------------------------------------
Staleness is only a *lie to readers* when the public serving path reads the
object. `config/hevy_template_cache.json` is ~6 weeks past its declared 24h TTL
and that is correct — it is a demand-driven cache written on a miss, and its
readers fall back to the movement catalog's hint. Gating on a cron-derived
cadence would make that a permanent false alarm while proving nothing.

So ``--strict`` fails on a mirror that is **stale or unowned AND read from
`lambdas/web/`**, and warns otherwise. The serving path, not the schedule, is
what turns staleness into something a reader is told.

What the first `repo_source` WARN turned out to be (#2084)
---------------------------------------------------------
The warn on `config/challenges_catalog.json` was worth having. Its `seeds/`
origin still named six real, non-consenting clinicians; the live object named
the fictional cast, so the divergence looked like "live evolved, seed is stale"
— true, and not the whole story. The live object was itself a **pre-#1904**
first-pass remap onto *retired* personas, superseded 2026-08-01 by the roster-
clean catalog that reached only `site/config/`. `/api/challenges` (which reads
bucket-root `config/`) was still serving 49 off-roster recommender names on
2026-08-03 while `/api/challenge_catalog` (which reads `site/config/`) was
clean — two endpoints, one catalog, two different casts.

The lesson generalises past this file: "the live object diverges from its repo
origin" says nothing about **which** is current. Both can be stale relative to
a third copy. Promote to a twin and the question stops being askable.

Read-only: ListObjectsV2 + HeadObject. Never writes, never invalidates.

    python3 deploy/config_mirror_audit.py            # report
    python3 deploy/config_mirror_audit.py --strict   # …and exit 1 on a serving finding
    python3 deploy/config_mirror_audit.py --json     # machine-readable
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config_twin_registry import (  # noqa: E402
    REPO_CONFIG_DIR,
    S3_CONFIG_PREFIX,
    Registry,
    derive,
    expand_alias_twins,
)

S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
AWS_REGION = os.environ.get("AWS_REGION", "us-west-2")

# Consumers under this tree are the public serving path — the same definition
# config_twin_sync uses, so severity means the same thing in both tools.
SERVING_PATH_PREFIX = "lambdas/web/"

OWNER_REPO_TWIN = "repo_twin"
OWNER_ALIAS = "alias"
OWNER_REPO_SOURCE = "repo_source"
OWNER_WRITER = "writer"
OWNER_NONE = "unowned"

# Module-level constants a writer may use to declare how long its output stays
# valid. Matched by NAME so the writer keeps ownership of the number: this file
# never supplies a max-age of its own, per the freshness-window rule (a window
# encodes the WRITER's cadence, so it has to come from the writer).
_TTL_NAME_PATTERNS = ("*TTL*", "*MAX_AGE*", "*REFRESH_SECONDS*", "*REFRESH_INTERVAL*")

_ICON = {"ok": "🟢", "warn": "🟡", "fail": "🔴"}


@dataclass
class Finding:
    key: str
    owner: str
    detail: str
    consumers: list[str] = field(default_factory=list)
    serving: bool = False
    verdict: str = "ok"  # ok | warn | fail
    age_seconds: int | None = None
    max_age_seconds: int | None = None
    source: str | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Writer-declared max-age (AST)
# ─────────────────────────────────────────────────────────────────────────────


_ARITH = {
    ast.Mult: lambda a, b: a * b,
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.FloorDiv: lambda a, b: a // b if b else None,
}


def _static_int(node: ast.AST | None) -> int | None:
    """Best-effort int from an expression, digging through wrapper calls.

    `TTL_SECONDS = int(os.environ.get("HEVY_TEMPLATE_CACHE_TTL", str(24 * 3600)))`
    is the shape that matters, and it defeats the obvious approach twice over:
    the real number is the env-var DEFAULT (three calls deep), and it is written
    as `24 * 3600`, which `ast.literal_eval` refuses — it folds only `+`/`-` for
    complex literals, never `*`. A window written the way humans write windows
    would therefore read as "no window declared", and the freshness assertion
    would silently never apply. So: fold the arithmetic here, then recurse into
    call arguments to reach the default wherever the writer wrapped it.
    """
    if node is None:
        return None
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            return None
        return int(node.value)
    if isinstance(node, ast.BinOp):
        operation = _ARITH.get(type(node.op))
        left, right = _static_int(node.left), _static_int(node.right)
        if operation is not None and left is not None and right is not None:
            folded = operation(left, right)
            return None if folded is None else int(folded)
        return None
    if isinstance(node, ast.Call):
        for arg in list(node.args) + [kw.value for kw in node.keywords]:
            found = _static_int(arg)
            if found is not None:
                return found
    return None


def writer_max_age(repo_root: str, modules: tuple[str, ...]) -> tuple[int | None, str | None]:
    """The writer's own declared validity window, in seconds.

    Returns (seconds, "module:CONST") or (None, None) when the writer declares
    none — in which case this audit asserts NO freshness for the object rather
    than inventing a window. A silent default here would be a hand-picked
    constant wearing a derivation's clothes.
    """
    best: tuple[int, str] | None = None
    for module in modules:
        path = os.path.join(repo_root, module.replace("/", os.sep))
        try:
            with open(path, "r", encoding="utf-8") as handle:
                tree = ast.parse(handle.read())
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                continue
            target = node.targets[0]
            if not isinstance(target, ast.Name):
                continue
            if not any(fnmatch.fnmatch(target.id, pattern) for pattern in _TTL_NAME_PATTERNS):
                continue
            seconds = _static_int(node.value)
            if seconds and seconds > 0 and (best is None or seconds > best[0]):
                best = (seconds, f"{module}:{target.id}")
    return (best[0], best[1]) if best else (None, None)


# ─────────────────────────────────────────────────────────────────────────────
# Repo sources outside config/
# ─────────────────────────────────────────────────────────────────────────────


def repo_sources_by_basename(repo_root: str) -> dict[str, list[str]]:
    """Git-tracked files OUTSIDE `config/`, indexed by basename.

    Derived from the index rather than a list of blessed directories, so the
    `seeds/` originals are found without this file naming `seeds/`.
    """
    try:
        paths = [
            p
            for p in subprocess.run(
                ["git", "-C", repo_root, "ls-files", "-z"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.split("\0")
            if p
        ]
    except (subprocess.CalledProcessError, FileNotFoundError):
        # Not a git checkout (tarball, test fixture) — walk instead, so the
        # derivation still works rather than silently reporting everything
        # unowned, which would be a false alarm in the gating direction.
        paths = []
        for dirpath, dirnames, filenames in os.walk(repo_root):
            dirnames[:] = [d for d in dirnames if d not in ("__pycache__", ".git", "node_modules")]
            for filename in filenames:
                rel = os.path.relpath(os.path.join(dirpath, filename), repo_root).replace(os.sep, "/")
                paths.append(rel)

    index: dict[str, list[str]] = {}
    for path in paths:
        if path.startswith(REPO_CONFIG_DIR + "/"):
            continue
        index.setdefault(path.rsplit("/", 1)[-1], []).append(path)
    return index


# ─────────────────────────────────────────────────────────────────────────────
# The audit
# ─────────────────────────────────────────────────────────────────────────────


def readers_of(registry: Registry, key: str, repo_root: str) -> list[str]:
    """Deployed modules that read this live S3 key.

    Pattern edges are matched with fnmatch; a bare-filename edge only counts
    when a repo `config/` file with that name actually exists, which is the same
    bound the registry puts on its loose reader harvest.
    """
    modules: set[str] = set()
    for pattern, mods in registry.read_patterns.items():
        if fnmatch.fnmatch(key, pattern):
            modules.update(mods)
    basename = key.rsplit("/", 1)[-1]
    if basename in registry.bare_reads and os.path.exists(os.path.join(repo_root, key.replace("/", os.sep))):
        modules.update(registry.bare_reads[basename])
    return sorted(modules)


def audit(registry: Registry, live: dict[str, datetime], repo_root: str, now: datetime) -> list[Finding]:
    """Classify every live `config/` object a deployed module reads."""
    twin_keys = set(registry.by_key())
    alias_twins = {t.key: t for t in expand_alias_twins(registry, list(live))}
    sources = repo_sources_by_basename(repo_root)
    findings: list[Finding] = []

    for key in sorted(live):
        consumers = readers_of(registry, key, repo_root)
        if not consumers:
            continue  # nothing deployed reads it — not a serving-truth question
        serving = any(m.startswith(SERVING_PATH_PREFIX) for m in consumers)
        finding = Finding(key=key, owner=OWNER_NONE, detail="", consumers=consumers, serving=serving)

        writers = tuple(sorted({m for pattern, mods in registry.runtime_written.items() if fnmatch.fnmatch(key, pattern) for m in mods}))

        if key in twin_keys:
            finding.owner = OWNER_REPO_TWIN
            finding.source = key
            finding.detail = "repo twin — byte equality asserted by config_twin_sync"
        elif key in alias_twins:
            finding.owner = OWNER_ALIAS
            finding.source = alias_twins[key].alias_of
            finding.detail = f"alias of {alias_twins[key].alias_of} — byte equality asserted by config_twin_sync (#2057)"
        elif writers:
            finding.owner = OWNER_WRITER
            finding.source = ", ".join(writers)
            max_age, declared_by = writer_max_age(repo_root, writers)
            age = int((now - live[key]).total_seconds())
            finding.age_seconds = age
            finding.max_age_seconds = max_age
            if max_age is None:
                finding.detail = f"written by {finding.source}; no declared validity window, so no freshness assertion"
                finding.verdict = "warn"
            elif age > max_age:
                finding.detail = f"STALE — {age}s old, past the {max_age}s window declared at {declared_by}"
                finding.verdict = "fail" if serving else "warn"
            else:
                finding.detail = f"fresh — {age}s old, within the {max_age}s window declared at {declared_by}"
        else:
            matches = sources.get(key.rsplit("/", 1)[-1], [])
            if matches:
                finding.owner = OWNER_REPO_SOURCE
                finding.source = ", ".join(matches)
                finding.detail = f"origin {finding.source} — outside config/, so no twin asserts the bytes still match"
                finding.verdict = "warn"
            else:
                finding.detail = "UNOWNED — no repo file produces it and no deployed module writes it"
                finding.verdict = "fail" if serving else "warn"

        findings.append(finding)
    return findings


def summarize(findings: list[Finding]) -> dict:
    failures = [f for f in findings if f.verdict == "fail"]
    return {
        "bucket": S3_BUCKET,
        "audited": len(findings),
        "by_owner": {owner: sum(1 for f in findings if f.owner == owner) for owner in sorted({f.owner for f in findings})},
        "failures": [f.key for f in failures],
        "warnings": [f.key for f in findings if f.verdict == "warn"],
        "findings": [asdict(f) for f in findings],
        "clean": not failures,
    }


def _live_objects(s3) -> dict[str, datetime]:
    """{key: LastModified} for bucket-root `config/` (paginated, read-only)."""
    live: dict[str, datetime] = {}
    token = None
    while True:
        kwargs = {"Bucket": S3_BUCKET, "Prefix": S3_CONFIG_PREFIX}
        if token:
            kwargs["ContinuationToken"] = token
        page = s3.list_objects_v2(**kwargs)
        for item in page.get("Contents", []):
            live[item["Key"]] = item["LastModified"]
        if not page.get("IsTruncated"):
            return live
        token = page.get("NextContinuationToken")
        if not token:
            return live


def _print_human(report: dict) -> None:
    print(f"config mirror ownership — s3://{report['bucket']}/config/ ({report['audited']} live objects read by deployed code)")
    for owner, count in sorted(report["by_owner"].items()):
        print(f"  {count:3}  {owner}")
    print()
    for raw in report["findings"]:
        if raw["verdict"] == "ok":
            continue
        tag = " [SERVING]" if raw["serving"] else ""
        print(f"  {_ICON[raw['verdict']]} {raw['verdict'].upper():4} {raw['key']}{tag}")
        print(f"           {raw['detail']}")
    if report["clean"]:
        print("  🟢 no serving-path mirror is stale or unowned")
    else:
        print(f"\n  {len(report['failures'])} serving-path mirror(s) stale or unowned — a reader is being told something nothing asserts")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--strict", action="store_true", help="exit 1 when a serving-path mirror is stale or unowned")
    parser.add_argument("--json", action="store_true", dest="as_json", help="machine-readable report")
    args = parser.parse_args()

    import boto3

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    registry = derive(repo_root)
    s3 = boto3.client("s3", region_name=AWS_REGION)
    live = _live_objects(s3)

    findings = audit(registry, live, repo_root, datetime.now(timezone.utc))
    report = summarize(findings)

    if args.as_json:
        print(json.dumps(report, indent=2, sort_keys=True, default=str))
    else:
        _print_human(report)

    return 1 if (args.strict and not report["clean"]) else 0


if __name__ == "__main__":
    sys.exit(main())
