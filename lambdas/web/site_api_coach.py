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

import json
import os
from datetime import datetime
from decimal import Decimal  # noqa: F401

import boto3
from boto3.dynamodb.conditions import Key
from phase_filter import with_phase_filter  # ADR-058

# CC-00/CC-09 shared-layer modules. Imported defensively so a site-api CODE deploy
# that lands BEFORE the layer (with these modules) is published doesn't break the
# whole handler — the coaches endpoints just serve shaped-empty 200s until the
# layer catches up. (CI ships code, not the layer — see handover gotcha #1.)
try:
    import coach_stance
    import persona_registry

    _COACH_MODULES = True
except Exception:  # pragma: no cover - exercised only during the layer-lag window
    coach_stance = None
    persona_registry = None
    _COACH_MODULES = False

from web.site_api_common import (
    EXPERIMENT_START,
    PT,
    USER_PREFIX,
    _decimal_to_float,
    _error,
    _load_s3_json,
    _ok,
    logger,
    table,
)

try:
    from constants import EXPERIMENT_BASELINE_WEIGHT_LBS
except Exception:  # pragma: no cover - constants always present in layer
    EXPERIMENT_BASELINE_WEIGHT_LBS = 306.87

# ── CC-00/01/02/09 — Coaches-as-Characters surfacing ─────────────────────────
_S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
_S3 = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-west-2"))

_DISCLOSURE = (
    "An AI character. Reads Matthew's real data and speaks in its own voice — "
    "correlative, never causal. The personality is a lens on real numbers, not a real person."
)


def _registry():
    return persona_registry.load_registry(_S3, _S3_BUCKET)


def _latest_weight_lbs():
    """Most recent Withings weight_lbs, or None (caller falls back to baseline)."""
    try:
        resp = table.query(
            **with_phase_filter(
                {
                    "KeyConditionExpression": Key("pk").eq(f"{USER_PREFIX}withings") & Key("sk").begins_with("DATE#"),
                    "ScanIndexForward": False,
                    "Limit": 5,
                }
            )
        )
        for it in resp.get("Items", []):
            w = _decimal_to_float(it).get("weight_lbs")
            if w:
                return float(w)
    except Exception as _e:
        logger.warning(f"[coaches] weight read: {_e}")
    return None


def _track_record(coach_id):
    """Confirmed/refuted hit-rate from the COACH#<id>/LEARNING# eval trail (CC-02).
    Honest pre-D-05: empty -> hit_rate None, preliminary True. Always labelled
    self-assessment, never external validation (ER-05)."""
    confirmed = refuted = 0
    recent = []
    try:
        resp = table.query(
            **with_phase_filter(
                {
                    "KeyConditionExpression": Key("pk").eq(f"COACH#{coach_id}") & Key("sk").begins_with("LEARNING#"),
                    "ScanIndexForward": False,
                    "Limit": 60,
                }
            )
        )
        for it in resp.get("Items", []):
            it = _decimal_to_float(it)
            st = it.get("status")
            if st == "confirmed":
                confirmed += 1
            elif st == "refuted":
                refuted += 1
            if st in ("confirmed", "refuted") and len(recent) < 6:
                recent.append(
                    {
                        "date": it.get("date") or it.get("sk", "").replace("LEARNING#", "").split("#")[0],
                        "status": st,
                        "metric": it.get("metric"),
                        "reason": it.get("reason", ""),
                    }
                )
    except Exception as _e:
        logger.warning(f"[coaches] track_record {coach_id}: {_e}")
    decided = confirmed + refuted
    return {
        "confirmed": confirmed,
        "refuted": refuted,
        "decided": decided,
        "hit_rate_pct": round(confirmed / decided * 100, 1) if decided else None,
        "preliminary": decided < 12,
        "n_note": "preliminary — fewer than 12 decided predictions" if decided < 12 else f"n={decided} decided",
        "recent": recent,
        "caveat": "Self-assessment of this coach's own calls — not external validation.",
    }


def _quality_trend(coach_id):
    """Quality-gate score trend if cached at COACH#<id>/QUALITY#, else empty.
    Always labelled self-assessment (ER-05)."""
    scores = []
    try:
        resp = table.query(
            **with_phase_filter(
                {
                    "KeyConditionExpression": Key("pk").eq(f"COACH#{coach_id}") & Key("sk").begins_with("QUALITY#"),
                    "ScanIndexForward": False,
                    "Limit": 14,
                }
            )
        )
        for it in resp.get("Items", []):
            it = _decimal_to_float(it)
            if it.get("score") is not None:
                scores.append({"date": it.get("sk", "").replace("QUALITY#", ""), "score": it.get("score")})
    except Exception:
        pass
    return {
        "scores": list(reversed(scores)),
        "caveat": "Self-assessment, not external validation (ER-05).",
    }


def _tuning_log_for(coach_id):
    """Tuning-changelog entries relevant to this coach (CC-03), newest first."""
    log = _load_s3_json("config/coaches/tuning_log.json", "tuning_log")
    entries = [e for e in log.get("entries", []) if e.get("coach") in (coach_id, "all")]
    return list(reversed(entries))[:10]


def _voice_subset(coach_config_key):
    """Curated, public-safe slice of a coach's voice spec for the page."""
    cfg = _load_s3_json(f"config/coaches/{coach_config_key}.json", "coach_cfg")
    examples = cfg.get("few_shot_examples") or []
    example = examples[0] if examples else None
    if isinstance(example, dict):
        example = example.get("output") or example.get("text") or example.get("example") or next(iter(example.values()), None)
    return {
        "decision_style": cfg.get("decision_style"),
        "structural_voice_rules": cfg.get("structural_voice_rules"),
        "few_shot_example": example,
    }


def _relationships(coach_id):
    """In/out influence-graph edges for this coach (top 3 each)."""
    g = _load_s3_json("config/coaches/influence_graph.json", "influence_graph")
    weights = g.get("weights", {})
    out_edges, in_edges = [], []
    for edge, w in weights.items():
        if "→" not in edge:
            continue
        src, dst = [x.strip() for x in edge.split("→")]
        if src == coach_id:
            out_edges.append({"coach": dst, "weight": w})
        elif dst == coach_id:
            in_edges.append({"coach": src, "weight": w})
    out_edges.sort(key=lambda e: -e["weight"])
    in_edges.sort(key=lambda e: -e["weight"])
    return {"leans_on": out_edges[:3], "leaned_on_by": in_edges[:3]}


def _character(p):
    """Public-safe personality slice from board_of_directors.json — the fictional
    background + traits that shape this coach's prompt. Config-only, no inference."""
    key = p.get("board_persona_key")
    if not key:
        return {}
    members = (_load_s3_json("config/board_of_directors.json", "board_dir") or {}).get("members", {})
    m = members.get(key) or {}
    if not m:
        return {}
    persn = m.get("personality") or {}
    voice = m.get("voice") or {}
    return {
        "title": m.get("title"),
        "principles": (m.get("principles") or [])[:5],
        "voice": {k: voice.get(k) for k in ("tone", "style", "catchphrase") if voice.get(k)},
        "tendencies": (persn.get("tendencies") or [])[:4],
        "signature_behavior": persn.get("signature_behavior"),
        "arc": persn.get("arc_seed"),
        "relationship_to_matthew": m.get("relationship_to_matthew"),
        "focus_areas": (m.get("focus_areas") or [])[:6],
    }


def _working_hypotheses(coach_id, limit=6):
    """Live working hypotheses: open THREAD# (observation/prediction/concern) + pending
    PREDICTION# claims. Already-computed by the coach engine; read-only here."""
    out = []
    try:
        tr = table.query(
            **with_phase_filter(
                {"KeyConditionExpression": Key("pk").eq(f"COACH#{coach_id}") & Key("sk").begins_with("THREAD#"), "Limit": 25}
            )
        )
        for it in tr.get("Items", []):
            d = _decimal_to_float(it)
            if (d.get("status") or "").lower() in ("open", "active") and d.get("summary"):
                out.append({"claim": d["summary"], "kind": d.get("type") or "thread", "since": d.get("created_date")})
    except Exception as _e:
        logger.warning(f"[coach] threads: {_e}")
    try:
        pr = table.query(
            **with_phase_filter(
                {"KeyConditionExpression": Key("pk").eq(f"COACH#{coach_id}") & Key("sk").begins_with("PREDICTION#"), "Limit": 25}
            )
        )
        for it in pr.get("Items", []):
            d = _decimal_to_float(it)
            if (d.get("status") or "").lower() in ("pending", "confirming") and d.get("claim_natural"):
                out.append({"claim": d["claim_natural"], "kind": "prediction", "status": d.get("status"), "since": d.get("created_date")})
    except Exception as _e:
        logger.warning(f"[coach] predictions: {_e}")
    return out[:limit]


def _coach_daily(coach_id):
    """CC-08: today's cached daily reflection for a coach (generated/coach_daily.json),
    or None. Read-only over the batch-written artifact — never inferenced here."""
    doc = _load_s3_json("generated/coach_daily.json", "coach_daily")
    r = (doc.get("reflections") or {}).get(coach_id)
    return r.get("text") if isinstance(r, dict) else None


def _recent_outputs(coach_id, limit=25):  # CC-07: depth for the daily-journey timeline
    out = []
    try:
        resp = table.query(
            **with_phase_filter(
                {
                    "KeyConditionExpression": Key("pk").eq(f"COACH#{coach_id}") & Key("sk").begins_with("OUTPUT#"),
                    "ScanIndexForward": False,
                    "Limit": limit,
                }
            )
        )
        for it in resp.get("Items", []):
            it = _decimal_to_float(it)
            out.append(
                {
                    "date": it.get("sk", "").replace("OUTPUT#", "").split("#")[0],
                    "summary": it.get("key_recommendation") or it.get("observatory_summary") or "",
                    "themes": it.get("themes", []),
                }
            )
    except Exception:
        pass
    return out


def _stance_block(coach_id, weight_lbs):
    """Resolve the coach's current stance rung from real data (CC-09).
    Falls back to the entry rung when the band metric isn't available yet."""
    stance = coach_stance.load_stance(coach_id, _S3, _S3_BUCKET)
    ladder = stance.get("stage_ladder", [])
    metric = stance.get("band_metric")
    value = weight_lbs if metric == "weight_lbs" else None
    rung = coach_stance.resolve_stage(ladder, value) or (ladder[0] if ladder else None)
    return {
        "band_metric": metric,
        "current_value": value,
        "rung": rung,
        "ladder": [{"stage_id": s.get("stage_id"), "headline": s.get("headline")} for s in ladder],
    }


def handle_coaches(event):
    """GET /api/coaches — the roster (CC-01). Shaped-empty 200 by design."""
    if not _COACH_MODULES:
        return _ok({"coaches": [], "count": 0, "disclosure": _DISCLOSURE}, cache_seconds=60)
    try:
        ops = {k: v for k, v in _registry().get("personas", {}).items() if v.get("operational")}
        order = persona_registry.OPERATIONAL_COACH_IDS
        coaches = []
        for pid, p in ops.items():
            tr = _track_record(pid)
            headline = (
                f"{tr['hit_rate_pct']:.0f}% hit-rate · n={tr['decided']}" if tr["hit_rate_pct"] is not None else "track record accruing"
            )
            coaches.append(
                {
                    "persona_id": pid,
                    "name": p.get("name"),
                    "domain": p.get("domain"),
                    "short_bio": p.get("short_bio"),
                    "emoji": p.get("emoji"),
                    "color": p.get("color"),
                    "board_role": p.get("board_role"),
                    "headline_stat": headline,
                }
            )
        coaches.sort(key=lambda c: order.index(c["persona_id"]) if c["persona_id"] in order else 99)
        return _ok({"coaches": coaches, "count": len(coaches), "disclosure": _DISCLOSURE}, cache_seconds=300)
    except Exception as _e:
        logger.warning(f"[/api/coaches] {_e}")
        return _ok({"coaches": [], "count": 0}, cache_seconds=60)


def _team_tensions():
    """Live cross-coach disagreements from the integrator digest (CC-10).
    Same source as get_coach_disagreements; honest empty pre-data."""
    try:
        item = table.get_item(Key={"pk": f"{USER_PREFIX}ai_analysis", "sk": "EXPERT#integrator"}).get("Item")
        if not item:
            return []
        item = _decimal_to_float(item)
        raw = item.get("disagreements") or item.get("active_disagreements") or []
        out = []
        for d in raw if isinstance(raw, list) else []:
            if not isinstance(d, dict):
                continue
            coaches = d.get("coaches_involved") or d.get("coaches") or []
            # WQA-06: the integrator digest stores the argument as position_a/position_b
            # + nakamura_call (the integrator's adjudication). Earlier code read the wrong
            # field names, so the head-to-head came back empty. Read the real names first.
            out.append(
                {
                    "topic": d.get("topic") or d.get("domain") or "",
                    "coaches": coaches,
                    "position_a": d.get("position_a") or d.get("coach_a_position"),
                    "position_b": d.get("position_b") or d.get("coach_b_position"),
                    "resolution": (d.get("nakamura_call") or d.get("resolution_suggested") or d.get("tension") or d.get("summary") or ""),
                }
            )
        return out
    except Exception as _e:
        logger.warning(f"[coach_team] tensions: {_e}")
        return []


def _lead_block(team_focus):
    """The Principal Investigator (Dr. Eli Marsh) — the lead above the 8 coaches.
    A non-operational orchestrator persona; surfaced as the head of the team."""
    lp = _registry().get("personas", {}).get("eli_marsh")
    if not lp:
        return None
    return {
        "persona_id": "eli_marsh",
        "name": lp.get("name"),
        "emoji": lp.get("emoji"),
        "color": lp.get("color"),
        "role": lp.get("board_role"),
        "short_bio": lp.get("short_bio"),
        "philosophy": lp.get("philosophy"),
        "expertise": lp.get("expertise", []),
        "staff_focus": (team_focus or [])[:3],  # what he's got the staff focused on
    }


def handle_panel_ledger(event):
    """GET /api/panel_ledger — The Panel's running bet scoreboard (the proof-of-honesty
    artifact) + the current open bet. Reads the podcast series_state (PANELCAST#).
    Shaped-empty 200 before the first weekly episode."""
    try:
        it = table.get_item(Key={"pk": f"{USER_PREFIX}panelcast", "sk": "STATE#current"}).get("Item")
        state = json.loads(it.get("state_json", "{}")) if it else {}
    except Exception as _e:
        logger.warning(f"[panel_ledger] {_e}")
        state = {}
    ledger = state.get("bet_ledger", [])
    record = {o: sum(1 for b in ledger if b.get("outcome") == o) for o in ("won", "lost", "open")}
    return _ok(
        {
            "open_bet": state.get("open_bet"),
            "episode_count": state.get("episode_count", 0),
            "ledger": list(reversed(ledger)),  # newest first
            "record": record,
            "disclosure": "The coaches make falsifiable calls; we score them against real data, hits and misses alike.",
        },
        cache_seconds=300,
    )


def handle_coach_team(event):
    """GET /api/coach_team — the "My Team" view (CC-10): the team's collective read
    on Matthew right now. Stance focus + per-coach huddle + the live tension map.
    All from CC-09 stance + the integrator digest; no new inference. Shaped-empty 200."""
    if not _COACH_MODULES:
        return _ok({"huddle": [], "team_focus": [], "tensions": []}, cache_seconds=60)
    try:
        ops = {k: v for k, v in _registry().get("personas", {}).items() if v.get("operational")}
        weight = _latest_weight_lbs() or EXPERIMENT_BASELINE_WEIGHT_LBS
        huddle, focus, stages = [], [], {}
        for pid in persona_registry.OPERATIONAL_COACH_IDS:
            p = ops.get(pid)
            if not p:
                continue
            rung = _stance_block(pid, weight).get("rung") or {}
            stages[pid] = rung.get("stage_id")
            cares = rung.get("cares_most") or []
            if cares:
                focus.append(cares[0])
            watches = rung.get("watches") or []
            huddle.append(
                {
                    "persona_id": pid,
                    "name": p.get("name"),
                    "emoji": p.get("emoji"),
                    "stage_id": rung.get("stage_id"),
                    "headline": rung.get("headline"),
                    "read_of_him": rung.get("read_of_him"),
                    "watch": watches[0] if watches else None,
                    "graduation_gate": rung.get("graduation_gate"),
                }
            )
        seen = set()
        team_focus = [f for f in focus if not (f in seen or seen.add(f))]
        all_same = len(set(stages.values())) == 1 and bool(stages)
        return _ok(
            {
                "as_of_weight_lbs": weight,
                "lead": _lead_block(team_focus),
                "team_focus": team_focus,
                "huddle": huddle,
                "tensions": _team_tensions(),
                "all_same_stage": all_same,
                "current_stage": next(iter(stages.values())) if all_same else None,
                "disclosure": _DISCLOSURE,
            },
            cache_seconds=300,
        )
    except Exception as _e:
        logger.warning(f"[/api/coach_team] {_e}")
        return _ok({"huddle": [], "team_focus": [], "tensions": []}, cache_seconds=60)


def handle_coach(event):
    """GET /api/coach/{persona_id} (or ?id=) — one coach page (CC-01 + CC-02)."""
    if not _COACH_MODULES:
        return _ok({"persona_id": None, "stance": {}, "report_card": {}}, cache_seconds=60)
    try:
        path = event.get("rawPath") or (event.get("requestContext", {}).get("http", {}) or {}).get("path") or ""
        qs = event.get("queryStringParameters") or {}
        pid = (qs.get("id") or path.rstrip("/").split("/")[-1] or "").strip()
        p = _registry().get("personas", {}).get(pid)
        if not p or not p.get("operational"):
            return _error(404, "Unknown coach")
        weight = _latest_weight_lbs() or EXPERIMENT_BASELINE_WEIGHT_LBS
        return _ok(
            {
                "persona_id": pid,
                "name": p.get("name"),
                "domain": p.get("domain"),
                "short_bio": p.get("short_bio"),
                "emoji": p.get("emoji"),
                "color": p.get("color"),
                "board_role": p.get("board_role"),
                "type": p.get("type"),
                "disclosure": _DISCLOSURE,
                "character": _character(p),
                "working_hypotheses": _working_hypotheses(pid),
                "stance": _stance_block(pid, weight),
                "voice": _voice_subset(p["coach_config_key"]),
                "relationships": _relationships(pid),
                "report_card": {
                    "track_record": _track_record(pid),
                    "quality_trend": _quality_trend(pid),
                    "tuning_log": _tuning_log_for(pid),
                },
                "recent_outputs": _recent_outputs(pid),
                "daily": _coach_daily(pid),
            },
            cache_seconds=300,
        )
    except Exception as _e:
        logger.warning(f"[/api/coach] {_e}")
        return _ok({"persona_id": None, "stance": {}, "report_card": {}}, cache_seconds=60)


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
                    "week_label": item.get("week_label"),
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
                # Genesis-anchored display label (Week N / Prologue) — the raw `week` is an
                # ISO calendar week (2026-W25) that read "w24/w25" on the site (#2). Producer
                # writes week_label; falls back to the ISO week until the backfill lands.
                "week_label": i.get("week_label"),
                "ai_tone": i.get("ai_tone", "mixed"),
                "ai_generated_at": i.get("ai_generated_at"),
                "has_matthew_response": bool(i.get("matthew_agreement")),
            }
            for i in items
        ]
        return _ok({"entries": entries, "count": len(entries)}, cache_seconds=300)

    # AI Analysis (GET with ?expert= query param)


def handle_experiment_synthesis():
    """GET /api/experiment_synthesis — the board's cross-week arc of the whole run (C-1).

    Reads the precomputed EXPERT#experiment_arc record (written by ai-expert-analyzer
    once >=2 weeks of lab notes exist). Honest-null before then; the Experiment view
    falls back to its week-by-week tone list.
    """
    ai_pk = f"{USER_PREFIX}ai_analysis"
    item = table.get_item(Key={"pk": ai_pk, "sk": "EXPERT#experiment_arc"}).get("Item")
    if not item:
        return _ok({"arc": None, "throughline": None, "chapters": [], "week_count": 0, "generated_at": None}, cache_seconds=300)
    item = _decimal_to_float(item)
    return _ok(
        {
            "arc": item.get("arc"),
            "throughline": item.get("throughline"),
            "chapters": item.get("chapters", []),
            "week_count": int(item.get("week_count") or 0),
            "generated_at": item.get("generated_at"),
        },
        cache_seconds=300,
    )


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
