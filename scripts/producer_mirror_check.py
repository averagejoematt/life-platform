#!/usr/bin/env python3
"""producer_mirror_check.py — the #2818 producer↔gate cron-mirror rule.

Extracted from check_doc_facts.py (which sits at the #1665 1200-line ceiling);
check_doc_facts spec-loads this module and re-exports the names, so its CLI
behaviour and the test contract are unchanged. See the block comment below for
the rule's full rationale.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# ── #2818: producer-cron mirror literals (lambdas/ vs cdk/stacks/) ────────────
# The #1205 rule above polices crons quoted in DOCS. #2818 is the same drift class in
# CODE: a QA/operational module that derives a window expectation from a producer's
# schedule ("which day may this artifact honestly carry at this hour") necessarily
# carries a copy of that producer's cron — the Lambda bundle cannot read cdk/ at
# runtime. #2670's fix hand-typed the derived cutoff (10:30 PT) with the cron in a
# comment, and nothing asserted the literal pair compute_stack.py ↔
# qa_check_outputs.py agreed — 16:40Z is 08:40 PST in winter: safe the day it was
# written, unguarded from then on.
#
# The convention this rule enforces: the mirroring module declares the cron ONCE in a
# module-level dict named `PRODUCER_CRON_MIRRORS` ({function_name: "cron(...)"}) and
# derives its windows from that entry. This rule sweeps ALL of lambdas/ for such
# declarations (the SET — any future producer-gate pair joins by using the same name,
# never by being enumerated here) and diffs every entry against the function's real
# schedule(s) in the CDK — ground truth is `generate_platform_model.extract_lambdas()`
# (#2845), the same AST walk as the #1205 rule, never an aws_cdk import.
#
# PRECISION: only a dict literal assigned (Assign OR AnnAssign — the #1677 blind-walk
# lesson) to exactly that name is read, and only str->str entries are compared; a
# function absent from the CDK map is itself a hit (the producer was renamed/removed
# or its schedule went dynamic — either way the mirror no longer describes reality).
PRODUCER_MIRROR_NAME = "PRODUCER_CRON_MIRRORS"


def _collect_producer_mirrors(files) -> list[tuple]:
    """(path, lineno, function_name, cron) for every entry of every module-level
    `PRODUCER_CRON_MIRRORS` dict in `files`. AST-read as text, never imported, so the
    sweep can't drag in a lambda's runtime deps. Exposed so the regression test can
    plant a drifted mirror in a scratch file and prove the rule bites (#1189)."""
    out = []
    for src in files:
        try:
            text = src.read_text(encoding="utf-8")
        except OSError:
            continue
        if PRODUCER_MIRROR_NAME not in text:
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                target, value = node.targets[0].id, node.value
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                target, value = node.target.id, node.value
            else:
                continue
            if target != PRODUCER_MIRROR_NAME or not isinstance(value, ast.Dict):
                continue
            for k, v in zip(value.keys, value.values):
                if isinstance(k, ast.Constant) and isinstance(k.value, str) and isinstance(v, ast.Constant) and isinstance(v.value, str):
                    out.append((src, k.lineno, k.value, v.value))
    return out


def _producer_mirror_hits(mirrors, cdk_map: dict) -> list[str]:
    """Mirror entries that disagree with the function's real CDK schedule(s)."""
    hits = []
    for src, lineno, name, cron in mirrors:
        try:
            rel = src.relative_to(ROOT)
        except ValueError:
            rel = src  # scratch file outside the repo (the non-vacuous test)
        if name not in cdk_map:
            hits.append(
                f"{rel}:{lineno}: {PRODUCER_MIRROR_NAME} names `{name}`, which has no resolvable cron in "
                f"cdk/stacks/ — renamed, removed, or its schedule went dynamic (#2818)"
            )
        elif cron not in cdk_map[name]:
            hits.append(f"{rel}:{lineno}: mirror for `{name}` claims {cron}, " f"CDK schedules {' or '.join(cdk_map[name])} (#2818)")
    return hits
