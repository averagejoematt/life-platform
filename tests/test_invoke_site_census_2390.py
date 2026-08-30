"""tests/test_invoke_site_census_2390.py — the THREE-seam invoke-site census (#2390).

WHY THIS EXISTS (and why the wiring registry could not do it)
------------------------------------------------------------
`tests/grounding_wiring.py` derives its surfaces from grounding-CHOKEPOINT callers.
That is the right derivation for "does this surface arm every gate class", and the
wrong one for "does every AI generation path have a grounding decision at all": a
module that reaches Bedrock and never calls a chokepoint is *structurally invisible*
to it. #2390 measured the gap — 23 modules import `bedrock_client` against 13 in
SURFACES — and the live consequence was reader text published with no registered
decision behind it.

This census inverts the derivation. It starts at the MODEL SEAM and walks outward:
every module under `lambdas/` and `mcp/` that references one of the three seams must
resolve to exactly one of

  (a) SURFACES        — a registered grounding surface in `tests/grounding_wiring.py`
                        (matched by MODULE; the per-class policy is that file's job);
  (b) EXEMPTIONS      — a written per-module exemption whose destination was VERIFIED
                        by following the write to serving code, not inferred from a
                        module name (the census run of 2026-08-09, two Explore agents);
  (c) UNGATED_READER_KNOWN — a reader-facing path with NO registered decision, mapped
                        to its filed issue. A tracked defect, visible in the ledger.
                        Never a silent bless, and never a quiet exemption either.

THE THREE SEAMS (a two-seam census misses the chronicle)
--------------------------------------------------------
  * `bedrock_client.invoke`        — ADR-062's single chokepoint;
  * `retry_utils.call_anthropic_raw`;
  * `retry_utils.call_anthropic_api` — DISCOVERED by the census. The Wednesday
    chronicle reaches Bedrock through `chronicle_prompt.call_anthropic` →
    `call_anthropic_api` → `invoke`. The issue text named only the first two seams;
    binding only those leaves the platform's flagship reader narrative invisible.

BOTH DIRECTIONS
---------------
A new ungated seam call fails the census (a), and an EXEMPTIONS/KNOWN entry whose
module no longer touches a seam fails it too (b) — so the tables cannot rot into a
stale hand-list that records a repo that stopped existing.

A REFERENCE, NOT A CALL
-----------------------
The derivation counts a *reference* to a seam, not only a call of it. Two live
patterns pass the seam as a VALUE: `qa_check_reader_truth` hands
`bedrock_client.invoke` to `reader_truth_qa.assess_prose`, and `eyeball_calibration`
takes an injectable `invoke_fn` defaulting to it. A call-only derivation would score
both as "no AI here".
"""

import ast
import os
import textwrap

import pytest
from grounding_wiring import REPO, SURFACES

# ── The seams ────────────────────────────────────────────────────────────────
# `call_anthropic_raw` / `call_anthropic_api` are unique names in this repo, so any
# reference to them is the seam. `invoke` is not unique (boto3 Lambda fan-out uses it
# too — daily_brief_lambda's `_lambda_client.invoke` is NOT an AI call), so it counts
# only when it resolves to the `bedrock_client` module or to a name imported FROM it.
UNIQUE_SEAMS = frozenset({"call_anthropic_raw", "call_anthropic_api"})
SEAM_MODULES = frozenset({"bedrock_client", "retry_utils"})
SCAN_ROOTS = ("lambdas", "mcp")

# A vacuous derivation (a rename, a broken walk, an AST change) must fail rather than
# pass with an empty set. The census measured 50 modules on 2026-08-09.
CENSUS_FLOOR = 40

# ── Destination classes for an exemption ─────────────────────────────────────
OWNER_EMAIL = "owner-email"  # SES to EMAIL_RECIPIENT only; no reader surface
OWNER_CHAT_MCP = "owner-chat/MCP"  # Matthew's own tools/chat; never rendered publicly
OPERATIONAL = "operational"  # a verdict/metric/score, never rendered as prose
INTERNAL_INPUT = "internal-input"  # feeds a DOWNSTREAM gated generator
SEAM_DEF = "seam-def"  # defines/relays the seam; not a generation site
DELEGATED_GATED = "delegated-gated"  # the generation IS gated, at another module's surface
# #2430. The one class whose destination IS a reader surface. It exists so a partial gate
# stops being invisible without being dressed up as coverage: the entry must say what the
# deterministic gate DOES check, NAME the classes it does not arm, and say why the surface
# is declared rather than registered. It is a weaker record than a SURFACES entry by
# construction — use it only where registering is blocked by something written down, and
# never to retire a class someone could arm today.
READER_DECLARED_PARTIAL = "reader-prose/declared-partial"
DESTINATION_CLASSES = frozenset(
    {OWNER_EMAIL, OWNER_CHAT_MCP, OPERATIONAL, INTERNAL_INPUT, SEAM_DEF, DELEGATED_GATED, READER_DECLARED_PARTIAL}
)


def _ex(destination, reason, gated_by=None):
    entry: dict[str, str] = {"destination": destination, "reason": reason}
    if gated_by:
        entry["gated_by"] = gated_by
    return entry


# ── (b) EXEMPTIONS — destination verified, reason written ────────────────────
# Every reason below is transcribed from the #2390 census (2026-08-09), which followed
# each module's write to the code that serves it. A reason that only names the module
# ("it's internal") is not a reason; each says WHERE the text lands and WHY that
# destination does not need a registered grounding surface.
EXEMPTIONS: dict[str, dict[str, str]] = {
    # — owner-email: one recipient, and it is Matthew —
    "lambdas/emails/monthly_digest_lambda.py": _ex(
        OWNER_EMAIL,
        "SES to EMAIL_RECIPIENT only; the DDB write is a send-log, not a served record. No reader surface reads it.",
    ),
    "lambdas/emails/weekly_digest_lambda.py": _ex(
        OWNER_EMAIL,
        "SES to EMAIL_RECIPIENT only; the DDB write is a send-log. No reader surface reads it.",
    ),
    "lambdas/emails/monday_compass_lambda.py": _ex(
        OWNER_EMAIL,
        "Monday planning email — `RECIPIENT = os.environ['EMAIL_RECIPIENT']`, single ToAddresses, no S3/DDB row any /api/ route serves.",
    ),
    "lambdas/emails/nutrition_review_lambda.py": _ex(
        OWNER_EMAIL,
        "Saturday nutrition panel — `ses.send_email(Destination={'ToAddresses': [RECIPIENT]})` where RECIPIENT is EMAIL_RECIPIENT; owner-only.",
    ),
    "lambdas/emails/weekly_plate_lambda.py": _ex(
        OWNER_EMAIL,
        "Friday food magazine — guarded_send_email to EMAIL_RECIPIENT only; the grocery list has no public render path.",
    ),
    # — owner-chat / MCP: Matthew's own surface —
    "lambdas/coach/coach_checkin.py": _ex(
        OWNER_CHAT_MCP,
        "check-in questions Matthew answers in chat/MCP; a deterministic question bank is the fallback, so a model failure degrades to written text.",
    ),
    "lambdas/reading/reading_onboarding.py": _ex(
        OWNER_CHAT_MCP,
        "onboarding runs against the PRIVATE reading allow-list and lands in Matthew's own shelf state, not the public reading surfaces.",
    ),
    "lambdas/reading/reading_recall.py": _ex(
        OWNER_CHAT_MCP,
        "recall prompts are scoped by PRIVATE_ENTITY_TYPES and served through MCP to Matthew; no /api/ route returns them.",
    ),
    "lambdas/training/training_notes_llm.py": _ex(
        OWNER_CHAT_MCP,
        "MCP-only exercise-note classification against a fixed taxonomy allow-list — a label from a closed set, not prose, and not published.",
    ),
    "lambdas/intelligence/intelligence_common.py": _ex(
        OWNER_CHAT_MCP,
        # THE ISSUE'S PREMISE CORRECTION — see test_extract_thread_is_guard_wrapped below.
        "`extract_thread_from_narrative` re-parses a coach narrative into SOURCE#coach_thread, which feeds MCP + a prompt block. "
        "The #2390 issue text assumed this is what /api/coaching-dashboard renders; it is not — the site prefers OUTPUT#'s "
        "position_summary/observatory_summary written by coach_state_updater (site_api_lambda.py:930-932), so the Webb-card mechanism "
        "is that module (#2418), not this one. Its ONE write path is wrapped in `guard_derived_summary` (#2343 reading-date + #2390 "
        "fabricated-number classes), rejecting to `truncate_at_word(narrative)` — the already-gated narrative text.",
    ),
    # — operational: a verdict, a score, a metric. Never rendered as prose —
    "lambdas/operational/ai_quality_canary_lambda.py": _ex(
        OPERATIONAL, "emits a canary verdict + CloudWatch metric; its text is never published."
    ),
    "lambdas/operational/canary_lambda.py": _ex(
        OPERATIONAL, "synthetic health probe; the model output is a pass/fail signal, not content."
    ),
    "lambdas/operational/coherence_sentinel_lambda.py": _ex(
        OPERATIONAL, "post-hoc coherence auditor over already-published text; produces findings, publishes nothing."
    ),
    "lambdas/operational/qa_check_reader_truth.py": _ex(
        OPERATIONAL,
        "the reader-truth CI gate: passes `bedrock_client.invoke` INTO `reader_truth_qa.assess_prose` to judge already-published prose. "
        "A judge, not a writer — its output is a gate verdict.",
    ),
    "lambdas/emails/panelcast_qa.py": _ex(
        OPERATIONAL, "podcast QA judges — they score a script that another module wrote; the score never reaches a reader."
    ),
    "lambdas/coach/coach_quality_gate.py": _ex(
        OPERATIONAL, "ADR-108 quality gate — an LLM judge over generated coach text; returns a verdict that regenerates or holds."
    ),
    "lambdas/coach/voice_fidelity_harness.py": _ex(
        OPERATIONAL,
        "voice-fidelity scoring harness; the public artifact is a deterministic scoreboard of its scores, not any model prose.",
    ),
    "lambdas/privacy/broadcast_sensitivity_gate.py": _ex(
        OPERATIONAL, "fail-closed advisory sensitivity screen — its answer suppresses a broadcast; it writes no reader text."
    ),
    "lambdas/content/review_pack_ranker.py": _ex(
        OPERATIONAL,
        "the critic's model call yields a float ranking only. (Its OTHER role — baseline_mismatch_findings — IS a registered "
        "SURFACES auditor, so this module also appears there; the seam itself is the ranking call.)",
    ),
    # — internal-input: feeds a downstream gated generator —
    "lambdas/coach/coach_narrative_orchestrator.py": _ex(
        INTERNAL_INPUT, "assembles the BRIEF# packet consumed by ai_calls' gated coach pipeline; nothing it writes is served directly."
    ),
    "lambdas/compute/daily_insight_compute_lambda.py": _ex(
        INTERNAL_INPUT, "pre-computes insight rows read by the daily brief and the gated narrative surfaces downstream."
    ),
    "lambdas/emails/elena_state_updater.py": _ex(
        INTERNAL_INPUT, "refreshes Elena's PERSONA# notebook — prompt material for the chronicle, whose own generator is gated."
    ),
    "lambdas/ai/conversation_enrichment.py": _ex(
        INTERNAL_INPUT, "analysis-only enrichment; any quote that surfaces publicly passes the separate quote gate first."
    ),
    "lambdas/ingestion/social_enrichment_lambda.py": _ex(
        INTERNAL_INPUT, "membrane enrichment; public exposure is mediated by the membrane visibility rules + the quote gate."
    ),
    "lambdas/ingestion/journal_enrichment_lambda.py": _ex(
        INTERNAL_INPUT,
        "extracts structured `enriched_*` signals (labels, entities, causal hints) into the journal row — raw material for grounding and "
        "hypothesis candidates. The one field with a public path, `enriched_notable_quote`, is unreachable until Matthew MARKS it "
        "(site_api_diary.py: an unmarked line is structurally unreachable), and causal hints whose verbatim quote is absent from the entry "
        "are dropped deterministically.",
    ),
    # — reader prose, declared partial (the ONE entry in this class) —
    "lambdas/emails/coach_panel_podcast_lambda.py": _ex(
        READER_DECLARED_PARTIAL,
        "The Panel podcast — generated/panelcast/{wk<N>.mp3, episodes.json, feed.xml} served at /panelcast/*, so the destination IS a "
        "reader surface (verified: the S3GeneratedOrigin CloudFront behavior, and /story/panel/ links it). WHAT IS CHECKED, all "
        "deterministic and all fail-closed: er03_gate.er03_check per line on all three script paths (weekly, intro, repair) — "
        "correlative-only plus an allow-list numbers check against the week's own source; the Day-Zero hallucination regex; and the "
        "compassion/safety filter, which HOLDS the whole episode for a human on any hit. The panelcast_qa Haiku judges sit on top of "
        "that. CLASSES NOT ARMED, named rather than implied: dates (#1242), night-scope (#1968) and behavioral (#1699) — a two-host "
        "script about the week can carry a date the chronicle never contained. WHY DECLARED, NOT REGISTERED: the module sits AT its "
        "recorded cap of 1904 lines in tests/test_module_size_guard.py::BASELINE with zero headroom, so wiring grounding_findings in "
        "place costs net lines the ratchet refuses, and the sanctioned outcome for #2430 was to write the state down rather than "
        "raise a baseline or extract under time pressure. The extraction that would let it register is the follow-on work; until then "
        "this entry is the record, and the file's own docstring points here.",
    ),
    # — seam-def —
    "lambdas/common/retry_utils.py": _ex(
        SEAM_DEF, "DEFINES call_anthropic_raw/call_anthropic_api and relays to bedrock_client.invoke. A transport, not a generation site."
    ),
    "lambdas/ai/ai_transport.py": _ex(
        SEAM_DEF,
        "DEFINES call_anthropic (the daily brief's only door to Bedrock) and relays to bedrock_client.invoke — the retry ladder, the "
        "CloudWatch failure series and the AI-3 output hook, and nothing that knows what a coach or a brief is. Split out of ai_calls.py "
        "by #3082; the two grounding surfaces that own this path — ai_calls.py::_ground_legacy_output and ::_run_coach_v2_pipeline — "
        "stayed behind in ai_calls and are still registered in SURFACES, so the extraction moved the transport, not the decision.",
    ),
    # — delegated: the generation is gated, at a surface another module owns —
    "lambdas/coach/telegram_worker_lambda.py": _ex(
        DELEGATED_GATED,
        "the Telegram transport for the coach chat (ADR-151). The turn runs through coach_chat.run_turn with the grounding closure from "
        "coach_chat_grounding.build_grounder — the registry's ONLY no-exemption surface (all five classes) — so the seam here drives a "
        "generation that is gated there, not an unregistered one.",
        gated_by="lambdas/coach/coach_chat_grounding.py::build_grounder",
    ),
    "lambdas/coach/telegram_group.py": _ex(
        DELEGATED_GATED,
        "the board room (epic #2363) — the group-chat half of the same Telegram transport, split out of the worker for its size "
        "ceiling. A room turn runs through the identical seam: coach_chat.run_turn with the worker's _grounder_for closure over "
        "coach_chat_grounding.build_grounder (all five classes, no exemption), same as the 1:1 path. The module's own bedrock "
        "reference is the run_turn caller lambda; nothing reaches the model outside that gated turn.",
        gated_by="lambdas/coach/coach_chat_grounding.py::build_grounder",
    ),
}

# ── (c) UNGATED_READER_KNOWN — reader-facing, no registered decision, tracked ──
# Filed 2026-08-09 out of the same census. These are DEFECTS in the ledger, not
# exemptions: each says what a reader sees and where the fix is tracked. An entry
# leaves this table by landing a SURFACES registration, never by being re-described.
UNGATED_READER_KNOWN: dict[str, dict[str, object]] = {
    # coach_state_updater.py left this table 2026-08-10 the designed way (#2418): its
    # DERIVED READER PROSE — observatory_summary AND the key_recommendation that
    # outranks it on three of the six serving paths, AND elena_quote — now crosses one
    # registered chokepoint in this module, with no exemption
    # (grounding_wiring: "lambdas/coach/coach_state_updater.py::_gate_derived_prose",
    # numbers/dates/night/freshness, regenerate-once-then-HOLD to the gated `content`).
    # coach_ensemble_digest.py left this table 2026-08-09 the designed way (#2419):
    # its digest writer landed a SURFACES registration
    # (grounding_wiring: "lambdas/coach/coach_ensemble_digest.py::_apply_grounding_gate").
    # (#2420 RESOLVED 2026-08-09: hypothesis_engine_lambda.py left this table the designed
    # way — both prose paths are now registered SURFACES in tests/grounding_wiring.py.)
    # ai_expert_analyzer_lambda.py left this table 2026-08-09 the designed way (#2421):
    # all six model calls — including the Mode-B rewrite that used to mutate the text
    # AFTER the gate ran — route through one registered SURFACES chokepoint
    # (grounding_wiring: "lambdas/intelligence/ai_expert_analyzer_lambda.py::_gate_prose"),
    # so its DECLARED_OVERLAPS entry retired with it.
    "lambdas/emails/anomaly_detector_lambda.py": {
        "issue": 2422,
        "note": "the anomaly hypothesis enters the chronicle data packet as a grounding SOURCE — model-introduced numbers become "
        "allow-list vocabulary for reader text.",
    },
    "lambdas/intelligence/challenge_generator_lambda.py": {
        "issue": 2424,
        "note": "/api/challenges serves candidate rows, so LLM-authored challenge copy is reader-visible before review.",
    },
    # reading_enrich.py + reading_constellation.py left this table 2026-08-09 the
    # designed way (#2425): closed-vocabulary deterministic validation (domainTags/era)
    # plus the numbers/dates/freshness chokepoint on the free-text fields landed
    # SURFACES registrations ("lambdas/reading/reading_enrich.py::_grounded_themes",
    # "lambdas/reading/reading_constellation.py::_idea_grounding_findings").
    # field_notes_lambda left this table via #2426 — registered in SURFACES
    # (::_note_grounding_findings), regenerate-once-then-hold.
    # coach_history_summarizer.py left this table 2026-08-09 the designed way (#2428):
    # its COMPRESSED#latest compression writer landed a SURFACES registration
    # (grounding_wiring: "lambdas/coach/coach_history_summarizer.py::_apply_compression_gate",
    # regenerate-once-then-hold), and the board-answer reader (_coach_memory_bits)
    # now excludes ungated legacy rows — so the module's whole coverage is genuine
    # and its DECLARED_OVERLAPS entry is gone with it.
    # — the partial-gate cluster (#2430) —
    # THREE of the four left this table 2026-08-10 the designed way, by registering the
    # classes each can answer honestly in tests/grounding_wiring.py::SURFACES:
    #   coach_daily_reflection_lambda.py::_grounding_findings  (numbers/dates/freshness)
    #   coach_memoir_lambda.py::gate_check                     (numbers/dates/freshness)
    #   eyeball_calibration.py::_grounded_note                 (numbers/dates/freshness)
    # The fourth, coach_panel_podcast_lambda.py, moved to EXEMPTIONS as the single
    # READER_DECLARED_PARTIAL entry — a weaker record, and deliberately a written one:
    # the file is at its size-guard cap, so registering it is blocked until the
    # extraction lands. Read that entry, not this comment, for the reason.
    # STILL TRACKED. It carries #2430's number because the same census sweep filed it, but
    # it is OUTSIDE that issue's scope — the issue title names the other four — so it needs
    # its own issue once #2430 closes rather than inheriting a closed one.
    "lambdas/emails/chronicle_personas.py": {
        "issue": 2430,
        "note": "Margaret's revision + editor's note run AFTER the chronicle's grounding gate (wednesday_chronicle_lambda.py:768). The "
        "revision is number-guarded deterministically (margaret_editor_pass._deterministic_ok → fabricated_numbers against the same "
        "allow-list, rejecting to Elena's gated draft), so it is partial rather than open — but numbers are the only class it arms.",
    },
}

# One bucket per module — EXCEPT where a module's coverage is genuinely split across
# its call sites. Naming those explicitly is the point: a partial overlap has to be a
# decision someone wrote down, not a side effect of two tables disagreeing.
DECLARED_OVERLAPS: dict[str, tuple] = {
    # registered for some calls, tracked as ungated for the rest
    # (#2421 and #2428 both RESOLVED 2026-08-09: the analyzer's four paths and the
    # summarizer's compression call are gated + registered — no declared overlaps remain
    # for either; a new second-generation path in either module must register or red.)
    # registered surface is a DIFFERENT function from the seam call: review_pack_ranker's
    # `baseline_mismatch_findings` is a registered freshness AUDITOR, while the seam
    # itself is the critic's ranking call, which produces a float and no prose.
    "lambdas/content/review_pack_ranker.py": ("surfaces", "exemption"),
    # SAME SHAPE as review_pack_ranker, and deliberately NOT a retirement (#2573).
    #
    # The retirements above (#2419/#2420/#2421/#2425/#2426/#2428) share one structure: the
    # module's SEAM CALL was a prose WRITER that nothing gated, and registering a chokepoint
    # over that same prose left the exemption with nothing to excuse. The exemption died
    # because the thing it excused became gated.
    #
    # This module is the other shape. Its seam call (`_call_haiku` -> `call_anthropic_raw`)
    # is a JUDGE and stays one: it returns a verdict JSON that regenerates or holds, and no
    # byte of it is ever rendered to a reader. That is exactly what the EXEMPTIONS entry
    # says, and #2573 did not change one word of it — the OPERATIONAL destination is still
    # verified true.
    #
    # What #2573 added is a DIFFERENT function with NO seam call in it at all:
    # `_number_grounding_report` runs the deterministic ADR-104 grounder over the coach's
    # draft — someone else's text, arriving as input — before the LLM is consulted, and the
    # gate consumes that verdict rather than re-deciding it in prose. That earns a SURFACES
    # registration (numbers + freshness) because it IS a grounding chokepoint caller. It does
    # not make the Bedrock call a grounded generation, and retiring the exemption would
    # record that it did — asserting the judge's own output is now gated reader prose, which
    # is false in both halves.
    "lambdas/coach/coach_quality_gate.py": ("surfaces", "exemption"),
}


# ── The derivation ───────────────────────────────────────────────────────────
def _seam_names_bound_in(tree):
    """(bare names bound to a seam, module aliases for bedrock_client/retry_utils)."""
    bare = set()
    modaliases = set(SEAM_MODULES)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            tail = (node.module or "").split(".")[-1]
            for alias in node.names:
                if tail == "bedrock_client" and (alias.name == "invoke" or alias.name in UNIQUE_SEAMS):
                    bare.add(alias.asname or alias.name)
                if tail == "retry_utils" and alias.name in UNIQUE_SEAMS:
                    bare.add(alias.asname or alias.name)
                if alias.name in SEAM_MODULES:
                    modaliases.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[-1] in SEAM_MODULES:
                    modaliases.add(alias.asname or alias.name.split(".")[-1])
    return bare, modaliases


def seams_in_source(source):
    """The set of seam names REFERENCED in one module's source (call or value)."""
    tree = ast.parse(source)
    bare, modaliases = _seam_names_bound_in(tree)
    hits = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            if node.attr in UNIQUE_SEAMS:
                hits.add(node.attr)
            elif node.attr == "invoke":
                value = node.value
                owner = value.id if isinstance(value, ast.Name) else (value.attr if isinstance(value, ast.Attribute) else None)
                if owner in modaliases:
                    hits.add("invoke")
        elif isinstance(node, ast.Name):
            if node.id in UNIQUE_SEAMS:
                hits.add(node.id)
            elif node.id in bare:
                hits.add("invoke")
    return hits


def derive_invoke_sites(repo=REPO, roots=SCAN_ROOTS):
    """{module rel path: set(seams referenced)} across `lambdas/` and `mcp/`."""
    found: dict[str, set] = {}
    for root in roots:
        base_dir = os.path.join(repo, root)
        if not os.path.isdir(base_dir):
            continue
        for base, dirs, files in os.walk(base_dir):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for name in sorted(files):
                if not name.endswith(".py"):
                    continue
                path = os.path.join(base, name)
                rel = os.path.relpath(path, repo)
                # bedrock_client DEFINES `invoke`; it is the seam, not a site of it.
                if rel.endswith("ai/bedrock_client.py"):
                    continue
                with open(path, encoding="utf-8") as fh:
                    source = fh.read()
                if not any(tok in source for tok in ("invoke", *UNIQUE_SEAMS)):
                    continue
                try:
                    seams = seams_in_source(source)
                except SyntaxError:  # pragma: no cover — a syntax error is another gate's job
                    continue
                if seams:
                    found[rel] = seams
    return found


def surface_modules(surfaces=SURFACES):
    """The MODULE half of every registered grounding-surface key."""
    return {key.split("::", 1)[0] for key in surfaces}


def classify(module, surfaces_modules, exemptions=None, known=None):
    """The buckets a module lands in — ``[]`` means unclassified (the failure)."""
    exemptions = EXEMPTIONS if exemptions is None else exemptions
    known = UNGATED_READER_KNOWN if known is None else known
    buckets = []
    if module in surfaces_modules:
        buckets.append("surfaces")
    if module in exemptions:
        buckets.append("exemption")
    if module in known:
        buckets.append("known")
    return buckets


# ── The census, computed once ────────────────────────────────────────────────
SITES = derive_invoke_sites()
SURFACE_MODULES = surface_modules()


class TestDerivationIsReal:
    """A census that derives nothing passes everything. Prove it derived."""

    def test_census_floor(self):
        assert len(SITES) >= CENSUS_FLOOR, (
            f"the invoke-site census derived only {len(SITES)} modules (floor {CENSUS_FLOOR}). "
            "A collapsed derivation — a renamed seam, a moved package root, an AST shape change — "
            "makes every assertion below vacuous. Fix the derivation before touching the floor."
        )

    def test_all_three_seams_are_bound(self):
        """A two-seam census misses the chronicle. Prove the third one resolves."""
        seen = set().union(*SITES.values()) if SITES else set()
        assert seen == {"invoke", "call_anthropic_raw", "call_anthropic_api"}, f"seams actually resolved: {sorted(seen)}"
        api_callers = {m for m, s in SITES.items() if "call_anthropic_api" in s}
        assert "lambdas/emails/chronicle_prompt.py" in api_callers, (
            "the chronicle reaches Bedrock via chronicle_prompt.call_anthropic → call_anthropic_api → invoke. "
            f"If it is no longer derived, the third seam is not bound. call_anthropic_api callers: {sorted(api_callers)}"
        )

    def test_boto3_lambda_invoke_is_not_an_ai_seam(self):
        """`_lambda_client.invoke(...)` is a Lambda fan-out, not a model call."""
        assert "lambdas/emails/daily_brief_lambda.py" not in SITES, (
            "daily_brief_lambda's `invoke(` hits are boto3 Lambda fan-out. Counting them would inflate the census "
            "with orchestrators and teach the next reader that the census does not know what a seam is."
        )
        assert "mcp/tools_reading.py" not in SITES


class TestEveryInvokeSiteIsAccountedFor:
    def test_no_unclassified_invoke_site(self):
        unclassified = sorted(m for m in SITES if not classify(m, SURFACE_MODULES))
        assert not unclassified, (
            "these modules reach the model with no grounding decision on record:\n  "
            + "\n  ".join(f"{m} (seams: {sorted(SITES[m])})" for m in unclassified)
            + "\n\nAdd each to exactly one of: tests/grounding_wiring.py::SURFACES (register the surface), "
            "EXEMPTIONS (verify the destination and WRITE the reason), or UNGATED_READER_KNOWN (file the issue "
            "and map it). An AI invoke site that reaches a reader without a registered decision cannot ship (#2390)."
        )

    def test_each_site_lands_in_exactly_one_bucket(self):
        for module in sorted(SITES):
            buckets = classify(module, SURFACE_MODULES)
            if len(buckets) <= 1:
                continue
            declared = DECLARED_OVERLAPS.get(module)
            assert declared is not None, (
                f"{module} is in {buckets} — an undeclared overlap. If its coverage is genuinely split across call "
                "sites, add it to DECLARED_OVERLAPS and say so in its entry; otherwise pick one bucket."
            )
            assert tuple(buckets) == declared, f"{module}: declared overlap {declared}, actual {tuple(buckets)}"

    def test_an_exemption_is_never_also_a_tracked_defect(self):
        both = sorted(set(EXEMPTIONS) & set(UNGATED_READER_KNOWN))
        assert not both, f"blessed AND tracked is incoherent: {both}"

    def test_declared_overlaps_are_real(self):
        for module, declared in sorted(DECLARED_OVERLAPS.items()):
            assert module in SITES, f"{module} is a declared overlap but no longer references a seam — drop it."
            assert tuple(classify(module, SURFACE_MODULES)) == declared, f"{module} is no longer a {declared} overlap — drop or repoint it."


class TestTablesCannotRot:
    """Both directions: an entry whose module stopped touching a seam FAILS."""

    def test_no_stale_exemption(self):
        stale = sorted(m for m in EXEMPTIONS if m not in SITES)
        assert not stale, (
            f"these EXEMPTIONS entries no longer reference any seam: {stale}. "
            "Either the module moved (repoint the entry) or its AI path is gone (delete it). "
            "A registry of exemptions for code that does not exist records only that nobody looked."
        )

    def test_no_stale_known_defect(self):
        stale = sorted(m for m in UNGATED_READER_KNOWN if m not in SITES)
        assert not stale, f"these UNGATED_READER_KNOWN entries no longer reference any seam: {stale}. Verify the fix landed, then delete."

    def test_exemptions_are_written_not_gestured(self):
        for module, entry in sorted(EXEMPTIONS.items()):
            assert entry["destination"] in DESTINATION_CLASSES, f"{module}: unknown destination class {entry['destination']!r}"
            assert len(entry["reason"]) >= 60, f"{module}: an exemption reason under 60 chars is a gesture, not a verified destination"
            if entry["destination"] == DELEGATED_GATED:
                gated_by = entry.get("gated_by")
                assert gated_by in SURFACES, (
                    f"{module} claims its generation is gated at {gated_by!r}, but that is not a registered surface. "
                    "A delegation exemption is only honest while the surface it delegates to exists."
                )

    def test_known_defects_carry_a_filed_issue(self):
        for module, entry in sorted(UNGATED_READER_KNOWN.items()):
            issue = entry["issue"]
            assert isinstance(issue, int) and issue >= 2418, f"{module}: a tracked defect needs a real filed issue number, got {issue!r}"
            assert len(str(entry["note"])) >= 40, f"{module}: say what a reader sees, not just that it is ungated"


class TestMutationProof:
    """Acceptance box 4: prove the census actually reds."""

    def test_a_synthetic_ungated_invoke_site_reds_the_census(self, tmp_path):
        fake_repo = tmp_path / "repo"
        (fake_repo / "lambdas" / "compute").mkdir(parents=True)
        (fake_repo / "lambdas" / "compute" / "brand_new_narrator.py").write_text(
            "from ai.bedrock_client import invoke\n\n\ndef narrate(packet):\n    return invoke({'messages': packet})['text']\n"
        )
        sites = derive_invoke_sites(repo=str(fake_repo))
        assert "lambdas/compute/brand_new_narrator.py" in sites, "the derivation cannot see a brand-new ungated invoke site"
        unclassified = [m for m in sites if not classify(m, SURFACE_MODULES)]
        assert unclassified == ["lambdas/compute/brand_new_narrator.py"]

    def test_the_third_seam_alone_also_reds(self, tmp_path):
        """The chronicle's seam, on its own, must be enough to catch a module."""
        fake_repo = tmp_path / "repo"
        (fake_repo / "lambdas" / "emails").mkdir(parents=True)
        (fake_repo / "lambdas" / "emails" / "new_letter.py").write_text(
            "from common.retry_utils import call_anthropic_api\n\n\ndef write(req):\n    return call_anthropic_api(req)\n"
        )
        sites = derive_invoke_sites(repo=str(fake_repo))
        assert sites == {"lambdas/emails/new_letter.py": {"call_anthropic_api"}}
        assert [m for m in sites if not classify(m, SURFACE_MODULES)] == ["lambdas/emails/new_letter.py"]

    def test_removing_a_surfaces_entry_for_a_live_gated_module_reds(self):
        victim = "lambdas/compute/state_of_matthew_lambda.py"
        assert victim in SITES and classify(victim, SURFACE_MODULES) == ["surfaces"], "precondition: a live, registered, gated invoke site"
        without = SURFACE_MODULES - {victim}
        assert classify(victim, without) == [], "deregistering a gated reader surface must leave it unclassified — the census's whole job"

    def test_a_stale_exemption_reds(self):
        stale_table = dict(EXEMPTIONS)
        stale_table["lambdas/compute/module_that_was_deleted.py"] = _ex(OPERATIONAL, "x" * 61)
        stale = [m for m in stale_table if m not in SITES]
        assert stale == ["lambdas/compute/module_that_was_deleted.py"]


class TestPartnerEmailResolved2423:
    """#2423: the partner email left UNGATED_READER_KNOWN by landing a SURFACES
    registration, and its second seam (the direct-bedrock fallback) is gone.
    The census must see ONE seam, and it must classify as a registered surface."""

    def test_partner_email_has_exactly_one_seam(self):
        assert SITES.get("lambdas/emails/partner_email_lambda.py") == {"call_anthropic_raw"}, (
            "partner_email_lambda must reach the model through retry_utils.call_anthropic_raw ONLY — "
            "its direct-bedrock fallback seam was retired by #2423 and must not come back. "
            f"seams seen: {sorted(SITES.get('lambdas/emails/partner_email_lambda.py', set()))}"
        )

    def test_partner_email_is_a_registered_surface_not_a_tracked_defect(self):
        module = "lambdas/emails/partner_email_lambda.py"
        assert classify(module, SURFACE_MODULES) == ["surfaces"]
        assert module not in UNGATED_READER_KNOWN and module not in EXEMPTIONS


class TestExtractThreadIsGuarded:
    """Acceptance box 1, dispositioned honestly.

    The issue asked for `extract_thread_from_narrative` to be gated. The census found
    it ALREADY is — `guard_derived_summary` (#2343 reading-date fidelity + the #2390
    fabricated-number class) wraps its one write path, falling back to
    `truncate_at_word(narrative)`, the text the narrative gate already cleared. What
    the census corrected instead is the DESTINATION: this output feeds
    SOURCE#coach_thread → MCP + a prompt block, not the coaching-dashboard card the
    issue attributed to it. These tests pin both halves so a future edit that adds a
    second, unguarded write path fails here.
    """

    def _module(self):
        return pytest.importorskip("intelligence.intelligence_common")

    def test_position_summary_has_exactly_one_write_path_and_it_is_guarded(self):
        import inspect

        ic = self._module()
        src = inspect.getsource(ic.extract_thread_from_narrative)
        tree = ast.parse(textwrap.dedent(src))
        writes = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            for target in node.targets
            if isinstance(target, ast.Subscript) and isinstance(target.slice, ast.Constant) and target.slice.value == "position_summary"
        ]
        assert len(writes) == 1, f"expected ONE position_summary write path, found {len(writes)} — each needs its own guard"
        assert "guard_derived_summary(" in src, "the #2343/#2390 derived-summary guard is gone from the extractor"
        assert "truncate_at_word(narrative" in src, "the guard's rejection must fall back to the already-gated narrative text"

    def test_a_fabricated_number_in_the_condensation_falls_back_to_the_narrative(self, monkeypatch):
        """The #2390 class end to end: a figure the source never contained."""
        ic = self._module()
        narrative = "Your sleep held steady this week. You averaged 7 hours across the five nights I could see."
        fabricated = "I'm noticing your HRV sat at 133 all week, which is why I'd hold the load."

        def fake_call(req, timeout=30):
            import json as _json

            payload = _json.dumps(
                {
                    "position_summary": fabricated,
                    "predictions": [],
                    "surprises": [],
                    "emotional_investment": "observing",
                    "open_questions": [],
                }
            )
            return {"content": [{"type": "text", "text": payload}]}

        import common.retry_utils as retry_utils

        monkeypatch.setattr(retry_utils, "call_anthropic_raw", fake_call)
        out = ic.extract_thread_from_narrative("sleep", narrative, "fake-key")
        assert (
            "133" not in out["position_summary"]
        ), "the re-parse published a number the narrative never contained — a condensation is not licensed to introduce data (#2390)"
        assert out["position_summary"] == ic.truncate_at_word(narrative, 200)

    def test_a_faithful_condensation_survives(self, monkeypatch):
        """A guard that rejects everything is a guard nobody keeps."""
        ic = self._module()
        narrative = "Your sleep held steady this week. You averaged 7 hours across the five nights I could see."
        faithful = "I'm seeing steady sleep — about 7 hours across the nights I could see, so I'd keep the routine as is."

        def fake_call(req, timeout=30):
            import json as _json

            payload = _json.dumps(
                {
                    "position_summary": faithful,
                    "predictions": [],
                    "surprises": [],
                    "emotional_investment": "observing",
                    "open_questions": [],
                }
            )
            return {"content": [{"type": "text", "text": payload}]}

        import common.retry_utils as retry_utils

        monkeypatch.setattr(retry_utils, "call_anthropic_raw", fake_call)
        out = ic.extract_thread_from_narrative("sleep", narrative, "fake-key")
        assert out["position_summary"] == faithful
