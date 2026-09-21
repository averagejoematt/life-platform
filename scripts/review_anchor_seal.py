#!/usr/bin/env python3
"""scripts/review_anchor_seal.py — the review anchors as a SEALED, DERIVED artifact (#3607).

WHY THIS EXISTS
---------------
Thirteen of seventeen rows fell on the 2026-09-05 baseline and nothing in that artifact
could separate "the platform got worse" from "the bar moved". Three things were true of
the anchors at once:

  1. Four of them carried STALE HAND-TYPED LITERALS. Two anchors graded "inside the
     solo-operator $85/mo envelope" while the live AWS Budgets limit read 215.0; one
     graded "one coherent cycle-6 story" while SSM said 16; one measured a page floor
     against a page count that had grown past the number in the sentence.
  2. Three anchors were EXTENDED MID-RUN, by the run that found their specimen — so the
     bar that graded the row was written by the grader, after it looked.
  3. Six clauses PASSED BY SILENCE: a Day-4 spot-check on cycles that never reached Day
     4; a lever clause graded against an endpoint serving an empty list; a live-encoding
     clause graded on a day when every series is an empty array. A clause nobody could
     sample read exactly like a clause that passed.

#3603 froze the WORDING. It does not derive the numbers, does not forbid a loosening, and
gives the grader no third verdict. This module is the other three halves.

WHAT IT IS
----------
`docs/reviews/anchors/ANCHORS.json` is the anchor text, one record per lens, and
`docs/reviews/anchors/ANCHORS.sha256.json` is its content-addressed seal sibling — the
same shape as the pre-registration seal (`deploy/genesis_prereg_stamp.py`) and for the
same reason (the #3483 lesson: a sha sibling makes the artifact CANNOT-DISAGREE rather
than MUST-MENTION). The five charter primitives, named:

  * REGISTRY          — ANCHORS.json is the one place an anchor's text lives, and
                        `RESOLVERS` below is the one place a placeholder's source lives.
  * DERIVATION GUARD  — `bare_literals()`: a numeral inside an anchor that is neither a
                        `${placeholder}` nor a reference token (ADR-nnn, #nnnn, WCAG n.n)
                        reds the freeze test. The rubric now submits to the same net it
                        enforces on docs/.
  * RATCHET           — `freeze_diff()` is TIGHTENING-ONLY: a clause removed, weakened, or
                        with its evidence requirement relaxed reds, unless an owner-signed
                        dated line in the new file names that clause.
  * CONTRACT TEST     — `tests/test_anchor_freeze_3607.py`, four planted must-fails plus
                        their positive controls (loosening, stale literal, vacuous pass,
                        hash).
  * DEAD-MAN          — `header_block()`: the review prints the artifact's sha in its
                        report header every run, so a reader can tell at a glance whether
                        the bar moved or the platform did. A run whose header carries no
                        sha is a run whose grades nobody can compare.

THE THIRD VERDICT
-----------------
Every clause resolves to exactly one of MET (with a citation), FAILED (with a citation),
or UNOBSERVED (with the reason it could not be sampled) — `validate_verdicts()`. And
`lens_grade_ceiling()`: a lens with ANY UNOBSERVED clause cannot be graded A. That single
rule is what turns "all A" from a taste target into a hard one, because it makes silence
a failure everywhere it currently reads as a pass.

THE EXTENSION RULE
------------------
An extension proposed during a run goes to `proposed_extensions[]` with its authoring run
id and does NOT bind that run's grade (`clauses_for(record, include_proposed=...)`). The
run reports two grades per lens — frozen, and frozen+proposed — and `rows_moved_by()`
names which clause moved the row. At the next freeze the proposals are promoted into the
anchor and the file's hash changes.

USAGE
-----
    python3 scripts/review_anchor_seal.py --verify      # fail-closed seal + contract check
    python3 scripts/review_anchor_seal.py --header      # the block the review prints
    python3 scripts/review_anchor_seal.py --lens cto    # one lens, placeholders resolved
    python3 scripts/review_anchor_seal.py --seal        # re-stamp the sha sibling (after an edit)
    python3 scripts/review_anchor_seal.py --diff <ref>  # tightening-only diff vs a git ref

v1.0.0 — 2026-09-20 (#3607). Sibling of scripts/review_anchors.py (magnitudes, #3250) and
its `--freeze` header (#3603); this module owns the TEXT, they own the MAGNITUDES.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

ANCHORS_REL = "docs/reviews/anchors/ANCHORS.json"
SEAL_REL = "docs/reviews/anchors/ANCHORS.sha256.json"

#: The three anchor levels the panel has always pinned across the A..F span. A record
#: carrying a level outside this tuple is a schema error, not a silent extra.
ANCHOR_LEVELS = ("A", "C", "F")

MET = "MET"
FAILED = "FAILED"
UNOBSERVED = "UNOBSERVED"
VERDICTS = (MET, FAILED, UNOBSERVED)


class AnchorsUnsealed(RuntimeError):
    """Raised when a caller asks for the anchors and the seal does not verify. The review
    refuses to run rather than grading against an unsealed bar — the same fail-closed
    posture the prereg seal takes."""


# ── the placeholder registry (derivation guard, half one) ─────────────────────
@dataclass
class Resolution:
    """One placeholder, resolved — or honestly not.

    `observed=False` is the whole point: a value nobody could read is never guessed and
    never defaulted. Every clause carrying an unobservable placeholder resolves UNOBSERVED,
    which blocks an A for that lens rather than quietly grading against a stale number.
    """

    name: str
    value: object = None
    source: str = ""
    observed: bool = True
    reason: str = ""

    def rendered(self) -> str:
        return str(self.value) if self.observed else f"<UNOBSERVED:{self.name}>"


def _load_module(rel: str, name: str):
    path = os.path.join(REPO, rel)
    spec = importlib.util.spec_from_file_location(name, path)
    if not (spec and spec.loader):
        raise RuntimeError(f"cannot load {rel}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _ast_constant(rel: str, name: str):
    """A module-level constant read WITHOUT executing the module.

    `tests/visual_qa.py` reaches for Playwright and a browser; importing it to read a
    floor would make the anchor resolution depend on a browser install. Same rule
    `scripts/budget_ceilings.py` states for the governor: import when you can, parse when
    you can't, hand-copy never.
    """
    src = os.path.join(REPO, rel)
    with open(src, encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=src)
    for node in tree.body:
        targets = node.targets if isinstance(node, ast.Assign) else ([node.target] if isinstance(node, ast.AnnAssign) else [])
        for t in targets:
            if isinstance(t, ast.Name) and t.id == name and getattr(node, "value", None) is not None:
                return ast.literal_eval(node.value)
    raise KeyError(f"{name} not found at module level in {rel}")


def _resolve_ceiling(ctx: dict) -> Resolution:
    """The monthly base ceiling — the EXACT value `cdk/stacks/core_stack.py` puts on the
    AWS Budgets backstop at synth time. Its parser is reused, never re-implemented: that
    module's own `_governor_budget_amount_usd()` delegates to `budget_ceilings`, so both
    the backstop and this anchor read one number out of the governor source."""
    mod = _load_module("scripts/budget_ceilings.py", "_anchor_budget_ceilings")
    return Resolution(
        "ceiling", mod.budget_amount_usd(), "scripts/budget_ceilings.budget_amount_usd() — the value cdk/stacks/core_stack.py synths"
    )


def _resolve_surge_ceiling(ctx: dict) -> Resolution:
    mod = _load_module("scripts/budget_ceilings.py", "_anchor_budget_ceilings")
    fam = mod.read_family()
    base, surge = fam.active_pair(ctx.get("today"))
    value = surge if surge is not None else fam.surge
    return Resolution(
        "surge_ceiling", int(value) if float(value).is_integer() else value, "scripts/budget_ceilings.read_family().active_pair()"
    )


def _resolve_cycle(ctx: dict) -> Resolution:
    """The experiment cycle, from SSM `/life-platform/experiment-cycle`.

    OFFLINE IS NOT A GUESS. No credentials, no boto3, a throttle, a typo in the parameter
    name — every one of them yields UNOBSERVED with the reason attached, which blocks an A
    on every lens whose anchors cite the cycle. The alternative (fall back to a repo
    constant) is how 'cycle-6' survived ten cycles in a graded anchor.
    """
    client = ctx.get("ssm_client")
    try:
        if client is None:
            import boto3  # noqa: PLC0415 — optional at module scope on purpose

            client = boto3.client("ssm", region_name=ctx.get("region", "us-west-2"))
        raw = client.get_parameter(Name="/life-platform/experiment-cycle")["Parameter"]["Value"]
        return Resolution("cycle", int(str(raw).strip()), "SSM /life-platform/experiment-cycle")
    except Exception as exc:  # noqa: BLE001 — every failure mode is the same verdict
        return Resolution(
            "cycle",
            None,
            "SSM /life-platform/experiment-cycle",
            observed=False,
            reason=f"could not read SSM /life-platform/experiment-cycle ({type(exc).__name__}: {exc}) — UNOBSERVED, never a guess",
        )


def _resolve_cycle_day(ctx: dict) -> Resolution:
    """Day-N of the running cycle, from the genesis constant the whole platform reads.
    Local and always observable — which is the point: a clause that says 'on the day this
    run occupies' cannot be satisfied by sampling a day the cycle never reached."""
    start = _ast_constant("lambdas/common/constants.py", "EXPERIMENT_START_DATE")
    today = ctx.get("today") or date.today()
    delta = (today - date.fromisoformat(start)).days
    return Resolution(
        "cycle_day", max(0, delta + 1) if delta >= 0 else 0, f"lambdas/common/constants.EXPERIMENT_START_DATE ({start}) vs {today}"
    )


def _resolve_page_count(ctx: dict) -> Resolution:
    if os.path.join(REPO, "tests") not in sys.path:
        sys.path.insert(0, os.path.join(REPO, "tests"))
    mod = _load_module("tests/qa_manifest.py", "_anchor_qa_manifest")
    return Resolution("page_count", len(mod.visual_pages()), "tests/qa_manifest.visual_pages()")


def _resolve_min_n(ctx: dict) -> Resolution:
    return Resolution(
        "min_n", _ast_constant("lambdas/ai/voice_fidelity_core.py", "MIN_N_FOR_VERDICT"), "lambdas/ai/voice_fidelity_core.MIN_N_FOR_VERDICT"
    )


def _resolve_distinct_margin(ctx: dict) -> Resolution:
    value = _ast_constant("lambdas/ai/voice_fidelity_core.py", "_DISTINCT_MARGIN_PTS")
    return Resolution("distinct_margin", value, "lambdas/ai/voice_fidelity_core._DISTINCT_MARGIN_PTS")


def _resolve_lane_budget(ctx: dict) -> Resolution:
    """The required pre-merge lane's wall-clock budget, in seconds.

    The checks run in parallel workflows, so the lane's cost is its SLOWEST required
    check, not their sum. `typical_seconds` is WRITTEN by `deploy/write_lane_posture.py`
    from live runs (#3608 box 4) — reading it here is what kills 'fast' and 'in seconds'
    as ungraded adjectives in the devex anchor.
    """
    with open(os.path.join(REPO, "deploy", "github_posture.json"), encoding="utf-8") as fh:
        posture = json.load(fh)
    checks = (posture.get("main_required_checks_ruleset") or {}).get("required_status_checks") or []
    seconds = [c.get("typical_seconds") for c in checks if isinstance(c.get("typical_seconds"), (int, float))]
    if not seconds:
        return Resolution(
            "lane_budget", None, "deploy/github_posture.json", observed=False, reason="no required check carries a measured typical_seconds"
        )
    return Resolution(
        "lane_budget",
        max(seconds),
        "deploy/github_posture.json::main_required_checks_ruleset.required_status_checks[].typical_seconds (max — the checks run in parallel)",
    )


def _resolve_type_floor_px(ctx: dict) -> Resolution:
    return Resolution("type_floor_px", _ast_constant("tests/visual_qa.py", "SVG_TEXT_FLOOR_PX"), "tests/visual_qa.SVG_TEXT_FLOOR_PX")


def _resolve_mobile_viewport(ctx: dict) -> Resolution:
    return Resolution(
        "mobile_viewport", _ast_constant("tests/a11y_audit.py", "MOBILE_VIEWPORT")["width"], "tests/a11y_audit.MOBILE_VIEWPORT['width']"
    )


def _resolve_a11y_viewports(ctx: dict) -> Resolution:
    values = _ast_constant("tests/a11y_audit.py", "VIEWPORTS")
    return Resolution("a11y_viewports", ", ".join(values), "tests/a11y_audit.VIEWPORTS")


#: name -> (resolver, one-line statement of where the value comes from). A placeholder
#: that is not in this registry is a defect: the anchor would cite a number nobody
#: produces, which is the phantom-procedure shape one level down.
RESOLVERS: dict[str, tuple] = {
    "ceiling": (_resolve_ceiling, "the governor's monthly base ceiling, via the parser core_stack synths the AWS Budgets backstop from"),
    "surge_ceiling": (_resolve_surge_ceiling, "the governor's reader-surge ceiling for the day of the run"),
    "cycle": (_resolve_cycle, "SSM /life-platform/experiment-cycle (UNOBSERVED offline, never a guess)"),
    "cycle_day": (_resolve_cycle_day, "Day-N of the running cycle, from EXPERIMENT_START_DATE"),
    "page_count": (_resolve_page_count, "the page registry the visual sweep actually walks"),
    "min_n": (_resolve_min_n, "the voice-fidelity floor below which a distinguishability verdict is noise"),
    "distinct_margin": (_resolve_distinct_margin, "points above chance a coach must clear to count as distinct"),
    "lane_budget": (_resolve_lane_budget, "the measured wall-clock of the slowest required pre-merge check"),
    "type_floor_px": (_resolve_type_floor_px, "the site's own smallest-shipping type register"),
    "mobile_viewport": (_resolve_mobile_viewport, "the mobile width the a11y sweep measures at"),
    "a11y_viewports": (_resolve_a11y_viewports, "the viewport set the a11y sweep enumerates"),
}


def resolve_all(names=None, ctx: dict | None = None) -> dict[str, Resolution]:
    """Resolve the named placeholders (default: every one in the registry). A resolver that
    RAISES is recorded as UNOBSERVED with the exception attached — a broken derivation must
    not take the review down, and must not silently become a pass either."""
    ctx = dict(ctx or {})
    out: dict[str, Resolution] = {}
    for name in sorted(names if names is not None else RESOLVERS):
        fn = RESOLVERS.get(name, (None, ""))[0]
        if fn is None:
            out[name] = Resolution(
                name, None, "", observed=False, reason=f"no resolver registered for ${{{name}}} in scripts/review_anchor_seal.RESOLVERS"
            )
            continue
        try:
            out[name] = fn(ctx)
        except Exception as exc:  # noqa: BLE001
            out[name] = Resolution(name, None, RESOLVERS[name][1], observed=False, reason=f"{type(exc).__name__}: {exc}")
    return out


# ── the derivation guard: no bare literal inside an anchor ────────────────────
PLACEHOLDER_RE = re.compile(r"\$\{([a-z][a-z0-9_]*)\}")

#: Digit-bearing tokens that are IDENTIFIERS, not magnitudes — an ADR number, an issue
#: reference, a WCAG success criterion, an HTTP status, a date. These name a thing; they
#: do not set a bar, so they cannot go stale the way `$85` did. Everything else with a
#: digit in it must be a placeholder.
REFERENCE_FORMS = (
    re.compile(r"ADR-\d+(?:/\d+)*"),
    re.compile(r"#\d+"),
    re.compile(r"WCAG \d+(?:\.\d+)*"),
    re.compile(r"SC \d+(?:\.\d+)*"),
    re.compile(r"HTTP \d{3}"),
    re.compile(r"GSI\d"),
    re.compile(r"\bv\d\b"),
    re.compile(r"\btier \d\b"),
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
    re.compile(r"\b[A-Z]{2,}-\d+\b"),
    # Proper nouns that happen to carry a digit. `S3` is a service, not a quantity: it
    # cannot go stale, which is the only property that matters here.
    re.compile(r"\bS3\b"),
    re.compile(r"\bEC2\b"),
    re.compile(r"\bsha-?256\b", re.IGNORECASE),
    re.compile(r"\bOAuth ?2(?:\.\d)?\b"),
    re.compile(r"\bus-[a-z]+-\d\b"),
    re.compile(r"\bISO ?8601\b"),
)


def _covered_spans(text: str) -> list[tuple[int, int]]:
    spans = [m.span() for m in PLACEHOLDER_RE.finditer(text)]
    for rx in REFERENCE_FORMS:
        spans.extend(m.span() for m in rx.finditer(text))
    return spans


def bare_literals(text: str) -> list[str]:
    """Every numeral in `text` that is neither inside a `${placeholder}` nor part of a
    reference token. This is the check that would have caught all four live stale
    literals: `$85`, `cycle-6`, a page count, a lane described as 'in seconds'."""
    spans = _covered_spans(text)
    hits, seen = [], set()
    for m in re.finditer(r"\d[\d,.]*", text):
        s, e = m.span()
        if any(a <= s and e <= b for a, b in spans):
            continue
        start = max(0, s - 12)
        snippet = text[start : min(len(text), e + 12)].strip()
        if snippet not in seen:
            seen.add(snippet)
            hits.append(snippet)
    return hits


def render(text: str, resolutions: dict[str, Resolution]) -> tuple[str, list[str]]:
    """Substitute every `${name}`. Returns (rendered text, names that could not be
    observed) — a non-empty second element is exactly the UNOBSERVED condition for the
    clause that carried it."""
    unresolved: list[str] = []

    def _sub(m):
        name = m.group(1)
        res = resolutions.get(name)
        if res is None:
            unresolved.append(name)
            return f"<UNRESOLVED:{name}>"
        if not res.observed:
            unresolved.append(name)
        return res.rendered()

    return PLACEHOLDER_RE.sub(_sub, text), unresolved


# ── the artifact + its seal ───────────────────────────────────────────────────
def anchors_path(repo: str = REPO) -> str:
    return os.path.join(repo, ANCHORS_REL)


def seal_path(repo: str = REPO) -> str:
    return os.path.join(repo, SEAL_REL)


def sha256_of(path: str) -> str:
    """Over the EXACT BYTES on disk — never over a re-serialization of the parsed object.
    A seal that hashes `json.dumps(json.load(f))` verifies a shape, not a file."""
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def build_seal(repo: str = REPO, now: datetime | None = None) -> dict:
    data = load_anchors_unchecked(repo)
    sha = sha256_of(anchors_path(repo))
    return {
        "artifact": os.path.basename(ANCHORS_REL),
        "artifact_path": ANCHORS_REL,
        "algorithm": "sha256",
        "sha256": sha,
        "sealed_at": (now or datetime.now(timezone.utc)).isoformat(),
        "frozen_at": data.get("frozen_at"),
        "lenses": sorted(r["lens"] for r in data.get("records", [])),
        "verify": f"shasum -a 256 {ANCHORS_REL}",
        "seal_note": (
            "The hash covers the artifact's exact bytes. Edit ANCHORS.json and this file no "
            "longer verifies; `python3 scripts/review_anchor_seal.py --verify` fails closed and "
            "the review refuses to grade against an unsealed bar (#3607, the #3483 shape)."
        ),
    }


def write_seal(repo: str = REPO, now: datetime | None = None) -> dict:
    seal = build_seal(repo, now)
    with open(seal_path(repo), "w", encoding="utf-8") as fh:
        json.dump(seal, fh, indent=2)
        fh.write("\n")
    return seal


def load_anchors_unchecked(repo: str = REPO) -> dict:
    with open(anchors_path(repo), encoding="utf-8") as fh:
        return json.load(fh)


def verify_seal(repo: str = REPO) -> list[str]:
    """[] means the artifact on disk is the artifact the sibling names. Anything else is a
    hard stop for every caller."""
    problems: list[str] = []
    apath, spath = anchors_path(repo), seal_path(repo)
    if not os.path.isfile(apath):
        return [f"no anchor artifact at {ANCHORS_REL}"]
    if not os.path.isfile(spath):
        return [f"no seal sibling at {SEAL_REL} — run: python3 scripts/review_anchor_seal.py --seal"]
    try:
        with open(spath, encoding="utf-8") as fh:
            seal = json.load(fh)
    except ValueError as exc:
        return [f"{SEAL_REL} is not valid JSON ({exc})"]
    actual = sha256_of(apath)
    if seal.get("sha256") != actual:
        problems.append(
            f"SEAL MISMATCH: {ANCHORS_REL} hashes to {actual}, {SEAL_REL} names {seal.get('sha256')} — the anchors moved without a re-seal"
        )
    if seal.get("algorithm") != "sha256":
        problems.append(f"seal algorithm {seal.get('algorithm')!r} is not sha256")
    try:
        data = load_anchors_unchecked(repo)
    except ValueError as exc:
        return problems + [f"{ANCHORS_REL} is not valid JSON ({exc})"]
    lenses = sorted(r.get("lens", "") for r in data.get("records", []))
    if seal.get("lenses") != lenses:
        problems.append(f"seal names lenses {seal.get('lenses')} but the artifact carries {lenses}")
    return problems


def load_anchors(repo: str = REPO) -> dict:
    """The one sanctioned read. Fail-closed: an unsealed or mismatched artifact raises
    rather than being graded against."""
    problems = verify_seal(repo)
    if problems:
        raise AnchorsUnsealed("; ".join(problems))
    return load_anchors_unchecked(repo)


def record_for(data: dict, lens: str) -> dict | None:
    for rec in data.get("records", []):
        if rec.get("lens") == lens:
            return rec
    return None


# ── the schema contract ───────────────────────────────────────────────────────
REQUIRED_RECORD_KEYS = ("lens", "title", "anchors", "frozen_at", "frozen_by", "supersedes_sha", "derived_fields", "proposed_extensions")


def schema_problems(data: dict) -> list[str]:
    """Structural contract over the artifact — what a record must carry, what a clause must
    carry, and the two rules that make the rest of the machinery meaningful: every clause
    has an id and a stated evidence requirement (there is no MET without a citable source),
    and `derived_fields` is exactly the placeholder set the record's own text uses."""
    problems: list[str] = []
    if not isinstance(data.get("records"), list) or not data["records"]:
        return ["ANCHORS.json carries no records[]"]
    seen_lenses, seen_ids = set(), set()
    for rec in data["records"]:
        lens = rec.get("lens", "<unnamed>")
        for key in REQUIRED_RECORD_KEYS:
            if key not in rec:
                problems.append(f"{lens}: record is missing {key!r}")
        if lens in seen_lenses:
            problems.append(f"{lens}: duplicate lens record")
        seen_lenses.add(lens)
        if rec.get("supersedes_sha") is None and not rec.get("supersedes_note"):
            problems.append(f"{lens}: supersedes_sha is null with no supersedes_note saying what it was promoted from")
        anchors = rec.get("anchors") or {}
        if set(anchors) != set(ANCHOR_LEVELS):
            problems.append(f"{lens}: anchor levels {sorted(anchors)} != {list(ANCHOR_LEVELS)}")
        used: set[str] = set()
        for level in sorted(anchors):
            clauses = anchors[level]
            if not isinstance(clauses, list) or not clauses:
                problems.append(f"{lens}.{level}: no clauses")
                continue
            for clause in clauses:
                cid = clause.get("id", "")
                if not cid.startswith(f"{lens}.{level}."):
                    problems.append(f"{lens}.{level}: clause id {cid!r} is not namespaced <lens>.<level>.<n>")
                if cid in seen_ids:
                    problems.append(f"duplicate clause id {cid!r}")
                seen_ids.add(cid)
                if not clause.get("text"):
                    problems.append(f"{cid}: empty text")
                if not clause.get("evidence"):
                    problems.append(f"{cid}: no evidence requirement — a clause with no stated source can only ever pass by silence")
                for lit in bare_literals(clause.get("text", "")) + bare_literals(clause.get("evidence", "")):
                    problems.append(
                        f"{cid}: bare literal {lit!r} — every magnitude in an anchor is a ${{placeholder}} resolved at grading time"
                    )
                used |= set(PLACEHOLDER_RE.findall(clause.get("text", ""))) | set(PLACEHOLDER_RE.findall(clause.get("evidence", "")))
        for ext in rec.get("proposed_extensions") or []:
            for key in ("id", "anchor", "text", "evidence", "proposed_by_run", "proposed_on"):
                if not ext.get(key):
                    problems.append(
                        f"{lens}: proposed extension {ext.get('id', '?')!r} is missing {key!r} — an extension with no authoring run cannot be kept out of that run's grade"
                    )
            for lit in bare_literals(ext.get("text", "")):
                problems.append(f"{lens}/{ext.get('id', '?')}: bare literal {lit!r} in a proposed extension")
        unknown = sorted(n for n in used if n not in RESOLVERS)
        if unknown:
            problems.append(f"{lens}: placeholder(s) {unknown} have no resolver in scripts/review_anchor_seal.RESOLVERS")
        declared = set(rec.get("derived_fields") or [])
        if declared != used:
            problems.append(f"{lens}: derived_fields {sorted(declared)} != the placeholders its text uses {sorted(used)}")
    return problems


# ── the ratchet: tightening-only ──────────────────────────────────────────────
#: Words that carry a clause's STRENGTH. A rewrite that drops one of these without adding
#: another is the loosening shape the 2026-09-05 run had no way to notice: `every` -> `the
#: sampled`, `no` -> `few`, `must` -> `should`.
STRENGTH_TOKENS = (
    "every",
    "all ",
    "each",
    "no ",
    "never",
    "zero",
    "must",
    "exactly",
    "only",
    "any ",
    "within",
    "before",
    "cannot",
    "refuses",
)


def strength(text: str) -> int:
    low = " " + text.lower() + " "
    return sum(low.count(tok) for tok in STRENGTH_TOKENS)


@dataclass
class Loosening:
    kind: str
    clause: str
    detail: str

    def line(self) -> str:
        return f"{self.kind} {self.clause}: {self.detail}"


def _clause_map(data: dict) -> dict[str, dict]:
    out = {}
    for rec in data.get("records", []):
        for level, clauses in (rec.get("anchors") or {}).items():
            for clause in clauses:
                out[clause.get("id", f"{rec.get('lens')}.{level}.?")] = clause
    return out


def freeze_diff(old: dict, new: dict) -> list[Loosening]:
    """Every way the new artifact is WEAKER than the old one. Empty means the edit was a
    tightening (or a pure addition), which is the only kind of anchor edit that lands
    without an owner signature."""
    out: list[Loosening] = []
    old_clauses, new_clauses = _clause_map(old), _clause_map(new)
    old_lenses = {r.get("lens") for r in old.get("records", [])}
    new_lenses = {r.get("lens") for r in new.get("records", [])}
    for lens in sorted(old_lenses - new_lenses):
        out.append(Loosening("LENS-REMOVED", lens, "a graded lens left the artifact — its bar is now unstated"))
    for cid in sorted(set(old_clauses) - set(new_clauses)):
        out.append(Loosening("CLAUSE-REMOVED", cid, f"dropped: {old_clauses[cid].get('text', '')[:110]}"))
    for cid in sorted(set(old_clauses) & set(new_clauses)):
        was, now = old_clauses[cid], new_clauses[cid]
        if strength(now.get("text", "")) < strength(was.get("text", "")):
            out.append(
                Loosening(
                    "CLAUSE-WEAKENED", cid, f"quantifier strength fell ({strength(was.get('text', ''))} -> {strength(now.get('text', ''))})"
                )
            )
        was_ev, now_ev = was.get("evidence", ""), now.get("evidence", "")
        if now_ev != was_ev and (strength(now_ev) < strength(was_ev) or len(now_ev) < len(was_ev) * 0.75):
            out.append(Loosening("EVIDENCE-RELAXED", cid, "the evidence requirement shrank — a clause may not become easier to cite"))
        lost = set(PLACEHOLDER_RE.findall(was.get("text", ""))) - set(PLACEHOLDER_RE.findall(now.get("text", "")))
        if lost:
            out.append(
                Loosening(
                    "DERIVATION-DROPPED", cid, f"placeholder(s) {sorted(lost)} removed — a derived threshold may not go back to prose"
                )
            )
    return out


def owner_login(repo: str = REPO) -> str:
    """The one identity allowed to sign a loosening, derived from the GitHub posture rather
    than typed here — the same account the required-checks ruleset names as its bypass
    actor. One home for the owner's handle."""
    with open(os.path.join(repo, "deploy", "github_posture.json"), encoding="utf-8") as fh:
        posture = json.load(fh)
    actors = (posture.get("main_required_checks_ruleset") or {}).get("bypass_actors") or []
    for actor in actors:
        if actor.get("actor_type") == "User" and actor.get("login"):
            return actor["login"]
    raise KeyError("deploy/github_posture.json names no User bypass actor — the owner identity has no source")


def signed_loosenings(data: dict, repo: str = REPO) -> dict[str, dict]:
    """`{clause id: the signed line}` for every valid owner signature in the artifact. An
    entry signed by anyone else, undated, or with no reason is NOT a signature."""
    out: dict[str, dict] = {}
    try:
        owner = owner_login(repo)
    except (OSError, KeyError, ValueError):
        return out
    for entry in data.get("loosenings") or []:
        if entry.get("signed_by") != owner or not entry.get("why"):
            continue
        try:
            date.fromisoformat(str(entry.get("signed_on", "")))
        except ValueError:
            continue
        for cid in entry.get("clauses") or []:
            out[cid] = entry
    return out


def unsigned_loosenings(old: dict, new: dict, repo: str = REPO) -> list[Loosening]:
    """The ratchet's verdict: every weakening the new file did NOT buy with an owner-signed
    dated line. Non-empty reds the freeze test."""
    signed = signed_loosenings(new, repo)
    return [item for item in freeze_diff(old, new) if item.clause not in signed]


def anchors_at_ref(ref: str, repo: str = REPO) -> dict | None:
    """The artifact as it stood at a git ref — the previous sha the ratchet diffs against."""
    try:
        out = subprocess.run(["git", "show", f"{ref}:{ANCHORS_REL}"], cwd=repo, capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0 or not out.stdout.strip():
        return None
    try:
        return json.loads(out.stdout)
    except ValueError:
        return None


# ── the third verdict ─────────────────────────────────────────────────────────
@dataclass
class ClauseVerdict:
    clause_id: str
    verdict: str
    citation: str = ""
    reason: str = ""
    proposed: bool = False


@dataclass
class LensGrading:
    lens: str
    ceiling: str
    unobserved: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


def clauses_for(record: dict, include_proposed: bool = False) -> list[dict]:
    """The clause set a run grades against. `include_proposed=False` is the FROZEN set —
    the only one that binds the run's grade. The proposed set is the second, advisory
    grade: an extension written during a run never moves that run's row."""
    out = []
    for level in ANCHOR_LEVELS:
        for clause in (record.get("anchors") or {}).get(level, []):
            out.append(dict(clause, level=level, proposed=False))
    if include_proposed:
        for ext in record.get("proposed_extensions") or []:
            out.append(dict(ext, level=ext.get("anchor", "A"), proposed=True))
    return out


def validate_verdicts(record: dict, verdicts, include_proposed: bool = False) -> list[str]:
    """Every clause resolves to exactly one of the three, and the two that claim knowledge
    must cite it. A MET with no citation is the shape this whole story is about."""
    problems: list[str] = []
    expected = {c["id"] for c in clauses_for(record, include_proposed)}
    seen: set[str] = set()
    for v in verdicts:
        cid = v.clause_id
        if cid not in expected:
            problems.append(
                f"{cid}: verdict for a clause that is not in this lens's {'frozen+proposed' if include_proposed else 'frozen'} set"
            )
        if cid in seen:
            problems.append(f"{cid}: graded twice")
        seen.add(cid)
        if v.verdict not in VERDICTS:
            problems.append(f"{cid}: verdict {v.verdict!r} is not one of {VERDICTS}")
        elif v.verdict in (MET, FAILED) and not v.citation:
            problems.append(f"{cid}: {v.verdict} with no citation — a file:line, a URL, or a query result, or the verdict is {UNOBSERVED}")
        elif v.verdict == UNOBSERVED and not v.reason:
            problems.append(f"{cid}: {UNOBSERVED} with no reason it could not be sampled")
    for cid in sorted(expected - seen):
        problems.append(f"{cid}: ungraded — every clause resolves to {'/'.join(VERDICTS)}; silence is not a pass")
    return problems


def lens_grade_ceiling(record: dict, verdicts, include_proposed: bool = False) -> LensGrading:
    """The rule that makes 'all A' observable: ANY unobserved clause caps the lens below A.

    The cap is A- rather than a refusal, because an unobservable clause is a fact about the
    sampling window, not evidence of decay — but it can never be silently absorbed into an
    A again. A FAILED clause caps at B+ by the same logic: the row cannot be top of the
    scale with a reproduced failure against its own bar.
    """
    problems = validate_verdicts(record, verdicts, include_proposed)
    unobserved = sorted(v.clause_id for v in verdicts if v.verdict == UNOBSERVED)
    failed = sorted(v.clause_id for v in verdicts if v.verdict == FAILED)
    ceiling = "A"
    if unobserved:
        ceiling = "A-"
    if failed:
        ceiling = "B+"
    return LensGrading(record.get("lens", "?"), ceiling, unobserved, failed, problems)


def rows_moved_by(record: dict, frozen: LensGrading, proposed: LensGrading) -> list[str]:
    """Which clause moved the row between the frozen grade and the frozen+proposed grade —
    the sentence a run has to be able to write before an extension is allowed to count."""
    if frozen.ceiling == proposed.ceiling:
        return []
    moved = (set(proposed.unobserved) | set(proposed.failed)) - (set(frozen.unobserved) | set(frozen.failed))
    known = {c["id"] for c in clauses_for(record, include_proposed=True) if c.get("proposed")}
    return sorted(moved & known) or sorted(moved)


# ── the dead-man: the hash in every report header ─────────────────────────────
def header_block(repo: str = REPO, ctx: dict | None = None) -> str:
    """The block the review prints in its report header, every run. A run whose header has
    no sha graded against a bar nobody can reconstruct."""
    lines = ["REVIEW ANCHORS — sealed artifact (#3607)"]
    problems = verify_seal(repo)
    if problems:
        lines += ["", "  SEAL DOES NOT VERIFY — the review must not grade against this file:"]
        lines += [f"    ✗ {p}" for p in problems]
        lines += ["", "  Repair: re-seal deliberately (python3 scripts/review_anchor_seal.py --seal) in a reviewable PR."]
        return "\n".join(lines)
    data = load_anchors_unchecked(repo)
    with open(seal_path(repo), encoding="utf-8") as fh:
        seal = json.load(fh)
    lines += [
        "",
        f"  artifact   {ANCHORS_REL}",
        f"  sha256     {seal['sha256']}",
        f"  sealed_at  {seal.get('sealed_at')}",
        f"  frozen_at  {data.get('frozen_at')}   lenses: {len(data.get('records', []))}",
        "",
        "  Placeholders resolved for this run:",
    ]
    resolutions = resolve_all(ctx=ctx)
    for name in sorted(resolutions):
        res = resolutions[name]
        if res.observed:
            lines.append(f"    ${{{name}}} = {res.value}   [{res.source}]")
        else:
            lines.append(f"    ${{{name}}} = {UNOBSERVED}   [{res.reason}]")
    signed = signed_loosenings(data, repo)
    if signed:
        lines += ["", "  OWNER-SIGNED LOOSENINGS IN FORCE (a lower bar than the previous seal):"]
        for cid, entry in sorted(signed.items()):
            lines.append(f"    {cid} — signed {entry['signed_on']} by {entry['signed_by']}: {entry['why']}")
    else:
        lines += ["", "  Owner-signed loosenings: none — every clause is at or above the previous seal."]
    lines += [
        "",
        f"  Every clause resolves {MET} (cited) / {FAILED} (cited) / {UNOBSERVED} (with the reason it",
        f"  could not be sampled). A lens with ANY {UNOBSERVED} clause cannot be graded A. An extension",
        "  proposed during this run goes to proposed_extensions[] and does not bind this run's grade.",
        "",
    ]
    return "\n".join(lines)


def _print_lens(lens: str, repo: str, ctx: dict) -> int:
    data = load_anchors_unchecked(repo)
    rec = record_for(data, lens)
    if rec is None:
        print(f"no anchor record for lens {lens!r}; known: {sorted(r['lens'] for r in data.get('records', []))}")
        return 2
    resolutions = resolve_all(rec.get("derived_fields") or [], ctx=ctx)
    print(f"{rec['lens']} — {rec['title']}   (frozen {rec['frozen_at']} by {rec['frozen_by']})")
    for clause in clauses_for(rec, include_proposed=True):
        text, unresolved = render(clause["text"], resolutions)
        tag = "PROPOSED " if clause.get("proposed") else ""
        print(f"\n  [{tag}{clause['level']}] {clause['id']}")
        print(f"    {text}")
        print(f"    evidence: {render(clause.get('evidence', ''), resolutions)[0]}")
        if unresolved:
            print(f"    -> {UNOBSERVED} unless sampled another way: {sorted(set(unresolved))}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--verify", action="store_true", help="fail-closed seal + schema check (exit 1 on any problem)")
    ap.add_argument("--header", action="store_true", help="the block the review prints in its report header")
    ap.add_argument("--lens", default=None, help="print one lens's anchors with placeholders resolved")
    ap.add_argument("--seal", action="store_true", help="re-stamp the sha sibling after a deliberate edit")
    ap.add_argument("--diff", default=None, help="tightening-only diff of the working artifact against a git ref")
    ap.add_argument("--json", action="store_true", help="machine-readable output for --verify")
    args = ap.parse_args(argv)
    ctx: dict = {}

    if args.seal:
        seal = write_seal()
        print(f"SEALED {ANCHORS_REL} -> {SEAL_REL}\n  sha256 {seal['sha256']}\n  sealed_at {seal['sealed_at']}")
        return 0
    if args.diff:
        old = anchors_at_ref(args.diff)
        if old is None:
            print(f"no {ANCHORS_REL} at {args.diff} — nothing to diff against (a first seal has no predecessor)")
            return 0
        items = unsigned_loosenings(old, load_anchors_unchecked())
        if not items:
            print(f"TIGHTENING-ONLY vs {args.diff}: no clause was weakened, removed, or had its evidence relaxed.")
            return 0
        print(f"LOOSENED vs {args.diff} with no owner signature:")
        for item in items:
            print(f"  ✗ {item.line()}")
        return 1
    if args.lens:
        return _print_lens(args.lens, REPO, ctx)
    if args.header:
        print(header_block(ctx=ctx))
        return 0

    problems = verify_seal() or []
    if not problems:
        problems += schema_problems(load_anchors_unchecked())
    if args.json:
        print(json.dumps({"artifact": ANCHORS_REL, "problems": problems, "ok": not problems}, indent=2))
    elif problems:
        print(f"❌ {ANCHORS_REL} — {len(problems)} problem(s):")
        for p in problems:
            print(f"  ✗ {p}")
    else:
        print(f"✅ {ANCHORS_REL} verifies against {SEAL_REL} and satisfies the anchor contract.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
