#!/usr/bin/env python3
"""config_twin_registry.py — DERIVE the repo↔S3 `config/` twin set (#2019).

The bucket-root `config/` prefix is the third deploy prefix (after `site/` and
`generated/`, ADR-046) and until this module it had NO deploy path at all: a
merged change to a repo `config/` file never reached S3, so the site-api Lambda
kept serving the pre-merge bytes. Measured live 2026-08-02 — a merged citation
withdrawal kept serving withdrawn citations for ~13h while CI printed green.

The twin set is DERIVED, never hand-enumerated, so a newly added repo config
file joins the deploy path automatically (guard the set, not the instance):

    base      = every git-tracked file under the repo's `config/` tree
    minus     = non-twin artifacts (docs, `*.example.*`) — an EXCLUSION rule,
                not an enumeration of the set
    minus     = keys written at RUNTIME by a Lambda (AST-derived) — syncing one
                of those would clobber live state
    annotated = which consumer modules read each key (AST-derived), which in
                turn drives the CloudFront `/api/*` invalidation set

Two asymmetric safety rules, because the two directions have opposite failure
costs:

  * WRITER scan is precise + arg-level. A write key we cannot resolve is NOT
    silently ignored and NOT allowed to swallow the whole prefix — it lands in
    `unresolved_writers`, which `tests/test_config_twin_sync.py` pins to empty.
    A new unresolvable `config/` write therefore reds a test and gets a human.
  * READER scan is deliberately loose (harvest every `config/…` string literal
    in the consumer tree). Over-collecting a reader only means we invalidate a
    little more than strictly needed; under-collecting would mean a synced
    object never starts serving.

This module is operator tooling under `deploy/` — it is NOT part of any Lambda
bundle (#781) and must stay import-light (stdlib only).
"""

from __future__ import annotations

import ast
import fnmatch
import os
import subprocess
from dataclasses import dataclass, field
from typing import Iterable

# The repo directory whose files are twins of bucket-root `config/` objects.
REPO_CONFIG_DIR = "config"

# S3 key prefix the twins land under (bucket root, NOT `site/config/` — the
# latter is a CloudFront-served static mirror that experiment resets purge).
S3_CONFIG_PREFIX = "config/"

# Trees scanned for consumers/writers of `config/` keys. `deploy/` is excluded
# on purpose: operator scripts (deploy_coach_intelligence.sh, restart_pipeline)
# are deploy paths, not runtime writers.
CONSUMER_ROOTS = ("lambdas", "mcp")

# Files under repo `config/` that are NOT twins of an S3 object. This is an
# exclusion RULE (patterns), not an enumeration of the twin set — adding a new
# `config/foo.json` still joins the set automatically.
NOT_TWIN_PATTERNS = (
    "*.md",  # README.md and friends — repo documentation, never served
    "*.example.json",  # committed templates (pii_denylist.example.json)
    "*.example.*",
    ".*",  # dotfiles
)

# boto3 S3 write calls whose key argument we resolve. Value = where the key is:
# ("kwarg", "Key") or ("arg", <zero-based positional index>).
_WRITE_CALLS = {
    "put_object": ("kwarg", "Key"),
    "copy_object": ("kwarg", "Key"),
    "delete_object": ("kwarg", "Key"),
    "upload_file": ("arg", 2),  # upload_file(Filename, Bucket, Key)
    "upload_fileobj": ("arg", 2),  # upload_fileobj(Fileobj, Bucket, Key)
}

# A resolved key pattern whose final path segment is exactly "*" is unbounded —
# it would match every twin. Never used to exclude; reported instead.
_UNBOUNDED = "*"


@dataclass(frozen=True)
class Twin:
    """One repo file ↔ one bucket-root S3 `config/` object."""

    key: str  # S3 key, e.g. "config/supplement_registry.json"
    repo_path: str  # absolute path to the repo twin
    consumers: tuple[str, ...] = ()  # consumer modules that read this key
    alias_of: str | None = None  # set when `key` is an ALIAS of another twin's key

    @property
    def consumed(self) -> bool:
        """True when a deployed consumer reads this key from S3.

        Drives severity: a drifted CONSUMED twin is actively serving stale
        bytes (FAIL); a drifted unconsumed twin is untidy, not a lie (WARN).
        """
        return bool(self.consumers)


@dataclass
class Registry:
    twins: list[Twin] = field(default_factory=list)
    runtime_written: dict[str, tuple[str, ...]] = field(default_factory=dict)
    unresolved_writers: list[str] = field(default_factory=list)
    excluded_not_twin: list[str] = field(default_factory=list)
    bundled_into_lambda: list[str] = field(default_factory=list)
    # Wildcard read patterns that reach an EXISTING twin's content through a
    # second key (#2057) -> the repo twin key that backs them. Expanded to
    # concrete keys against the live namespace by `expand_alias_twins`.
    alias_patterns: dict[str, str] = field(default_factory=dict)
    # Which modules read each alias pattern — carried onto the expanded Twin so
    # `_is_serving` still decides invalidation/severity correctly.
    alias_consumers: dict[str, tuple[str, ...]] = field(default_factory=dict)
    # Every `config/…` read pattern seen in the consumer tree -> the modules
    # that read it. The coverage audit (#2057) needs the raw reader edges, not
    # just the ones that resolved to a repo twin.
    read_patterns: dict[str, tuple[str, ...]] = field(default_factory=dict)
    # Bare filename read edges (`_load_json("training_week.json")`).
    bare_reads: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def by_key(self) -> dict[str, Twin]:
        return {t.key: t for t in self.twins}


# ─────────────────────────────────────────────────────────────────────────────
# AST key resolution
# ─────────────────────────────────────────────────────────────────────────────


def _module_consts(tree: ast.AST) -> dict[str, str]:
    """Every `NAME = <statically-resolvable str>` in the module.

    Walks the WHOLE tree, not just module level: real key constants are often
    bound inside an `init()` (`_DASHBOARD_KEY = f"dashboard/{user}/data.json"`,
    `output_writers.py`). Only str-resolvable values are recorded, so the
    `NAME = None` forward-declaration that usually precedes them is skipped
    rather than shadowing the real value.
    """
    consts: dict[str, str] = {}
    for _ in range(2):  # two passes: let constants defined later resolve earlier refs
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                continue
            target = node.targets[0]
            if not isinstance(target, ast.Name):
                continue
            value = _resolve(node.value, consts)
            if value is not None:
                consts[target.id] = value
    return consts


def _resolve(node: ast.AST | None, consts: dict[str, str]) -> str | None:
    """Best-effort static value of a key expression.

    Dynamic segments collapse to "*" so the result is an fnmatch pattern.
    Returns None when nothing string-like can be recovered.
    """
    if node is None:
        return None
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else None
    if isinstance(node, ast.JoinedStr):  # f-string
        parts = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            else:
                parts.append(_UNBOUNDED)
        return _collapse("".join(parts))
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _resolve(node.left, consts) or _UNBOUNDED
        right = _resolve(node.right, consts) or _UNBOUNDED
        return _collapse(left + right)
    if isinstance(node, ast.Name):
        return consts.get(node.id)
    if isinstance(node, ast.Call):
        # os.environ.get("X", "default") / os.getenv("X", "default")
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name in ("get", "getenv") and len(node.args) >= 2:
            return _resolve(node.args[1], consts)
        return None
    return None


def _collapse(pattern: str) -> str:
    """Squash runs of `*` so `config/**/x` == `config/*/x` for fnmatch."""
    while "**" in pattern:
        pattern = pattern.replace("**", "*")
    return pattern


def _is_unbounded(pattern: str) -> bool:
    """True when the pattern's final segment is a bare `*` (matches anything)."""
    return pattern.rstrip("/").rsplit("/", 1)[-1] == _UNBOUNDED


# ─────────────────────────────────────────────────────────────────────────────
# Consumer + writer scans
# ─────────────────────────────────────────────────────────────────────────────


def _enclosing_function(tree: ast.AST, target: ast.AST) -> ast.FunctionDef | None:
    """The FunctionDef whose body (transitively) contains `target`."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for child in ast.walk(node):
                if child is target:
                    return node  # type: ignore[return-value]
    return None


def _resolve_via_callers(
    tree: ast.AST,
    consts: dict[str, str],
    key_node: ast.AST,
    write_node: ast.AST,
) -> set[str] | None:
    """One-hop resolution of `put_object(Key=<param>)` inside a helper.

    `hevy_template_cache._write_s3_json(key, payload)` does `Key=key`; the real
    keys only appear at its call sites (`_write_s3_json(CACHE_KEY, …)`). Without
    this hop the writer resolves to "unknown" and the runtime-written key would
    NOT be excluded from the sync set — the dangerous direction.

    Returns the set of keys passed by in-module callers, or None if the key node
    is not a plain parameter reference.
    """
    if not isinstance(key_node, ast.Name):
        return None
    func = _enclosing_function(tree, write_node)
    if func is None:
        return None
    params = [a.arg for a in func.args.args]
    if key_node.id not in params:
        return None
    index = params.index(key_node.id)

    resolved: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        called = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", None)
        if called != func.name:
            continue
        arg_node = None
        for keyword in node.keywords:
            if keyword.arg == key_node.id:
                arg_node = keyword.value
        if arg_node is None and len(node.args) > index:
            arg_node = node.args[index]
        value = _resolve(arg_node, consts)
        resolved.add(value if value is not None else _UNBOUNDED)
    return resolved or None


def _scan_module(path: str, source: str) -> tuple[set[str], set[str], set[str], set[str]]:
    """Return (read_patterns, write_patterns, unresolved_writes, bare_filenames)."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set(), set(), set(), set()

    consts = _module_consts(tree)
    reads: set[str] = set()
    writes: set[str] = set()
    unresolved: set[str] = set()
    bare: set[str] = set()

    # Loose reader harvest: every `config/…` string that appears anywhere.
    #
    # `bare` closes the indirection blind spot: `routine_generator._load_json`
    # builds its key as f"{S3_CONFIG_PREFIX}{name}" — the full key never appears
    # as a literal, only the bare filename does at the call site
    # (`_load_json("training_week.json")`). A bare filename is only ever promoted
    # to a consumer edge when a repo twin with that basename actually exists, so
    # the false-positive surface is bounded by the repo config/ tree itself.
    for node in ast.walk(tree):
        if isinstance(node, (ast.Constant, ast.JoinedStr)):
            value = _resolve(node, consts)
            if not value:
                continue
            if value.startswith(S3_CONFIG_PREFIX) and not _is_unbounded(value):
                reads.add(value)
            elif "/" not in value and "." in value and " " not in value:
                bare.add(value)
    for value in consts.values():
        if value.startswith(S3_CONFIG_PREFIX) and not _is_unbounded(value):
            reads.add(value)

    # Precise writer scan: resolve the key argument of each S3 write call.
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
        spec = _WRITE_CALLS.get(name or "")
        if spec is None:
            continue
        kind, where = spec
        if kind == "kwarg":
            key_node = next((kw.value for kw in node.keywords if kw.arg == where), None)
        else:
            key_node = node.args[where] if len(node.args) > where else None
        value = _resolve(key_node, consts)
        candidates: set[str]
        if value is None:
            # `Key=<param>` inside a helper — resolve through its call sites.
            hopped = _resolve_via_callers(tree, consts, key_node, node)
            if hopped is None:
                # Genuinely opaque. Only a concern in a module that also touches
                # config/ — elsewhere it is some other prefix and not our problem.
                if reads:
                    unresolved.add(f"{path}:{node.lineno} (unresolvable key)")
                continue
            candidates = hopped
        else:
            candidates = {value}

        for candidate in candidates:
            if not candidate.startswith(S3_CONFIG_PREFIX):
                if candidate == _UNBOUNDED and reads:
                    unresolved.add(f"{path}:{node.lineno} (unresolvable key)")
                continue
            if _is_unbounded(candidate):
                unresolved.add(f"{path}:{node.lineno} -> {candidate}")
            else:
                writes.add(candidate)

    return reads, writes, unresolved, bare


def _iter_python(repo_root: str, roots: Iterable[str]) -> Iterable[str]:
    for root in roots:
        base = os.path.join(repo_root, root)
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in ("__pycache__", "archive", "node_modules")]
            for filename in filenames:
                if filename.endswith(".py"):
                    yield os.path.join(dirpath, filename)


def _tracked_config_files(repo_root: str) -> list[str]:
    """Git-tracked files under repo `config/`, relative-posix."""
    config_dir = os.path.join(repo_root, REPO_CONFIG_DIR)
    if not os.path.isdir(config_dir):
        return []
    try:
        out = subprocess.run(
            ["git", "-C", repo_root, "ls-files", "-z", "--", REPO_CONFIG_DIR],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        return sorted(p for p in out.split("\0") if p)
    except (subprocess.CalledProcessError, FileNotFoundError):
        # Not a git checkout (or git unavailable) — fall back to a walk so the
        # derivation still works in a tarball/test fixture.
        found = []
        for dirpath, dirnames, filenames in os.walk(config_dir):
            dirnames[:] = [d for d in dirnames if d != "__pycache__"]
            for filename in filenames:
                abs_path = os.path.join(dirpath, filename)
                found.append(os.path.relpath(abs_path, repo_root).replace(os.sep, "/"))
        return sorted(found)


def _is_not_twin(rel_path: str) -> bool:
    name = rel_path.rsplit("/", 1)[-1]
    return any(fnmatch.fnmatch(name, pattern) for pattern in NOT_TWIN_PATTERNS)


def bundled_config_keys(repo_root: str) -> set[str]:
    """Repo `config/` files STAGED INTO the Lambda zip by build_bundle.py.

    `config/food_vocabulary.json` is copied to the bundle root and read from
    the package (`meal_grouper.load_vocab`), never from S3 — it has no S3 twin
    and syncing one would create an object nothing reads. Derived by scanning
    build_bundle.py for `os.path.join(REPO_ROOT, "config", <name>)`, so a file
    that later stops being bundled rejoins the S3 twin set automatically.
    """
    path = os.path.join(repo_root, "deploy", "build_bundle.py")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
    except (OSError, SyntaxError):
        return set()

    keys: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not (isinstance(node.func, ast.Attribute) and node.func.attr == "join"):
            continue
        parts = [a.value if isinstance(a, ast.Constant) and isinstance(a.value, str) else None for a in node.args]
        if REPO_CONFIG_DIR in parts:
            index = parts.index(REPO_CONFIG_DIR)
            tail = [p for p in parts[index + 1 :] if p]
            if tail:
                keys.add(S3_CONFIG_PREFIX + "/".join(tail))
    return keys


# ─────────────────────────────────────────────────────────────────────────────
# Alias keys (#2057)
# ─────────────────────────────────────────────────────────────────────────────
#
# A repo `config/x.json` is normally read from S3 at the SAME key, which is why
# the twin map is `key = rel_path`. Some consumers instead read the same content
# through a user-scoped key: `character_engine` and `site_api_vitals` both read
# `config/{user_id}/character_sheet.json`, and `board_loader` reads
# `config/{user_id}/board_of_directors.json`. Those objects are byte-identical
# to their repo files (verified live 2026-08-03) — they are a SECOND KEY for an
# existing twin, not a second writer.
#
# Because the map is 1:1 on the path, the alias key was invisible to the #2019
# drift check by construction. That is not cosmetic: `restart_pipeline` rewrites
# repo `config/character_sheet.json` on every experiment reset and the merge
# syncs bucket-root only, so the serving path would keep reading the OUTGOING
# cycle's baseline — the merged-looked-live class with a reset as its trigger.


def _alias_patterns(reads: dict[str, set[str]], twin_keys: Iterable[str]) -> dict[str, str]:
    """Wildcard read patterns that reach exactly one repo twin's content.

    A pattern qualifies only when its FINAL segment is a literal filename that
    resolves to exactly one repo twin. That single rule is what separates an
    alias from a family:

      * `config/*/character_sheet.json` — leaf is literal, one repo twin backs
        it. An alias.
      * `config/coaches/*.json` — the leaf itself is the wildcard, so it names a
        FAMILY whose members each already have their own twin at their own key.
        Never an alias; treating it as one would map eight distinct coach files
        onto whichever twin happened to match.
    """
    by_basename: dict[str, list[str]] = {}
    for key in twin_keys:
        by_basename.setdefault(key.rsplit("/", 1)[-1], []).append(key)

    aliases: dict[str, str] = {}
    for pattern in reads:
        if _UNBOUNDED not in pattern:
            continue
        basename = pattern.rsplit("/", 1)[-1]
        if _UNBOUNDED in basename:
            continue  # a family, not an alias
        sources = by_basename.get(basename, [])
        if len(sources) != 1 or sources[0] == pattern:
            continue
        aliases[pattern] = sources[0]
    return aliases


def _split_pattern(pattern: str) -> tuple[str, str] | None:
    """`config/*/x.json` -> ("config/", "/x.json"). None if not single-wildcard."""
    if pattern.count(_UNBOUNDED) != 1:
        return None
    head, tail = pattern.split(_UNBOUNDED, 1)
    return head, tail


def alias_segments(patterns: Iterable[str], live_keys: Iterable[str]) -> set[str]:
    """Wildcard segments actually present in the live `config/` namespace.

    Derived from the live keys rather than from a hardcoded user id, so a second
    user prefix would join the checked set on its own. Segments are collected
    across ALL alias patterns and then applied to all of them — otherwise an
    alias object that has been DELETED from S3 would simply stop being checked,
    which is the failure this whole class is about.
    """
    live = list(live_keys)
    segments: set[str] = set()
    for pattern in patterns:
        split = _split_pattern(pattern)
        if split is None:
            continue
        head, tail = split
        for key in live:
            if key.startswith(head) and key.endswith(tail) and len(key) > len(head) + len(tail):
                segment = key[len(head) : len(key) - len(tail)]
                if segment and "/" not in segment:
                    segments.add(segment)
    return segments


def expand_alias_twins(registry: Registry, live_keys: Iterable[str]) -> list[Twin]:
    """Concrete alias Twins for `registry.alias_patterns` × observed segments.

    Each expanded Twin points at the SOURCE repo file, so the existing
    byte-for-byte drift check and `--apply` upload work unchanged: the alias key
    is simply a second destination for the same repo bytes.
    """
    by_key = registry.by_key()
    segments = sorted(alias_segments(registry.alias_patterns, live_keys))
    expanded: list[Twin] = []

    for pattern, source_key in sorted(registry.alias_patterns.items()):
        split = _split_pattern(pattern)
        source = by_key.get(source_key)
        if split is None or source is None:
            continue
        head, tail = split
        for segment in segments:
            key = f"{head}{segment}{tail}"
            if key == source_key or key in by_key:
                continue
            expanded.append(
                Twin(
                    key=key,
                    repo_path=source.repo_path,
                    consumers=registry.alias_consumers.get(pattern, ()),
                    alias_of=source_key,
                )
            )
    return expanded


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────


def derive(repo_root: str, consumer_roots: Iterable[str] = CONSUMER_ROOTS) -> Registry:
    """Derive the repo↔S3 `config/` twin set for `repo_root`."""
    reads: dict[str, set[str]] = {}
    writes: dict[str, set[str]] = {}
    bare: dict[str, set[str]] = {}
    unresolved: list[str] = []

    for path in sorted(_iter_python(repo_root, consumer_roots)):
        try:
            with open(path, "r", encoding="utf-8") as handle:
                source = handle.read()
        except OSError:
            continue
        rel = os.path.relpath(path, repo_root).replace(os.sep, "/")
        module_reads, module_writes, module_unresolved, module_bare = _scan_module(rel, source)
        for pattern in module_reads:
            reads.setdefault(pattern, set()).add(rel)
        for pattern in module_writes:
            writes.setdefault(pattern, set()).add(rel)
        for name in module_bare:
            bare.setdefault(name, set()).add(rel)
        unresolved.extend(module_unresolved)

    registry = Registry(
        runtime_written={k: tuple(sorted(v)) for k, v in sorted(writes.items())},
        unresolved_writers=sorted(unresolved),
        read_patterns={k: tuple(sorted(v)) for k, v in sorted(reads.items())},
        bare_reads={k: tuple(sorted(v)) for k, v in sorted(bare.items())},
    )
    bundled = bundled_config_keys(repo_root)
    registry.bundled_into_lambda = sorted(bundled)

    for rel_path in _tracked_config_files(repo_root):
        if _is_not_twin(rel_path) or rel_path in bundled:
            registry.excluded_not_twin.append(rel_path)
            continue
        key = rel_path  # repo `config/x` ↔ S3 `config/x` — same relative path
        if any(fnmatch.fnmatch(key, pattern) for pattern in writes):
            # Runtime-written: syncing repo bytes over it would clobber live state.
            continue
        consumers: set[str] = set()
        for pattern, modules in reads.items():
            if fnmatch.fnmatch(key, pattern):
                consumers |= modules
        consumers |= bare.get(key.rsplit("/", 1)[-1], set())
        registry.twins.append(
            Twin(
                key=key,
                repo_path=os.path.join(repo_root, rel_path.replace("/", os.sep)),
                consumers=tuple(sorted(consumers)),
            )
        )

    registry.twins.sort(key=lambda t: t.key)

    # Alias patterns are derived AFTER the twin set exists — an alias is defined
    # by the twin it resolves to, so it cannot be computed before them (#2057).
    registry.alias_patterns = _alias_patterns(reads, (t.key for t in registry.twins))
    registry.alias_consumers = {pattern: tuple(sorted(reads.get(pattern, set()))) for pattern in registry.alias_patterns}
    return registry
