"""mcp/surface_index.py — the DERIVED index of every platform surface (#3668).

WHY THIS EXISTS
---------------
Two failure modes, and the second is the expensive one.

**Unreachable data.** The owner asked his Claude "what cycle are we on" and was told
the platform does not track it. It tracks it in three places that agree
(``CYCLE_GENESES``, SSM ``/life-platform/experiment-cycle``, ``experiment_stamp()``);
no MCP tool exposed any of them. 134 site-API endpoints, 76 MCP tools, 59 owner-relevant
endpoints with no name-overlapping tool. The honest assistant reported the absence it
could see, and the platform made it wrong.

**Reachable data that cannot be interpreted.** One night produced five specimens, and in
every one the platform was RIGHT and unable to say so:

===================  =============================  ==================================
surface              platform state                 what a careful assistant concluded
===================  =============================  ==================================
cycle number         held in 3 places               "the platform doesn't track it"
nutrition            filtered exactly as asked      "direct contradiction"
ACWR                 computed, 0.929, full cover    "the Lambda hasn't run"
habits               captured, mis-dated            "0 of 61 completed"
water                ingested, wrong day            (silently absent)
===================  =============================  ==================================

The nutrition one is the cleanest: ``/api/source_freshness`` reports *fresh through
2026-09-06* and the nutrition surface reports *no data 16 Aug – 05 Sep*. **Both are
correct.** Six intervening days carry ``phase=pilot`` (the erroneous copy-paste week the
owner asked to be excluded); freshness reads the partition with ``include_pilot=True``
and the nutrition door reads it through the default ADR-058 filter. Neither surface
stated the rule it applied, so a caller had no way to reconcile two right answers and
reported a contradiction.

Coverage alone fixes NONE of that. An assistant with a tool per endpoint would still
have said "no ACWR data". So every surface in this index declares, alongside its data:

  * the **phase filter** it applies (``experiment-only`` / ``includes-pilot`` /
    ``mixed`` / ``undeclared``) and how to ask for the unfiltered view,
  * the **date basis** (Pacific calendar day vs UTC vs the DynamoDB ``DATE#`` key),
  * whether row **provenance** (live capture vs backfill) is distinguished at all —
    reported as ``undeclared`` where it is not, because that gap is the thing that made
    a 2026-05 bulk import of 473 Hevy workouts read as data loss.

WHAT IS DERIVED AND WHAT IS WRITTEN DOWN
----------------------------------------
The **set** of surfaces is derived, never listed: it comes from
``deploy/endpoint_registry.discover_endpoint_records`` — the SAME AST walk
``sync_doc_metadata`` and ``tests/test_api_schema_completeness.py`` already use (#1436's
"one walk, two consumers" rule; this module is the third consumer, not a fourth walk).
``deploy/endpoint_registry.py`` is staged at the MCP bundle root by
``build_bundle.stage_mcp`` so the runtime and the repo run the same code.

The **governing rule** per surface is derived too, by AST call-analysis of the handler
and its one-hop delegate: a ``_query_source`` / ``_latest_item`` / ``with_phase_filter``
call with ``include_pilot=True`` is an unfiltered read, without it a filtered one. That
is why the declaration cannot drift from the code — nobody has to remember to update it.

What is WRITTEN DOWN is a decoration layer only:

  * ``READER_ONLY_SURFACES`` — the exclusion registry. Each entry carries a reason in
    prose. Write endpoints are excluded by DERIVATION (POST-only), not by listing.
  * ``SURFACE_NOTES`` — the plain-English question / example phrasing / params for the
    surfaces that have one. **A surface with no note still appears in the index**, with
    ``annotated: false`` and a derived fallback question, so a route shipped tomorrow is
    reachable tomorrow. ``tests/test_mcp_surface_index_3668.py`` plants a route into the
    source text and fails if it does not appear.

v1.0.0 — 2026-09-06 (#3668)
"""

from __future__ import annotations

import ast
import os
from functools import lru_cache
from typing import Any

# ── Locating the route source, in both worlds ────────────────────────────────
# Repo checkout: <repo>/lambdas/web/site_api_lambda.py
# MCP bundle:    <bundle root>/web/site_api_lambda.py  (the tree is staged at the root)
_HERE = os.path.dirname(os.path.abspath(__file__))
_PARENT = os.path.dirname(_HERE)

_SITE_API_CANDIDATES = (
    os.path.join(_PARENT, "web", "site_api_lambda.py"),  # bundle root
    os.path.join(_PARENT, "lambdas", "web", "site_api_lambda.py"),  # repo checkout
)


def site_api_path() -> str:
    """Absolute path to ``site_api_lambda.py``, or "" when unavailable."""
    for cand in _SITE_API_CANDIDATES:
        if os.path.isfile(cand):
            return cand
    return ""


def web_package_dir() -> str:
    """Directory holding the ``web/`` split modules, or "" when unavailable."""
    p = site_api_path()
    return os.path.dirname(p) if p else ""


def lambdas_root() -> str:
    """Directory holding the packaged ``lambdas/`` tree (``web/``, ``experiment/``, …)."""
    d = web_package_dir()
    return os.path.dirname(d) if d else ""


def _discover_records(source: str | None = None) -> dict:
    """The ONE AST walk (#1436), resolved from whichever world we are running in."""
    try:  # MCP bundle: staged at the root by build_bundle.stage_mcp
        from endpoint_registry import discover_endpoint_records  # type: ignore
    except ImportError:  # repo checkout / CI
        from deploy.endpoint_registry import discover_endpoint_records

    path = site_api_path()
    if source is not None:
        return discover_endpoint_records(source=source, path=path or None)
    if not path:
        return {}
    with open(path, encoding="utf-8") as fh:
        return discover_endpoint_records(source=fh.read(), path=path)


# ═══════════════════════════════════════════════════════════════════════════
# The exclusion registry — reader-only surfaces, each with a written reason
# ═══════════════════════════════════════════════════════════════════════════
# NOT a list of "everything the waiter refuses": write endpoints are excluded by
# DERIVATION (a POST-only route can never be a read), so this registry holds only the
# GET-able surfaces that answer a READER's question rather than a fact about Matthew.
# A stale entry (naming a path the router no longer has) fails the guard test, so this
# cannot rot into a list of ghosts.
READER_ONLY_SURFACES: dict[str, str] = {
    "/api/healthz": "Liveness probe for CloudFront and the monitoring stack. Carries no fact about Matthew.",
    "/api/sub_count": "Subscriber count rendered as social proof on the site. An audience metric, not a personal one.",
    "/api/verify_subscriber": "Verifies a website reader's subscription token. Reader identity, never owner data.",
    "/api/board_ask": (
        "The reader Q&A door. It is answered by a DIFFERENT Lambda (site_api_ai_lambda), so the in-process "
        "waiter physically cannot reach it — excluding it is honesty about reach, not a policy choice."
    ),
    "/api/ladder_counts": "Engagement-ladder rung counts across readers. An audience metric.",
    "/api/cohort_strip": "Anonymous reader cohort distribution behind a k-anonymity gate. Other people's numbers.",
    "/api/broadcast": "The public social feed of ingested human-origin posts. Other people's writing.",
    "/api/social_context": "Contextual social embeds for site pages. A rendering concern, not a fact.",
    "/api/predict_week": "Reader prediction-game tallies. Audience participation, not measurement.",
    "/api/experiment_library": "Reader-facing experiment catalog with vote counts. The owner's own experiments are on /api/experiments.",
    "/api/challenge_catalog": "Reader challenge catalog with vote counts.",
    "/api/current_challenge": "The reader-facing challenge card rendered on the site.",
    "/api/challenges": "Reader challenge list with follow counts.",
    "/api/experiment_detail": "Reader-facing experiment card with follow/vote counts.",
    "/api/ritual_log": (
        "The one-tap evening-ritual CAPTURE endpoint the site UI posts through. The owner logs a ritual with "
        "the capture tools; reading it back through here would be reaching for a write surface."
    ),
}

# Reasons the derivation itself produces (never hand-listed per path).
_WRITE_ONLY_REASON = "Write endpoint ({methods}) — the waiter is read-only by contract, so a mutating route is never indexed."


# ═══════════════════════════════════════════════════════════════════════════
# The annotation layer — optional decoration over a derived set
# ═══════════════════════════════════════════════════════════════════════════
# Each value: (question, example phrasing, [param specs]). ABSENCE IS FINE: an
# unannotated route still appears with a derived fallback question and
# `annotated: false`, which is what makes "a new route shows up without an edit here"
# structurally true rather than a promise.
SURFACE_NOTES: dict[str, tuple[str, str, list[dict]]] = {
    "/api/vitals": (
        "Where are the daily vitals right now — weight, HRV, resting HR, recovery, sleep?",
        "how are my vitals today?",
        [{"name": "date", "required": False, "description": "YYYY-MM-DD — the cockpit as it stood on a past morning."}],
    ),
    "/api/vitals_depth": ("What are the slower arc metrics — VO2max trend, walking heart rate, fitness age?", "is my VO2max moving?", []),
    "/api/journey": ("What is the weight trajectory and the projected goal date?", "how far through the weight journey am I?", []),
    "/api/habits": ("How are the habits going — which fired today, and what is the completion rate?", "how are my habits going?", []),
    "/api/habit_streaks": ("Which habit streaks are alive and how long are they?", "what streaks am I on?", []),
    "/api/habit_registry": ("Which habits are even being tracked, and in which group?", "what habits am I tracking?", []),
    "/api/vice_streaks": ("How long since each vice was last logged?", "how long clean?", []),
    "/api/receipts": ("What is the platform costing — the budget envelope, spend to date, and the tier?", "what is this costing me?", []),
    "/api/inference_receipt": ("What did the AI calls cost, broken down by feature and model?", "what did the AI spend go to?", []),
    "/api/ledger": ("What does the accountability ledger (the Snake Fund) hold?", "what's in the ledger?", []),
    "/api/hypotheses": ("What did I pre-register, and how is each hypothesis doing?", "what did I pre-register this cycle?", []),
    "/api/forecast": ("What does the model forecast next, and how were past forecasts graded?", "what's the forecast?", []),
    "/api/survival": (
        "How long have past cycles survived, and what does that imply for this one?",
        "how long do my cycles usually last?",
        [],
    ),
    "/api/cycle_compare": ("How does this cycle compare against the previous ones?", "how does this cycle compare to the last?", []),
    "/api/what_changed": ("What changed this month versus last?", "what changed this month?", []),
    "/api/changes-since": (
        "What is new since a given timestamp?",
        "what's changed since Tuesday?",
        [{"name": "ts", "required": False, "description": "ISO instant or YYYY-MM-DD to diff from."}],
    ),
    "/api/timeline": ("What is the experiment timeline of events?", "walk me through the timeline", []),
    "/api/recap": ("What is the 'previously on' cold-open for where the experiment stands?", "recap where I am", []),
    "/api/correlations": (
        "Which cross-domain correlations are currently supported by the data?",
        "what correlates with my sleep?",
        [
            {"name": "featured", "required": False, "description": "'true' for the featured set only."},
            {"name": "limit", "required": False, "description": "max rows."},
        ],
    ),
    "/api/sleep_correlations": ("What does sleep correlate with?", "what wrecks my sleep?", []),
    "/api/pillar_coupling": ("How strongly are the character pillars coupled to each other?", "which pillars move together?", []),
    "/api/state_of_matthew": ("What is the weekly model brief — the state of Matthew?", "what's the state of me?", []),
    "/api/observatory_week": (
        "What did one domain's week look like?",
        "how was my training week?",
        [{"name": "domain", "required": False, "description": "training | nutrition | sleep | mind | physical | glucose."}],
    ),
    "/api/source_freshness": ("Which data sources are fresh, stale, or paused — and how dark is each?", "is any of my data stale?", []),
    "/api/last_sync": ("When did each ingestion Lambda actually last write?", "when did Whoop last sync?", []),
    "/api/status": ("Is the platform healthy end to end?", "is everything running?", []),
    "/api/platform_stats": ("What are the platform's own numbers — records, sources, uptime?", "how big is the platform now?", []),
    "/api/presence": ("Am I actively logging, or have I gone quiet?", "have I gone quiet?", []),
    "/api/character": (
        "What does the character sheet say — pillar scores and level?",
        "what's my character sheet?",
        [{"name": "date", "required": False, "description": "YYYY-MM-DD — the sheet as of a past morning."}],
    ),
    "/api/character_stats": ("What are the raw character-engine stats?", "what are my pillar scores?", []),
    "/api/character_receipt": (
        "Show the progression receipt — why did the score move?",
        "why did my score change?",
        [
            {"name": "date", "required": False, "description": "YYYY-MM-DD."},
            {"name": "verify", "required": False, "description": "'1' replays the day against the live engine."},
        ],
    ),
    "/api/achievements": ("Which achievement badges are earned?", "what have I unlocked?", []),
    "/api/nutrition_overview": (
        "What do the last 30 days of nutrition look like — macros, protein adherence, eating window?",
        "how's my nutrition?",
        [],
    ),
    "/api/glucose": ("What is the CGM picture — time in range, mean glucose, variability?", "how's my glucose?", []),
    "/api/meal_glucose": ("Which meals spiked me, and by how much?", "which meals spike me?", []),
    "/api/training_overview": ("What does training look like — volume, load, frequency?", "how's my training?", []),
    "/api/workouts": ("Which workouts happened, and what was in them?", "what did I lift this week?", []),
    "/api/strength_benchmarks": ("Where do my lifts sit against the benchmarks?", "how strong am I?", []),
    "/api/labs": ("What do the bloodwork panels say?", "what did my last labs show?", []),
    "/api/phenoage": ("What is the transparent Levine PhenoAge computation?", "what's my phenotypic age?", []),
    "/api/physical_overview": ("What is the physical pillar's overview?", "how's my body doing?", []),
    "/api/mind_overview": ("What is the mind pillar's overview?", "how's my head?", []),
    "/api/reading_overview": ("What is the reading picture — pace, wheel, cockpit line?", "how's my reading going?", []),
    "/api/supplements": ("What is the supplement protocol and adherence?", "what am I supposed to be taking?", []),
    "/api/protocols": ("What protocols am I running?", "what protocols am I on?", []),
    "/api/methods": ("Which statistical method does each published number use?", "how is that number computed?", []),
    "/api/coaches": ("Who is on the coaching roster and what does each one own?", "who are my coaches?", []),
    "/api/panel_ledger": ("What has the coaching panel decided, and what happened to it?", "what did the panel decide?", []),
    "/api/predictions": (
        "What did the coaches predict, and how did those predictions land?",
        "what did the coaches predict?",
        [
            {"name": "status", "required": False, "description": "pending | correct | wrong."},
            {"name": "coach_id", "required": False, "description": "restrict to one coach."},
            {"name": "limit", "required": False, "description": "max rows."},
        ],
    ),
    "/api/wrong": ("Where has the platform been wrong on the record?", "what has the platform got wrong?", []),
    "/api/discoveries": ("What has actually been discovered — active hypotheses and AI findings?", "what have we found?", []),
}


# ═══════════════════════════════════════════════════════════════════════════
# Governing-rule derivation (the #3668 second-comment requirement)
# ═══════════════════════════════════════════════════════════════════════════
# Every DDB read in the web package goes through one of these helpers, and each takes an
# `include_pilot` keyword that defaults to False (the ADR-058 filter). So "did this
# surface hide the pilot rows?" is answerable by counting call sites — not by trusting a
# comment, and not by a per-surface literal somebody has to remember to update.
_PHASE_READER_FNS = frozenset(
    {
        "_query_source",
        "_latest_item",
        "_latest_item_asof",
        "query_source",
        "with_phase_filter",
        "_apply_phase_filter",
        "singleton_visible",
        "query_source_range",
    }
)

_PACIFIC_MARKERS = ("pacific_today", "pacific_now", "America/Los_Angeles", "PACIFIC", "PT)")
_UTC_MARKERS = ("utcnow", "timezone.utc", "datetime.UTC")
_PROVENANCE_MARKERS = ("ingested_at", "backfill", "captured_at", "imported_at", "is_backfill", "write_time")

PHASE_EXPERIMENT_ONLY = "experiment-only"
PHASE_INCLUDES_PILOT = "includes-pilot"
PHASE_MIXED = "mixed"
PHASE_UNDECLARED = "undeclared"

_PHASE_MEANING = {
    PHASE_EXPERIMENT_ONLY: (
        "Rows tagged phase=pilot are HIDDEN (ADR-058). Pre-genesis days and every wiped prior cycle are "
        "excluded on purpose. An empty answer here means 'excluded by a rule you asked for', NOT 'never recorded'."
    ),
    PHASE_INCLUDES_PILOT: (
        "Reads the partition UNFILTERED (include_pilot=True). Pre-genesis days and prior-cycle rows are INCLUDED, "
        "so this surface can legitimately report data on days an experiment-only surface reports as empty."
    ),
    PHASE_MIXED: (
        "Applies BOTH readings: some reads are experiment-only, some pass include_pilot=True. Compare a specific "
        "field against a single-rule surface before concluding two numbers disagree."
    ),
    PHASE_UNDECLARED: (
        "No phase-filtered read was found in this handler or its one-hop delegate. Either it does not touch the "
        "phase-tagged partitions, or it reads them through an indirection this analysis does not follow — treat "
        "the filter as UNKNOWN, never as 'unfiltered'."
    ),
}

UNFILTERED_VIA = (
    "The HTTP surfaces take no include_pilot parameter, so the unfiltered view is not reachable through this "
    "surface. Use the MCP tool `get_daily_snapshot` with include_pilot=true (a single day, every source) or "
    "`get_workouts` with include_pilot=true — those are the read paths that expose the switch."
)


@lru_cache(maxsize=64)
def _module_tree(dotted: str) -> Any:
    """Parse a ``web.site_api_x`` style module out of whichever tree we are in."""
    root = lambdas_root()
    if not root:
        return None
    rel = os.path.join(*dotted.split(".")) + ".py"
    path = os.path.join(root, rel)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return ast.parse(fh.read(), filename=path)
    except Exception:  # noqa: BLE001 — a rule we cannot derive is reported UNKNOWN, never guessed
        return None


def _alias_map(tree: Any) -> dict[str, str]:
    """``{local name: dotted module}`` for every ``from web import x as _x`` / ``from web.y import z``."""
    out: dict[str, str] = {}
    if tree is None:
        return out
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                local = alias.asname or alias.name
                if node.module == "web":
                    out[local] = f"web.{alias.name}"
                elif node.module.startswith("web."):
                    out[local] = node.module
    return out


def _func_node(tree: Any, name: str) -> Any:
    if tree is None:
        return None
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    return None


def _analyse(dotted: str, fname: str, depth: int, seen: set) -> dict:
    """Walk a handler (and, at depth>0, its same-package delegates) for rule markers."""
    acc: dict[str, Any] = {
        "filtered_reads": 0,
        "pilot_reads": 0,
        "pacific": False,
        "utc": False,
        "date_key": False,
        "provenance": False,
        "chain": [],
    }
    key = (dotted, fname)
    if key in seen or depth < 0:
        return acc
    seen.add(key)
    tree = _module_tree(dotted)
    fn = _func_node(tree, fname)
    if fn is None:
        return acc
    acc["chain"].append(f"{dotted}.{fname}")
    aliases = _alias_map(tree)

    try:
        seg = ast.unparse(fn)
    except Exception:  # noqa: BLE001 — py<3.9 or an odd node; markers just go unfound
        seg = ""
    if any(m in seg for m in _PACIFIC_MARKERS):
        acc["pacific"] = True
    if any(m in seg for m in _UTC_MARKERS):
        acc["utc"] = True
    if "DATE#" in seg:
        acc["date_key"] = True
    if any(m in seg for m in _PROVENANCE_MARKERS):
        acc["provenance"] = True

    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        fname_called = node.func.id if isinstance(node.func, ast.Name) else (node.func.attr if isinstance(node.func, ast.Attribute) else "")
        if fname_called in _PHASE_READER_FNS:
            pilot = any(kw.arg == "include_pilot" and isinstance(kw.value, ast.Constant) and kw.value.value is True for kw in node.keywords)
            acc["pilot_reads" if pilot else "filtered_reads"] += 1
        # One hop onward, two shapes:
        #   `_habits.habits(...)`  — the facade -> split-module delegate every /api door uses
        #   `_query_source(...)`   — a same-module helper (site_api_freshness's own reader,
        #                            which is where its include_pilot=True actually lives)
        if depth <= 0:
            continue
        target_mod = target_fn = None
        if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
            target_mod, target_fn = aliases.get(node.func.value.id), node.func.attr
        elif isinstance(node.func, ast.Name) and _func_node(tree, node.func.id) is not None:
            target_mod, target_fn = dotted, node.func.id
        if not target_mod:
            continue
        sub = _analyse(target_mod, target_fn, depth - 1, seen)
        acc["filtered_reads"] += sub["filtered_reads"]
        acc["pilot_reads"] += sub["pilot_reads"]
        acc["pacific"] = acc["pacific"] or sub["pacific"]
        acc["utc"] = acc["utc"] or sub["utc"]
        acc["date_key"] = acc["date_key"] or sub["date_key"]
        acc["provenance"] = acc["provenance"] or sub["provenance"]
        acc["chain"].extend(sub["chain"])
    return acc


def _handler_for(path: str, tree: Any) -> tuple[str, str] | None:
    """``(dotted module, function name)`` that answers ``path``, resolved from source."""
    if tree is None:
        return None
    imports = _alias_map(tree)
    name = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict):
            for target in node.targets:
                if not isinstance(target, ast.Name) or target.id not in ("ROUTES", "_SIMPLE_ROUTES"):
                    continue
                for k, v in zip(node.value.keys, node.value.values):
                    if not (isinstance(k, ast.Constant) and k.value == path):
                        continue
                    if target.id == "ROUTES" and isinstance(v, ast.Name):
                        name = v.id
                    elif (
                        target.id == "_SIMPLE_ROUTES" and isinstance(v, ast.Tuple) and len(v.elts) == 2 and isinstance(v.elts[1], ast.Name)
                    ):
                        name = v.elts[1].id
    if name is None:
        # inline `if path == "...": return handle_x(event)` inside _dispatch_route
        dispatch = _func_node(tree, "_dispatch_route")
        for node in ast.walk(dispatch) if dispatch is not None else []:
            if not isinstance(node, ast.If):
                continue
            test = ast.unparse(node.test) if hasattr(ast, "unparse") else ""
            # ast.unparse normalises to single quotes; match on the literal either way.
            if repr(path) not in test and f'"{path}"' not in test:
                continue
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name) and sub.func.id.lstrip("_").startswith("handle"):
                    name = sub.func.id
                    break
            if name:
                break
    if not name:
        return None
    return (imports.get(name, "web.site_api_lambda"), name)


def _rule_for(path: str, tree: Any) -> dict:
    """The governing-rule declaration for one surface — derived, never written down."""
    resolved = _handler_for(path, tree)
    if resolved is None:
        return {
            "phase_filter": PHASE_UNDECLARED,
            "phase_filter_meaning": _PHASE_MEANING[PHASE_UNDECLARED],
            "unfiltered_view": UNFILTERED_VIA,
            "date_basis": "undeclared",
            "row_provenance": "undeclared — this surface does not distinguish live capture from backfilled history",
            "derived_from": [],
        }
    dotted, fname = resolved
    a = _analyse(dotted, fname, depth=2, seen=set())
    if a["filtered_reads"] and a["pilot_reads"]:
        phase = PHASE_MIXED
    elif a["pilot_reads"]:
        phase = PHASE_INCLUDES_PILOT
    elif a["filtered_reads"]:
        phase = PHASE_EXPERIMENT_ONLY
    else:
        phase = PHASE_UNDECLARED

    if a["pacific"] and a["utc"]:
        basis = "mixed — both a Pacific calendar day and a UTC instant appear in this handler"
    elif a["pacific"]:
        basis = "Pacific calendar day (America/Los_Angeles) — the calendar every genesis is declared in"
    elif a["utc"]:
        basis = "UTC — note a UTC 'today' is already tomorrow after 17:00 PT, which is how a same-day row reads as missing"
    else:
        basis = "undeclared"
    if a["date_key"]:
        basis += "; rows are keyed on the DynamoDB sort key DATE#YYYY-MM-DD"

    return {
        "phase_filter": phase,
        "phase_filter_meaning": _PHASE_MEANING[phase],
        "unfiltered_view": UNFILTERED_VIA,
        "date_basis": basis,
        "row_provenance": (
            "declared — the handler reads a capture/ingest timestamp"
            if a["provenance"]
            else "undeclared — this surface does not distinguish live capture from backfilled history (a bulk import and a live day look identical)"
        ),
        "derived_from": a["chain"],
        "phase_read_counts": {"filtered": a["filtered_reads"], "include_pilot": a["pilot_reads"]},
    }


# ═══════════════════════════════════════════════════════════════════════════
# The index
# ═══════════════════════════════════════════════════════════════════════════


def surface_name(path: str) -> str:
    """``/api/nutrition_overview`` → ``nutrition_overview``; ``/api/coach/`` → ``coach``."""
    return path[len("/api/") :].strip("/").replace("/", ".") if path.startswith("/api/") else path.strip("/")


def _fallback_question(name: str) -> str:
    return f"(no note written yet) The platform's `{name}` surface — call it to see its shape."


def build_index(source: str | None = None) -> dict[str, dict]:
    """The derived index: ``{surface name: record}``, INCLUDING excluded surfaces.

    Excluded ones carry ``owner_relevant: False`` plus the reason, because "this exists
    and is deliberately not for you" is a different answer from "no such surface" — and
    telling them apart is the whole point of #3668.
    """
    records = _discover_records(source)
    tree = None
    path = site_api_path()
    if source is not None:
        try:
            tree = ast.parse(source)
        except Exception:  # noqa: BLE001
            tree = None
    elif path:
        try:
            with open(path, encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), filename=path)
        except Exception:  # noqa: BLE001
            tree = None

    index: dict[str, dict] = {}
    for p in sorted(records):
        rec = records[p]
        methods = sorted(rec.methods) if rec.methods else []
        name = surface_name(p)
        excluded = None
        if methods and "GET" not in methods and "OPTIONS" not in methods:
            excluded = _WRITE_ONLY_REASON.format(methods="/".join(methods))
        elif p in READER_ONLY_SURFACES:
            excluded = READER_ONLY_SURFACES[p]

        note = SURFACE_NOTES.get(p)
        question, example, params = note if note else (_fallback_question(name), "", [])
        entry = {
            "name": name,
            "path": p,
            "question": question,
            "example_phrasing": example,
            "params": params,
            "methods": methods or ["GET"],
            "mechanisms": sorted(rec.mechanisms),
            "is_prefix": bool(rec.is_prefix),
            "annotated": note is not None,
            "owner_relevant": excluded is None,
        }
        if excluded:
            entry["excluded_reason"] = excluded
        else:
            entry["rule"] = _rule_for(p, tree)
        index[name] = entry
    return index


@lru_cache(maxsize=1)
def cached_index() -> dict[str, dict]:
    """``build_index()`` memoised for the life of a warm container."""
    return build_index()


def reachable(index: dict[str, dict] | None = None) -> dict[str, dict]:
    """Only the surfaces the waiter will serve."""
    idx = index if index is not None else cached_index()
    return {k: v for k, v in idx.items() if v.get("owner_relevant")}


# ═══════════════════════════════════════════════════════════════════════════
# Reconciliation — two right answers that look like a contradiction
# ═══════════════════════════════════════════════════════════════════════════
def explain_discrepancy(name_a: str, name_b: str, index: dict[str, dict] | None = None) -> dict:
    """Why can these two surfaces disagree, and is that disagreement EXPLAINED?

    The nutrition specimen in prose: ``source_freshness`` says fresh through today and
    ``nutrition_overview`` says no data for three weeks. Both correct — one reads the
    partition with ``include_pilot=True`` and the other applies the ADR-058 filter. With
    both rules stated, that stops being a contradiction and becomes a sentence a caller
    can say out loud.

    ``differs_on == []`` is the load-bearing NEGATIVE: two surfaces under the SAME rule
    that disagree are a real disagreement, and this function says so instead of handing
    back a filter to blame it on.
    """
    idx = index if index is not None else cached_index()
    a, b = idx.get(name_a), idx.get(name_b)
    if a is None or b is None:
        return {"reconcilable": False, "error": f"unknown surface(s): {[n for n, s in ((name_a, a), (name_b, b)) if s is None]}"}
    rule_a, rule_b = a.get("rule") or {}, b.get("rule") or {}
    differs = [k for k in ("phase_filter", "date_basis", "row_provenance") if rule_a.get(k) != rule_b.get(k)]
    if differs:
        clauses = []
        for k in differs:
            clauses.append(f"{k}: `{name_a}` = {rule_a.get(k)!r}; `{name_b}` = {rule_b.get(k)!r}")
        explanation = (
            f"These two surfaces apply DIFFERENT rules ({', '.join(differs)}), so a numeric disagreement between "
            f"them is expected and explainable rather than a contradiction. " + " | ".join(clauses)
        )
    else:
        explanation = (
            f"`{name_a}` and `{name_b}` apply the SAME phase filter, date basis and provenance rule. A disagreement "
            "between them is a REAL disagreement — do not attribute it to a filter."
        )
    return {
        "surfaces": [name_a, name_b],
        "differs_on": differs,
        "reconcilable": True,
        "explanation": explanation,
        "rules": {name_a: rule_a, name_b: rule_b},
    }
