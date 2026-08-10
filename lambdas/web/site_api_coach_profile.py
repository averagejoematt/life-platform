"""lambdas/web/site_api_coach_profile.py — who each coach IS (/api/coaches, /api/coach/{id}).

Split out of ``site_api_coach.py`` (#1654 — god-module breakup). One seam: **the
character**. The roster and the per-coach page — the persona registry read, the
authored fiction-design material (traits, voice, relationships, influence graph),
the self-assessed report card, and the #1387 dossier that renders what a coach
knows VERBATIM from its own COACH# memory under a fail-closed privacy pass.

What this module deliberately does NOT own: the coach's current *read* of Matthew
(``site_api_coach_stance``) and its graded record (``site_api_coach_ledger``). A
coach page assembles both through the facade, so those seams stay one concern each.

The routed handler entrypoints stay in the ``site_api_coach`` facade as thin
delegators; the logic lives here. Handlers receive the facade's ``globals()`` as
``_g`` and read the monkeypatched/injectable state via ``_g["<name>"]`` — ``table``,
``_load_s3_json``, ``persona_registry``, and every sibling helper this module calls
across the seam (``_stance_block``, ``_docket_rows``, …). That is what keeps
``monkeypatch.setattr(site_api_coach, "table", …)`` landing exactly as it did before
the split, and it is why nothing here imports the facade — no import cycle.
"""

from boto3.dynamodb.conditions import Key
from coach import (
    coach_corrections,  # #1689 ledger — reused by the dossier retract/correct path (#1387)
    coach_derived_prose,  # #2418: the derived-prose read seam — a held condensation falls back to gated `content`
    coach_dossier,  # #1387: the verbatim, privacy-filtered dossier projection (bundled module)
    coach_traits,  # #1113: authored trait scores for the immersive bios (bundled module)
)
from experiment.phase_filter import singleton_visible, with_phase_filter  # ADR-058 / #946
from privacy import diary_consent  # #1483 (ADR-142 tier 2): the conversation-allude projection (bundled module)

from web.site_api_common import (
    USER_PREFIX,
    _decimal_to_float,
    _error,
    _ok,
    logger,
)

_DISCLOSURE = (
    "An AI character. Reads Matthew's real data and speaks in its own voice — "
    "correlative, never causal. The personality is a lens on real numbers, not a real person."
)


def _registry(*, _g):
    _S3 = _g["_S3"]
    _S3_BUCKET = _g["_S3_BUCKET"]
    persona_registry = _g["persona_registry"]
    return persona_registry.load_registry(_S3, _S3_BUCKET)


# Last-resort byline if the registry module itself failed to import. Pinned equal
# to config/personas.json's lead by tests/test_board_lead_single_character.py.
_LEAD_FALLBACK = ("Dr. Eli Marsh", "Principal Investigator — Program Lead")


def _lead_byline(*, _g):
    """(name, title) of the board lead, from the persona registry (#1986).

    The weekly call, the month rollup and the arc are all signed by ONE character —
    the registry's single ``lead: true`` persona. These bylines used to be three
    separate string literals naming a persona the roster did not serve, which is
    how the cast forked. Fail-soft to the registry's pinned fallback so a byline
    never renders empty.
    """
    _S3 = _g["_S3"]
    _S3_BUCKET = _g["_S3_BUCKET"]
    persona_registry = _g["persona_registry"]
    try:
        return persona_registry.lead_byline(_S3, _S3_BUCKET)
    except Exception as _e:  # noqa: BLE001 — a byline lookup must never 500 an endpoint
        # Also covers persona_registry being None (the defensive import above).
        logger.warning(f"[lead_byline] {_e}")
        return _LEAD_FALLBACK


def _latest_weight_lbs(*, _g):
    """Most recent Withings weight_lbs, or None (caller falls back to baseline)."""
    table = _g["table"]
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


def _reader_reason(raw):
    """Reader-facing translation of machine-spec eval reasons (truth audit 2026-07-10).

    ~32 LEARNING# records carry internal grader notation like
    "[null-threshold machine spec re-routed to directional] recovery_score trend=down
    (slope=-0.0480), predicted=up" — that leaked verbatim onto 6 of 8 public report
    cards. Translate at the API boundary ONLY (storage untouched): the known
    directional re-route form becomes plain reader copy; any other bracketed
    machine-spec prefix is stripped."""
    import re

    txt = str(raw or "")
    stripped = re.sub(r"^\s*\[[^\]]*\]\s*", "", txt).strip()
    if stripped != txt.strip():  # a bracketed machine-spec prefix was present
        m = re.match(r"^(\w+)\s+trend=(\w+)\s*\(slope=[-+\d.eE]+\)\s*,\s*predicted=(\w+)\s*$", stripped)
        if m:
            metric = m.group(1).replace("_", " ")
            return f"graded on direction — no numeric threshold was set; {metric} trended {m.group(2)}, the call said {m.group(3)}"
    return stripped


def _track_record(coach_id, *, _g):
    """Confirmed/refuted hit-rate from the COACH#<id>/LEARNING# eval trail (CC-02).
    Honest pre-D-05: empty -> hit_rate None, preliminary True. Always labelled
    self-assessment, never external validation (ER-05)."""
    _reader_reason = _g["_reader_reason"]
    table = _g["table"]
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
            if (it.get("channel") or "data") == "conversation":
                # ADR-141 privacy tier: conversation learnings quote Matthew's
                # verbatim check-in answers — Matthew-private, never rendered
                # publicly (their status is also outside confirmed/refuted).
                continue
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
                        "reason": _reader_reason(it.get("reason", "")),
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


def _conversation_references(coach_id, limit=5, *, _g):
    """#1483 (ADR-142 theme-referenceable tier): the coach's recent check-in
    conversations with Matthew, projected to SANCTIONED fields only — date,
    coarse laundered theme, read direction/weight — via
    diary_consent.conversation_reference. The verbatim conversation text
    (answer_quote / takeaway / question on the ADR-141 LEARNING# rows —
    Matthew-private) never enters this payload: the projection BUILDS from an
    allowlist, it does not copy-and-filter. Honest-empty on no data or failure."""
    table = _g["table"]
    refs = []
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
            if (it.get("channel") or "data") != "conversation":
                continue
            ref = diary_consent.conversation_reference(_decimal_to_float(it))
            if ref:
                refs.append(ref)
            if len(refs) >= limit:
                break
    except Exception as _e:
        logger.warning(f"[coaches] conversation refs {coach_id}: {_e}")
    return {
        "references": refs,
        "count": len(refs),
        "note": "What was said stays private — these record only that a conversation happened, its coarse theme, and how it moved the coach's read (ADR-142).",
    }


def _quality_trend(coach_id, *, _g):
    """Quality-gate score trend if cached at COACH#<id>/QUALITY#, else empty.
    Always labelled self-assessment (ER-05)."""
    table = _g["table"]
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


def _tuning_log_for(coach_id, *, _g):
    """Tuning-changelog entries relevant to this coach (CC-03), newest first."""
    _load_s3_json = _g["_load_s3_json"]
    log = _load_s3_json("config/coaches/tuning_log.json", "tuning_log")
    entries = [e for e in log.get("entries", []) if e.get("coach") in (coach_id, "all")]
    return list(reversed(entries))[:10]


def _voice_subset(coach_config_key, *, _g):
    """Curated, public-safe slice of a coach's voice spec for the page."""
    _load_s3_json = _g["_load_s3_json"]
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


def _relationships(coach_id, *, _g):
    """In/out influence-graph edges for this coach (top 3 each)."""
    _load_s3_json = _g["_load_s3_json"]
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


def _character(p, *, _g):
    """Public-safe personality slice from board_of_directors.json — the fictional
    background + traits that shape this coach's prompt. Config-only, no inference."""
    _load_s3_json = _g["_load_s3_json"]
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
        # #1113 prompt transparency: the real source list this coach's prompt reads
        # (config-authored, public-safe source names — never values).
        "data_sources": (m.get("data_sources") or [])[:8],
        "principles": (m.get("principles") or [])[:5],
        "voice": {k: voice.get(k) for k in ("tone", "style", "catchphrase") if voice.get(k)},
        "tendencies": (persn.get("tendencies") or [])[:4],
        "signature_behavior": persn.get("signature_behavior"),
        "arc": persn.get("arc_seed"),
        "relationship_to_matthew": m.get("relationship_to_matthew"),
        "focus_areas": (m.get("focus_areas") or [])[:6],
    }


def _working_hypotheses(coach_id, limit=6, *, _g):
    """Live working hypotheses: open THREAD# (observation/prediction/concern) + pending
    PREDICTION# claims. Already-computed by the coach engine; read-only here."""
    table = _g["table"]
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


def _coach_daily(coach_id, *, _g):
    """CC-08: today's cached daily reflection for a coach (generated/coach_daily.json),
    or None. Read-only over the batch-written artifact — never inferenced here."""
    _load_s3_json = _g["_load_s3_json"]
    doc = _load_s3_json("generated/coach_daily.json", "coach_daily")
    r = (doc.get("reflections") or {}).get(coach_id)
    return r.get("text") if isinstance(r, dict) else None


def _coach_memoir(coach_id, *, _g):
    """#553: the coach's latest quarterly memoir (generated/coach_memoirs.json),
    or None pre-first-quarter. Read-only over the batch-written artifact —
    never inferenced here."""
    _load_s3_json = _g["_load_s3_json"]
    doc = _load_s3_json("generated/coach_memoirs.json", "coach_memoirs")
    m = (doc.get("memoirs") or {}).get(coach_id)
    return m if isinstance(m, dict) else None


def _recent_outputs(coach_id, limit=25, *, _g):  # CC-07: depth for the daily-journey timeline
    table = _g["table"]
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
                    "summary": coach_derived_prose.served_summary(it),
                    "themes": it.get("themes", []),
                }
            )
    except Exception:
        pass
    return out


def _dossier_block(coach_id, *, _g):
    """#1387 — The Coach Dossier: what this coach knows, rendered VERBATIM from the
    COACH# partitions. Deterministic build — no LLM anywhere in this path; every
    line carries its date and, where derivable, an evidence link.

    Privacy pass first (AC2): every free-text field crosses
    coach_dossier.find_dossier_violations (journal_quotes/privacy_guard vocabularies
    + genotype patterns) — a hit withholds the WHOLE record and the payload counts
    it. ADR-141 §4: channel=conversation LEARNING# rows never enter this block.
    Corrections reuse the #1689 ledger (surface=coach_dossier): retractions remove
    a record here (counted, including RELATIONSHIP#state — #1794); correction
    notes render dated under the original line. Per-SECTION fail-soft — a
    commitments/learnings/relationship/docket query error yields that section's
    honest empty, never a 500 (the dossier must not take the coach page down).
    The CORRECTIONS read is different and deliberately fail-CLOSED (#1796): an
    error there withholds every section corrections apply to (rather than
    serving them unfiltered, which could republish a record under an unread
    retraction) and sets `degraded=True` so the failure is disclosed, not
    masked behind `retracted: 0`."""
    _docket_rows = _g["_docket_rows"]
    _reader_reason = _g["_reader_reason"]
    table = _g["table"]
    withheld = 0

    def _rows(sk_prefix, limit):
        resp = table.query(
            **with_phase_filter(
                {
                    "KeyConditionExpression": Key("pk").eq(f"COACH#{coach_id}") & Key("sk").begins_with(sk_prefix),
                    "ScanIndexForward": False,
                    "Limit": limit,
                }
            )
        )
        return [_decimal_to_float(i) for i in resp.get("Items", [])]

    commitments = []
    try:
        for it in _rows("COMMITMENT#", 60):
            entry, status = coach_dossier.commitment_entry(it)
            if status == coach_dossier.WITHHELD:
                withheld += 1
            elif entry:
                commitments.append(entry)
    except Exception as _e:
        logger.warning(f"[dossier] commitments {coach_id}: {_e}")
    commitments.sort(key=lambda e: e.get("date") or "", reverse=True)

    learnings = []
    try:
        for it in _rows("LEARNING#", 60):
            entry, status = coach_dossier.learning_entry(it, reason_translator=_reader_reason)
            if status == coach_dossier.WITHHELD:
                withheld += 1
            elif entry:
                learnings.append(entry)
    except Exception as _e:
        logger.warning(f"[dossier] learnings {coach_id}: {_e}")
    learnings = learnings[:25]

    relationship = None
    try:
        rel_item = table.get_item(Key={"pk": f"COACH#{coach_id}", "sk": "RELATIONSHIP#state"}).get("Item")
        if singleton_visible(rel_item):  # #946/#1085: a wiped cycle's state never serves pre-start
            entry, status = coach_dossier.relationship_entry(_decimal_to_float(rel_item))
            if status == coach_dossier.WITHHELD:
                withheld += 1
            else:
                relationship = entry
    except Exception as _e:
        logger.warning(f"[dossier] relationship {coach_id}: {_e}")

    docket_positions = []
    try:
        # #1799: phase-filter IN the query here too — tombstoned prior-cycle OPEN# rows
        # (the reset tombstones, never deletes) must not consume this page either. The
        # post-query singleton_visible check below stays as the belt to that suspenders.
        for it in _docket_rows("OPEN#", 40, newest_first=False):
            if not singleton_visible(it):
                continue
            entry, status = coach_dossier.docket_entry(_decimal_to_float(it), coach_id)
            if status == coach_dossier.WITHHELD:
                withheld += 1
            elif entry:
                docket_positions.append(entry)
    except Exception as _e:
        logger.warning(f"[dossier] docket {coach_id}: {_e}")
    docket_positions.sort(key=lambda e: e.get("resolution_date") or "")

    retracted = 0
    degraded = False
    try:
        ledger = [_decimal_to_float(r) for r in coach_corrections.list_corrections(table, limit=500)]
        corrections = coach_dossier.dossier_corrections(ledger, coach_id)
        if corrections:
            commitments, r1 = coach_dossier.apply_corrections(commitments, corrections)
            learnings, r2 = coach_dossier.apply_corrections(learnings, corrections)
            docket_positions, r3 = coach_dossier.apply_corrections(docket_positions, corrections)
            # #1794: relationship is a single dict, not a list — round-trip it
            # through the same list-shaped apply_corrections so RELATIONSHIP#state
            # retractions are honored exactly like every other record class.
            relationship_wrapped, r4 = coach_dossier.apply_corrections([relationship] if relationship else [], corrections)
            relationship = relationship_wrapped[0] if relationship_wrapped else None
            retracted = r1 + r2 + r3 + r4
    except Exception as _e:
        logger.warning(f"[dossier] corrections {coach_id}: {_e}")
        # #1796: FAIL CLOSED. A corrections-read error must never let a possibly-
        # retracted record slip out uncorrected — the corrected sections are
        # withheld entirely (honest-empty) rather than served unfiltered, and the
        # payload's own honesty ledger discloses the degradation instead of
        # silently reporting retracted=0 while serving retracted content.
        commitments, learnings, docket_positions, relationship = [], [], [], None
        degraded = True

    disclosure = (
        "Rendered verbatim from this coach's memory records — deterministic build, no AI in the "
        "render path. Every line carries its date. Lines that fail the standing privacy filter are "
        "withheld and counted; records Matthew has retracted are removed and counted — the "
        "retraction itself is a logged correction, never a silent edit."
    )
    if degraded:
        disclosure += (
            " The corrections ledger could not be read for this request, so commitments, learnings, "
            "docket positions, and relationship state are withheld rather than risk serving a record "
            "under an unread retraction."
        )

    return {
        "verbatim": True,
        "commitments": commitments,
        "commitment_counts": coach_dossier.commitment_counts(commitments),
        "learnings": learnings,
        "relationship": relationship,
        "docket_positions": docket_positions,
        "withheld": withheld,
        "retracted": retracted,
        "degraded": degraded,
        "disclosure": disclosure,
    }


def handle_coaches(event, *, _g):
    """GET /api/coaches — the roster (CC-01). Shaped-empty 200 by design."""
    _COACH_MODULES = _g["_COACH_MODULES"]
    _registry = _g["_registry"]
    _track_record = _g["_track_record"]
    persona_registry = _g["persona_registry"]
    if not _COACH_MODULES:
        return _ok({"coaches": [], "count": 0, "disclosure": _DISCLOSURE}, cache_seconds=60)
    try:
        personas = _registry().get("personas", {})
        ops = {k: v for k, v in personas.items() if v.get("operational")}
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
                    "tier": "staff",
                }
            )
        coaches.sort(key=lambda c: order.index(c["persona_id"]) if c["persona_id"] in order else 99)
        # #1112 — the head coach leads the roster (lead tier, the cast hierarchy).
        # Non-operational: he files no domain reads and makes no graded calls, so
        # his headline is his role — never a fabricated track-record line (ADR-104).
        lead = personas.get(persona_registry.LEAD_PERSONA_ID)
        if lead and lead.get("lead"):
            coaches.insert(
                0,
                {
                    "persona_id": persona_registry.LEAD_PERSONA_ID,
                    "name": lead.get("name"),
                    "domain": lead.get("domain"),
                    "short_bio": lead.get("short_bio"),
                    "emoji": lead.get("emoji"),
                    "color": lead.get("color"),
                    "board_role": lead.get("board_role"),
                    "headline_stat": "runs the program",
                    "tier": "lead",
                },
            )
        return _ok({"coaches": coaches, "count": len(coaches), "disclosure": _DISCLOSURE}, cache_seconds=300)
    except Exception as _e:
        logger.warning(f"[/api/coaches] {_e}")
        return _ok({"coaches": [], "count": 0}, cache_seconds=60)


def handle_coach(event, *, _g):
    """GET /api/coach/{persona_id} (or ?id=) — one coach page (CC-01 + CC-02)."""
    EXPERIMENT_BASELINE_WEIGHT_LBS = _g["EXPERIMENT_BASELINE_WEIGHT_LBS"]
    _COACH_MODULES = _g["_COACH_MODULES"]
    _character = _g["_character"]
    _coach_daily = _g["_coach_daily"]
    _coach_memoir = _g["_coach_memoir"]
    _conversation_references = _g["_conversation_references"]
    _dossier_block = _g["_dossier_block"]
    _latest_weight_lbs = _g["_latest_weight_lbs"]
    _quality_trend = _g["_quality_trend"]
    _recent_outputs = _g["_recent_outputs"]
    _registry = _g["_registry"]
    _relationships = _g["_relationships"]
    _stance_block = _g["_stance_block"]
    _stance_from_latest = _g["_stance_from_latest"]
    _stance_history = _g["_stance_history"]
    _stance_latest = _g["_stance_latest"]
    _track_record = _g["_track_record"]
    _tuning_log_for = _g["_tuning_log_for"]
    _voice_subset = _g["_voice_subset"]
    _working_hypotheses = _g["_working_hypotheses"]
    if not _COACH_MODULES:
        return _ok({"persona_id": None, "stance": {}, "report_card": {}}, cache_seconds=60)
    try:
        path = event.get("rawPath") or (event.get("requestContext", {}).get("http", {}) or {}).get("path") or ""
        qs = event.get("queryStringParameters") or {}
        pid = (qs.get("id") or path.rstrip("/").split("/")[-1] or "").strip()
        p = _registry().get("personas", {}).get(pid)
        # #1112: the head coach (lead: true) gets a detail page too — every other
        # non-operational persona (narrator, board-only figures) still 404s.
        is_lead = bool(p and p.get("lead") and not p.get("operational"))
        if not p or not (p.get("operational") or is_lead):
            return _error(404, "Unknown coach")
        weight = _latest_weight_lbs() or EXPERIMENT_BASELINE_WEIGHT_LBS
        if is_lead:
            # No weight-band ladder config exists for the lead and the opinion
            # engine writes him no weekly stance — the staff ladder fallback would
            # fabricate a scaffold. Serve an explicit source:"none" (honest-empty,
            # ADR-104); if a STANCE#latest ever lands for him it wins, same as staff.
            latest = _stance_latest(pid)
            stance = _stance_from_latest(latest) if latest else {"source": "none", "headline_read": "", "stage": {}}
        else:
            stance = _stance_block(pid, weight)
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
                "tier": "lead" if is_lead else "staff",
                # Lead-tier extras (config-authored persona fields; null for staff —
                # their character block carries the equivalent material).
                "philosophy": p.get("philosophy"),
                "expertise": p.get("expertise", []),
                "disclosure": _DISCLOSURE,
                "character": _character(p),
                # #1113: authored (deterministic, human-written) trait scores — the
                # cast sheet, labelled as authored fiction-design by its own disclosure.
                "trait_scores": coach_traits.traits_for(pid),
                "working_hypotheses": _working_hypotheses(pid),
                "stance": stance,
                "stance_history": _stance_history(pid),
                # The lead has no generation voice spec (config/coaches/{id}.json) —
                # null is the honest value, and the front-end omits the section.
                "voice": _voice_subset(p["coach_config_key"]) if p.get("coach_config_key") else None,
                "relationships": _relationships(pid),
                "report_card": {
                    "track_record": _track_record(pid),
                    "quality_trend": _quality_trend(pid),
                    "tuning_log": _tuning_log_for(pid),
                },
                "recent_outputs": _recent_outputs(pid),
                # #1483 (ADR-142 tier 2): semi-private conversation references —
                # sanctioned fields only; the words exchanged never cross the wire.
                "conversations": _conversation_references(pid),
                # #1387: the dossier — what this coach knows, verbatim from COACH#
                # memory (privacy-filtered, correction-aware, no LLM in the path).
                "dossier": _dossier_block(pid),
                "daily": _coach_daily(pid),
                "memoir": _coach_memoir(pid),
            },
            cache_seconds=300,
        )
    except Exception as _e:
        logger.warning(f"[/api/coach] {_e}")
        return _ok({"persona_id": None, "stance": {}, "report_card": {}}, cache_seconds=60)
