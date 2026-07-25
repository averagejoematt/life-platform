"""lambdas/web/site_api_protocols.py — protocol/experiment surface split out of
site_api_data.py (#1654): experiments / supplements / protocols / domains / routine.
Handlers read facade state via `_g` (see freshness)."""

import re
from datetime import datetime, timedelta, timezone

from boto3.dynamodb.conditions import Key
from phase_filter import with_phase_filter

from web.site_api_common import (
    PT,
    USER_ID,
    USER_PREFIX,
    _decimal_to_float,
    _load_s3_json,
    _load_supp_metadata,
    _ok,
    _scrub_blocked_terms,
    logger,
)


def _norm_ws(s):
    return re.sub(r"\s+", " ", str(s)).strip()


def _public_note(text):
    """#1569: screen a VERBATIM Matthew note for public serving.

    Runs the canonical runtime content filter (marijuana/porn etc. — the same term
    list the CI content-policy scan enforces). A verbatim quote is all-or-nothing:
    if the filter would alter it at all (a blocked term excised, or the refuse-whole
    sentinel), the note is withheld ENTIRELY rather than published as a mangled
    fragment. Empty/withheld → None, and an absent note renders NOTHING on the card
    (no nag state) — the honest-empty contract (AC3, #1569)."""
    if not text or not str(text).strip():
        return None
    raw = str(text).strip()
    scrubbed = _scrub_blocked_terms(raw)
    if not scrubbed or _norm_ws(scrubbed) != _norm_ws(raw):
        return None
    return scrubbed.strip()


# S3-config container caches for the protocols/domains passthroughs.
_protocols_cache = None
_domains_cache = None


_ROUTINE_HIDDEN_VARIANTS = ("floor", "re_entry")


def experiments(*, _g) -> dict:
    """
    GET /api/experiments
    Returns: list of experiments with status (no sensitive metric data).
    Cache: 3600s (1 hr).
    """
    # Facade state injected via `_g` (the delegator's globals()) — same module the test patched.
    _experiment_catalog = _g["_experiment_catalog"]
    table = _g["table"]
    pk = f"{USER_PREFIX}experiments"
    resp = table.query(
        **with_phase_filter(
            {  # ADR-058: hide pilot experiments
                "KeyConditionExpression": "pk = :pk",
                "ExpressionAttributeValues": {":pk": pk},
                "ScanIndexForward": False,
                "Limit": 50,
            }
        )
    )
    items = _decimal_to_float(resp.get("Items", []))

    datetime.now(timezone.utc).strftime("%Y-%m-%d")

    experiments = []
    for item in items:
        if not item.get("sk", "").startswith("EXP#"):
            continue
        start = item.get("start_date", "")
        end = item.get("end_date")
        status = item.get("status", "unknown")

        # Compute duration in days
        duration_days = None
        try:
            end_d = datetime.strptime(end, "%Y-%m-%d") if end else datetime.now(timezone.utc).replace(tzinfo=None)
            start_d = datetime.strptime(start, "%Y-%m-%d")
            duration_days = max(0, (end_d - start_d).days)
        except Exception:
            pass

        # Day number (for active experiments) — April 1 start = Day 1 on April 1, Day 2 on April 2, etc.
        days_in = None
        planned_duration = item.get("planned_duration_days")
        if status == "active" and start:
            try:
                days_in = (datetime.now(PT).date() - datetime.strptime(start, "%Y-%m-%d").date()).days + 1
            except Exception:
                pass

        # Progress pct for active
        progress_pct = None
        if status == "active" and days_in is not None and planned_duration:
            progress_pct = min(100, round(days_in / int(planned_duration) * 100))

        # #1569 the widened Third Wall: the OPTIONAL verbatim Matthew note ("why I
        # said yes, in his words"), content-filtered for public serving. Only added
        # to the payload when present + clean — an absent note is simply not a key,
        # so the card's honest-empty render (nothing) needs no null handling.
        matthew_note = _public_note(item.get("matthew_note"))

        experiments.append(
            {
                "id": item.get("sk", "").replace("EXP#", ""),
                "name": item.get("name", "Unnamed"),
                "status": status,
                "start_date": start,
                "end_date": end,
                # Substitute the {duration} template token (was leaking literally into the
                # rendered hypothesis: "...for {duration} days will reduce...").
                "hypothesis": (item.get("hypothesis", "") or "").replace("{duration}", str(planned_duration or duration_days or "several")),
                "tags": item.get("tags", []),
                # Phase 2 additions
                "outcome": item.get("outcome") or item.get("result_summary"),
                "result_summary": item.get("result_summary") or item.get("outcome"),
                "primary_metric": item.get("primary_metric"),
                "baseline_value": item.get("baseline_value"),
                "result_value": item.get("result_value"),
                "metrics_tracked": item.get("metrics_tracked", []),
                "planned_duration_days": planned_duration,
                "duration_days": duration_days,
                "days_in": days_in,
                "progress_pct": progress_pct,
                "confirmed": item.get("confirmed", False),
                "hypothesis_confirmed": item.get("hypothesis_confirmed"),
                # EXP-2: depth fields
                "mechanism": item.get("mechanism"),
                "key_finding": item.get("key_finding"),
                "protocol": item.get("protocol"),
                "evidence_tier": item.get("evidence_tier"),
                # EL-16+: Evolution fields for Record zone
                "grade": item.get("grade"),
                "compliance_pct": item.get("compliance_pct"),
                "reflection": item.get("reflection"),
                "library_id": item.get("library_id"),
                "duration_tier": item.get("duration_tier"),
                "experiment_type": item.get("experiment_type"),
                "iteration": item.get("iteration", 1),
                # #539: the frozen n-of-1 design + pre-registration stamp + the
                # deterministic close-path analysis (effect, CI, n's, verdict).
                "design": item.get("design"),
                "pre_registered_at": item.get("pre_registered_at"),
                # #1413 SCED: provenance of the randomized-start draw (window, k,
                # drawn_at) — the card can prove the start was drawn, not chosen.
                "start_draw": item.get("start_draw"),
                # #728: the public timestamped artifact frozen at creation —
                # the page renders this as the before-the-results proof link.
                "pre_registration_url": item.get("prereg_url"),
                "analysis": item.get("analysis"),
                # #1117: the justification contract — why now (with its provenance:
                # explicit | hypothesis | library), priority, hoped outcome, the
                # measurement plan, evidence links. Legacy/unannotated records simply
                # carry nulls and the page renders nothing (ADR-104 honest-empty).
                "why_now": item.get("why_now"),
                "why_now_source": item.get("why_now_source"),
                "priority": item.get("priority"),
                "hoped_outcome": item.get("hoped_outcome"),
                "measurement": item.get("measurement"),
                "evidence_links": item.get("evidence_links") or [],
                "origin": "live",  # an actual run on the ledger (this experiment cycle)
                # #1569: verbatim note (his words) beside the machine's read. Present
                # ONLY when written + clean; absent keys keep the default card shape.
                **({"matthew_note": matthew_note} if matthew_note else {}),
                **({"matthew_note_at": item.get("matthew_note_at")} if matthew_note and item.get("matthew_note_at") else {}),
            }
        )
    experiments.sort(key=lambda x: x["start_date"], reverse=True)

    # Overlay the experiment library (the catalog of what's planned / in flight).
    # Live runs take precedence; library entries already running are not duplicated.
    live_lib_ids = {x.get("library_id") for x in experiments if x.get("library_id")}
    live_names = {(x.get("name") or "").strip().lower() for x in experiments}
    experiments.extend(_experiment_catalog(live_lib_ids, live_names))

    return _ok({"experiments": experiments}, cache_seconds=3600)


def supplements(*, _g) -> dict:
    """
    GET /api/supplements
    Returns full supplement registry (groups, items, genome SNPs) from S3 config.
    Merges DynamoDB adherence data when available.
    Cache: 3600s (1 hr).
    """
    # Facade state injected via `_g` (the delegator's globals()) — same module the test patched.
    table = _g["table"]
    registry = _load_supp_metadata()
    if not registry or not registry.get("groups"):
        # Registry config unavailable — shaped-empty 200 rather than a console 503.
        return _ok(
            {"groups": {}, "total_count": 0, "genome_snps": [], "as_of_date": datetime.now(timezone.utc).strftime("%Y-%m-%d")},
            cache_seconds=300,
        )

    # Try to merge DynamoDB adherence data
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    pk = f"{USER_PREFIX}supplements"
    item = None
    for date in (today, yesterday):
        resp = table.get_item(Key={"pk": pk, "sk": f"DATE#{date}"})
        item = _decimal_to_float(resp.get("Item"))
        if item:
            break
    if not item:
        resp = table.query(
            KeyConditionExpression=Key("pk").eq(pk),
            ScanIndexForward=False,
            Limit=5,
        )
        items = _decimal_to_float(resp.get("Items", []))
        item = items[0] if items else None

    # Build adherence lookup from DynamoDB
    adherence_lookup = {}
    if item:
        for s in item.get("supplements", []):
            name = s.get("name", "").lower().replace(" ", "_").replace("-", "_")
            adherence_lookup[name] = s.get("adherence_pct")

    as_of_date = item.get("date", yesterday) if item else yesterday

    # Merge adherence into registry groups
    groups = registry.get("groups", {})
    total_count = 0
    for gkey, group in groups.items():
        for supp in group.get("items", []):
            total_count += 1
            adh = adherence_lookup.get(supp.get("key", ""))
            if adh is not None:
                supp["adherence_pct"] = adh

    return _ok(
        {
            "as_of_date": as_of_date,
            "groups": groups,
            "genome_snps": registry.get("genome_snps", []),
            "total_count": total_count,
        },
        cache_seconds=3600,
    )


def routine(*, _g) -> dict:
    """GET /api/routine — the current prescribed training block for the cockpit
    levers strip (#1066, the #974 follow-up).

    FAIL-CLOSED public projection over the ROUTINE# partition (the Hevy routine
    write-loop's system of record, ADR-066/067): the block name (current phase
    from the phase registry) + a prescription SUMMARY — archetype, exercise/set
    counts, target date. Built field-by-field; the stored IR is never spread.
    Deliberately NOT returned: the IR title (force_title can carry user-authored
    free text), notes (session cues + private notes), exercise names/loads/reps,
    rationale, inputs_snapshot (recovery/deficit internals), budget_used, and
    the Hevy ids. Read-only; always a shaped 200 — the cockpit self-hides when
    nothing is prescribed. Cache: 900s.
    """
    # Facade state injected via `_g` (the delegator's globals()) — same module the test patched.
    _load_phase_state = _g["_load_phase_state"]
    pre_start_meta = _g["pre_start_meta"]
    table = _g["table"]
    today = datetime.now(PT).strftime("%Y-%m-%d")

    # The current block — registry truth (what phase we're IN), like the stack.
    state = _load_phase_state() or {}
    phase = state.get("current") or ((state.get("phases") or [None])[0])
    block = {"phase": phase, "phase_started": state.get("current_started")} if phase else None

    # Newest index rows first (sk = DATE#<target_date>#ROUTINE#<id>).
    rows = []
    try:
        resp = table.query(
            KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}routine_index"),
            ScanIndexForward=False,
            Limit=16,
        )
        rows = _decimal_to_float(resp.get("Items", []))
    except Exception as e:
        logger.warning("handle_routine index read failed: %s", e)

    rows = [
        r
        for r in rows
        if r.get("routine_id") and (r.get("variant") or "") not in _ROUTINE_HIDDEN_VARIANTS and (r.get("status") or "") != "archived"
    ]
    # Prefer the newest prescription on/before today; else the nearest upcoming
    # one (a session staged for tomorrow / Day 1 is honestly "prescribed") —
    # rows are newest-first, so the last remaining row is the nearest future date.
    current = next((r for r in rows if str(r.get("target_date") or "") <= today), None)
    if current is None and rows:
        current = rows[-1]

    routine = None
    if current:
        ir: dict = {}
        try:
            resp = table.get_item(
                Key={"pk": f"USER#{USER_ID}#ROUTINE#{current['routine_id']}", "sk": "VERSION#current"},
                ProjectionExpression="target_date, archetype, variant, #st, exercises, branches, hevy_pushed_at",
                ExpressionAttributeNames={"#st": "status"},
            )
            ir = _decimal_to_float(resp.get("Item")) or {}
        except Exception as e:
            logger.warning("handle_routine IR read failed: %s", e)
        src = ir or current
        # Counts come from the recommended branch's own exercise list when one
        # exists (that is what the pushed Hevy routine actually shows, #417 2b),
        # else the routine-level list. Unknown (IR read failed) → honest nulls.
        exercises = None
        if ir:
            for b in ir.get("branches") or []:
                if b.get("recommended") and b.get("exercises"):
                    exercises = b["exercises"]
                    break
            if exercises is None:
                exercises = ir.get("exercises") or []
        target = str(src.get("target_date") or "")
        try:
            # NB: datetime.strptime (not a module-level `date` import) — two
            # handlers in this module use `date` as a loop variable (F402).
            days_out = (datetime.strptime(target, "%Y-%m-%d") - datetime.strptime(today, "%Y-%m-%d")).days
        except ValueError:
            days_out = None
        routine = {
            "target_date": target or None,
            "archetype": src.get("archetype"),
            "variant": src.get("variant"),
            "status": src.get("status"),
            "days_out": days_out,
            "exercise_count": len(exercises) if exercises is not None else None,
            "total_sets": sum(len(e.get("sets") or []) for e in exercises) if exercises is not None else None,
            "pushed": bool(ir.get("hevy_pushed_at")),
        }

    data = {"available": routine is not None, "as_of_date": today, "block": block, "routine": routine}
    _pre = pre_start_meta()
    data["pre_start"] = bool(_pre)
    if _pre:
        data.update(_pre)
    return _ok(data, cache_seconds=900)


def protocols(*, _g) -> dict:
    """GET /api/protocols — Return protocol definitions from DynamoDB."""
    # Facade state injected via `_g` (the delegator's globals()) — same module the test patched.
    table = _g["table"]
    protocols_pk = f"{USER_PREFIX}protocols"
    try:
        resp = table.query(
            **with_phase_filter(
                {  # ADR-058: hide pilot protocols
                    "KeyConditionExpression": Key("pk").eq(protocols_pk) & Key("sk").begins_with("PROTOCOL#"),
                    "ScanIndexForward": True,
                }
            )
        )
        protocols = []
        for item in _decimal_to_float(resp.get("Items", [])):
            item.pop("pk", None)
            item.pop("sk", None)
            protocols.append(item)
        return _ok({"protocols": protocols, "count": len(protocols)}, cache_seconds=3600)
    except Exception as e:
        logger.warning("handle_protocols: DynamoDB query failed, falling back to S3: %s", e)
        global _protocols_cache
        if _protocols_cache is None:
            _protocols_cache = _load_s3_json("site/config/protocols.json", "protocols")
        protocols = _protocols_cache.get("protocols", [])
        return _ok({"protocols": protocols, "count": len(protocols)}, cache_seconds=3600)


def domains() -> dict:
    """GET /api/domains — Return domain groupings from S3 config."""
    global _domains_cache
    if _domains_cache is None:
        _domains_cache = _load_s3_json("site/config/domains.json", "domains")
    domains = _domains_cache.get("domains", [])
    return _ok({"domains": domains, "count": len(domains)}, cache_seconds=3600)
