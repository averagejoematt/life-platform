"""coach_summarizer_support.py — deterministic builders behind the history summarizer (#2428).

Split from coach_history_summarizer.py to pay the module-size ratchet when the
compression path joined the module's ADR-104 gate: the structural fallback
compressed state and the LEARNING#/CONFIDENCE# track-record rollup are pure
functions over already-read records — no AWS clients, no LLM calls, no gate
decisions. The summarizer stays the only orchestrator, and ADR-141 screening
stays with it: the rollup takes the screen as a callable, so raw conversation
takeaway text still has exactly one route into a publicly-served prompt
(coach_history_summarizer._screened_takeaway).
"""

from datetime import datetime, timezone


def build_fallback_compressed_state(coach_id, meta, state):
    """Build a minimal compressed state when the LLM call fails.

    Better than nothing — preserves structural data without AI narrative.
    """
    now_iso = datetime.now(timezone.utc).isoformat()

    # Derive last output date from outputs
    outputs = state.get("outputs", [])
    last_output_date = None
    if outputs:
        for output in outputs:
            sk = output.get("sk", "")
            if sk.startswith("OUTPUT#"):
                date_part = sk.replace("OUTPUT#", "").split("#")[0]
                if date_part:
                    last_output_date = date_part
                    break

    # Build confidence state from records
    confidence_state = {}
    for conf in state.get("confidence_records", []):
        subdomain = conf.get("subdomain", conf.get("sk", "").replace("CONFIDENCE#", ""))
        mean = conf.get("mean_confidence", 0.5)
        confidence_state[subdomain] = round(mean, 3)

    # Extract recent themes from last 5 outputs
    recent_themes = []
    for output in outputs[:5]:
        for theme in output.get("themes", []):
            if theme not in recent_themes:
                recent_themes.append(theme)
                if len(recent_themes) >= 10:
                    break
        if len(recent_themes) >= 10:
            break

    return {
        "coach_id": coach_id,
        "display_name": meta["display_name"],
        "domain": meta["domain"],
        "summary": f"[FALLBACK — LLM compression failed] Coach {meta['display_name']} "
        f"has {len(outputs)} outputs, "
        f"{len(state.get('open_threads', []))} open threads, "
        f"{len(state.get('active_predictions', []))} active predictions. "
        f"Manual review recommended.",
        "key_concerns": [],
        "key_recommendations": [],
        "active_threads": [
            {"id": t.get("sk", "").replace("THREAD#", ""), "summary": t.get("summary", "")} for t in state.get("open_threads", [])[:5]
        ],
        "active_predictions": [
            {
                "id": p.get("prediction_id", p.get("sk", "").replace("PREDICTION#", "")),
                "claim": p.get("claim_natural", ""),
                "status": p.get("status", "pending"),
            }
            for p in state.get("active_predictions", [])[:5]
        ],
        "confidence_state": confidence_state,
        "recent_themes": recent_themes[:10],
        "positions_taken": [],
        "corrections_made": [],
        "relationship_notes": "",
        "last_output_date": last_output_date,
        "compressed_at": now_iso,
        "_fallback": True,
        # #2428: deterministic-by-construction — every field is copied or counted from
        # stored records, no LLM text, so it clears the compression gate trivially and
        # may keep grounding board-answer prompts (site_api_ai_lambda._coach_memory_bits).
        "grounding_gated": True,
    }


def summarize_track_record(learning, confidence_records, screened_takeaway):
    """Reduce LEARNING#/CONFIDENCE# into the grounding block the stance reasons from.

    Mirrors the hit/miss accounting site_api_coach._track_record surfaces publicly,
    so the stance's self-assessment agrees with the coach page's headline stat.

    #1481 (ADR-141): conversation-channel learnings are split out — they carry
    Matthew's own words, never a graded verdict, so they ground the stance as a
    DISTINCT evidence class and are structurally excluded from the hit rate.
    """
    _hit = {"confirmed", "correct", "hit", "true"}
    _miss = {"refuted", "incorrect", "miss", "false"}
    confirmed = refuted = 0
    recent = []
    conversation_recent = []
    conversation_count = 0
    concessions = []  # #1386: docket disputes this coach LOST — future reads must cite them
    concession_count = 0
    for rec in learning or []:
        if (rec.get("channel") or "data") == "conversation":
            conversation_count += 1
            if len(conversation_recent) < 6:
                conversation_recent.append(
                    {
                        "date": rec.get("date") or rec.get("sk", "").replace("LEARNING#", "").split("#")[0],
                        "subdomain": rec.get("subdomain", ""),
                        "confidence_direction": rec.get("confidence_direction", "hold"),
                        # ADR-141 §4 (#1789): no verbatim answer text in the stance
                        # grounding message — STANCE# prose serves publicly — and the
                        # coach's own takeaway crosses only through the deterministic
                        # screen (the numeric gates downstream read digits, not
                        # semantics). checkin_id is the pointer for audit.
                        "takeaway": screened_takeaway(rec),
                        "checkin_id": rec.get("checkin_id", ""),
                    }
                )
            continue  # never in the verdict tally — hit rates stay data-derived
        verdict = (rec.get("verdict") or rec.get("outcome") or rec.get("result") or "").lower()
        if verdict in _hit:
            confirmed += 1
        elif verdict in _miss:
            refuted += 1
        # #1386: a lost docket dispute wrote its concession VERBATIM to this
        # coach's memory — surface it as a standing, citable evidence class
        # (it also counts as a refuted verdict above, channel=data).
        if rec.get("record_type") == "docket_concession":
            concession_count += 1
            if len(concessions) < 5:
                concessions.append(
                    {
                        "date": rec.get("date") or rec.get("sk", "").replace("LEARNING#", "").split("#")[0],
                        "topic": rec.get("topic", ""),
                        "concession": rec.get("concession", ""),
                        "docket_ref": rec.get("docket_ref", ""),
                    }
                )
        if len(recent) < 8:
            recent.append(
                {
                    "date": rec.get("sk", "").replace("LEARNING#", "").split("#")[0],
                    "verdict": verdict or "pending",
                    "claim": (rec.get("claim_natural") or rec.get("claim") or "")[:160],
                }
            )
    decided = confirmed + refuted
    confidence = {}
    confidence_provenance = {}
    for conf in confidence_records or []:
        sub = conf.get("subdomain", conf.get("sk", "").replace("CONFIDENCE#", ""))
        confidence[sub] = round(conf.get("mean_confidence", 0.5), 3)
        confidence_provenance[sub] = conf.get("source") or "data"
    return {
        "confirmed": confirmed,
        "refuted": refuted,
        "decided": decided,
        "hit_rate_pct": round(100 * confirmed / decided) if decided else None,
        "recent": recent,
        "confidence": confidence,
        "confidence_provenance": confidence_provenance,
        "conversation_learnings": {
            "count": conversation_count,
            "recent": conversation_recent,
            "note": (
                "channel=conversation — what this coach learned from Matthew's own check-in answers "
                "(self-graded, bounded). A different evidence class than the data-derived verdicts above; "
                "never counted in the hit rate."
            ),
        },
        "standing_concessions": {
            "count": concession_count,
            "recent": concessions,
            "note": (
                "Docket disputes this coach LOST (#1386) — resolved by deterministic code against a "
                "criterion agreed at open, concession recorded verbatim. When the stance touches one of "
                "these topics it must cite the concession, never relitigate it."
            ),
        },
    }
