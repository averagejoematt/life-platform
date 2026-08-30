"""lambdas/web/site_api_coach_narrative.py — the written reads (/api/coach_analysis, /api/recap, …).

Split out of ``site_api_coach.py`` (#1654 — god-module breakup). One seam: **the
narrative surfaces** — every endpoint that serves a PRE-COMPUTED piece of AI-written
prose (a coach's domain analysis, an expert's lab note, Elena's "previously on"
recap, the board's cross-week arc, the integrator's week call and month rollup, the
per-coach learning timeline). No inference happens here; each handler is a guarded
read of a record some batch Lambda already wrote.

The two guards that make this a single concern, and why they belong together:

  * the **staleness** guard (``_current_day_n``) — a stored narrative whose own day
    count outruns the live experiment is from a previous cycle and is refused, not
    served (Stage0 Fix 3; the "still 268 lbs over fifty-five days" defect);
  * the **regeneration-paused** disclosure (``_regeneration_paused``, #802) — at
    budget tier >= 2 the writers skip entirely, so served prose can be a HELD read.
    Every narrative endpoint says so rather than presenting a stale line present-tense.

The routed handler entrypoints stay in the ``site_api_coach`` facade as thin
delegators; the logic lives here. Handlers receive the facade's ``globals()`` as
``_g`` and read the monkeypatched/injectable state via ``_g["<name>"]`` (``table``,
``EXPERIMENT_START``, ``_current_day_n``, ``_regeneration_paused``,
``_integrator_digest``, ``_lead_byline`` — all live patch points in the suite).
This module does NOT import the facade; no import cycle.
"""

from boto3.dynamodb.conditions import Key
from coach import audience_guard  # #2972 — the public-audience frame (public_read)
from coach.persona_registry import (  # coaching-team v2: names come from the registry
    OPERATIONAL_SHORT_IDS,  # #3172: the ai_analysis EXPERT# keyspace
    display_map as _registry_display_map,
    short_id_names as _registry_short_names,
)
from experiment.phase_filter import singleton_visible, with_phase_filter  # ADR-058 / #946

from web.site_api_common import (
    PT,
    USER_PREFIX,
    _decimal_to_float,
    _error,
    _ok,
    as_of_day_n,
    content_vintage,
    logger,
    pre_start_meta,
)


def _regeneration_paused(feature: str) -> bool:
    """True if the budget-tier ladder (ADR-063/125) currently pauses regeneration
    of `feature` narratives — i.e. any content still being served is a HELD, not a
    live, read. Callers attach this alongside `generated_at` so the front-end can
    give an honest "as of / refresh paused" disclosure instead of presenting a
    stale narrative present-tense (R22-CONTENT-03, #802).

    Only call this with a feature name actually registered in
    budget_guard._FEATURE_CUTOFF AND actually checked by that feature's writer
    Lambda — e.g. "chronicle" (wednesday_chronicle_lambda, recap included) and
    "coach_narrative" (coach_narrative_orchestrator, the OUTPUT# records
    /api/coach_analysis reads). Fail-open to False (not paused) on any error,
    mirroring budget_guard's own fail-open design — an SSM blip must never
    manufacture a false disclosure banner.
    """
    try:
        from ai.budget_guard import allow

        return not allow(feature)
    except Exception:
        return False


def _current_day_n(*, _g) -> int:
    """Day-of-experiment (1-indexed) under the active EXPERIMENT_START_DATE.
    Used by Stage0 Fix 3 freshness guard to refuse to serve generated
    narrative that claims a day count newer than the live experiment."""
    EXPERIMENT_START = _g["EXPERIMENT_START"]
    datetime = _g["datetime"]
    today = datetime.now(PT).date()
    try:
        start = datetime.strptime(EXPERIMENT_START, "%Y-%m-%d").date()
    except Exception:
        return 0
    return max((today - start).days + 1, 0)


def handle_experiment_synthesis(*, _g):
    """GET /api/experiment_synthesis — the board's cross-week arc of the whole run (C-1).

    Reads the precomputed EXPERT#experiment_arc record (written by ai-expert-analyzer
    once >=2 weeks of lab notes exist). Honest-null before then; the Experiment view
    falls back to its week-by-week tone list.
    """
    _lead_byline = _g["_lead_byline"]
    table = _g["table"]
    ai_pk = f"{USER_PREFIX}ai_analysis"
    item = table.get_item(Key={"pk": ai_pk, "sk": "EXPERT#experiment_arc"}).get("Item")
    if not singleton_visible(item):  # #946: honest-null while tombstoned from a reset
        return _ok({"arc": None, "throughline": None, "chapters": [], "week_count": 0, "generated_at": None}, cache_seconds=300)
    item = _decimal_to_float(item)
    # #1986: the arc is signed by the same board lead as the weekly call and the
    # month rollup. Served here so the front-end renders the registry's lead
    # instead of carrying its own copy of a name.
    _lead_name, _lead_title = _lead_byline()
    return _ok(
        {
            "arc": item.get("arc"),
            "throughline": item.get("throughline"),
            "chapters": item.get("chapters", []),
            "week_count": int(item.get("week_count") or 0),
            "generated_at": item.get("generated_at"),
            "coach_name": _lead_name,
            "coach_title": _lead_title,
        },
        cache_seconds=300,
    )


def handle_recap(*, _g):
    """GET /api/recap — Elena's "previously on" cold-open (backend serial phase 3).

    Reads the chronicle recap (`RECAP#latest`), written when a chronicle week is
    published. Honest-null before the first recap exists; the timeline view then falls
    back to its front-end-derived "story so far". Withholds a stale record (one that
    survived a genesis re-anchor) the same way handle_ai_analysis does.
    """
    _current_day_n = _g["_current_day_n"]
    _regeneration_paused = _g["_regeneration_paused"]
    table = _g["table"]
    item = table.get_item(Key={"pk": f"{USER_PREFIX}chronicle", "sk": "RECAP#latest"}).get("Item")
    # #1085 (extends #946): the wiped RECAP#latest was only being withheld by the
    # day-count guard below (record claims day 7 > pre-start day 0) — it would have
    # resurfaced on day 7 of the NEW cycle. Tombstone/phase guard closes it for good.
    if not singleton_visible(item):
        return _ok({"recap": None}, cache_seconds=300)
    item = _decimal_to_float(item)
    rec_days = item.get("experiment_day")
    if rec_days is not None:
        try:
            if int(rec_days) > _current_day_n():
                logger.info("[recap] record claims day %s but current is %s — withholding stale recap", rec_days, _current_day_n())
                return _ok({"recap": None}, cache_seconds=300)
        except (TypeError, ValueError):
            pass
    return _ok(
        {
            "recap": {
                "story_so_far": item.get("story_so_far"),
                "recent_beats": item.get("recent_beats", []),
                "where_we_are_now": item.get("where_we_are_now"),
                "threads_to_watch": item.get("threads_to_watch", []),
                "as_of": item.get("as_of"),
                "as_of_week": item.get("as_of_week"),
                "author": item.get("author", "Elena Voss"),
                "generated_at": item.get("generated_at"),
                # #802: the Wednesday chronicle (and this recap, written at its
                # publish time) skips entirely at budget tier >= 2 — a served
                # recap can be a HELD read, not this week's. Honest disclosure.
                "regeneration_paused": _regeneration_paused("chronicle"),
            }
        },
        cache_seconds=300,
        # #3252 sibling sweep: the recap is a stored narrative written at chronicle
        # publish time — the envelope declares ITS instant, not the request's.
        content_as_of=content_vintage(item.get("generated_at")),
    )


def handle_ai_analysis(event, *, _g):
    """GET /api/ai_analysis"""
    _current_day_n = _g["_current_day_n"]
    table = _g["table"]
    qs = event.get("queryStringParameters") or {}
    expert_key = qs.get("expert", "mind")
    # Roster-derived whitelist, never re-typed (#2334; guard:
    # tests/test_coach_roster_set_guard_2334.py).
    from coach.persona_registry import OPERATIONAL_SHORT_IDS

    if expert_key not in OPERATIONAL_SHORT_IDS:
        return _error(400, "Invalid expert key")
    ai_pk = f"{USER_PREFIX}ai_analysis"
    ai_item = table.get_item(Key={"pk": ai_pk, "sk": f"EXPERT#{expert_key}"}).get("Item")
    # #946: singleton_visible closes the tombstone gap the days_in_experiment
    # guard below can't see (a wiped record whose day count is <= today's).
    if not singleton_visible(ai_item):
        return _ok({"expert_key": expert_key, "analysis": None, "generated_at": None}, cache_seconds=300)
    ai_item = _decimal_to_float(ai_item)
    # Stage0 Fix 3 (2026-05-30): freshness guard. The Brandt block on /explorer/
    # was rendering "still 268 lbs over fifty-five days" because a pre-restart
    # analysis record survived the genesis re-anchor. If the record's
    # days_in_experiment is newer than the live experiment day count, the
    # narrative is from a previous experiment cycle — refuse to serve it.
    rec_days = ai_item.get("days_in_experiment")
    if rec_days is not None:
        try:
            if int(rec_days) > _current_day_n():
                logger.info(
                    f"[ai_analysis] {expert_key} record claims day {rec_days} "
                    f"but current is day {_current_day_n()} — withholding stale narrative"
                )
                return _ok(
                    {
                        "expert_key": expert_key,
                        "analysis": None,
                        "generated_at": None,
                        "stale": True,
                    },
                    cache_seconds=300,
                )
        except (TypeError, ValueError):
            pass
    analysis_val = ai_item.get("analysis", "")
    if "[AI_UNAVAILABLE]" in (analysis_val or ""):
        analysis_val = None
    resp_data = {
        "expert_key": expert_key,
        "analysis": analysis_val,
        "generated_at": ai_item.get("generated_at", ""),
    }
    if ai_item.get("key_recommendation"):
        resp_data["key_recommendation"] = ai_item["key_recommendation"]
    if ai_item.get("journaling_prompt"):
        resp_data["journaling_prompt"] = ai_item["journaling_prompt"]
    if ai_item.get("elena_quote"):
        resp_data["elena_quote"] = ai_item["elena_quote"]
    if ai_item.get("week_number"):
        resp_data["week_number"] = int(ai_item["week_number"])
    if ai_item.get("days_in_experiment"):
        resp_data["days_in_experiment"] = int(ai_item["days_in_experiment"])
    return _ok(resp_data, cache_seconds=300)


# #3172: "training" has no dedicated `ai_analysis` EXPERT# row of its own — the
# coaching-team v2 merge (2026-08-10) folded it into physical_coach, and
# ai_expert_analyzer_lambda's roster (OPERATIONAL_SHORT_IDS) never grew a
# separate "training" expert_key to match. Mirrors coach_observatory_renderer's
# alias of the same name.
_EXPERT_KEY_ALIAS = {"training": "physical"}


def _journaling_prompt_for_domain(table, domain):
    """#3172: ``journaling_prompt`` is written by
    ``intelligence.ai_expert_analyzer_lambda::generate_and_cache`` onto the
    ``ai_analysis`` ``EXPERT#{expert_key}`` row — the ``COACH#{coach_id}``
    ``OUTPUT#`` row ``handle_coach_analysis`` otherwise reads never carries it
    (``coach.coach_state_updater::_write_output_record``'s item dict has no such
    key; it never did), so ``output.get("journaling_prompt")`` was a permanent
    dead-zone None. Resolve from the real producer instead.
    """
    expert_key = _EXPERT_KEY_ALIAS.get(domain, domain)
    if expert_key not in OPERATIONAL_SHORT_IDS:
        return None
    try:
        item = table.get_item(Key={"pk": f"{USER_PREFIX}ai_analysis", "sk": f"EXPERT#{expert_key}"}).get("Item")
    except Exception:
        return None
    if not singleton_visible(item):
        return None
    return (item or {}).get("journaling_prompt")


def handle_coach_analysis(event, *, _g):
    """GET /api/coach_analysis"""
    _integrator_digest = _g["_integrator_digest"]
    _latest_cycle_digest = _g["_latest_cycle_digest"]
    _regeneration_paused = _g["_regeneration_paused"]
    table = _g["table"]
    qs = event.get("queryStringParameters") or {}
    raw_domain = qs.get("domain", "sleep")
    _coach_map = {
        "sleep": "sleep_coach",
        "nutrition": "nutrition_coach",
        # Coaching-team v2 (2026-08-10): the merged Performance seat serves the
        # training domain — Dr. Sarah Chen retired, Dr. Max Reyes absorbs it.
        "training": "physical_coach",
        "mind": "mind_coach",
        "physical": "physical_coach",
        "glucose": "glucose_coach",
        "labs": "labs_coach",
        "explorer": "explorer_coach",
    }
    # The Cockpit (/cockpit/) discloses the 7 CHARACTER PILLARS, whose names differ from the
    # coach-domain names above — alias them so a pillar click resolves to the right coach.
    _pillar_alias = {"movement": "physical", "metabolic": "glucose"}
    # Pillars with no dedicated board coach: return a graceful empty read (200), not a 400,
    # so the Cockpit shows its deterministic fallback without a console error.
    _no_coach_pillars = {"relationships", "consistency"}
    domain = _pillar_alias.get(raw_domain, raw_domain)
    coach_id = _coach_map.get(domain)
    if not coach_id:
        if raw_domain in _no_coach_pillars:
            return _ok({"coach_id": None, "domain": raw_domain, "analysis": None}, cache_seconds=600)
        return _error(400, f"Invalid domain. Use one of: {', '.join(sorted(_coach_map))}")

    # Registry-derived names/initials/title/color (coaching-team v2). #2757: this used
    # to re-type its own title/color per coach and had already drifted from the
    # registry (nutrition_coach's color here was the pre-roster-v2 '#10b981' while
    # /api/coaches — registry-derived — served '#22c55e'). display_map() already
    # carries title/color (falls back to board_role when a persona has no dedicated
    # `title`), so this surface now derives entirely. `include=("operational",
    # "retired")` keeps the retired training_coach entry resolvable for cross-coach
    # references inside historical OUTPUT#/ENSEMBLE# records.
    _coach_display = _registry_display_map(include=("operational", "retired"))

    try:
        coach_pk = f"COACH#{coach_id}"

        # 1. Most recent OUTPUT# record
        out_resp = table.query(
            **with_phase_filter(
                {  # ADR-058: hide pilot coach outputs
                    "KeyConditionExpression": Key("pk").eq(coach_pk) & Key("sk").begins_with("OUTPUT#"),
                    "ScanIndexForward": False,
                    "Limit": 1,
                }
            )
        )
        out_items = out_resp.get("Items", [])
        if not out_items:
            return _ok({"coach_id": coach_id, "domain": domain, "analysis": None}, cache_seconds=300)

        output = _decimal_to_float(out_items[0])
        # Prefer observatory_summary over full content
        analysis_text = output.get("observatory_summary") or output.get("content", "")
        if "[AI_UNAVAILABLE]" in (analysis_text or ""):
            analysis_text = None

        # 2. Open threads
        thread_reference = None
        try:
            thread_resp = table.query(
                **with_phase_filter(
                    {  # ADR-058: hide pilot coach threads
                        "KeyConditionExpression": Key("pk").eq(coach_pk) & Key("sk").begins_with("THREAD#"),
                    }
                )
            )
            threads = [_decimal_to_float(t) for t in thread_resp.get("Items", []) if t.get("status") == "open"]
            if threads:
                # Pick most recently referenced thread
                threads.sort(key=lambda t: t.get("last_referenced", ""), reverse=True)
                thread_reference = threads[0].get("summary", "")
        except Exception:
            pass

        # 3. Ensemble digest — cross-coach references (#1085: tombstone/phase-guarded)
        cross_coach_reference = None
        # #2333: coach_ensemble_digest stamps `_fallback: True` on a digest produced
        # without the LLM (budget-paused at tier >= 1, ADR-125 — the common case, not
        # the rare one, per #1927). Nothing downstream of _latest_cycle_digest checked
        # it, so a template-generated digest rendered indistinguishably from a genuine
        # cross-coach read. ADR-104 behavioral-absence semantics: disclose the paused
        # state explicitly rather than staying silent about it.
        ensemble_fallback = False
        # #3252 sibling sweep: when a stored ensemble digest's content actually lands
        # in this response (cross_coach_reference below), its `created_at` joins the
        # envelope's vintage set — content_vintage takes the OLDEST constituent.
        _ensemble_created_at = None
        try:
            digest = _latest_cycle_digest()
            if digest:
                ensemble_fallback = bool(digest.get("_fallback"))
                disagreements = digest.get("active_disagreements", [])
                for d in disagreements:
                    coaches = d.get("coaches", [])
                    if coach_id in coaches:
                        cross_coach_reference = d.get("topic", "")
                        _ensemble_created_at = digest.get("created_at")
                        break
        except Exception:
            pass

        # 4. Computation guardrails — data availability
        data_availability = "preliminary"
        try:
            comp_resp = table.query(
                **with_phase_filter(
                    {  # ADR-058: hide pilot computation results
                        "KeyConditionExpression": Key("pk").eq("COACH#computation") & Key("sk").begins_with("RESULTS#"),
                        "ScanIndexForward": False,
                        "Limit": 1,
                    }
                )
            )
            comp_items = comp_resp.get("Items", [])
            if comp_items:
                guardrails = _decimal_to_float(comp_items[0]).get("statistical_guardrails", {})
                # Find the guardrail for this domain's primary source
                for source_name, source_guardrails in guardrails.items():
                    if isinstance(source_guardrails, dict):
                        for metric, g in source_guardrails.items():
                            if isinstance(g, dict):
                                data_availability = g.get("data_availability", "preliminary")
                                break
                        break
        except Exception:
            pass

        # 5. Revision signal — recent learning records
        revision_signal = None
        try:
            learn_resp = table.query(
                **with_phase_filter(
                    {  # ADR-058: hide pilot coach learnings
                        "KeyConditionExpression": Key("pk").eq(coach_pk) & Key("sk").begins_with("LEARNING#"),
                        "ScanIndexForward": False,
                        "Limit": 3,
                    }
                )
            )
            for item in learn_resp.get("Items", []):
                item = _decimal_to_float(item)
                # ADR-141 §4 defense-in-depth (2026-07-26 review): conversation-channel
                # learnings are Matthew-private — filter explicitly, don't rely on the
                # type-field vocabulary alone. Also keeps conversation rows from
                # crowding the Limit=3 window a real position_revision needs.
                if (item.get("channel") or "data") == "conversation":
                    continue
                if item.get("type") == "position_revision":
                    revision_signal = item.get("revised_position", "")[:100]
                    break
        except Exception:
            pass

        # 6. Confidence language
        confidence_language = "preliminary"
        try:
            output.get("themes", [])
            # Use the overall confidence from the generation if available
            conf = output.get("confidence")
            if conf is not None:
                conf_f = float(conf)
                if conf_f >= 0.85:
                    confidence_language = "highly_confident"
                elif conf_f >= 0.7:
                    confidence_language = "fairly_confident"
                elif conf_f >= 0.5:
                    confidence_language = "moderate"
                elif conf_f >= 0.3:
                    confidence_language = "preliminary"
                else:
                    confidence_language = "uncertain"
        except Exception:
            pass

        display = _coach_display.get(coach_id, {})
        # The dateline (2026-08-27). `generated_at` alone dates the read in CALENDAR
        # terms, but the frozen prose dates ITSELF in EXPERIMENT-DAY terms ("Day 10 as
        # of today") — two frames that never reconcile for a reader who cannot convert
        # Aug 26 into Day 10. While regeneration is paused (ADR-125 tier >= 2) the gap
        # widens by a day every day, and on 2026-08-27 a Day-10 sentence served on
        # Day 11 tripped the gating visual-QA judge on /coaching/by-coach/#physical_coach.
        # Serving the content's OWN day number is the fix: the pause stays exactly as
        # it is, and the held text is LABELLED with the day it describes instead of
        # being re-served as though it were today's. Derived, never re-read from the
        # record's optional `days_in_experiment` stamp (see as_of_day_n's docstring).
        _generated_at = output.get("created_at") or output.get("generated_at", "")
        # #3252 sibling sweep: every STORED record whose prose lands in this response
        # contributes its own stamp; content_vintage() reports the OLDEST — the
        # envelope may not claim more freshness than its stalest member (ADR-104).
        _vintage_stamps = [_generated_at, _ensemble_created_at]
        resp = {
            "coach_id": coach_id,
            "coach_name": display.get("name", ""),
            "coach_initials": display.get("initials", ""),
            "coach_title": display.get("title", ""),
            "coach_color": display.get("color", ""),
            "domain": domain,
            "analysis": analysis_text,
            # #2972: the PUBLIC-audience read — the only field the reader-facing board
            # detail (/method/board/, evidence.js renderBoard) renders. Guarded on the
            # FULL stored text (never a truncated slice); absent (stripped below) until
            # the coach's next run writes a reader-safe `public_summary`, and the board
            # shows its designed honest-empty state meanwhile. `analysis` stays the
            # coaching-register read pending the #2959 audience-rubric adjudication for
            # the /coaching/* exhibit pages.
            "public_read": audience_guard.public_read(output),
            "key_recommendation": output.get("key_recommendation") or (output.get("themes", [""])[0] if output.get("themes") else None),
            "elena_quote": output.get("elena_quote"),
            "journaling_prompt": _journaling_prompt_for_domain(table, domain),  # #3172: real producer is ai_analysis EXPERT#
            "thread_reference": thread_reference,
            "revision_signal": revision_signal,
            "cross_coach_reference": cross_coach_reference,
            # #2333: True only when the newest ENSEMBLE#digest CYCLE# record was
            # produced without the LLM (budget-paused or an LLM failure) — a reader
            # can then label `cross_coach_reference` (or its absence) honestly instead
            # of presenting a template as a coach's cross-domain reasoning.
            "ensemble_fallback": ensemble_fallback,
            "confidence_language": confidence_language,
            "data_availability": data_availability,
            "generated_at": _generated_at,
            "as_of_day_n": as_of_day_n(_generated_at, _g["EXPERIMENT_START"]),
            "week_number": output.get("week_number"),
            "days_in_experiment": output.get("days_in_experiment"),
            # #802: coach_narrative_orchestrator skips this coach's OUTPUT# write
            # entirely at budget tier >= 2 — a served analysis can be a HELD read
            # from before the pause, not today's. Honest disclosure alongside
            # generated_at rather than a silent present-tense stale read.
            "regeneration_paused": _regeneration_paused("coach_narrative"),
        }

        # Add cross-domain context note from the integrator (if available)
        try:
            _int_item = _integrator_digest() or {}  # #946: tombstone/phase-guarded
            _cdn = _int_item.get("cross_domain_notes", {})
            _int_used = False
            if isinstance(_cdn, dict) and domain in _cdn:
                resp["cross_domain_note"] = _cdn[domain]
                _int_used = True
            if _int_item.get("analysis"):
                resp["weekly_priority"] = _int_item["analysis"]
                _int_used = True
            # #3252: the integrator's prose landed in the response, so its stamp
            # joins the vintage set (the same generated_at /api/weekly_priority declares).
            if _int_used:
                _vintage_stamps.append(_int_item.get("generated_at"))
        except Exception:
            pass

        # Strip None values for cleaner JSON
        resp = {k: v for k, v in resp.items() if v is not None}
        return _ok(resp, cache_seconds=300, content_as_of=content_vintage(*_vintage_stamps))
    except Exception as _e:
        logger.warning(f"[/api/coach_analysis] {_e}")
        return _ok({"coach_id": coach_id, "domain": domain, "analysis": None}, cache_seconds=60, degraded=_e)


def handle_coach_timeline(event, *, _g):
    """GET /api/coach_timeline"""
    table = _g["table"]
    try:
        qs = event.get("queryStringParameters") or {}
        coach_id = qs.get("coach_id", "")

        _tl_coach_names = _registry_short_names(include_retired=True)  # history keeps real bylines
        _tl_coach_id_map = {
            "sleep": "sleep_coach",
            "nutrition": "nutrition_coach",
            "training": "training_coach",
            "mind": "mind_coach",
            "physical": "physical_coach",
            "glucose": "glucose_coach",
            "labs": "labs_coach",
            "explorer": "explorer_coach",
        }

        if coach_id not in _tl_coach_names:
            return _error(400, "Invalid or missing coach_id")

        coach_pk = f"COACH#{_tl_coach_id_map[coach_id]}"
        milestones = []

        # Query OUTPUT# records for stance_changes, predictions, surprises, emotional_investment
        try:
            out_resp = table.query(
                **with_phase_filter(
                    {  # ADR-058: hide pilot timeline outputs
                        "KeyConditionExpression": Key("pk").eq(coach_pk) & Key("sk").begins_with("OUTPUT#"),
                        "ScanIndexForward": False,
                        "Limit": 20,
                    }
                )
            )
            prev_investment = None
            for out_item in out_resp.get("Items", []):
                out_item = _decimal_to_float(out_item)
                out_date = out_item.get("sk", "").replace("OUTPUT#", "")

                # Stance changes
                stance_changes = out_item.get("stance_changes", [])
                if isinstance(stance_changes, list):
                    for sc in stance_changes:
                        if isinstance(sc, dict):
                            milestones.append(
                                {
                                    "date": out_date,
                                    "type": "stance_change",
                                    "text": sc.get("topic", sc.get("text", "Position revised")),
                                    "detail": sc.get("new_stance", sc.get("detail", "")),
                                }
                            )
                        elif isinstance(sc, str):
                            milestones.append(
                                {
                                    "date": out_date,
                                    "type": "stance_change",
                                    "text": sc,
                                    "detail": "",
                                }
                            )

                # Resolved predictions
                preds = out_item.get("predictions", [])
                if isinstance(preds, list):
                    for p in preds:
                        if isinstance(p, dict) and p.get("status") in ("confirmed", "refuted"):
                            milestones.append(
                                {
                                    "date": out_date,
                                    "type": "prediction_resolved",
                                    "text": p.get("text", p.get("prediction", "")),
                                    "detail": f"Status: {p['status']}",
                                }
                            )

                # Surprises
                surprises = out_item.get("surprises", [])
                if isinstance(surprises, list):
                    for s in surprises:
                        if isinstance(s, dict):
                            milestones.append(
                                {
                                    "date": out_date,
                                    "type": "surprise",
                                    "text": s.get("text", s.get("observation", "")),
                                    "detail": s.get("detail", s.get("significance", "")),
                                }
                            )
                        elif isinstance(s, str):
                            milestones.append(
                                {
                                    "date": out_date,
                                    "type": "surprise",
                                    "text": s,
                                    "detail": "",
                                }
                            )

                # Emotional investment changes
                current_investment = out_item.get("emotional_investment", "neutral")
                if prev_investment and current_investment != prev_investment:
                    milestones.append(
                        {
                            "date": out_date,
                            "type": "investment_change",
                            "text": f"Investment shifted: {prev_investment} -> {current_investment}",
                            "detail": "",
                        }
                    )
                prev_investment = current_investment

                # Learning log entries
                learning_log = out_item.get("learning_log", [])
                if isinstance(learning_log, list):
                    for entry in learning_log:
                        if isinstance(entry, dict):
                            milestones.append(
                                {
                                    "date": out_date,
                                    "type": "stance_change",
                                    "text": entry.get("lesson", entry.get("text", "")),
                                    "detail": entry.get("detail", ""),
                                }
                            )
        except Exception:
            pass

        # Also check LEARNING# records
        try:
            learn_resp = table.query(
                **with_phase_filter(
                    {  # ADR-058: hide pilot timeline learnings
                        "KeyConditionExpression": Key("pk").eq(coach_pk) & Key("sk").begins_with("LEARNING#"),
                        "ScanIndexForward": False,
                        "Limit": 20,
                    }
                )
            )
            for l_item in learn_resp.get("Items", []):
                l_item = _decimal_to_float(l_item)
                if (l_item.get("channel") or "data") == "conversation":
                    # ADR-141 privacy tier: never surface conversation-learning
                    # text (verbatim check-in quotes) on a public timeline.
                    continue
                l_date = l_item.get("sk", "").replace("LEARNING#", "")
                l_type = l_item.get("type", "stance_change")
                milestones.append(
                    {
                        "date": l_date,
                        "type": (
                            l_type
                            if l_type in ("stance_change", "prediction_resolved", "surprise", "investment_change")
                            else "stance_change"
                        ),
                        "text": l_item.get("lesson", l_item.get("revised_position", l_item.get("text", ""))),
                        "detail": l_item.get("detail", l_item.get("evidence", "")),
                    }
                )
        except Exception:
            pass

        # Sort by date descending, deduplicate by text
        milestones.sort(key=lambda m: m.get("date", ""), reverse=True)
        seen_texts = set()
        unique_milestones = []
        for m in milestones:
            key = m.get("text", "")[:80]
            if key and key not in seen_texts:
                seen_texts.add(key)
                unique_milestones.append(m)

        return _ok(
            {
                "coach_id": coach_id,
                "coach_name": _tl_coach_names[coach_id],
                "milestones": unique_milestones[:50],
            },
            cache_seconds=600,
        )
    except Exception as _e:
        logger.warning(f"[/api/coach_timeline] {_e}")
        return _ok({"coach_id": "", "coach_name": "", "milestones": []}, cache_seconds=60, degraded=_e)


def handle_weekly_priority(event, *, _g):
    """GET /api/weekly_priority"""
    _integrator_digest = _g["_integrator_digest"]
    _lead_byline = _g["_lead_byline"]
    try:
        # PRE-START (#948, the #939 contract): any stored integrator record predates
        # the staged genesis — serving it would present the wiped cycle's "week's
        # call" as current. Honest null + the countdown fields; every consumer
        # already renders the empty state. Inert (normal path, pre_start=False)
        # once genesis <= today.
        _pre = pre_start_meta()
        if _pre:
            return _ok({"weekly_priority": None, "cross_domain_notes": {}, **_pre}, cache_seconds=300)
        _int_item = _integrator_digest()  # #946: tombstone/phase-guarded
        if not _int_item:
            return _ok({"weekly_priority": None, "cross_domain_notes": {}, "pre_start": False}, cache_seconds=300)
        _lead_name, _lead_title = _lead_byline()
        # #3252 — the SET, not the instance. This endpoint reads the SAME stored
        # EXPERT#integrator record the coaching-dashboard's `weekly_priority` block
        # reads, and it is the second surface that renders the integrator's
        # relative-time prose ("eleven days into the cycle"), on /coaching/'s week
        # lens. Fixing only the dashboard would leave this one unanchored, which is
        # precisely how #802 shipped ONE surface and left the door's first screen
        # lying (#1971's lesson). Same derived day number, same declared vintage.
        _wp_generated_at = _int_item.get("generated_at", "")
        return _ok(
            {
                "weekly_priority": _int_item.get("analysis", ""),
                "cross_domain_notes": _int_item.get("cross_domain_notes", {}),
                "generated_at": _wp_generated_at,
                "as_of_day_n": as_of_day_n(_wp_generated_at, _g["EXPERIMENT_START"]),
                "week_number": _int_item.get("week_number"),
                "coach_name": _lead_name,
                "coach_title": _lead_title,
                "pre_start": False,
            },
            cache_seconds=300,
            content_as_of=content_vintage(_wp_generated_at),
        )
    except Exception as _e:
        logger.warning(f"[/api/weekly_priority] {_e}")
        return _ok({"weekly_priority": None}, cache_seconds=60, degraded=_e)


def handle_month_rollup(*, _g):
    """GET /api/month_rollup — the integrator's month-altitude rollup (#1115).

    Reads the precomputed EXPERT#integrator_month record (written weekly by
    ai-expert-analyzer from the trailing ~4 weekly lab notes; honest-skipped
    while fewer than 2 week notes exist). Honest-null pre-start, while
    tombstoned after a reset (#946), when nothing is written yet (the designed
    early-cycle empty state — ADR-104), and when the stored record's day count
    outruns the live experiment day (a prior cycle's rollup is never served).
    """
    _current_day_n = _g["_current_day_n"]
    _lead_byline = _g["_lead_byline"]
    table = _g["table"]
    try:
        _pre = pre_start_meta()
        if _pre:
            return _ok({"narrative": None, **_pre}, cache_seconds=300)
        item = table.get_item(Key={"pk": f"{USER_PREFIX}ai_analysis", "sk": "EXPERT#integrator_month"}).get("Item")
        if not singleton_visible(item):
            return _ok({"narrative": None, "pre_start": False}, cache_seconds=300)
        item = _decimal_to_float(item)
        _lead_name, _lead_title = _lead_byline()
        rec_days = item.get("days_in_experiment")
        if rec_days is not None:
            try:
                if int(rec_days) > _current_day_n():
                    logger.info(
                        "[month_rollup] record claims day %s but current is %s — withholding stale rollup", rec_days, _current_day_n()
                    )
                    return _ok({"narrative": None, "pre_start": False}, cache_seconds=300)
            except (TypeError, ValueError):
                pass
        return _ok(
            {
                "narrative": item.get("narrative") or None,
                "headline": item.get("headline") or None,
                "week_count": item.get("week_count"),
                "window_label": item.get("window_label") or None,
                "generated_at": item.get("generated_at", ""),
                "coach_name": _lead_name,
                "coach_title": _lead_title,
                "pre_start": False,
            },
            cache_seconds=3600,
            # #3252 sibling sweep: the rollup is a weekly-written stored narrative —
            # declare the writer's own generated_at as the content's vintage.
            content_as_of=content_vintage(item.get("generated_at", "")),
        )
    except Exception as _e:
        logger.warning(f"[/api/month_rollup] {_e}")
        return _ok({"narrative": None}, cache_seconds=60, degraded=_e)
