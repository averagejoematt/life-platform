"""tests/phase_prompt_census.py — the derived phase-prose census (#3614).

WHY THIS EXISTS
---------------
`ai_context.build_experiment_phase_context` / `format_experiment_phase_context` is
the ONE place the platform is allowed to say what day of the experiment it is
(#1086). The guard on that rule was a PER-DOOR test: `tests/test_phase_context_coverage.py`
drives each known narrative builder and asserts the block's marker appears, plus a
HAND-TYPED list of eight module paths. #3519 extended it to the /api/explain door as
one more instance. A hand list cannot fail on the door nobody added to it, which is
the shape that produced the Day-1 leak in the first place.

So this derives the SET instead: every module under ``lambdas/`` that BUILDS a
Bedrock/Anthropic message AND writes phase prose of its own — a day number, a genesis
date, or the words "restarted"/"reset" — is a member, and `DECISIONS` below records
one verdict per member. A module that hand-types a fourth phase line lands in the
census with no entry and reds the test.

WHAT COUNTS AS A MEMBER (both halves are structural, neither is a filename)
--------------------------------------------------------------------------
* **builds a message** — an AST dict literal carrying ``"messages"``, or a
  ``{"role": …, "content": …}`` turn, or a ``"system"`` alongside ``"model"`` /
  ``"max_tokens"``. That is the request body shape, not a name, so a new door that
  spells its invoke differently is still caught.
* **writes phase prose** — a string constant or f-string, at least 12 characters and
  containing a space, matching one of `PHASE_PATTERNS`. The prose filter is what
  keeps dict keys and identifiers (``day_n``, ``days_in_window``, ``genesis_mismatch``)
  out: those are how a module READS the anchor, and reading it is the sanctioned path.

THE HAZARD THIS FILE IS A SPECIMEN OF
-------------------------------------
A text match that reads the comment explaining it has bitten this repo four times in
recent sessions (one ratchet PASSED its own must-fail control). This census scans for
the literal words above, and this module's own prose contains every one of them. Two
structural answers, in order of how much they carry:

  1. The scan root is ``lambdas/`` — ``tests/`` is not swept, so this file is not in
     the corpus at all. `test_the_census_is_not_a_member_of_its_own_set` MEASURES that
     rather than assuming it: it runs `scan_source` over this module's own text and
     asserts the verdict is "not a member".
  2. Within a member, DOCSTRINGS ARE EXCLUDED from the prose scan (`_docstring_ids`).
     A module that explains in its docstring why it must not hand-type a day line is
     not thereby a hand-typer. Comments are invisible to `ast` and need no rule.

Neither is an exemption list, which is the point: no member is special-cased by name.
"""

from __future__ import annotations

import ast
import os
import re

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(_HERE)
SCAN_ROOT = "lambdas"

# The ONE sanctioned source of a phase claim (#1086). `_phase_context_block` is the
# per-module injector that wraps the formatter (site_api_ai_prompt, #2276); naming it
# keeps the census from calling an indirection a violation.
PROVIDERS = (
    "build_experiment_phase_context",
    "format_experiment_phase_context",
    "_phase_context_block",
    "PHASE_CONTEXT_MARKER",
)

# A day number, a genesis date, or the reset/restart vocabulary — the three the
# acceptance names, spelled as the prose a prompt would actually carry.
PHASE_PATTERNS = (
    r"\bday\s+(?:\{|\d|n\b)",
    r"\bdays?\s+(?:in|into|of)\b[^.]{0,40}\bexperiment\b",
    r"\brestarted\b",
    r"\breset\b",
    r"\bgenesis\b",
    r"\bexperiment\s+(?:started|began|begins|starts)\b",
)
_PHASE_RE = re.compile("|".join(PHASE_PATTERNS), re.I)

_MIN_PROSE_LEN = 12

# ── Decisions, one per derived member ────────────────────────────────────────
# DERIVED: the module obtains its phase claim from the shared provider. Anything else
# is a written reason for why its own phase prose is not a second source of truth.
DERIVED = "DERIVED"

DECISIONS = {
    "lambdas/emails/coach_panel_podcast_lambda.py": DERIVED,
    "lambdas/content/review_pack_ranker.py": (
        "NOT A PROMPT. The matching string is a FINDING detail — genesis_mismatch's "
        '"generated {gen_date}, BEFORE the current genesis {start_date_iso}" — emitted by the '
        "deterministic ranker into Matthew's review pack, and the genesis it names is the caller's "
        "`start_date_iso` argument, threaded from EXPERIMENT_START_DATE, never a date this module "
        "decides. The module's Bedrock body belongs to the separate Haiku critic, whose prompt carries "
        "no phase claim at all. Revisit if the critic prompt ever states the day or the cycle."
    ),
    "lambdas/operational/reader_truth_qa.py": (
        "DELIBERATE, and it is the rubric rather than a narrative. `_phase_line` states the ground "
        "truth an editorial JUDGE grades the live site against, and it needs clauses the reader-facing "
        "block does not have: the LOWER bound (#1917 — a window SMALLER than day_n is expected and "
        "correct after a restart, and omitting that made the judge flag 5-on-Day-6 three runs running) "
        "and the cycle sentence (#2959 — the oracle inferred the cycle from a prior-cycle diary card). "
        "Its phase FACTS are not a second anchor: `phase_context()` reads day_n and EXPERIMENT_START_DATE, "
        "and registers with the #2813 PT-day producer/gate contract sweep. Revisit if the shared block "
        "ever grows a lower-bound clause — then this should consume it."
    ),
}


# ── The derivation ───────────────────────────────────────────────────────────
def _docstring_ids(tree):
    """ids of the string nodes that are DOCSTRINGS — see the hazard note above."""
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", None)
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
                out.add(id(body[0].value))
    return out


def builds_model_message(tree):
    """The request-body shape, by structure rather than by the name of the invoke."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        keys = {k.value for k in node.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)}
        if "messages" in keys or ("role" in keys and "content" in keys) or ("system" in keys and ({"model", "max_tokens"} & keys)):
            return True
    return False


def phase_prose(tree):
    """[(lineno, text)] — every non-docstring prose string that states a phase claim."""
    docs = _docstring_ids(tree)
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs:
            text = node.value
        elif isinstance(node, ast.JoinedStr):
            text = "".join(v.value for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str))
        else:
            continue
        if len(text) >= _MIN_PROSE_LEN and " " in text and _PHASE_RE.search(text):
            hits.append((node.lineno, text[:160]))
    return sorted(set(hits))


def scan_source(rel_path, source):
    """The census verdict for one module's source text.

    ``{"builds": bool, "prose": [...], "member": bool, "uses_provider": bool}``.
    """
    tree = ast.parse(source)
    builds = builds_model_message(tree)
    prose = phase_prose(tree)
    return {
        "rel_path": rel_path,
        "builds": builds,
        "prose": prose,
        "member": bool(builds and prose),
        "uses_provider": any(p in source for p in PROVIDERS),
    }


def scan_tree(repo=REPO):
    """{rel_path: evidence} for every member under ``lambdas/``."""
    found = {}
    root = os.path.join(repo, SCAN_ROOT)
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in sorted(files):
            if not f.endswith(".py"):
                continue
            path = os.path.join(base, f)
            rel = os.path.relpath(path, repo)
            with open(path, encoding="utf-8") as fh:
                source = fh.read()
            ev = scan_source(rel, source)
            if ev["member"]:
                found[rel] = ev
    return found


def census_problems(members=None, decisions=None):
    """Every violation of the #3614 phase-census contract, as a list of strings.

    Pure over its inputs so the plant-a-fourth-line control runs against a synthetic
    member set on every build, not once in a session.
    """
    members = scan_tree() if members is None else members
    decisions = DECISIONS if decisions is None else decisions
    problems = []
    for rel, ev in sorted(members.items()):
        decision = decisions.get(rel)
        where = "; ".join(f"line {ln}: {txt[:70]!r}" for ln, txt in ev["prose"][:3])
        if decision is None:
            problems.append(
                f"{rel} builds a model message AND writes its own phase prose ({where}) with no entry in "
                "tests/phase_prompt_census.DECISIONS. Obtain the claim from ai_context."
                "build_experiment_phase_context / format_experiment_phase_context (#1086) and mark it DERIVED, "
                "or write down why this module's phase prose is not a second source of truth."
            )
            continue
        if decision == DERIVED:
            if not ev["uses_provider"]:
                problems.append(
                    f"{rel} is marked DERIVED but references none of {PROVIDERS} — it states a phase claim it did not "
                    "obtain from the shared provider"
                )
            continue
        if not isinstance(decision, str) or len(decision.strip()) < 120:
            problems.append(
                f"{rel}: a non-DERIVED verdict needs a substantive written reason (what the prose is, and why it is not a claim)"
            )
    for rel in sorted(set(decisions) - set(members)):
        problems.append(
            f"tests/phase_prompt_census.DECISIONS names {rel}, which the census no longer finds (moved, renamed, or the prose is gone)"
        )
    return problems
