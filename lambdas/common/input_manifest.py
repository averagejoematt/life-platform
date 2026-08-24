"""input_manifest.py — the source-completeness contract for compute (#3049, DIL-024).

THE DEFECT THIS CLOSES
----------------------
The five compute Lambdas run at fixed UTC minutes (ADR-052 ordering), with the
ordering held only by a wall-clock comment in ``cdk/stacks/compute_stack.py``
("Was reading yesterday's sheet"). None of them gates on upstream arrival, and
none of them recorded — anywhere, per run — WHICH of its inputs were actually
current when it ran. A connector that arrives late therefore produces an
*unqualified* "complete" day score, and the only detection is the post-hoc
``ComputeOutputsMissing`` alarm, which fires on a missing OUTPUT and is blind to
a present output built on absent INPUT.

This module is the contract primitive (kin to epic #2842) for that gap: every
compute run stamps its output with a per-input freshness manifest, and an output
whose inputs were stale or missing publishes ``input_status = "partial"`` instead
of passing as complete (ADR-104 — honest numbers everywhere).

SCOPE GUARD (issue #3049, explicit): **no event-driven rebuild.** The crons stay
exactly as they are. The manifest makes the blindness VISIBLE; it does not
reschedule anything, does not gate a run, and never suppresses a write.

FOUR RULES THIS MODULE HOLDS
----------------------------
1. **Thresholds are DERIVED, never hand-stated** (#2003 class). ``stale_hours``
   comes from ``ingestion.source_registry`` — the same facet the freshness
   checker, MCP ``get_freshness_status`` and ``ingestion.source_state`` read. A
   source's cadence is stated in exactly one place in this repo and this is not
   it. If the registry cannot be read, the verdict is ``unknown`` — there is no
   fallback constant here to drift out of sync.
2. **The frame is Pacific** (#2506/#2675/#2813 class). Age is measured from the
   START of the latest covered Pacific day to now, with aware-datetime
   arithmetic, so the two US DST transitions produce 23h/25h days rather than a
   naive ``days * 24``. ``build_input_manifest``/``manifest_for`` are registered
   with the ``pt_day_contract`` sweep so their day defaults are proven Pacific.
3. **Freshness wins, and paused is off-by-design.** Precedence mirrors
   ``ingestion.source_state.resolve_source_state``: fresh data means ``fresh``
   whatever the registry declares, and a registry-``paused`` source that is not
   fresh reads ``paused`` — never ``stale`` — so Garmin's ADR-074 pause can
   never qualify an output.
4. **Fail-closed to ``unknown``, never to ``fresh``.** An unreadable partition,
   an unparseable date or an unreadable registry yields ``unknown``, and a
   manifest containing any ``unknown`` is NOT ``complete``. Nothing in here can
   turn "I could not look" into "everything was fine" — the mistake
   ``lambdas/health/pillar_absence.py`` already refuses to make.

VOCABULARY (deliberately the one already in this codebase, not a new one)
------------------------------------------------------------------------
Per source: ``fresh`` / ``stale`` / ``missing`` / ``paused`` / ``unknown`` —
the ``site_api_freshness`` + MCP ``tools_labs`` row vocabulary, plus ``missing``
for "no row on the partition at all" (MCP's ``no_data``, named as #3049 names it).
Roll-up: ``complete`` / ``partial`` / ``unknown``.

WHAT LANDS ON THE RECORD
------------------------
``attach_input_manifest`` stamps two fields on the output item::

    item["input_manifest"] = {...}   # the full per-source detail
    item["input_status"]   = "complete" | "partial" | "unknown"

``input_status`` is flattened deliberately: the daily brief and the site API ask
only "was this day qualified?", and making them unpack a nested dict to find out
is how a consumer ends up not asking.

WHERE IT IS STAMPED — ONE CHOKEPOINT, NOT FIVE CALL SITES
----------------------------------------------------------
``common.compute_metadata.tag_record`` is already the single place every compute
output passes through immediately before ``put_item`` — it is what stamps
``run_id``, ``computed_at`` and ADR-058's ``phase``. The input manifest is the
same kind of write-time provenance, so it is stamped there, via ``stamp_output``,
and the five Lambdas need no per-call-site plumbing at all. Two consequences
worth stating plainly:

* ``MANIFEST_OUTPUTS`` below is the allowlist. Only the declared compute output
  partitions are stamped — the receipts, achievement, milestone and
  platform_memory rows those same Lambdas also write are not, because they are
  not the day's claim.
* The manifest is built ONCE per (compute Lambda, Pacific day) and reused across
  every output of that run, so ``computed_metrics`` / ``day_grade`` /
  ``habit_scores`` can never carry three different answers to the same question.

**Nothing here runs outside Lambda.** ``current_run_manifest`` returns None when
``AWS_LAMBDA_FUNCTION_NAME`` is unset and no table was injected, so a unit test
that calls ``tag_record`` cannot be turned into a DynamoDB round trip by this
module. Tests exercise the real path by injecting a ``table=``.
"""

import os
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Iterable, Optional, Tuple

from common.pacific_time import PACIFIC, pacific_now, pacific_today

# ── Per-source verdicts ───────────────────────────────────────────────────────
STATUS_FRESH = "fresh"
STATUS_STALE = "stale"
STATUS_MISSING = "missing"
STATUS_PAUSED = "paused"
STATUS_UNKNOWN = "unknown"

#: The verdicts that qualify an output. ``paused`` is NOT here (off by design,
#: ADR-074) and neither is ``unknown`` (it downgrades the roll-up separately —
#: "I could not look" is not the same claim as "it was late").
DEGRADING_STATUSES = frozenset({STATUS_STALE, STATUS_MISSING})

# ── Roll-up verdicts ──────────────────────────────────────────────────────────
MANIFEST_COMPLETE = "complete"
MANIFEST_PARTIAL = "partial"
MANIFEST_UNKNOWN = "unknown"

# ══════════════════════════════════════════════════════════════════════════════
# The declarations — which upstream sources each compute Lambda actually reads
# ══════════════════════════════════════════════════════════════════════════════
#
# Keyed by the CDK ``function_name`` in ``cdk/stacks/compute_stack.py`` so a
# rename there cannot silently orphan a manifest —
# ``tests/test_input_manifest_contract_3049.py`` resolves every key against that
# file. Values are ``source_registry`` ids: this is a statement about what a
# Lambda READS, not about any source's cadence (see rule 1 — the cadence is the
# registry's to state, and this module never restates one).
#
# DERIVED partitions are deliberately absent. ``computed_metrics``,
# ``habit_scores``, ``day_grade``, ``engagement_state``, ``platform_memory``,
# ``character_sheet`` and friends are compute OUTPUTS, not connectors: they carry
# their own ``input_status`` once this ships, they have no registry cadence to
# judge against, and inventing a second threshold table for them here is exactly
# the drift #2003 is about. Chaining an upstream ``partial`` through a downstream
# manifest is a real follow-on, and it is a follow-on — not this issue.
#
# Only the five Lambdas #3049 names are in scope. The other compute Lambdas in
# ``compute_stack.py`` (forecast-engine, scenario-explorer, episode-detect,
# anomaly-detector, weekly-correlation, personal-baselines, the coach jobs) are
# out of scope by the issue text; extending the map is one tuple each.
COMPUTE_INPUTS: Dict[str, Tuple[str, ...]] = {
    "character-sheet-compute": (
        "apple_health",
        "food_delivery",
        "habitify",
        "hevy",
        "macrofactor",
        "notion",
        "strava",
        "todoist",
        "whoop",
        "withings",
    ),
    "adaptive-mode-compute": (
        "apple_health",
        "eightsleep",
        "macrofactor",
        "notion",
        "whoop",
        "withings",
    ),
    "daily-metrics-compute": (
        "apple_health",
        "habitify",
        "hevy",
        "macrofactor",
        "notion",
        "strava",
        "whoop",
        "withings",
    ),
    "daily-insight-compute": (
        "apple_health",
        "eightsleep",
        "macrofactor",
        "notion",
        "strava",
        "supplements",
        "todoist",
        "whoop",
        "withings",
    ),
    "hypothesis-engine": (
        "apple_health",
        "eightsleep",
        "garmin",
        "habitify",
        "macrofactor",
        "notion",
        "strava",
        "whoop",
        "withings",
    ),
}

#: Which compute OUTPUT partitions carry the stamp, and whose declaration judges
#: them. Keyed by the ``source_id`` every writer already passes to
#: ``compute_metadata.tag_record``, so the allowlist is expressed in the
#: vocabulary the chokepoint already speaks.
#:
#: An allowlist rather than "stamp everything this Lambda writes" on purpose: the
#: same invocations also write progression receipts, achievement first-earns,
#: milestone ledger rows and platform_memory entries. Those are side records, not
#: the day's claim, and stamping them would put a 1-2 KB manifest on partitions
#: nobody would ever read it from.
MANIFEST_OUTPUTS: Dict[str, str] = {
    "character_sheet": "character-sheet-compute",
    "adaptive_mode": "adaptive-mode-compute",
    "engagement_state": "adaptive-mode-compute",
    "computed_metrics": "daily-metrics-compute",
    "day_grade": "daily-metrics-compute",
    "habit_scores": "daily-metrics-compute",
    "computed_insights": "daily-insight-compute",
    "hypotheses": "hypothesis-engine",
}


# ══════════════════════════════════════════════════════════════════════════════
# Registry reads — fail-soft, and fail-soft ALWAYS lands on `unknown`
# ══════════════════════════════════════════════════════════════════════════════


def stale_after_hours(source: str) -> Optional[int]:
    """The registry's staleness threshold for one source, in hours.

    ``None`` means "cannot judge" — an unknown source id, or a registry this
    bundle cannot import. It is never a number: a hardcoded fallback here would
    be a second cadence statement, and the whole point of reading the registry is
    that there is only one (#2003). Callers turn ``None`` into ``unknown``.
    """
    try:
        from ingestion.source_registry import DEFAULT_STALE_HOURS, SOURCE_REGISTRY
    except Exception:  # noqa: BLE001 — an unreadable registry must not decide a source is fine
        return None
    entry = SOURCE_REGISTRY.get(source)
    if entry is None:
        return None
    override = entry.get("stale_hours")
    try:
        return int(override if override is not None else DEFAULT_STALE_HOURS)
    except (TypeError, ValueError):
        return None


def _paused(source: str) -> bool:
    """Whether the source is intentionally off (ADR-074 Garmin, registry facet).

    Delegates to ``ingestion.source_state.is_paused`` rather than re-reading the
    facet, so the pause declaration stays in one place (#2715's lesson: two
    halves of the same fact that never met)."""
    try:
        from ingestion.source_state import is_paused

        return bool(is_paused(source))
    except Exception:  # noqa: BLE001 — never let this read invent a pause
        return False


# ══════════════════════════════════════════════════════════════════════════════
# The judgment — pure, and Pacific
# ══════════════════════════════════════════════════════════════════════════════


def pacific_day_start(day_iso: str) -> datetime:
    """Aware datetime at 00:00 of a Pacific calendar day.

    ``PACIFIC`` is imported from ``common.pacific_time`` rather than constructed
    here — ``tests/test_time_invariant_helpers_1964.py`` forbids a second
    ``ZoneInfo("America/Los_Angeles")`` anywhere in ``lambdas/``.
    """
    d = date.fromisoformat(str(day_iso)[:10])
    return datetime(d.year, d.month, d.day, tzinfo=PACIFIC)


def age_hours(latest_day: str, now: datetime) -> float:
    """Real elapsed hours from the start of ``latest_day`` (Pacific) to ``now``.

    Why not ``(today - latest).days * 24``: a US DST transition makes a Pacific
    calendar day 23 or 25 hours long, so the naive form disagrees with reality by
    an hour for every window spanning the second Sunday in March or the first
    Sunday in November. That is a one-hour error on a threshold measured in
    hours — enough to flip a verdict, twice a year, silently. Both directions are
    pinned in ``tests/test_input_manifest_contract_3049.py``.

    **Both operands are normalised to UTC before subtracting, and that is
    load-bearing.** Python's ``datetime.__sub__`` documents that when both
    operands are aware AND share the same ``tzinfo`` object it *ignores* the
    tzinfo and subtracts the wall-clock fields — which is exactly the shape here
    (both sides carry the one ``PACIFIC`` singleton), so the obvious
    ``now.astimezone(PACIFIC) - pacific_day_start(day)`` silently returns the
    NAIVE answer and reintroduces the very bug this function exists to avoid.
    The first draft of this module had that form; the DST tests caught it.
    """
    return (now.astimezone(timezone.utc) - pacific_day_start(latest_day).astimezone(timezone.utc)).total_seconds() / 3600.0


def judge_source(
    latest_day: Optional[str],
    *,
    now: datetime,
    threshold_hours: Optional[int],
    paused: bool = False,
) -> Tuple[str, Optional[float]]:
    """``(status, age_hours|None)`` for ONE input source. Pure — no I/O, no clock.

    Precedence mirrors ``ingestion.source_state``: freshness wins outright, so
    re-enabling a paused source flips it to ``fresh`` the moment data flows, with
    no second edit anywhere.
    """
    if threshold_hours is None:
        return STATUS_UNKNOWN, None
    if not latest_day:
        return (STATUS_PAUSED if paused else STATUS_MISSING), None
    try:
        age = age_hours(latest_day, now)
    except (ValueError, TypeError):
        return STATUS_UNKNOWN, None
    if age < threshold_hours:
        return STATUS_FRESH, age
    return (STATUS_PAUSED if paused else STATUS_STALE), age


def latest_source_day(table: Any, source: str, *, user_id: str) -> Optional[str]:
    """Newest ``DATE#`` day present on a source partition, or ``None``.

    Deliberately CROSS-PHASE (no ``with_phase_filter``): "is this connector
    current?" is a question about the pipe, not about the experiment generation,
    and a newest-first ``Limit: 1`` read with the phase filter attached goes blind
    after every reset — the #2080 lesson the freshness checker already learned.

    Raises whatever the table raises; ``build_input_manifest`` turns a read
    failure into ``unknown``.
    """
    from boto3.dynamodb.conditions import Key

    resp = table.query(
        KeyConditionExpression=Key("pk").eq(f"USER#{user_id}#SOURCE#{source}") & Key("sk").begins_with("DATE#"),
        ScanIndexForward=False,
        Limit=1,
        ProjectionExpression="sk",
    )
    items = resp.get("Items") or []
    if not items:
        return None
    sk = str(items[0].get("sk") or "")
    return sk[5:15] if sk.startswith("DATE#") else None


# ══════════════════════════════════════════════════════════════════════════════
# The manifest
# ══════════════════════════════════════════════════════════════════════════════


def build_input_manifest(
    sources: Iterable[str],
    *,
    table: Any = None,
    user_id: Optional[str] = None,
    today_iso: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Judge every declared input and roll it up into one DDB-safe manifest.

    ``today_iso`` is the Pacific day the manifest is stamped as-of; it defaults
    to ``pacific_today()`` and is swept by ``tests/test_pt_day_contract_sweep_2813.py``.
    ``now`` defaults to ``pacific_now()`` and exists so tests can freeze the clock
    without patching a module global.

    ``table=None`` is a real, honest state, not a test hook: with no table there
    is nothing to observe, so every source reads ``unknown`` and the roll-up
    refuses to say ``complete``.

    Numbers are ``Decimal`` on the way out — boto3 rejects ``float`` and this dict
    is written straight into DynamoDB by four of the five callers.
    """
    now = now or pacific_now()
    as_of_day = today_iso or pacific_today()
    user_id = user_id or os.environ.get("USER_ID", "matthew")

    rows: Dict[str, Dict[str, Any]] = {}
    for source in sorted(set(sources)):
        threshold = stale_after_hours(source)
        row: Dict[str, Any] = {
            "status": STATUS_UNKNOWN,
            "latest_day": None,
            "age_hours": None,
            "stale_after_hours": threshold,
        }
        if table is None:
            row["reason"] = "no table handle — inputs unobserved this run"
            rows[source] = row
            continue
        try:
            latest = latest_source_day(table, source, user_id=user_id)
        except Exception as exc:  # noqa: BLE001 — an unreadable partition is `unknown`, never `fresh`
            row["reason"] = f"input partition unreadable: {type(exc).__name__}"
            rows[source] = row
            continue
        status, age = judge_source(latest, now=now, threshold_hours=threshold, paused=_paused(source))
        row["status"] = status
        row["latest_day"] = latest
        row["age_hours"] = None if age is None else Decimal(str(round(age, 2)))
        if threshold is None:
            row["reason"] = f"no registry cadence for '{source}' — cannot judge"
        rows[source] = row

    degraded = sorted(s for s, r in rows.items() if r["status"] in DEGRADING_STATUSES)
    unobserved = sorted(s for s, r in rows.items() if r["status"] == STATUS_UNKNOWN)

    if degraded:
        status = MANIFEST_PARTIAL
    elif unobserved or not rows:
        # An empty declaration is not a clean bill of health — it is a Lambda
        # whose inputs nobody declared. Same verdict as "could not look".
        status = MANIFEST_UNKNOWN
    else:
        status = MANIFEST_COMPLETE

    return {
        "as_of_day": as_of_day,
        "judged_at": now.astimezone(timezone.utc).isoformat(),
        "status": status,
        "complete": status == MANIFEST_COMPLETE,
        "degraded": degraded,
        "unobserved": unobserved,
        "input_count": len(rows),
        "sources": rows,
        "contract": "input-manifest-v1",
    }


def manifest_for(
    compute_id: str,
    *,
    table: Any = None,
    user_id: Optional[str] = None,
    today_iso: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """``build_input_manifest`` over one compute Lambda's declared inputs.

    ``compute_id`` is the CDK ``function_name``. An id with no declaration yields
    an ``unknown`` manifest rather than a silent ``complete`` — see the empty-map
    branch above.
    """
    return build_input_manifest(
        COMPUTE_INPUTS.get(compute_id, ()),
        table=table,
        user_id=user_id,
        today_iso=today_iso,
        now=now,
    )


def attach_input_manifest(item: Dict[str, Any], manifest: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Stamp a compute output record with its manifest. Returns the same dict.

    A falsy manifest is a no-op so every call site can pass ``input_manifest=None``
    on a path that could not build one (backfills, the sick-day freeze) without a
    branch — an ABSENT ``input_status`` reads as "this record predates the
    contract", which is a different and equally honest claim from ``unknown``.
    """
    if not manifest:
        return item
    item["input_manifest"] = manifest
    item["input_status"] = manifest.get("status") or MANIFEST_UNKNOWN
    return item


# ══════════════════════════════════════════════════════════════════════════════
# The write chokepoint — one manifest per run, stamped by compute_metadata
# ══════════════════════════════════════════════════════════════════════════════

#: ``{(compute_id, pacific_day): manifest_or_None}`` for the life of a warm
#: container. Keyed by the DAY as well as the Lambda so a container that survives
#: midnight cannot serve yesterday's judgment as today's — the failure mode a
#: bare per-invocation cache (``compute_metadata._RUN_ID``) already has, and one
#: this module must not inherit, because unlike a run_id the manifest is a claim
#: about the world.
_RUN_MANIFESTS: Dict[Any, Optional[Dict[str, Any]]] = {}

_AMBIENT_TABLE: Any = None


def _ambient_table() -> Any:
    """The Lambda's own table handle, built lazily. ``None`` if unavailable.

    Only ever reached from inside a Lambda (``current_run_manifest`` checks
    ``AWS_LAMBDA_FUNCTION_NAME`` first), so this cannot fire during a unit test.
    """
    global _AMBIENT_TABLE
    if _AMBIENT_TABLE is None:
        try:
            import boto3

            _AMBIENT_TABLE = boto3.resource("dynamodb", region_name=os.environ.get("AWS_REGION", "us-west-2")).Table(
                os.environ.get("TABLE_NAME", "life-platform")
            )
        except Exception:  # noqa: BLE001 — no table means no manifest, never a broken write
            return None
    return _AMBIENT_TABLE


def reset_run_manifests() -> None:
    """Drop the per-container cache. For tests and for an explicit re-judge."""
    _RUN_MANIFESTS.clear()


def current_run_manifest(compute_id: str, *, table: Any = None) -> Optional[Dict[str, Any]]:
    """This run's manifest for one compute Lambda, built at most once per PT day.

    Returns ``None`` — meaning "do not stamp anything" — when there is no table
    to observe with. That is the case for every unit test and every local script:
    an unstamped record honestly reads as "predates/outside the contract", which
    is a better outcome than a synthesized verdict or an import-time boto3 call.
    """
    injected = table is not None
    if not injected:
        if not os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
            return None
        table = _ambient_table()
        if table is None:
            return None
    key = (compute_id, pacific_today())
    if not injected and key in _RUN_MANIFESTS:
        return _RUN_MANIFESTS[key]
    try:
        manifest = manifest_for(compute_id, table=table)
    except Exception:  # noqa: BLE001 — observability must never block a compute write
        manifest = None
    if not injected:
        _RUN_MANIFESTS[key] = manifest
    return manifest


def stamp_output(record: Dict[str, Any], source_id: str, *, table: Any = None) -> Dict[str, Any]:
    """Stamp a compute output with its run's input manifest, if it carries one.

    Called from ``compute_metadata.tag_record``. A ``source_id`` outside
    ``MANIFEST_OUTPUTS`` is a no-op, so every other writer that shares that
    chokepoint (ingestion, receipts, ledgers) is completely unaffected.
    """
    compute_id = MANIFEST_OUTPUTS.get(source_id)
    if not compute_id:
        return record
    return attach_input_manifest(record, current_run_manifest(compute_id, table=table))


def manifest_note(manifest: Optional[Dict[str, Any]]) -> Optional[str]:
    """One honest sentence for a reader surface, or ``None`` when there is nothing to say.

    Lives here so the daily brief and the site API cannot describe the same
    manifest two different ways (the #1955/#2898 one-claim-one-source discipline).
    """
    if not manifest:
        return None
    status = manifest.get("status")
    if status == MANIFEST_PARTIAL:
        names = ", ".join(manifest.get("degraded") or []) or "one or more inputs"
        return f"Computed on partial input — {names} was stale or missing when this ran, " "so today's numbers are qualified, not complete."
    if status == MANIFEST_UNKNOWN:
        names = ", ".join(manifest.get("unobserved") or []) or "one or more inputs"
        return (
            f"Input completeness unverified — {names} could not be read when this ran. "
            "Absence of evidence, not evidence of a complete day."
        )
    return None


# ── #2813 PT-day contract registration ────────────────────────────────────────
# Both public entry points resolve a "what day is it" default, which is the exact
# shape every production timezone escape since #2506 has worn. Registered on the
# REAL functions (never a test-only shadow) so the standing sweep drives their own
# defaults at a PT-evening instant. Wrapped fail-soft, mirroring
# `ai/grounding_gate_params.py`: registration must never be what breaks an import.
try:  # pragma: no cover — registration side effect only
    from common.pt_day_contract import pt_day_contract as _pt_day_contract

    build_input_manifest = _pt_day_contract(extract=lambda m: m["as_of_day"], args=((),))(build_input_manifest)
    manifest_for = _pt_day_contract(extract=lambda m: m["as_of_day"], args=("daily-metrics-compute",))(manifest_for)
except Exception:  # noqa: BLE001
    pass
