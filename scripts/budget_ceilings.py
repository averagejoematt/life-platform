"""scripts/budget_ceilings.py — the ONE derivation of the budget-ceiling family (#2898).

WHAT THIS IS
  `lambdas/operational/cost_governor_lambda.py` is the single authoritative source
  for the monthly AI/platform spend ceiling: `MONTHLY_CEILING`, `SURGE_CEILING_USD`,
  and the dated-window pair `_TEMP_CEILING_USD` / `_TEMP_SURGE_CEILING_USD` gated by
  `_TEMP_CEILING_WINDOW`. This module reads those four numbers *out of that file* and
  hands them to every non-importing consumer, so the number exists in exactly one
  place in the tree.

WHY PARSE INSTEAD OF IMPORT
  Importing the governor executes its body, which constructs four boto3 clients. The
  two consumers here are the CI lint job (`scripts/check_doc_facts.py`, no boto3) and
  `cdk synth` (a Node-driven Python process that must not acquire an AWS dependency to
  compute a budget amount). Where import IS viable the consumer imports instead — see
  `lambdas/web/site_api_budget.py`, which already imports the governor's price table
  and now takes its fail-closed ceiling fallback from `MONTHLY_CEILING` directly.
  So: import when you can, parse when you can't, hand-copy never.

WHO USES IT
  * `scripts/check_doc_facts.py::_governor_ceilings` — the prose gate's allowed SET
    (this module is where that AST parse used to live; it was lifted here verbatim so
    two parsers would not exist).
  * `cdk/stacks/core_stack.py` — the AWS Budgets backstop amount.
  * `tests/test_budget_ceiling_registry_2898.py` — the derivation guard that proves no
    consumer in lambdas/, cdk/, mcp/ or site/ hand-types one of these numbers.

THE DATED WINDOW IS PART OF THE FAMILY (#2898 acceptance box 4)
  `_TEMP_CEILING_WINDOW` is `[start, end)`; inside it the ACTIVE pair is the temp pair,
  outside it the permanent pair. `active_pair()`/`figures()` take `today` as an
  argument so a caller can stand on either side of the boundary without touching the
  wall clock — the live gate passes None and gets `date.today()`.
"""

from __future__ import annotations

import ast
import datetime as _dt
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parent.parent
GOVERNOR_SRC = ROOT / "lambdas" / "operational" / "cost_governor_lambda.py"

# The governor's own names. Spelled once, here — a consumer never names them again.
BASE_NAME = "MONTHLY_CEILING"
SURGE_NAME = "SURGE_CEILING_USD"
WINDOW_NAME = "_TEMP_CEILING_WINDOW"
WINDOW_BASE_NAME = "_TEMP_CEILING_USD"
WINDOW_SURGE_NAME = "_TEMP_SURGE_CEILING_USD"


def _const_number(node):
    """A numeric literal out of `X = 5.0` or `X = float(os.environ.get("Y", "5"))`.

    For a `.get(key, default)` call the DEFAULT is the last arg, not the first —
    reading args[0] there would return the env-var name and silently yield nothing.
    """
    if isinstance(node, ast.Constant):
        try:
            return float(node.value)
        except (TypeError, ValueError):
            return None
    if isinstance(node, ast.Call) and node.args:
        is_get = isinstance(node.func, ast.Attribute) and node.func.attr == "get"
        return _const_number(node.args[-1] if is_get else node.args[0])
    return None


def _const_date(node):
    """`date(2026, 8, 1)` → datetime.date(2026, 8, 1); anything else → None."""
    if isinstance(node, ast.Call) and len(node.args) == 3:
        parts = [a.value for a in node.args if isinstance(a, ast.Constant) and isinstance(a.value, int)]
        if len(parts) == 3:
            try:
                return _dt.date(*parts)
            except ValueError:
                return None
    return None


class CeilingFamily(NamedTuple):
    """The four numbers + the window they switch on, as parsed from the governor.

    Any field may be None when the governor could not be read — callers decide what
    that means for them (the doc gate degrades to "no opinion"; CDK refuses to synth).
    """

    base: float | None
    surge: float | None
    window_base: float | None
    window_surge: float | None
    window: tuple[_dt.date, _dt.date] | None
    source: Path

    # ── the family, in the forms consumers actually want ──────────────────────
    def window_active(self, today: _dt.date | None = None) -> bool:
        """True while the dated window is in force. End date is EXCLUSIVE — the
        governor's own auto-revert semantics, restated nowhere else."""
        if not self.window:
            return False
        today = today or _dt.date.today()
        return self.window[0] <= today < self.window[1]

    def active_pair(self, today: _dt.date | None = None) -> tuple[float | None, float | None]:
        """(base, surge) in force on `today` — the temp pair inside the window."""
        if self.window_active(today) and self.window_base is not None:
            return self.window_base, self.window_surge
        return self.base, self.surge

    def figures(self, today: _dt.date | None = None) -> set[int]:
        """Every ceiling figure that may legitimately be stated as CURRENT truth.

        The permanent pair always (a doc may name the base while a window runs — it
        is what the window reverts to), plus the window pair only while it runs.
        """
        allowed = {int(v) for v in (self.base, self.surge) if v is not None}
        if self.window_active(today):
            allowed |= {int(v) for v in (self.window_base, self.window_surge) if v is not None}
        return allowed

    def all_figures(self) -> set[int]:
        """Every figure in the family, window or not — what a HAND-TYPED COPY guard
        cares about. `figures()` asks "may prose say this today?"; this asks "is this
        number owned by the governor at all?", and a consumer must derive either way."""
        return {int(v) for v in (self.base, self.surge, self.window_base, self.window_surge) if v is not None}

    def provenance(self, today: _dt.date | None = None) -> str:
        """One human-readable line explaining which figures are allowed and why."""
        why = [f"base/surge {sorted(int(v) for v in (self.base, self.surge) if v is not None)}"]
        if not self.window:
            return "; ".join(why)
        temp = sorted(int(v) for v in (self.window_base, self.window_surge) if v is not None)
        if self.window_active(today):
            why.append(f"dated window {temp} in effect {self.window[0]}..{self.window[1]}")
        else:
            why.append(f"dated window {self.window[0]}..{self.window[1]} NOT in effect")
        return "; ".join(why)


_MISSING = CeilingFamily(None, None, None, None, None, GOVERNOR_SRC)


def read_family(src: Path | None = None) -> CeilingFamily:
    """Parse the ceiling family out of the governor. Never imports, never raises."""
    src = src or GOVERNOR_SRC
    if not src.exists():
        return _MISSING._replace(source=src)
    consts: dict[str, float] = {}
    window = None
    tree = ast.parse(src.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign) or not isinstance(node.targets[0], ast.Name):
            continue
        name = node.targets[0].id
        if name == WINDOW_NAME and isinstance(node.value, ast.Tuple) and len(node.value.elts) == 2:
            lo, hi = (_const_date(e) for e in node.value.elts)
            if lo and hi:
                window = (lo, hi)
        else:
            val = _const_number(node.value)
            if val is not None:
                consts[name] = val
    return CeilingFamily(
        base=consts.get(BASE_NAME),
        surge=consts.get(SURGE_NAME),
        window_base=consts.get(WINDOW_BASE_NAME),
        window_surge=consts.get(WINDOW_SURGE_NAME),
        window=window,
        source=src,
    )


def governor_ceilings(today: _dt.date | None = None, src: Path | None = None) -> tuple[set[int], str]:
    """(allowed ceiling figures, provenance string) — the shape the doc gate wants.

    `today` is injectable so the regression tests can stand inside and outside the
    dated window without depending on wall-clock; the live gate passes None.
    """
    fam = read_family(src)
    if fam.source is not None and not fam.source.exists():
        return set(), "cost_governor_lambda.py not found"
    return fam.figures(today), fam.provenance(today)


def base_ceiling_usd(src: Path | None = None) -> float:
    """The permanent monthly base ceiling, for a consumer that needs ONE number.

    Raises rather than defaulting: a caller that reaches this (CDK synth writing the
    AWS Budgets backstop) must not quietly fall back to a guessed dollar amount — a
    silently-wrong budget limit is the failure mode this whole issue is about.
    """
    fam = read_family(src)
    if fam.base is None:
        raise RuntimeError(f"budget ceiling not derivable from {fam.source} — refusing to guess an amount (#2898)")
    return fam.base


def budget_amount_usd(src: Path | None = None) -> float | int:
    """The base ceiling in the form CloudFormation's Budget `Amount` should receive.

    Integral values come back as `int` so the synthesized template reads `150`, exactly
    as the hand-typed literal did — `150.0` would be a template diff, and a template diff
    on a CfnBudget is an unnecessary resource update on the next deploy for no change in
    meaning. This coercion lives HERE rather than in `core_stack.py` for one reason: the
    derivation guard must be able to assert it without importing `aws_cdk`. CDK is not
    installed in the offline test job (`tests/test_role_policies.py` stubs the module to
    work around exactly that), and a test that imports a real stack both costs ~2.6s of
    jsii startup and inherits whatever stub a sibling test left in `sys.modules`.
    """
    base = base_ceiling_usd(src)
    return int(base) if float(base).is_integer() else base
