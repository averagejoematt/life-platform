"""lambdas/web/site_api_protocols.py — protocol/experiment surface split out of
site_api_data.py (#1654): experiments / supplements / protocols / domains / routine.
Handlers read facade state via `_g` (see freshness)."""

import hashlib
import re
from datetime import datetime, timedelta, timezone

from boto3.dynamodb.conditions import Key
from experiment.phase_filter import with_phase_filter

from web.site_api_common import (
    PT,
    USER_ID,
    USER_PREFIX,
    _decimal_to_float,
    _is_blocked_vice,
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

    Runs the canonical runtime content filter (the channel-derived blocked-term
    list — the same vocabulary the CI content-policy scan enforces). A verbatim quote is all-or-nothing:
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

    datetime.now(PT).strftime("%Y-%m-%d")

    experiments = []
    for item in items:
        if not item.get("sk", "").startswith("EXP#"):
            continue
        # #2240: /api/experiments publishes live run names and ids — same
        # never-public-vocabulary screen the challenge routes apply (name AND id).
        if _is_blocked_vice(item.get("name", "") or "") or _is_blocked_vice(item.get("sk", "").replace("EXP#", "")):
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
            {"groups": {}, "total_count": 0, "genome_snps": [], "as_of_date": datetime.now(PT).strftime("%Y-%m-%d")},
            cache_seconds=300,
        )

    # Try to merge DynamoDB adherence data
    today = datetime.now(PT).strftime("%Y-%m-%d")
    yesterday = (datetime.now(PT) - timedelta(days=1)).strftime("%Y-%m-%d")
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
    the Hevy ids; the platform routine id leaves only as `routine_ref` (a 12-hex
    digest — the same one /api/session serves for the same pick, #4338).
    Today's routine is `pick_todays_routine`'s pick — the SAME session
    /api/session names. Read-only; always a shaped 200 — the cockpit self-hides when
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

    # ONE pick of today's routine, shared with /api/session (#4338) — the two routes name the same session.
    pick = pick_todays_routine(table, today, lambda: _program_next(today))
    current = None
    ir: dict = {}
    if pick["ir"] is not None:
        current, ir = {"routine_id": pick["routine_id"]}, pick["ir"]
    else:
        # Nothing picked for today: the newest prescription on/before today, else the nearest upcoming one
        # (a session staged for tomorrow / Day 1 is honestly "prescribed") — rows are newest-first, so the
        # last remaining row is the nearest future date. Today's rows the picker READ and passed over are
        # never named here: /api/session serves the program for them, and this route must not name a
        # draft that one declined (#4338). A row whose IR was unreadable stays eligible — index truth.
        rows = [r for r in pick["rows"] if str(r["routine_id"]) not in pick["declined"]]
        current = next((r for r in rows if str(r.get("target_date") or "") <= today), None)
        if current is None and rows:
            current = rows[-1]
        if current:
            ir = _read_routine_ir(table, str(current["routine_id"]))

    routine = None
    if current:
        src = ir or current
        # Counts come from the recommended branch's own exercise list when one
        # exists (that is what the pushed Hevy routine actually shows, #417 2b),
        # else the routine-level list. Unknown (IR read failed) → honest nulls.
        exercises = _routine_exercises(ir) if ir else None
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
            # the same public handle /api/session serves for the same pick — agreement is checkable (#4338)
            "routine_ref": routine_ref(current.get("routine_id")),
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
        return _ok({"protocols": protocols, "count": len(protocols)}, cache_seconds=3600, degraded=e)


def domains() -> dict:
    """GET /api/domains — Return domain groupings from S3 config."""
    global _domains_cache
    if _domains_cache is None:
        _domains_cache = _load_s3_json("site/config/domains.json", "domains")
    domains = _domains_cache.get("domains", [])
    return _ok({"domains": domains, "count": len(domains)}, cache_seconds=3600)


# ── /api/session — today's session as it will be lifted (E3, epic #4182) ─────
# Owner ruling 2026-09-26 ~23:05 PT, option (a): exercise NAMES + sets × reps + the
# LOAD in pounds are public. Nothing else from a routine row leaves: no title, no
# notes, no coach text, no rationale, no inputs_snapshot, no RPE targets, no Hevy ids.
# The two tuples below ARE the public shape — tests/test_routine_endpoint.py asserts
# the served body carries exactly these keys, so a key added here without being
# added there is a red, and a key added there without a privacy reason is a review.
_SESSION_KEYS = ("date", "state", "reason", "source", "kind", "session_role", "position_label", "routine_ref", "exercises", "as_of")
_EXERCISE_KEYS = ("name", "sets", "reps", "load_lbs", "loads_lbs")

_SOURCE_COMMITTED = "hevy-routine"  # pushed to Hevy — the routine on his phone
_SOURCE_DRAFT = "hevy-routine-draft"  # drafted (nightly pre-draft or chat), not yet pushed
_SOURCE_PROGRAM = "program"  # no routine for the day — the program's own prescription for the next session

_KG_TO_LBS = 2.20462  # the constant training.muscle_volume._KG_TO_LBS uses; the IR stores weight_kg (hevy_compiler)


def _lbs(kg) -> "int | None":
    """Whole pounds from a stored weight_kg; None when the set carries no load (a timed or bodyweight set)."""
    try:
        v = float(kg)
    except (TypeError, ValueError):
        return None
    return int(round(v * _KG_TO_LBS)) if v > 0 else None


def _reps_of(sets: list) -> "int | str | None":
    """The rep target of the exercise, from its TOP (first) set: an int when the range collapses
    (or the set names a single `reps`), the range as "a–b" when it does not — exactly what Hevy shows
    him. None for a set with no rep target (a timed set)."""
    for s in sets:
        if not isinstance(s, dict):
            continue
        lo, hi, reps = s.get("rep_range_start"), s.get("rep_range_end"), s.get("reps")
        try:
            if lo is not None and hi is not None:
                lo_i, hi_i = int(float(lo)), int(float(hi))
                return lo_i if lo_i == hi_i else f"{lo_i}–{hi_i}"
            if reps is not None:
                return int(float(reps))
        except (TypeError, ValueError):
            pass
        return None
    return None


def _movement_name(movement_key, catalog: dict, alias_titles: dict) -> "str | None":
    """The Hevy-catalog title for a routine movement_key — by key, or for the ADR-069 `tmpl:<id>`
    form through the entry whose template-id hint IS that id, then the alias registry's own titles
    (the same two resolvers adherence scoring uses, `health.adherence_calc`). A catalog-style key
    that resolves nowhere is rendered from its own words ("barbell_bench_press" → "Barbell bench
    press") — a transliteration, not a guess; an unresolvable template id has no honest name → None,
    and the page drops that row rather than print an id."""
    if not movement_key:
        return None
    key = str(movement_key)
    try:
        from health.adherence_calc import _catalog_entry_for

        entry = _catalog_entry_for(key, catalog or {})
    except Exception as e:  # noqa: BLE001 — the name resolver must not take the route down
        # the key is a routine-record field — never logged (CodeQL py/clear-text-logging-sensitive-data, PR #4318)
        logger.warning("handle_session catalog lookup failed: %s", type(e).__name__)
        entry = {}
    if entry.get("title"):
        return str(entry["title"])
    if key.startswith("tmpl:"):
        t = (alias_titles or {}).get(key[len("tmpl:") :]) or (alias_titles or {}).get(key[len("tmpl:") :].upper())
        return str(t) if t else None
    return key.replace("_", " ").strip().capitalize() or None


def _load_movement_names() -> "tuple[dict, dict]":
    """(catalog, alias titles) — the bundled config/movement_catalog.json (S3 `config/` when the local
    file is absent) + the alias registry's `titles`. Both non-fatal: an unreadable catalog means
    transliterated names, never a 500."""
    catalog: dict = {}
    titles: dict = {}
    try:
        from health.adherence_calc import _load_catalog, _load_template_aliases

        catalog = _load_catalog() or {}
        titles = (_load_template_aliases() or {}).get("titles") or {}
    except Exception as e:  # noqa: BLE001
        logger.warning("handle_session movement catalog unavailable: %s", e)
    return catalog, titles


def _exercise_row(ex: dict, catalog: dict, titles: dict) -> dict:
    """ONE exercise as the page reads it — built field-by-field from the IR row; the row is never spread."""
    sets = [s for s in (ex.get("sets") or []) if isinstance(s, dict)]
    loads = [lb for lb in (_lbs(s.get("weight_kg")) for s in sets) if lb is not None]
    return {
        "name": _movement_name(ex.get("movement_key"), catalog, titles),
        "sets": len(sets),
        "reps": _reps_of(sets),
        # the top set's load (the heavy scheme is one top set + back-offs at −10 %) …
        "load_lbs": max(loads) if loads else None,
        # … and every set's load in order, so "3 × 4–6 · 123 lb" can be read as 123 · 110 · 110
        "loads_lbs": loads or None,
    }


def _routine_exercises(ir: dict) -> list:
    """The exercise list Hevy actually shows: the recommended branch's own list when one exists
    (#417 2b), else the routine-level list — the same choice /api/routine's counts make."""
    for b in ir.get("branches") or []:
        if isinstance(b, dict) and b.get("recommended") and b.get("exercises"):
            return list(b["exercises"])
    return list(ir.get("exercises") or [])


def _stamped_role(ir: dict) -> "str | None":
    """The session role the generator (calendar) or the nightly pre-draft stamped on the routine — the
    ONLY field read from inputs_snapshot, and only to pick the routine; the snapshot never leaves."""
    snap = ir.get("inputs_snapshot") or {}
    if not isinstance(snap, dict):
        return None
    role = (snap.get("calendar") or {}).get("session_role") or (snap.get("nightly_predraft") or {}).get("session_role")
    return str(role) if role else None


def _program_next(today: str) -> "tuple[dict | None, str | None]":
    """(next_session, reason-when-none): the program's own answer for `today` — the next UNDONE
    session of the v0.4 sequence over the Hevy record since the block start (#4110; a Flex never
    advances it, #4312). A Hevy read that raises is handed to next_session as None so it says
    `sequence_unreadable` by name — never session 1 by default."""
    from training import program_structure, session_sequence

    if not getattr(program_structure, "ACTIVE", False):
        return None, "no active training program"
    workouts = None
    try:
        workouts = session_sequence.load_block_workouts(today)
    except Exception as e:  # noqa: BLE001 — named below, never a fabricated position
        logger.warning("handle_session block record read failed: %s", e)
    try:
        nxt = session_sequence.next_session(today, workouts)
    except Exception as e:  # noqa: BLE001
        logger.warning("handle_session next_session failed: %s", e)
        return None, "the program's session sequence could not be computed"
    if nxt is None:
        return None, f"before the program's first session ({session_sequence.block_start()})"
    if not nxt.get("session_role"):
        return None, "the record of lifted sessions could not be read, so the next session in the sequence is unknown"
    return nxt, None


def _program_exercises(role: str, deload: bool, catalog: dict, titles: dict) -> list:
    """The program's prescription for one role as exercise rows: names from the catalog, sets and the
    rep range from the exposure — no loads (the program prescribes % of a top set; the pounds live on
    the drafted routine, which is why the draft is preferred when it exists)."""
    from training import program_structure

    rx = program_structure.session_prescription_for_role(role, deload=deload, catalog_movements=(catalog or {}).get("movements") or None)
    rows = []
    for e in rx.get("exposures") or []:
        sets = e.get("sets") or []
        reps = None
        if sets and isinstance(sets[0], dict) and sets[0].get("reps"):
            lo, hi = sets[0]["reps"][0], sets[0]["reps"][-1]
            reps = int(lo) if int(lo) == int(hi) else f"{int(lo)}–{int(hi)}"
        name = _movement_name(e.get("movement_key"), catalog, titles) if e.get("movement_key") else None
        if not name and e.get("pattern"):
            name = str(e["pattern"]).replace("_", " ").capitalize()
        rows.append({"name": name, "sets": len(sets), "reps": reps, "load_lbs": None, "loads_lbs": None})
    return rows


def routine_ref(routine_id) -> "str | None":
    """The PUBLIC handle of a picked routine: 12 hex of sha256 over the platform routine id. The id
    itself never leaves (the #4318 privacy sweep); the ref lets a reader, a page or a contract test
    check that /api/routine and /api/session name the same routine (#4338). None for no routine."""
    if not routine_id:
        return None
    return hashlib.sha256(f"routine:{routine_id}".encode()).hexdigest()[:12]


_ROUTINE_IR_PROJECTION = (
    "target_date, archetype, variant, #st, exercises, branches, hevy_pushed_at, hevy_routine_id, "
    "inputs_snapshot.calendar.session_role, inputs_snapshot.nightly_predraft.session_role"
)


def _read_routine_ir(table, routine_id: str) -> dict:
    """VERSION#current of one routine, projected to what the two routes read; {} on a failed read."""
    try:
        resp = table.get_item(
            Key={"pk": f"USER#{USER_ID}#ROUTINE#{routine_id}", "sk": "VERSION#current"},
            ProjectionExpression=_ROUTINE_IR_PROJECTION,
            ExpressionAttributeNames={"#st": "status"},
        )
        return _decimal_to_float(resp.get("Item")) or {}
    except Exception as e:
        # no record field in the log line — the failure class is enough (CodeQL, PR #4318)
        logger.warning("routine IR read failed: %s", type(e).__name__)
        return {}


def _committed(ir: dict) -> bool:
    """Pushed to Hevy — the routine on his phone."""
    return bool(ir.get("hevy_routine_id")) or bool(ir.get("hevy_pushed_at")) or (ir.get("status") or "") == "active"


def pick_todays_routine(table, today: str, program_next) -> dict:
    """THE pick of today's routine — the ONE selection /api/routine and /api/session both serve (#4338;
    two pickers named an upper draft and a lower draft for 2026-09-27). Over today's visible index rows
    (floor / re-entry variants and archived rows never selected):
      1. a routine COMMITTED to Hevy — `source: hevy-routine`
      2. else the only draft; else the draft stamped with the sequence's next role; else the draft whose
         archetype is the next session's — `source: hevy-routine-draft`
      3. else none (two drafts, neither the program's next session: the program is the answer, #4110)
    `program_next` is a zero-arg callable returning `_program_next`'s (next_session, reason) — called
    only when two or more drafts need the sequence to decide, so /api/routine pays the Hevy read only then.

    Returns {"rows": the visible index rows newest-first (every date), "routine_id", "ir", "source",
    "declined": today's readable routine ids NOT picked}. "ir" is None when nothing was picked."""
    rows: list = []
    try:
        resp = table.query(
            KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}routine_index"),
            ScanIndexForward=False,
            Limit=32,
        )
        rows = _decimal_to_float(resp.get("Items", []))
    except Exception as e:
        logger.warning("routine index read failed: %s", e)
    rows = [
        r
        for r in rows
        if r.get("routine_id") and (r.get("variant") or "") not in _ROUTINE_HIDDEN_VARIANTS and (r.get("status") or "") != "archived"
    ]
    readable = []
    for r in rows:
        if str(r.get("target_date") or "") == today:
            ir = _read_routine_ir(table, str(r["routine_id"]))
            if ir:
                readable.append((str(r["routine_id"]), ir))

    committed = [p for p in readable if _committed(p[1])]
    drafts = [p for p in readable if not _committed(p[1])]
    picked, source = None, None
    if committed:
        picked, source = committed[0], _SOURCE_COMMITTED
    elif len(drafts) == 1:
        picked, source = drafts[0], _SOURCE_DRAFT
    elif drafts:
        nxt, _reason = program_next()
        next_role = (nxt or {}).get("session_role")
        next_arch = str((nxt or {}).get("archetype") or "").lower()
        by_role = [p for p in drafts if next_role and _stamped_role(p[1]) == next_role]
        by_arch = [p for p in drafts if next_arch and str(p[1].get("archetype") or "").lower() == next_arch]
        if by_role or by_arch:
            picked, source = (by_role or by_arch)[0], _SOURCE_DRAFT
    return {
        "rows": rows,
        "routine_id": picked[0] if picked else None,
        "ir": picked[1] if picked else None,
        "source": source,
        "declined": {rid for rid, _ in readable if not picked or rid != picked[0]},
    }


def session(*, _g) -> dict:
    """GET /api/session — the session Matthew lifts TODAY, as it will be lifted: exercise names,
    sets × reps, the load in pounds (owner ruling 2026-09-26, option (a); E3 of epic #4182).

    THE PICK, in order, all for the Pacific day (1–2 are `pick_todays_routine`, the ONE picker
    /api/routine serves too — #4338; both carry the pick's `routine_ref`):
      1. a routine COMMITTED to Hevy for today (`hevy_routine_id` / status active) — `source: hevy-routine`
      2. else the only DRAFT for today; else the draft whose stamped role is the sequence's next role;
         else the draft whose archetype is the next session's — `source: hevy-routine-draft`
      3. else the program's own prescription for the next undone session — `source: program`
         (names, sets × reps; loads null — the program prescribes % of a top set, not pounds)
      4. else `state: absent` with the reason (before the block start; the Hevy record unreadable)
    Two drafts and no program match is served as (3): the program is the engine's ONE answer to
    "what is next" (#4110). Floor / re-entry variants and archived routines are never selected,
    exactly as /api/routine.

    FAIL-CLOSED: `_SESSION_KEYS` / `_EXERCISE_KEYS` are the whole public shape, built field-by-field;
    the stored IR is never spread. Read-only; always a shaped 200. Cache: 900s, like /api/routine.
    """
    table = _g["table"]
    today = datetime.now(PT).strftime("%Y-%m-%d")
    as_of = datetime.now(timezone.utc).isoformat()

    def _out(state, *, reason=None, source=None, kind=None, role=None, label=None, ref=None, exercises=None):
        body = {
            "date": today,
            "state": state,
            "reason": reason,
            "source": source,
            "kind": kind,
            "session_role": role,
            "position_label": label,
            "routine_ref": ref,
            "exercises": [{k: e.get(k) for k in _EXERCISE_KEYS} for e in (exercises or [])],
            "as_of": as_of,
        }
        return _ok({k: body[k] for k in _SESSION_KEYS}, cache_seconds=900)

    # The program's position — read once; it names the role a draft must match and the position label.
    nxt, program_reason = _program_next(today)
    next_role = (nxt or {}).get("session_role")

    # ONE pick of today's routine, shared with /api/routine (#4338).
    pick = pick_todays_routine(table, today, lambda: (nxt, program_reason))
    picked, source = pick["ir"], pick["source"]

    catalog, titles = _load_movement_names()

    if picked is not None:
        from training import session_sequence

        archetype = str(picked.get("archetype") or "").lower()
        kind = "program" if archetype in session_sequence.program_archetypes() else "complement"
        role = _stamped_role(picked) if kind == "program" else None
        label = (nxt or {}).get("position_label") if role and role == next_role else None
        exercises = [_exercise_row(ex, catalog, titles) for ex in _routine_exercises(picked) if isinstance(ex, dict)]
        return _out("served", source=source, kind=kind, role=role, label=label, ref=routine_ref(pick["routine_id"]), exercises=exercises)

    if nxt is not None and next_role:
        try:
            exercises = _program_exercises(next_role, bool(nxt.get("deload")), catalog, titles)
        except Exception as e:  # noqa: BLE001 — a template the program cannot render is an absence, not a 500
            logger.warning("handle_session program prescription failed: %s", e)
            return _out("absent", reason="the program's prescription for the next session could not be built")
        return _out("served", source=_SOURCE_PROGRAM, kind="program", role=next_role, label=nxt.get("position_label"), exercises=exercises)

    return _out("absent", reason=program_reason or "no session drafted for today and none prescribed")
