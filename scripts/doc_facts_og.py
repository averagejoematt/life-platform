"""scripts/doc_facts_og.py — the OG share-card fact gate.

Split out of ``check_doc_facts.py`` (#3261) so the general card-literal rule could land
without pushing that file over the 1,200-line ceiling — the #1665 sibling shape, same as
``doc_facts_governance.py`` / ``doc_facts_ops.py``. The #1260 rule below is unchanged;
what is new is ``og_literal_hits``.

WHY A SECOND RULE EXISTS
------------------------
#1260 fixed a fabricated number on the **home** card (``"One man. 25 data sources."``
against a registry of 16) and guarded it with ``_og_source_hits`` — a scan for the single
phrase ``"N data sources"``. That guard was green for eight months while two SIBLING cards
on the same surface published worse numbers:

* ``og-builders.png`` drew ``116 MCP TOOLS / 59 LAMBDAS / $13 MONTHLY COST`` and the
  subtitle "How to build an AI health platform for $13/month". Truth on the day it was
  found: **76** tools, **104** Lambdas, **$146.07** MTD — the dollar figure off by 7.6x.
  ``build_builders`` even *loaded* the right values (``stats.get("platform", {})`` on a
  bare line) and discarded them.
* ``og-labs.png`` drew ``74 BIOMARKERS / 7 DRAWS`` against a live ``/api/labs`` reporting
  **152** biomarkers and **8** draws.

Both regenerate DAILY, so each was re-publishing itself every 24 hours.

THE LESSON, AND WHY THIS RULE IS NOT A THIRD PHRASE
---------------------------------------------------
A phrase-matched detector only ever sees the instance it was written for. Every
phrase-matched member of the #2959/#3003/#3199 suppressor family has failed in the field
the same way. So this rule does not look for phrases at all: it derives its subject from
**what the card actually draws** — every string literal reaching a registered drawing
primitive's text argument inside a ``build_*``/``render_*`` function — and flags any that
contains a digit. A number on a card is then one of exactly two things:

1. **data-sourced** — the literal is not a literal at all (an f-string over a lookup, a
   ``_fmt(...)`` call, a ``len(SOURCE_REGISTRY)``), and this rule never sees it; or
2. **explicitly exempted** — an ``# og-literal-ok: <reason>`` comment on the same line,
   which is reviewable in the diff and states out loud what the number is.

There is no third state. Re-introducing a hardcoded metric reds CI.

GUARDING THE SET OF PRIMITIVES, NOT JUST THE LITERALS
-----------------------------------------------------
The rule can only inspect calls it recognises, so an unrecognised drawing helper would be
a silent hole — the same shape as the bug. ``UNREGISTERED_PRIMITIVE`` closes it: any
callee whose dotted name looks like a drawing call (``draw.*``, ``_draw_*``,
``card_engine.draw_*``) and is NOT in ``TEXT_ARGS`` is itself reported, so adding a new
primitive forces its text arguments to be declared here.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# ── #1260: reader-facing "N data sources" scan (lambdas/web/og_*.py) ──────────
# The OG card lambda draws share-preview PNGs quoted on 72 pages — the platform's most
# distributed surface. og_image_lambda.py hardcoded "One man. 25 data sources." while the
# canonical registry (lambdas/ingestion/source_registry.py, SOURCE_REGISTRY) has 16 top-level
# sources — an uncomputed, inflated count exactly in the ADR-104 honest-numbers / stale-count
# drift class this gate was built to kill, but the doc scan scopes docs/* only and never
# reaches lambda-emitted strings. This rule policies the reader-facing "N data sources"
# phrasing in any lambdas/web/og_*.py against the LIVE registry length (the same source the
# fixed card derives from), so the card and the gate can never disagree.
#
# GROUND TRUTH is the registry itself, AST-counted (not the hand-maintained PLATFORM_FACTS
# data_sources literal, which counts a different — public-catalogue — surface): the card
# derives `len(SOURCE_REGISTRY)` at runtime, so the gate must police against exactly that.
#
# PRECISION: skip full-line `#` comments and HISTORICAL-framed lines (as the ceiling scan
# does). The correct card writes an f-string `{n} data sources` — no numeric literal — so a
# fixed card is clean; only a hardcoded digit next to "data sources" trips.
OG_DIR = ROOT / "lambdas" / "web"
SOURCE_REGISTRY_PATH = ROOT / "lambdas" / "ingestion" / "source_registry.py"
OG_SOURCE_COUNT = re.compile(r"(?<![\w.])(\d+)\s+data sources?\b")


def _dict_key_count(path: Path, name: str, depth: int = 0) -> int | None:
    """AST key count of the dict literal assigned to `name` in `path`, resolving
    `**SPLICE` entries against the sibling modules they come from. None = not found.

    #3565: this used to count only the Constant keys and drop every `**SPLICE`
    silently, which is how it returned 19 for a registry whose runtime `len()` is 22
    (the three closed-social entries live in source_registry_closed_social.py, #1677).
    A gate whose ground truth is smaller than the thing it polices cannot fire on the
    class it exists for: a card hardcoding the UNDER-count passed, while the card that
    correctly derives `len(SOURCE_REGISTRY)` printed a different number. An
    unresolvable splice now returns None — the caller exits 2 and says so — rather than
    quietly counting low.
    """
    if depth > 3 or not path.exists():
        return None
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, OSError):
        return None
    for node in ast.walk(tree):
        # Both forms: `X = {...}` is ast.Assign, `X: T = {...}` is ast.AnnAssign.
        # #1677 annotated SOURCE_REGISTRY and this walk silently returned None —
        # a discovery that finds nothing reads as "no data", not as "I broke".
        if isinstance(node, ast.AnnAssign):
            tgts = [node.target]
        elif isinstance(node, ast.Assign):
            tgts = list(node.targets)
        else:
            continue
        for tgt in tgts:
            if not (isinstance(tgt, ast.Name) and tgt.id == name and isinstance(node.value, ast.Dict)):
                continue
            total = 0
            for key, value in zip(node.value.keys, node.value.values):
                if isinstance(key, ast.Constant):
                    total += 1
                    continue
                if key is None and isinstance(value, ast.Name):  # `**SPLICE`
                    spliced = _resolve_splice(value.id, path.parent, depth)
                    if spliced is None:
                        return None  # fail loud, never count low
                    total += spliced
                    continue
                return None  # an unrecognised key form — do not guess
            return total
    return None


def _resolve_splice(name: str, search_dir: Path, depth: int) -> int | None:
    """Key count of a spliced dict, found in a sibling module of the registry."""
    for sibling in sorted(search_dir.glob("*.py")):
        found = _dict_key_count(sibling, name, depth + 1)
        if found is not None:
            return found
    return None


def _registry_source_count() -> int | None:
    """Top-level key count of SOURCE_REGISTRY in lambdas/ingestion/source_registry.py,
    AST-parsed INCLUDING its spliced sections — i.e. the number a runtime
    `len(SOURCE_REGISTRY)` produces, which is what the og cards actually print.

    Read as TEXT + AST (never imported) so the gate stays import-free and can't drag in a
    lambda's runtime deps. This is the ONE source of truth for the reader-facing count.
    """
    return _dict_key_count(SOURCE_REGISTRY_PATH, "SOURCE_REGISTRY")


def _scan_og_files() -> list[Path]:
    return sorted(OG_DIR.glob("og_*.py")) if OG_DIR.exists() else []


# #3565: the same rule, one surface out. The confirmation email a new subscriber
# receives said "real biometric data from 19 sources" for months — a reader-facing
# source-count claim in exactly the #1260 class, invisible to the gate because the
# scan globbed og_*.py only. These templates are reader-facing text emitted by a
# lambda, so they belong in the SAME scan set against the SAME registry truth.
# (Add a file here whenever a new subscriber-facing template names a source count.)
SOURCE_COUNT_TEMPLATES = (
    ROOT / "lambdas" / "web" / "email_subscriber_lambda.py",
    ROOT / "lambdas" / "web" / "subscriber_onboarding_lambda.py",
    ROOT / "lambdas" / "compute" / "weekly_signal_lambda.py",
    ROOT / "lambdas" / "emails" / "chronicle_email_sender_lambda.py",
    ROOT / "lambdas" / "emails" / "between_chronicle_lambda.py",
)


def _scan_source_count_files() -> list[Path]:
    """Every file the reader-facing "N data sources" rule polices: the og cards plus
    the subscriber-facing email templates (#1260 + #3565)."""
    return _scan_og_files() + [p for p in SOURCE_COUNT_TEMPLATES if p.exists()]


# ─────────────────────────────────────────────────────────────────────────────
# #3261: the general drawn-literal rule
# ─────────────────────────────────────────────────────────────────────────────

# Every drawing primitive the OG builders call, mapped to the argument positions and
# keyword names whose value is TEXT RENDERED ONTO THE CARD. A shape primitive draws no
# text and is registered with an empty tuple — registered-and-inert, never unknown.
#
# This map IS the contract: `UNREGISTERED_PRIMITIVE` below fails on any drawing-shaped
# callee missing from it, so a new helper cannot quietly carry an unchecked literal.
TEXT_ARGS: dict[str, tuple[tuple[int, ...], tuple[str, ...]]] = {
    "draw.text": ((1,), ("text",)),
    "draw.ellipse": ((), ()),
    "draw.line": ((), ()),
    "draw.rectangle": ((), ()),
    "draw.textlength": ((), ()),
    "_draw_metric": ((3, 4), ("value", "label")),
    "_draw_header": ((1,), ("page_label",)),
    "_draw_footer": ((), ()),
    "_draw_mark": ((), ()),
    "og._draw_header": ((1,), ("page_label",)),
    "card_engine.draw_header": ((1,), ("page_label",)),
    "card_engine.draw_metric": ((3, 4), ("value", "label")),
    "card_engine.draw_footer": ((1, 2), ("left_text", "right_text")),
    "card_engine.draw_title": ((1,), ("text",)),
    "card_engine.draw_uncertainty": ((3, 4), ("value", "label")),
    "card_engine.draw_brand_mark": ((), ()),
}

# A callee that LOOKS like drawing. Anything matching this and absent from TEXT_ARGS is a
# hole in the rule and is reported as such.
_DRAWLIKE = re.compile(r"^(draw\.[a-z_]+|_draw_[a-z_]+|og\._draw_[a-z_]+|card_engine\.draw[a-z_]*)$")

# Functions whose body is a card. Scoped so module-level helper text (log lines, S3 keys)
# is out of frame — the rule is about what a READER sees on a PNG.
_BUILDER = re.compile(r"^(build|render|_render)_")

# The one escape hatch. Same line as the literal, reason required.
_EXEMPT = re.compile(r"#\s*og-literal-ok:\s*(\S.+)")

_DIGIT = re.compile(r"\d")


def _dotted(func: ast.expr) -> str:
    parts: list[str] = []
    node = func
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    else:
        return ""
    return ".".join(reversed(parts))


def _drawn_text_nodes(call: ast.Call, spec) -> list[ast.expr]:
    positions, kwnames = spec
    out = [call.args[i] for i in positions if i < len(call.args)]
    out += [kw.value for kw in call.keywords if kw.arg in kwnames]
    return out


def _numeric_literals(node: ast.expr):
    """(lineno, text) for every string constant reachable as drawn text that contains a
    digit. An f-string is inspected PIECEWISE — its literal parts can carry a fabricated
    number even though its interpolations are honest."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str) and _DIGIT.search(node.value):
        yield node.lineno, node.value
    elif isinstance(node, ast.JoinedStr):
        for piece in node.values:
            if isinstance(piece, ast.Constant) and isinstance(piece.value, str) and _DIGIT.search(piece.value):
                yield getattr(piece, "lineno", node.lineno), piece.value


def og_literal_hits(files) -> list[str]:
    """Hardcoded numbers drawn onto OG cards, plus unregistered drawing primitives.

    ``files`` is an iterable of ``Path``. Exposed as a pure function so the regression
    tests can plant a fabricated literal in a scratch file and prove the rule bites
    (#1189's non-vacuous-scan lesson) — a rule nobody has watched fail is not a rule.
    """
    hits: list[str] = []
    for src in files:
        try:
            rel = src.relative_to(ROOT)
        except ValueError:
            rel = src  # scratch file outside the repo (the non-vacuous test)
        text = src.read_text(encoding="utf-8")
        lines = text.splitlines()
        exempt = {i for i, line in enumerate(lines, 1) if _EXEMPT.search(line)}
        try:
            tree = ast.parse(text)
        except SyntaxError as e:
            hits.append(f"{rel}: could not parse for the OG literal scan ({e}) — a scan that cannot read its subject is not a pass")
            continue
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) or not _BUILDER.match(fn.name):
                continue
            for call in ast.walk(fn):
                if not isinstance(call, ast.Call):
                    continue
                name = _dotted(call.func)
                if name not in TEXT_ARGS:
                    if _DRAWLIKE.match(name):
                        hits.append(
                            f"{rel}:{call.lineno}: {fn.name} calls the UNREGISTERED drawing primitive `{name}`. "
                            f"Add it to doc_facts_og.TEXT_ARGS with the argument positions that carry drawn text "
                            f"(use an empty tuple for a shape primitive) — an unrecognised primitive is a hole in "
                            f"this rule, which is the exact shape of #3261."
                        )
                    continue
                for node in _drawn_text_nodes(call, TEXT_ARGS[name]):
                    for lineno, literal in _numeric_literals(node):
                        if lineno in exempt:
                            continue
                        hits.append(
                            f"{rel}:{lineno}: {fn.name} draws the hardcoded literal {literal!r} onto an OG card. "
                            f"Share cards are the platform's most-distributed surface and regenerate DAILY, so a "
                            f"stale number republishes itself every 24h (#3261: 116 tools / 59 lambdas / $13 a month "
                            f"against 76 / 104 / $146). Derive it from the loaded data, or — if the number is "
                            f"structural and not a metric — annotate the line `# og-literal-ok: <reason>`."
                        )
    return hits
