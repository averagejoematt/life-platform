"""
lambdas/web/site_api_coach.py — coach intelligence + miscellaneous handlers.

Extracted from lambdas/web/site_api_lambda.py (P1.1 Phase B extension, 2026-05-27).

These were previously inline `if path == "/api/X":` blocks at the bottom
of lambda_handler. Each block did custom query-param parsing + DDB lookup,
so they didn't fit the ROUTES dispatch pattern (which calls handlers
with no args). Now they're proper functions taking event, callable from
the dispatcher as `return handle_X(event)`.

Endpoints:
  /api/field_notes      — weekly Field Notes (optional ?week= param)
  /api/ai_analysis      — cached AI expert analysis (?expert= param)
  /api/coach_analysis   — coach intelligence dashboard (?domain= param)
  /api/predictions      — coach prediction ledger (?status=&coach_id=&limit=)
  /api/coach_timeline   — coach thread timeline (?coach_id= param)
  /api/weekly_priority  — integrator synthesis (cross-domain weekly priority)
"""

from datetime import datetime
from decimal import Decimal  # noqa: F401

from boto3.dynamodb.conditions import Key
from phase_filter import with_phase_filter  # ADR-058

from web.site_api_common import (
    EXPERIMENT_START,
    PT,
    USER_PREFIX,
    _decimal_to_float,
    _error,
    _ok,
    logger,
    table,
)


def _current_day_n() -> int:
    """Day-of-experiment (1-indexed) under the active EXPERIMENT_START_DATE.
    Used by Stage0 Fix 3 freshness guard to refuse to serve generated
    narrative that claims a day count newer than the live experiment."""
    today = datetime.now(PT).date()
    try:
        start = datetime.strptime(EXPERIMENT_START, "%Y-%m-%d").date()
    except Exception:
        return 0
    return max((today - start).days + 1, 0)


def handle_field_notes(event):
    """GET /api/field_notes"""
    qs = event.get("queryStringParameters") or {}
    week_param = qs.get("week")
    fn_pk = f"{USER_PREFIX}field_notes"

    if week_param:
        # Single entry mode
        item = table.get_item(Key={"pk": fn_pk, "sk": f"WEEK#{week_param}"}).get("Item")
        if not item:
            return _ok({"entry": None, "week": week_param}, cache_seconds=300)
        item = _decimal_to_float(item)
        return _ok(
            {
                "entry": {
                    "week": item.get("week", week_param),
                    "ai_present": item.get("ai_present", ""),
                    "ai_cautionary": item.get("ai_cautionary"),
                    "ai_affirming": item.get("ai_affirming"),
                    "ai_tone": item.get("ai_tone", "mixed"),
                    "ai_generated_at": item.get("ai_generated_at"),
                    "matthew_agreement": item.get("matthew_agreement"),
                    "matthew_logged_at": item.get("matthew_logged_at"),
                }
            },
            cache_seconds=300,
        )
    else:
        # List mode — return all weeks (most recent first)
        resp = table.query(
            **with_phase_filter(
                {  # ADR-058: hide pilot field notes
                    "KeyConditionExpression": Key("pk").eq(fn_pk),
                    "ScanIndexForward": False,
                    "Limit": 52,
                }
            )
        )
        items = _decimal_to_float(resp.get("Items", []))
        entries = [
            {
                "week": i.get("week", i.get("sk", "").replace("WEEK#", "")),
                "ai_tone": i.get("ai_tone", "mixed"),
                "ai_generated_at": i.get("ai_generated_at"),
                "has_matthew_response": bool(i.get("matthew_agreement")),
            }
            for i in items
        ]
        return _ok({"entries": entries, "count": len(entries)}, cache_seconds=300)

    # AI Analysis (GET with ?expert= query param)


def handle_ai_analysis(event):
    """GET /api/ai_analysis"""
    qs = event.get("queryStringParameters") or {}
    expert_key = qs.get("expert", "mind")
    if expert_key not in ("mind", "nutrition", "training", "physical", "explorer", "labs", "glucose", "sleep"):
        return _error(400, "Invalid expert key")
    ai_pk = f"{USER_PREFIX}ai_analysis"
    ai_item = table.get_item(Key={"pk": ai_pk, "sk": f"EXPERT#{expert_key}"}).get("Item")
    if not ai_item:
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

    # Coach Intelligence Analysis (GET with ?domain= query param)


def handle_coach_analysis(event):
    """GET /api/coach_analysis"""
    qs = event.get("queryStringParameters") or {}
    raw_domain = qs.get("domain", "sleep")
    _coach_map = {
        "sleep": "sleep_coach",
        "nutrition": "nutrition_coach",
        "training": "training_coach",
        "mind": "mind_coach",
        "physical": "physical_coach",
        "glucose": "glucose_coach",
        "labs": "labs_coach",
        "explorer": "explorer_coach",
    }
    # The Cockpit (/now/) discloses the 7 CHARACTER PILLARS, whose names differ from the
    # coach-domain names above — alias them so a pillar click resolves to the right coach.
    _pillar_alias = {"movement": "training", "metabolic": "glucose"}
    # Pillars with no dedicated board coach: return a graceful empty read (200), not a 400,
    # so the Cockpit shows its deterministic fallback without a console error.
    _no_coach_pillars = {"relationships", "consistency"}
    domain = _pillar_alias.get(raw_domain, raw_domain)
    coach_id = _coach_map.get(domain)
    if not coach_id:
        if raw_domain in _no_coach_pillars:
            return _ok({"coach_id": None, "domain": raw_domain, "analysis": None}, cache_seconds=600)
        return _error(400, f"Invalid domain. Use one of: {', '.join(sorted(_coach_map))}")

    _coach_display = {
        "sleep_coach": {"name": "Dr. Lisa Park", "initials": "LP", "title": "Sleep & Circadian Rhythm Specialist", "color": "#818cf8"},
        "nutrition_coach": {"name": "Dr. Marcus Webb", "initials": "MW", "title": "Evidence-Based Nutrition", "color": "#10b981"},
        "training_coach": {"name": "Dr. Sarah Chen", "initials": "SC", "title": "Exercise Physiology & Strength", "color": "#3db88a"},
        "mind_coach": {
            "name": "Dr. Nathan Reeves",
            "initials": "NR",
            "title": "Psychiatrist \u2014 Behavioral Patterns",
            "color": "#a78bfa",
        },
        "physical_coach": {"name": "Dr. Victor Reyes", "initials": "VR", "title": "Longevity & Body Composition", "color": "#f59e0b"},
        "glucose_coach": {"name": "Dr. Amara Patel", "initials": "AP", "title": "Metabolic Health & CGM", "color": "#2dd4bf"},
        "labs_coach": {"name": "Dr. James Okafor", "initials": "JO", "title": "Clinical Pathology & Preventive Labs", "color": "#5ba4cf"},
        "explorer_coach": {"name": "Dr. Henning Brandt", "initials": "HB", "title": "Biostatistics & N=1 Research", "color": "#e879f9"},
    }

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

        # 3. Ensemble digest — cross-coach references
        cross_coach_reference = None
        try:
            dig_resp = table.query(
                KeyConditionExpression=Key("pk").eq("ENSEMBLE#digest") & Key("sk").begins_with("CYCLE#"),
                ScanIndexForward=False,
                Limit=1,
            )
            dig_items = dig_resp.get("Items", [])
            if dig_items:
                digest = _decimal_to_float(dig_items[0])
                disagreements = digest.get("active_disagreements", [])
                for d in disagreements:
                    coaches = d.get("coaches", [])
                    if coach_id in coaches:
                        cross_coach_reference = d.get("topic", "")
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
        resp = {
            "coach_id": coach_id,
            "coach_name": display.get("name", ""),
            "coach_initials": display.get("initials", ""),
            "coach_title": display.get("title", ""),
            "coach_color": display.get("color", ""),
            "domain": domain,
            "analysis": analysis_text,
            "key_recommendation": output.get("key_recommendation") or (output.get("themes", [""])[0] if output.get("themes") else None),
            "elena_quote": output.get("elena_quote"),
            "journaling_prompt": output.get("journaling_prompt"),
            "thread_reference": thread_reference,
            "revision_signal": revision_signal,
            "cross_coach_reference": cross_coach_reference,
            "confidence_language": confidence_language,
            "data_availability": data_availability,
            "generated_at": output.get("created_at") or output.get("generated_at", ""),
            "week_number": output.get("week_number"),
            "days_in_experiment": output.get("days_in_experiment"),
        }

        # Add cross-domain context note from the integrator (if available)
        try:
            _int_resp = table.get_item(Key={"pk": f"{USER_PREFIX}ai_analysis", "sk": "EXPERT#integrator"})
            _int_item = _decimal_to_float(_int_resp.get("Item", {}))
            _cdn = _int_item.get("cross_domain_notes", {})
            if isinstance(_cdn, dict) and domain in _cdn:
                resp["cross_domain_note"] = _cdn[domain]
            if _int_item.get("analysis"):
                resp["weekly_priority"] = _int_item["analysis"]
        except Exception:
            pass

        # Strip None values for cleaner JSON
        resp = {k: v for k, v in resp.items() if v is not None}
        return _ok(resp, cache_seconds=300)
    except Exception as _e:
        logger.warning(f"[/api/coach_analysis] {_e}")
        return _ok({"coach_id": coach_id, "domain": domain, "analysis": None}, cache_seconds=60)

    # Coaching Dashboard (GET — assembled dashboard data)


def handle_predictions(event):
    """GET /api/predictions"""
    try:
        qs = event.get("queryStringParameters") or {}
        status_filter = qs.get("status", "all")
        coach_filter = qs.get("coach_id", "")
        limit = min(int(qs.get("limit", "50")), 200)

        _pred_coach_names = {
            "sleep": "Dr. Lisa Park",
            "nutrition": "Dr. Marcus Webb",
            "training": "Dr. Sarah Chen",
            "mind": "Dr. Nathan Reeves",
            "physical": "Dr. Victor Reyes",
            "glucose": "Dr. Amara Patel",
            "labs": "Dr. James Okafor",
            "explorer": "Dr. Henning Brandt",
        }
        _pred_coach_ids = list(_pred_coach_names.keys())
        _pred_coach_id_map = {
            "sleep": "sleep_coach",
            "nutrition": "nutrition_coach",
            "training": "training_coach",
            "mind": "mind_coach",
            "physical": "physical_coach",
            "glucose": "glucose_coach",
            "labs": "labs_coach",
            "explorer": "explorer_coach",
        }

        if coach_filter and coach_filter not in _pred_coach_ids:
            return _error(400, "Invalid coach_id")

        scan_coaches = [coach_filter] if coach_filter else _pred_coach_ids
        all_predictions = []
        by_coach = {}

        for cid in scan_coaches:
            coach_pk = f"COACH#{_pred_coach_id_map[cid]}"
            by_coach[cid] = {"total": 0, "confirmed": 0, "refuted": 0, "pending": 0}

            try:
                out_resp = table.query(
                    **with_phase_filter(
                        {  # ADR-058: hide pilot predictions
                            "KeyConditionExpression": Key("pk").eq(coach_pk) & Key("sk").begins_with("OUTPUT#"),
                            "ScanIndexForward": False,
                            "Limit": 12,
                        }
                    )
                )
                for out_item in out_resp.get("Items", []):
                    out_item = _decimal_to_float(out_item)
                    preds = out_item.get("predictions", [])
                    out_date = out_item.get("sk", "").replace("OUTPUT#", "")
                    if not isinstance(preds, list):
                        continue
                    for p in preds:
                        if not isinstance(p, dict):
                            continue
                        p_status = p.get("status", "pending")
                        by_coach[cid]["total"] += 1
                        if p_status in ("confirmed", "refuted", "pending"):
                            by_coach[cid][p_status] += 1
                        else:
                            by_coach[cid]["pending"] += 1

                        if status_filter != "all" and p_status != status_filter:
                            continue

                        all_predictions.append(
                            {
                                "coach_id": cid,
                                "coach_name": _pred_coach_names[cid],
                                "text": p.get("text", p.get("prediction", "")),
                                "confidence": p.get("confidence", "medium"),
                                "status": p_status,
                                "date": out_date,
                                "target_date": p.get("target_date", ""),
                            }
                        )
            except Exception:
                pass

        # Sort predictions by date descending
        all_predictions.sort(key=lambda x: x.get("date", ""), reverse=True)
        all_predictions = all_predictions[:limit]

        # Compute overall stats
        total = sum(c["total"] for c in by_coach.values())
        confirmed = sum(c["confirmed"] for c in by_coach.values())
        refuted = sum(c["refuted"] for c in by_coach.values())
        pending = sum(c["pending"] for c in by_coach.values())
        resolved = confirmed + refuted
        accuracy_pct = round(confirmed / resolved * 100, 1) if resolved > 0 else 0

        return _ok(
            {
                "overall": {
                    "total": total,
                    "confirmed": confirmed,
                    "refuted": refuted,
                    "pending": pending,
                    "accuracy_pct": accuracy_pct,
                },
                "by_coach": by_coach,
                "predictions": all_predictions,
            },
            cache_seconds=300,
        )
    except Exception as _e:
        logger.warning(f"[/api/predictions] {_e}")
        return _ok({"overall": {}, "by_coach": {}, "predictions": []}, cache_seconds=60)

    # Coach Learning Timeline (GET with ?coach_id= query param)


def handle_coach_timeline(event):
    """GET /api/coach_timeline"""
    try:
        qs = event.get("queryStringParameters") or {}
        coach_id = qs.get("coach_id", "")

        _tl_coach_names = {
            "sleep": "Dr. Lisa Park",
            "nutrition": "Dr. Marcus Webb",
            "training": "Dr. Sarah Chen",
            "mind": "Dr. Nathan Reeves",
            "physical": "Dr. Victor Reyes",
            "glucose": "Dr. Amara Patel",
            "labs": "Dr. James Okafor",
            "explorer": "Dr. Henning Brandt",
        }
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
        return _ok({"coach_id": "", "coach_name": "", "milestones": []}, cache_seconds=60)

    # Weekly Priority (GET — integrator synthesis)


def handle_weekly_priority(event):
    """GET /api/weekly_priority"""
    try:
        _int_resp = table.get_item(Key={"pk": f"{USER_PREFIX}ai_analysis", "sk": "EXPERT#integrator"})
        _int_item = _decimal_to_float(_int_resp.get("Item", {}))
        if not _int_item:
            return _ok({"weekly_priority": None, "cross_domain_notes": {}}, cache_seconds=300)
        return _ok(
            {
                "weekly_priority": _int_item.get("analysis", ""),
                "cross_domain_notes": _int_item.get("cross_domain_notes", {}),
                "generated_at": _int_item.get("generated_at", ""),
                "week_number": _int_item.get("week_number"),
                "coach_name": "Dr. Kai Nakamura",
                "coach_title": "Integrative Health Director",
            },
            cache_seconds=300,
        )
    except Exception as _e:
        logger.warning(f"[/api/weekly_priority] {_e}")
        return _ok({"weekly_priority": None}, cache_seconds=60)
