"""tests/grounding_wiring.py — the derived grounding-gate surface registry (#1967).

WHY THIS EXISTS
---------------
``grounded_generation.grounding_findings()`` takes every gate class as an OPTIONAL
keyword (deliberate, for backward compat — #1691/#1699). That made per-surface coverage
a matter of *convention*: each new gate class had to be hand-wired into each caller and
nothing failed when one was missed. The measured state at the time this landed was 4 of
15 grounding surfaces arming the #1691 cycle-freshness class and 1 of 15 arming the
#1699 behavioral class — and the "seven days of an experiment" Day-1 leak (#1897) was
the live consequence.

HOW IT'S GUARDED (guard the SET, not the instance)
--------------------------------------------------
The surface list is **derived**, never hand-maintained: ``scan_tree()`` AST-scans
``lambdas/`` for every call to a grounding chokepoint and keys it by
``"<module path>::<outermost enclosing function>"``. ``SURFACES`` below only supplies the
*policy* for each discovered surface — which gate classes it must arm, and a written
reason for each one it does not. The test asserts BOTH directions:

  * every discovered surface has a ``SURFACES`` entry  -> a NEW ungated AI surface fails
    the build until someone decides its gate classes (this is the #1967 outcome);
  * every ``SURFACES`` entry still resolves to a real discovered surface -> the registry
    cannot rot into a stale hand-list.

and, per entry, ``required | exempt == GATE_CLASSES`` — so adding a class to
``GATE_CLASSES`` forces a *decision* on every existing surface rather than silently
leaving them all uncovered.
"""

import ast
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(_HERE)

# ── The gate classes, and how a caller ARMS each one ──────────────────────────
# kwargs: passing ALL of these to grounding_findings() arms the class.
# direct:  calling one of these grounded_generation helpers directly also arms it
#          (ai_calls' coach-v2 pipeline runs the two advisory gates as separate,
#          separately-logged steps rather than through the composite entrypoint).
GATE_CLASSES = {
    # ADR-104 allow-list number gate — the universal floor.
    "numbers": {"kwargs": ("allowed",), "direct": ()},
    # #1242 fabricated-date gate.
    "dates": {"kwargs": ("allowed_dates",), "direct": ()},
    # #1691 stale_baseline/stale_phase + #1897 experiment_span — the cycle anchors.
    "freshness": {
        "kwargs": ("generation_date_iso", "start_date_iso"),
        "direct": ("baseline_freshness_findings", "experiment_span_findings"),
    },
    # #1699 ungrounded-behavioral (same-day completed-action claim with no log).
    "behavioral": {"kwargs": ("available_logs",), "direct": ("ungrounded_behavioral_findings",)},
    # #1968 night-scope (a sleep/recovery/HRV figure with no night name, or one that
    # disagrees with that night's stored value after the wearable revised it).
    "night": {"kwargs": ("nightly_vitals",), "direct": ("night_scoped_vitals_findings",)},
}

# The composite entrypoint whose kwargs are read, plus the standalone gate helpers.
CHOKEPOINTS = {"grounding_findings"} | {fn for spec in GATE_CLASSES.values() for fn in spec["direct"]}

# Helpers that SUPPLY gate kwargs as a ``**spread``. AST sees only ``**call()``, so the
# provider has to declare what it arms. Renaming the provider without updating this map
# fails the wiring test instead of silently disarming every caller that spreads it.
PARAM_PROVIDERS = {"cycle_gate_params": frozenset({"freshness"})}
PARAM_PROVIDER_MODULE = "lambdas/ai/grounding_gate_params.py"

# ── Reusable exemption reasons (written once, cited per surface) ──────────────
_NO_LOG_MAP = (
    "no per-generation-date log-availability map at this layer: `available_logs` must be "
    "the real set of log categories present for the generation date (ai_calls' "
    "`_available_logs_for_today` derives it from the coach render payload). Passing a "
    "guessed or empty set would flag EVERY same-day behavioral claim, so arming this "
    "class here has to wait for that payload to be threaded through — not for a default."
)
_PRECEDENT_SCOPED_DATES = (
    "uses the framing-scoped precedent check (semantic_recall.precedent_citation_findings) "
    "instead of a blanket date allow-list — documented in-code at the call site: the "
    "coach-v2 allow-list deliberately excludes the few-shot voice block, so a blanket "
    "`allowed_dates` would false-flag ordinary data dates."
)
_AUDITOR = (
    "post-hoc freshness AUDITOR over already-published text, not a generation gate — it "
    "has no prompt/allow-list to ground numbers or dates against and no generation-day "
    "log map. Freshness is the only class that is meaningful (and it is armed)."
)
_NO_NIGHT_MAP = (
    "no night-keyed vitals map at this layer: `nightly_vitals` must be real stored "
    "readings keyed by NIGHT (ai_calls' `_nightly_vitals_for` derives it from the whoop "
    "rows the render already loaded). Passing a guessed or empty map would flag every "
    "sleep/recovery/HRV figure on the surface as unlabeled, which is how a gate gets "
    "switched off. Arming this class here waits on threading that map through — the "
    "same contract `available_logs` (#1699) has, and not a default."
)
_NOT_A_VITALS_SURFACE = (
    "this surface does not narrate night-scoped vitals — it has no sleep, recovery, HRV "
    "or resting-HR figure to scope to a night, so arming the class would be a no-op "
    "rather than coverage. Revisit if its subject matter widens."
)

_ALL = frozenset(GATE_CLASSES)


def _entry(required, exempt):
    return {"required": frozenset(required), "exempt": dict(exempt)}


# ── The registry: policy per DERIVED surface ─────────────────────────────────
SURFACES = {
    "lambdas/ai/ai_calls.py::_ground_legacy_output": _entry(
        ("numbers", "dates", "freshness"),
        {"behavioral": _NO_LOG_MAP, "night": _NO_NIGHT_MAP},
    ),
    "lambdas/ai/ai_calls.py::_run_coach_v2_pipeline": _entry(
        ("numbers", "freshness", "behavioral", "night"),
        {"dates": _PRECEDENT_SCOPED_DATES},
    ),
    "lambdas/coach/coach_history_summarizer.py::_apply_grounding_gate": _entry(
        ("numbers", "dates", "freshness"),
        {"behavioral": _NO_LOG_MAP, "night": _NO_NIGHT_MAP},
    ),
    "lambdas/coach/inter_coach_dialogue_lambda.py::generate_gated_turn": _entry(
        ("numbers", "dates", "freshness"),
        {"behavioral": _NO_LOG_MAP, "night": _NO_NIGHT_MAP},
    ),
    "lambdas/compute/state_of_matthew_lambda.py::narration_gate": _entry(
        ("numbers", "dates", "freshness"),
        {"behavioral": _NO_LOG_MAP, "night": _NO_NIGHT_MAP},
    ),
    "lambdas/content/review_pack_ranker.py::baseline_mismatch_findings": _entry(
        ("freshness",),
        {"numbers": _AUDITOR, "dates": _AUDITOR, "behavioral": _AUDITOR, "night": _AUDITOR},
    ),
    "lambdas/emails/ai_review_pack_lambda.py::_freshness_findings_for": _entry(
        ("freshness",),
        {"numbers": _AUDITOR, "dates": _AUDITOR, "behavioral": _AUDITOR, "night": _AUDITOR},
    ),
    "lambdas/emails/chronicle_prompt.py::installment_grounding_findings": _entry(
        ("numbers", "dates", "freshness"),
        {"behavioral": _NO_LOG_MAP, "night": _NO_NIGHT_MAP},
    ),
    "lambdas/emails/coach_nudge_lambda.py::_gate": _entry(
        ("numbers", "dates", "freshness"),
        {"behavioral": _NO_LOG_MAP, "night": _NO_NIGHT_MAP},
    ),
    "lambdas/emails/daily_debrief_lambda.py::narrate": _entry(
        ("numbers", "dates", "freshness"),
        {"behavioral": _NO_LOG_MAP, "night": _NO_NIGHT_MAP},
    ),
    "lambdas/intelligence/ai_expert_analyzer_lambda.py::generate_and_cache": _entry(
        ("numbers", "freshness", "night"),
        {
            "dates": (
                "the analyzer's allow-list is assembled from prompt + shared system + "
                "canonical facts, but its narratives cite dates drawn from retrieved "
                "blocks that are summarized rather than quoted into those sources — a "
                "blanket date gate needs that source audit first. Tracked with the "
                "module's ADR-080 split (it sits at the 2,000-line handler cap, so the "
                "wiring lands with the extraction, not as an append)."
            ),
            "behavioral": _NO_LOG_MAP,
        },
    ),
    "lambdas/reading/horizons_retrospective.py::_grounding_gate": _entry(
        ("numbers", "dates", "freshness"),
        {"behavioral": _NO_LOG_MAP, "night": _NOT_A_VITALS_SURFACE},
    ),
    "lambdas/web/site_api_ai_lambda.py::board_grounding_findings": _entry(
        ("numbers", "dates", "freshness"),
        {"behavioral": _NO_LOG_MAP, "night": _NO_NIGHT_MAP},
    ),
    "lambdas/web/site_api_ai_lambda.py::_handle_ask": _entry(
        ("numbers", "dates", "freshness"),
        {"behavioral": _NO_LOG_MAP, "night": _NO_NIGHT_MAP},
    ),
    "lambdas/web/site_api_ai_lambda.py::_handle_explain": _entry(
        ("numbers", "dates", "freshness"),
        {"behavioral": _NO_LOG_MAP, "night": _NO_NIGHT_MAP},
    ),
}


# ── The derivation ───────────────────────────────────────────────────────────
def _classes_for_call(func_name, kwarg_names, spread_providers):
    """Gate classes a single call arms."""
    armed = set()
    for cls, spec in GATE_CLASSES.items():
        if func_name in spec["direct"] and (not spec["kwargs"] or all(k in kwarg_names for k in spec["kwargs"])):
            armed.add(cls)
        elif func_name == "grounding_findings" and spec["kwargs"] and all(k in kwarg_names for k in spec["kwargs"]):
            armed.add(cls)
    for provider in spread_providers:
        armed |= set(PARAM_PROVIDERS.get(provider, ()))
    return armed


def scan_source(rel_path, source):
    """{surface_key: set(gate classes armed)} for one module's source text.

    The surface key is ``"<rel_path>::<outermost enclosing function>"`` — outermost so a
    nested ``_findings_fn`` closure (the shared regen-once shape) is attributed to the
    real surface, and so the key survives a closure rename.
    """
    found = {}
    tree = ast.parse(source)

    def visit(node, outer):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                visit(child, outer or child.name)
                continue
            if isinstance(child, ast.Call):
                fn = child.func
                name = fn.id if isinstance(fn, ast.Name) else (fn.attr if isinstance(fn, ast.Attribute) else None)
                if name in CHOKEPOINTS:
                    kwarg_names = {k.arg for k in child.keywords if k.arg}
                    spreads = set()
                    for k in child.keywords:
                        if k.arg is None and isinstance(k.value, ast.Call):
                            v = k.value.func
                            spreads.add(v.id if isinstance(v, ast.Name) else getattr(v, "attr", ""))
                    key = f"{rel_path}::{outer or '<module>'}"
                    found.setdefault(key, set())
                    found[key] |= _classes_for_call(name, kwarg_names, spreads)
            visit(child, outer)

    visit(tree, None)
    return found


def scan_tree(repo=REPO):
    """{surface_key: set(gate classes armed)} across all of ``lambdas/``.

    ``grounded_generation.py`` itself is skipped — it DEFINES the chokepoints and its
    internal dispatch is not a surface.
    """
    found = {}
    root = os.path.join(repo, "lambdas")
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in sorted(files):
            if not f.endswith(".py"):
                continue
            path = os.path.join(base, f)
            rel = os.path.relpath(path, repo)
            if rel == "lambdas/ai/grounded_generation.py":
                continue
            with open(path, encoding="utf-8") as fh:
                source = fh.read()
            if not any(cp in source for cp in CHOKEPOINTS):
                continue
            for key, classes in scan_source(rel, source).items():
                found.setdefault(key, set())
                found[key] |= classes
    return found
