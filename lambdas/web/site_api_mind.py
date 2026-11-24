"""lambdas/web/site_api_mind.py — mind/journal endpoints (journal_analysis, mind_overview).

Split out of site_api_observatory.py (#1654 slice 3 — god-module breakup). The
routed handler entrypoints stay in the site_api_observatory facade as thin
delegators; this module holds the logic. Handlers receive the facade's globals()
as `_g` and read the monkeypatched/injectable state (table / _query_source /
_experiment_date / EXPERIMENT_START) via `_g["<name>"]`. This module does NOT
import the facade — no import cycle. All other shared helpers come straight from
site_api_common (identical binding semantics to the pre-split facade).
"""

from datetime import datetime, timedelta

from boto3.dynamodb.conditions import Key
from experiment.phase_filter import with_phase_filter  # ADR-058
from health import character_privacy  # owner ruling 2026-11-05: the Mind pillar served is the public variant

from web.site_api_common import (
    PT,
    USER_PREFIX,
    _decimal_to_float,
    _ok,
)

JOURNAL_PRIVATE_TEXT = "The journal is private: what is written, and whether or when, is not published."


def journal_analysis(*, _g) -> dict:
    """
    GET /api/journal_analysis — PRIVATE since the owner's ruling of 2026-11-03.

    "Treat journal activity and journal-derived metadata as private by default, including structured
    data." Every field this route served was journal-derived: the per-day themes and sentiment, the
    analysed-entry dates (whether and when he wrote), the entry count and the theme percentages over
    it. ``journal_analysis`` is a private source family (``common.narrative_provenance``), so the
    route reads nothing and serves the honest empty shape — the same body whatever the journal holds.
    The analysis rows stay stored for the owner's own tools.
    Cache: 3600s.
    """
    today = datetime.now(PT).strftime("%Y-%m-%d")  # #2414: the reader's "today" is the Pacific day
    return _ok(
        {
            "daily_themes": [],
            "top_themes": [],
            "total_analyzed": None,
            "date_range": {"start": None, "end": today},
            "sentiment_trend": [],
            "private": JOURNAL_PRIVATE_TEXT,
        },
        cache_seconds=3600,
    )


def mind_overview(*, _g) -> dict:
    """
    GET /api/mind_overview
    Returns: vice streaks, social connection quality,
    mind pillar score, cognitive patterns (when journal data is available).
    Cache: 3600s.
    """
    table = _g["table"]
    _query_source = _g["_query_source"]
    _experiment_date = _g["_experiment_date"]
    today = datetime.now(PT).strftime("%Y-%m-%d")  # #2414: the reader's "today" is the Pacific day
    yesterday = (datetime.now(PT) - timedelta(days=1)).strftime("%Y-%m-%d")
    d30 = _experiment_date(30)
    d90 = _experiment_date(90)

    # ── 1. Mind pillar from character_sheet ──
    mind_pillar = None
    cs_pk = f"{USER_PREFIX}character_sheet"
    for date_str in [today, yesterday]:
        resp = table.get_item(Key={"pk": cs_pk, "sk": f"DATE#{date_str}"})
        record = character_privacy.public_sheet(_decimal_to_float(resp.get("Item")))  # the public variant only (2026-11-05)
        if record:
            mp = record.get("pillar_mind", {})
            mind_pillar = {
                "level": float(mp.get("level", 1)),
                "raw_score": float(mp.get("raw_score", 0)),
                "tier": mp.get("tier", "Foundation"),
            }
            if mp.get("not_instrumented"):  # owner ruling 2026-11-06: insufficient public data is a state, never a 0.0
                mind_pillar = {
                    "level": None,
                    "raw_score": None,
                    "tier": None,
                    "state": "unavailable",
                    "note": mp.get("not_instrumented_note"),
                }
            break

    # ── 2. (retired) The State-of-Mind mood read (How We Feel check-ins) — private activity (owner
    #    ruling 2026-11-05: its entries, average and count are omitted, common.activity_publication's
    #    STATE_OF_MIND_FIELDS); the owner's own tools read the rows directly. Not read here.

    # ── 3. (withheld) Restraint streaks — #6224, owner ruling 2026-11-23: no restraint streak, count or held/total
    #    is published without his explicit approval, and none was found. The nameless rows let a reader count the
    #    private categories and read their behaviour, and the stored daily held/total counted the never-public
    #    categories too. Both fields stay in the payload, always empty; nothing is read for them.
    vice_data: list = []

    # ── 4. Social connection quality (interactions) ──
    int_pk = f"{USER_PREFIX}interactions"
    try:
        int_resp = table.query(
            **with_phase_filter(
                {  # ADR-058: hide pilot interactions
                    "KeyConditionExpression": Key("pk").eq(int_pk) & Key("sk").between(f"DATE#{d30}", f"DATE#{today}~"),
                    "ScanIndexForward": True,
                }
            )
        )
        interactions = _decimal_to_float(int_resp.get("Items", []))
    except Exception:
        interactions = []

    total_interactions = len(interactions)
    depth_counts = {"surface": 0, "meaningful": 0, "deep": 0}
    for i in interactions:
        d = (i.get("depth") or "surface").lower()
        if d in depth_counts:
            depth_counts[d] += 1
    meaningful_pct = round((depth_counts["meaningful"] + depth_counts["deep"]) / total_interactions * 100) if total_interactions else 0

    # ── 5. Temptation resist rate (90d) ──
    temp_pk = f"{USER_PREFIX}temptations"
    try:
        temp_resp = table.query(
            **with_phase_filter(
                {  # ADR-058: hide pilot temptations
                    "KeyConditionExpression": Key("pk").eq(temp_pk) & Key("sk").between(f"DATE#{d90}", f"DATE#{today}~"),
                }
            )
        )
        temptations = _decimal_to_float(temp_resp.get("Items", []))
    except Exception:
        temptations = []

    total_temptations = len(temptations)
    resisted = sum(1 for t in temptations if t.get("resisted"))
    resist_rate = round(resisted / total_temptations * 100) if total_temptations else None

    # ── 6. (retired) The journal entry count — journal activity is private (owner ruling 2026-11-03);
    #    the partition is not read here.

    # ── 7. Meditation / breathwork (Apple Health) ──
    ah_mind = _query_source("apple_health", d30, today)
    meditation_sessions = []
    med_total_min = 0
    med_session_count = 0
    for h in ah_mind:
        _md = h.get("date") or h.get("sk", "").replace("DATE#", "")
        _bw_min = float(h.get("breathwork_minutes") or 0)
        _bw_sess = int(float(h.get("breathwork_sessions") or 0))
        # Also check mindful_minutes (Breathwrk app writes here via HAE)
        _mm_min = float(h.get("mindful_minutes") or 0)
        if _mm_min > 0 and _bw_min == 0:
            _bw_min = _mm_min
            _bw_sess = max(_bw_sess, 1)  # At least 1 session if we have minutes
        if _bw_min > 0 or _bw_sess > 0:
            meditation_sessions.append(
                {
                    "date": _md,
                    "minutes": round(_bw_min, 1),
                    "sessions": _bw_sess,
                }
            )
            med_total_min += _bw_min
            med_session_count += _bw_sess
    meditation_sessions.sort(key=lambda x: x["date"])
    meditation_data = {
        "sessions_30d": med_session_count,
        "total_minutes_30d": round(med_total_min, 1),
        "avg_session_min": round(med_total_min / med_session_count, 1) if med_session_count else None,
        "daily": meditation_sessions,
    }

    # ── 8. (withheld) The restraint timeline — #6224, see section 3. Always empty.
    vice_timeline: list = []

    # ── 9. (retired) The energy level read from the journal analysis — journal-derived, private
    #    (owner ruling 2026-11-03); not read.

    return _ok(
        {
            "mind": {
                "mind_pillar": mind_pillar,
                "resist_rate_pct": resist_rate,
                "total_temptations_90d": total_temptations,
                "resisted_90d": resisted,
                "total_interactions_30d": total_interactions,
                "meaningful_pct": meaningful_pct,
                "depth_counts": depth_counts,
            },
            "vice_streaks": vice_data,
            "vice_timeline": vice_timeline,
            "meditation": meditation_data,
        },
        cache_seconds=3600,
    )
