"""
coach_brief_input_gate.py — the coach-brief change-gate, moved UPSTREAM of the
narrative orchestrator (#3107, epic #2801).

WHY THIS EXISTS
---------------
ADR-126 gave the daily coach brief a generation cache: fingerprint the semantic
inputs, and on a quiet day reuse the last gate-passed text instead of paying full
Sonnet + gates to re-say the same silence. #2889 then fixed the fingerprint to
hash STRUCTURE rather than rendered prose, which removed `generation_date` from
the digest.

It still could not hit. Measured in #2889 (PR #3073): over **56 consecutive-day
coach-brief pairs, 0 were identical**. The reason is in the parts list itself —
`generation_cache.brief_parts` names six parts, and the largest of them, `brief`,
is `coach-narrative-orchestrator`'s Haiku output at **temperature 0.3**. A
sampled LLM output is not an input. Fingerprinting it asks "did the model happen
to emit the same JSON twice", and the answer at temp 0.3 over a ~2,500-token
structured brief is no, forever. No amount of fixing the *hashing* could fix
that; the gate was simply in the wrong place.

WHERE THE GATE BELONGS
----------------------
Downstream of the orchestrator, everything is already contaminated by a model
sample. So the gate moves to the only place where the inputs are still
deterministic: **before the orchestrator is invoked at all.** The chain is

    computation engine (deterministic)
      -> [THIS GATE]
      -> coach-narrative-orchestrator   (Haiku, temp 0.3)  <- first model call
      -> coach generation               (Sonnet)
      -> grounding + quality + presence gates (more Sonnet on a regen)

A hit here skips **the whole leg**, including the orchestrator's Haiku call —
which the old placement could never do, because it needed the orchestrator's
output to compute its key.

THE INPUT SET, AND THE ONE THING THAT MAKES IT HONEST
-----------------------------------------------------
The dangerous move would have been to gate on what the *caller* (`ai_calls`) can
see: the computation results, the domain slice, the data inventory, the voice
spec, the corrections. That set is deterministic — and badly incomplete. The
orchestrator re-reads a large state of its own from DynamoDB and S3 (all eight
coaches' compressed states, the ensemble digest, the influence graph, the
narrative arc, stance, site protocols, journal mood, engagement signal, open
threads, active predictions). Gating on the caller's view alone would skip the
orchestrator on a day when the orchestrator's OWN inputs had changed, and serve
yesterday's text as today's. That is the one failure `generation_cache`'s header
forbids: "a spurious regeneration costs money, a spurious reuse costs the truth."

So the orchestrator is asked for its own input digest first, through a
**fingerprint-only mode** that runs `_gather_all_state` and returns a hash with
**no model call**. It is one extra Lambda invoke of DynamoDB/S3 reads on a leg
that was about to cost two model calls; on a miss it is pure overhead measured in
milliseconds, and on a hit it is what makes the skip safe.

`prompt_template_hash()` closes the last hole. Because a hit skips the
orchestrator, the orchestrator's *code* is now part of what is being cached over
— a prompt-template edit that changes what the brief means would otherwise be
invisible to the fingerprint and would keep serving pre-deploy text. Hashing the
source bytes of the prompt-bearing modules is deliberately over-eager: ANY edit
to those files busts the gate, including edits that change nothing semantic. That
is the correct direction under this module's asymmetry — an unnecessary bust
costs one regeneration, and a missed bust costs the truth. It also needs no
version constant that someone must remember to bump.

FAIL-CLOSED, EVERYWHERE
-----------------------
Every way this gate can be uncertain resolves to "regenerate":

  * the orchestrator's fingerprint-mode invoke fails, times out, or returns no
    digest -> `upstream_parts` raises -> caller regenerates;
  * a prompt-bearing source file cannot be read -> `prompt_template_hash` returns
    None -> `upstream_parts` raises -> caller regenerates;
  * any unexpected exception in the caller's gate block -> regenerate.

Note what is NOT done: a missing digest is never folded into the fingerprint as
`None`. That would be stable across failures, so two consecutive failed digest
fetches would look like "unchanged" and serve stale text. The absence must be
loud, so it raises.

RELATION TO THE DOWNSTREAM CACHE
--------------------------------
The ADR-126 downstream entry (`daily_brief_<domain>`) is left exactly as it was.
It is cheap, it is the fallback if the upstream digest is ever unavailable, and
#3073's other surfaces (ensemble digest, daily reflection) share its machinery.
The upstream entry is a SECOND row under its own output type
(`daily_brief_<domain>_inputs`), written from the same gate-passed output.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Optional

# Referenced through the MODULE, never `from ... import name` — the shared-name binding
# is what a monkeypatching test replaces, and a module-level `from` import here would
# freeze the original function and make every such test silently exercise the wrong one.
from common import generation_cache as _gc

# ── The orchestrator system prompt ──────────────────────────────────────────
# Lives here rather than in coach_narrative_orchestrator.py for two reasons: the
# orchestrator is at its #1665 module-size ceiling (extracting this is what paid
# for the fingerprint-mode dispatch), and this module needs the prompt anyway —
# it is one of the template bytes the gate hashes. The orchestrator re-exports it
# as `SYSTEM_PROMPT`, so every existing caller and test is unchanged.
ORCHESTRATOR_SYSTEM_PROMPT = (
    "You are the Narrative Orchestrator — the 'showrunner' for a team of "
    "AI health coaches. Your job is to produce a structured generation brief "
    "that will guide one specific coach's next output.\n\n"
    "You are NOT the coach. You do not write the coaching content. You plan "
    "what the coach should write about, which threads to reference, what "
    "cross-coach context to incorporate, and what voice/structural guidance "
    "to follow.\n\n"
    "## Your Responsibilities\n\n"
    "1. **Thread management**: Identify which open threads the coach should "
    "address, which to leave dormant, and whether new threads should be "
    "opened based on computation results.\n\n"
    "2. **Cross-coach context**: Determine which other coaches' concerns, "
    "recommendations, or disagreements are relevant to this coach's domain. "
    "Weight by influence graph.\n\n"
    "3. **Prediction accountability**: Flag predictions that need addressing "
    "— confirmed, refuted, or approaching their evaluation window.\n\n"
    "4. **Narrative beat**: Set the narrative tone for this output based on "
    "the journey phase, recent arc history, and current data state.\n\n"
    "5. **Voice guidance**: Based on the coach's voice state, recommend "
    "opening types (avoiding overused patterns), structural approaches, and "
    "any anti-patterns to watch for.\n\n"
    "6. **Decision class ceiling**: Based on available evidence and data "
    "maturity, set the maximum decision class "
    "(observational/directional/interventional) the coach should use.\n\n"
    "7. **Computation context**: Package relevant trend data, statistical "
    "flags, and regression-to-mean warnings for the coach.\n\n"
    "## Statistical Guardrails (ENFORCE THESE)\n\n"
    '- <7 days of data: "Observational only — no directional claims"\n'
    '- <14 days of data: "Use preliminary framing"\n'
    '- Regression-to-mean warnings: "Do not claim intervention effect"\n'
    '- Autocorrelation flags: "Likely autocorrelation, not independent signal"\n'
    '- N=1 constraint: Always. "Unusual for you" only, never "unusual."\n\n'
    "## Output Format\n\n"
    "Return ONLY valid JSON matching the generation_brief schema. "
    "No markdown, no explanation, no preamble."
)

# The event key + value that puts the orchestrator into fingerprint-only mode.
FINGERPRINT_MODE = "inputs_fingerprint"

# Suffix distinguishing the upstream cache row from the ADR-126 downstream row.
UPSTREAM_SUFFIX = "_inputs"

# The coarse `Surface` dimension for GenerationSkippedUnchanged on this path.
# Deliberately coarse (#2837: 743 EMF series is already an open finding) and
# distinct from "coach_brief" so an upstream skip is attributable to THIS gate
# rather than collapsed into the downstream one that has never fired.
UPSTREAM_SURFACE = "coach_brief_inputs"

# The modules whose SOURCE BYTES define what the cached-over chain would produce:
# the orchestrator (skipped entirely on a hit — its prompt and brief assembly),
# the coach generation pipeline (the system-prompt and user-message templates),
# and this module (the prompt constant above now lives here). Relative to the
# bundle root, which is what `lambdas/` stages to (ADR-146).
PROMPT_SOURCE_MODULES = (
    "ai/ai_calls.py",
    "coach/coach_narrative_orchestrator.py",
    "coach/coach_brief_input_gate.py",
)

_BUNDLE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def upstream_output_type(output_type: str) -> str:
    """The upstream cache row's output type for a downstream `output_type`."""
    return f"{output_type}{UPSTREAM_SUFFIX}"


def prompt_template_hash(root: Optional[str] = None) -> Optional[str]:
    """SHA-256 over the source bytes of every prompt-bearing module.

    Returns None if ANY of them cannot be read — the caller must then treat the
    gate as unavailable and regenerate. Never substitute a placeholder: a
    constant stand-in is stable across failures, which is exactly the shape that
    would serve stale text (see the module docstring).
    """
    digest = hashlib.sha256()
    base = root or _BUNDLE_ROOT
    for rel in PROMPT_SOURCE_MODULES:
        try:
            with open(os.path.join(base, rel), "rb") as fh:
                digest.update(rel.encode("utf-8"))
                digest.update(fh.read())
        except OSError as e:  # noqa: BLE001 — unreadable source disables the gate
            print(f"[INPUT-GATE] prompt source unreadable ({rel}: {e}) — upstream gate disabled this run")
            return None
    return digest.hexdigest()


def orchestrator_input_digest(state: Any) -> str:
    """The orchestrator's gathered state, canonicalized and hashed.

    Called INSIDE the orchestrator (fingerprint-only mode), where `state` is
    `_gather_all_state(coach_id)`. `canonicalize` strips the same bookkeeping
    keys the ADR-126 cache strips, so a `_generated_at` on a compressed-state row
    does not bust the digest while a real state change does.
    """
    return _gc.brief_fingerprint(_gc.canonicalize(state))


def fetch_orchestrator_input_digest(lambda_client, coach_id: str, function_name: str = "coach-narrative-orchestrator") -> Optional[str]:
    """Ask the orchestrator for its input digest — a DDB/S3 read pass, NO model call.

    Returns None on any failure, which the caller must treat as "gate unavailable"
    (regenerate), never as a fingerprint component.
    """
    try:
        resp = lambda_client.invoke(
            FunctionName=function_name,
            InvocationType="RequestResponse",
            Payload=json.dumps({"coach_id": coach_id, "mode": FINGERPRINT_MODE}).encode(),
        )
        payload = json.loads(resp["Payload"].read())
        body = payload.get("body")
        parsed = json.loads(body) if isinstance(body, str) else (body or payload)
        digest = (parsed or {}).get(FINGERPRINT_MODE)
        return digest if isinstance(digest, str) and digest else None
    except Exception as e:  # noqa: BLE001 — fail-closed to regeneration
        print(f"[INPUT-GATE:{coach_id}] orchestrator input digest unavailable ({e}) — upstream gate disabled this run")
        return None


#: The inventory's rows: (display name, brief-data keys, registry source id or None).
#:
#: #3516: the registry id is what makes each line's caveat DERIVED rather than typed —
#: `source_registry.availability_facet` supplies the paused/lag status and its reason, so
#: a source becoming paused, or having its cadence loosened, changes this prompt with no
#: edit here. `None` means the row has no ingest source at all: DEXA scans and lab draws
#: are events, not pipes, and their absence carries no caveat to state.
INVENTORY_ROWS = (
    ("DEXA body composition", ("dexa",), None),
    ("Lab bloodwork", ("labs",), None),
    ("Body measurements", ("measurements",), "measurements"),
    ("MacroFactor nutrition", ("macrofactor",), "macrofactor"),
    ("Whoop recovery/sleep", ("whoop",), "whoop"),
    ("Garmin steps", ("garmin",), "garmin"),
    ("Strava activities", ("strava_7d",), "strava"),
    ("Eight Sleep bed temp", ("eightsleep",), "eightsleep"),
    ("CGM glucose", ("apple_health", "apple"), "apple_health"),
)

#: The rule that travels WITH the inventory rather than in the prompt template, so the
#: #3107 "gate and prompt read the same bytes" property covers it too, and so a surface
#: that renders the inventory cannot render it without the rule that reads it.
INVENTORY_RULE = (
    "  RULE: never attribute a CAUSE to an absence this inventory does not state. A row\n"
    "  marked PAUSED or LAGGING BY DESIGN must never be described as 'not syncing yet',\n"
    "  a sync failure, a connection problem, or something that 'needs to be running' —\n"
    "  say it is paused, or say the designed lag, in the inventory's own terms."
)


def _facet_caveat(source_id: Optional[str]) -> str:
    """The registry-derived caveat clause for one inventory row ('' when there is none).

    The SENTENCE is `source_registry.availability_facet`'s, not this module's — one
    wording for the whole platform, so this surface and the analyzer's
    `movement_source_reason` cannot describe the same paused source two ways.
    """
    if not source_id:
        return ""
    from ingestion import source_registry as _sr

    caveat = _sr.availability_facet(source_id)["caveat"]
    return f" — {caveat}" if caveat else ""


def data_inventory(data: dict) -> str:
    """The source list shown to every coach — availability PLUS the registry's facet.

    Extracted from `ai_calls._run_coach_v2_pipeline` (#3107) so the gate and the
    generation prompt read the SAME bytes — a gate keyed on a re-derived copy of
    a prompt fragment is a fixture-not-the-wire bug waiting to happen.

    #3516: it used to render `AVAILABLE / not available` and nothing else. Live Day-0
    coach output filled the missing reason in with a sync failure ("Garmin step data
    isn't syncing to my dashboard yet"; "MacroFactor isn't syncing yet ... it needs to be
    running by tomorrow") for a source paused by ADR-074 and one that is ~24h behind by
    design. The caveat is now the registry's own facet + its own `method` string.
    """
    data = data or {}
    lines = []
    for name, keys, source_id in INVENTORY_ROWS:
        value = None
        for key in keys:
            value = data.get(key)
            if value:
                break
        available = bool(value) and (not isinstance(value, list) or len(value) > 0)
        lines.append(f"  - {name}: {'AVAILABLE' if available else 'not available'}{_facet_caveat(source_id)}")
    return "\n".join(lines) + "\n" + INVENTORY_RULE


# ── #3516: the paused/lagging misattribution gate (regenerate-or-hold) ───────
#
# WHAT IS STRUCTURAL, AND WHAT IS NOT — stated plainly, because every phrase-matched
# suppressor in the #2959/#3003/#3199 family has failed in the field.
#
# The TRIGGER is structural and is the whole point: this can only fire on a source the
# REGISTRY says is paused or lag-by-design (`caveated_source_ids`), and only for the
# rows this inventory actually lists. It cannot be armed by a phrase, and it cannot fire
# on a live source however the sentence is worded.
#
# The DETECTION inside that trigger is a small vocabulary of sync-failure attributions,
# and it is not claimed to be exhaustive — a coach can always invent a new way to blame
# the pipe. Two things keep that honest rather than decorative: the positive controls are
# the two sentences that actually shipped on Day 0 (pinned in
# tests/test_coach_source_facets_3516.py), and the prompt now STATES the rule
# (`INVENTORY_RULE`), so the gate is the backstop for a rule the model was given, not the
# only thing standing between a paused source and a fabricated sync failure.
_SYNC_FAILURE_PATTERNS = (
    r"(?:is|are|isn't|is\s+not|aren't|are\s+not|not)\s+syncing",
    r"syncing\s+(?:yet|to\b)",
    r"(?:hasn't|has\s+not|haven't|have\s+not)\s+synced",
    r"sync(?:ing)?\s+(?:failure|issue|issues|problem|problems|gap|gaps|error|errors)",
    r"(?:needs?|need)\s+to\s+be\s+(?:running|syncing|connected|hooked\s+up)",
    r"(?:not|isn't|is\s+not)\s+connected",
    r"(?:re)?connect\s+(?:it|the\s+\w+)",
)


def source_facet_findings(text: str, data: Optional[dict] = None) -> list:
    """Sentences that blame a sync failure for a PAUSED or LAG-BY-DESIGN source.

    Returns a list of `{"type": "source_facet_misattribution", "source": id,
    "status": ..., "detail": ...}` — the grounded_generation finding shape, so a caller
    can compose it with the other gates. Pure: no I/O, no model call.
    """
    import re

    from ingestion import source_registry as _sr

    if not text:
        return []
    caveated = _sr.caveated_source_ids()
    watched = []
    for name, _keys, source_id in INVENTORY_ROWS:
        if not source_id or source_id not in caveated:
            continue
        label = _sr.source_label(source_id) or name.split()[0]
        watched.append((source_id, label, _sr.availability_facet(source_id)["status"]))
    if not watched:
        return []
    findings = []
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
        low = sentence.lower()
        if not any(re.search(p, low) for p in _SYNC_FAILURE_PATTERNS):
            continue
        for source_id, label, status in watched:
            if label.lower().replace(" ", "") in low.replace(" ", ""):
                findings.append(
                    {
                        "type": "source_facet_misattribution",
                        "source": source_id,
                        "status": status,
                        "detail": f"{label} is {status} in the source registry — a sync-failure attribution is false: {sentence.strip()[:180]}",
                    }
                )
                break
    return findings


def source_facet_correction(findings: list) -> str:
    """The one corrective instruction handed back to the model on a regeneration."""
    from ingestion import source_registry as _sr

    bits = []
    for f in findings:
        facet = _sr.availability_facet(f.get("source") or "")
        label = _sr.source_label(f.get("source") or "") or f.get("source")
        bits.append(f"{label}: {facet['caveat']}")
    return (
        "CORRECTION — you attributed a sync failure to a source that has none:\n- "
        + "\n- ".join(bits)
        + "\nRewrite those sentences using the inventory's own words, and change nothing else."
    )


def enforce_source_facet_attribution(text: str, data: Optional[dict], regenerate_fn=None):
    """Regenerate-or-hold on a paused/lagging misattribution (the ADR-108 shape).

    Returns `(text, finding_or_None)`. `text` is None when the draft is HELD — one
    corrective rewrite was offered and the claim survived it. A hold is the right
    terminal state here: the sentence tells every reader that a deliberately-paused
    source is a fixable outage, and shipping it is worse than shipping nothing.

    Fail-soft on infrastructure only: if `regenerate_fn` raises, the ORIGINAL text is
    held rather than published — a gate that cannot rewrite must not become a gate that
    cannot fail (the #2578 dark-gate shape).
    """
    findings = source_facet_findings(text, data)
    if not findings:
        return text, None
    if regenerate_fn is None:
        return None, findings[0]
    try:
        rewritten = regenerate_fn(source_facet_correction(findings))
    except Exception as e:  # noqa: BLE001
        print(f"[SOURCE-FACET] regeneration failed ({e}) — holding the draft rather than publishing the misattribution")
        return None, findings[0]
    if rewritten and not source_facet_findings(rewritten, data):
        return rewritten, findings[0]
    return None, findings[0]


def upstream_parts(
    coach_id: str,
    domain_label: str,
    comp_results: Any,
    domain_data: Any,
    inventory: str,
    corrections: Any,
    voice_spec: Any,
    orchestrator_inputs: Optional[str],
    template_hash: Optional[str],
) -> dict:
    """The named DETERMINISTIC parts of the pre-orchestrator gate.

    The names live here, not at the call site — same discipline as
    `generation_cache.brief_parts` (#2889): a caller that quietly drops a part
    narrows the fingerprint, and narrowing is the direction that serves stale
    output as fresh.

    Every part is computed WITHOUT a model call. Notably absent is `brief`, the
    orchestrator's Haiku sample that made the downstream fingerprint unable to hit
    (#3107) — it is represented here by `orchestrator_inputs`, the hash of what
    the orchestrator READS, which is what actually determines whether a fresh
    brief could say anything new.

    Raises ValueError when `orchestrator_inputs` or `template_hash` is missing.
    That is deliberate and load-bearing: folding an absent digest in as None
    would be stable across failures, so two failed fetches in a row would read as
    "nothing changed" and publish yesterday's text as today's.
    """
    if not orchestrator_inputs:
        raise ValueError("upstream_parts: orchestrator input digest is required — an absent digest must never fingerprint as a constant")
    if not template_hash:
        raise ValueError("upstream_parts: prompt template hash is required — an absent hash must never fingerprint as a constant")
    return {
        "coach_id": coach_id,
        "domain_label": domain_label,
        "comp_results": comp_results,
        "domain_data": domain_data,
        "data_inventory": inventory,
        "corrections": corrections,
        "voice_spec": voice_spec,
        "orchestrator_inputs": orchestrator_inputs,
        "prompt_template": template_hash,
    }


def serve_reuse(
    lambda_client,
    table,
    cw,
    namespace: str,
    coach_id: str,
    output_type: str,
    text: str,
    unchanged_since: Optional[str],
    today: str,
    *,
    surface: str,
    cache_output_type: Optional[str] = None,
) -> str:
    """Everything a cache HIT owes the rest of the platform, then return `text`.

    Bookkeeping + the skip metric + the coach-state-updater record, so that a
    reused day is indistinguishable downstream from a generated one (today still
    has a coach record and thread state) at zero Bedrock cost. Extracted from
    `ai_calls` (#3107) so the upstream and downstream hit paths cannot drift
    apart — and because `ai_calls` is at its #1665 ceiling.

    `output_type` is the one the state updater is told about (always the
    downstream/public one); `cache_output_type` is the row whose bookkeeping is
    bumped, defaulting to the same.
    """
    _gc.record_reuse(table, coach_id, cache_output_type or output_type, today)
    _gc.emit_skip_metric(cw, namespace, coach_id, surface=surface)
    try:
        lambda_client.invoke(
            FunctionName="coach-state-updater",
            InvocationType="Event",
            Payload=json.dumps(
                {
                    "coach_id": coach_id,
                    "output_text": text,
                    "output_type": output_type,
                    "generation_date": today,
                    "unchanged_since": unchanged_since,
                }
            ).encode(),
        )
    except Exception as e:  # noqa: BLE001 — never block serving a reused output
        print(f"[COACH-V2:{coach_id}] State updater invoke (reuse) failed (non-blocking): {e}")
    return text


class BriefCacheGate:
    """Both coach-brief cache gates behind one object, so `ai_calls` carries the
    POLICY (where each gate sits in the pipeline) and this module carries the
    MECHANISM (what is hashed, what a hit owes, what a failure means).

    That split is not cosmetic. `lambdas/ai/ai_calls.py` is at its #1665
    module-size ceiling, and the inline version of this logic is what #2889's
    docstring already had to argue back out of the call site once. It is also
    where the mistake this issue fixes was invisible: the fingerprint's parts were
    listed 40 lines away from the model call whose output one of them was.

    Every method is fail-soft in the direction of REGENERATING. A gate that cannot
    decide must never decide "unchanged".
    """

    def __init__(self, lambda_client, table, cw, namespace: str, coach_id: str, output_type: str):
        # `table` is constructed by the caller, not here, so a test can hand in a fake
        # and this stays hermetic — a gate that reaches for its own DDB resource is a
        # gate whose tests either hit the network or never exercise it.
        self.lambda_client = lambda_client
        self.table = table
        self.cw = cw
        self.namespace = namespace
        self.coach_id = coach_id
        self.output_type = output_type
        self.upstream_type = upstream_output_type(output_type)
        self.up_fp: Optional[str] = None
        self.up_parts: Optional[dict] = None
        self.down_fp: Optional[str] = None
        self.down_parts: Optional[dict] = None

    def _hit(self, output_type: str, parts: dict, surface: str, today: str):
        """Fingerprint `parts`, and on a hit do everything a hit owes. Returns
        `(fingerprint, reused_text_or_None)`."""
        fingerprint, reuse, since = _gc.check_reuse_or_explain(self.table, self.coach_id, output_type, parts)
        if not reuse:
            return fingerprint, None
        print(f"[COACH-V2:{self.coach_id}] {surface}: inputs unchanged since {since} — reusing gated output, skipping generation")
        text = serve_reuse(
            self.lambda_client,
            self.table,
            self.cw,
            self.namespace,
            self.coach_id,
            self.output_type,
            reuse,
            since,
            today,
            surface=surface,
            cache_output_type=output_type,
        )
        return fingerprint, text

    def check_upstream(self, domain_label, comp_results, domain_data, inventory, corrections, voice_spec, today) -> Optional[str]:
        """The #3107 gate — runs BEFORE the orchestrator, so a hit costs zero model
        calls. Returns the reusable text, or None to proceed with generation."""
        if self.table is None:
            return None
        try:
            self.up_parts = upstream_parts(
                self.coach_id,
                domain_label,
                comp_results,
                domain_data,
                inventory,
                corrections,
                voice_spec,
                fetch_orchestrator_input_digest(self.lambda_client, self.coach_id),
                prompt_template_hash(),
            )
            self.up_fp, text = self._hit(self.upstream_type, self.up_parts, UPSTREAM_SURFACE, today)
            return text
        except Exception as e:  # noqa: BLE001 — fail-closed to a full regeneration
            print(f"[COACH-V2:{self.coach_id}] upstream input gate unavailable (non-blocking): {e}")
            self.up_fp = self.up_parts = None
            return None

    def check_downstream(self, system_prompt, brief, domain_data, trends, inventory, corrections, today) -> Optional[str]:
        """The ADR-126 gate, unchanged (#738/#2889). Retained deliberately: it is the
        fallback whenever the upstream digest is unavailable, and #3073's sibling
        surfaces share its machinery. It just can no longer be the only one."""
        if self.table is None:
            return None
        try:
            # #2889: STRUCTURE, never rendered prose — canonicalize strips by dict KEY.
            self.down_parts = _gc.brief_parts(system_prompt, brief, domain_data, trends, inventory, corrections)
            self.down_fp, text = self._hit(self.output_type, self.down_parts, "coach_brief", today)
            return text
        except Exception as e:  # noqa: BLE001
            print(f"[COACH-V2:{self.coach_id}] generation cache unavailable (non-blocking): {e}")
            self.down_fp = self.down_parts = None
            return None

    def store(self, output: str, today: str) -> None:
        """Persist the fresh, gate-passed `output` under BOTH fingerprints.

        A row is written only where the corresponding gate actually ran. Writing a
        row keyed on a fingerprint that a degraded run produced is how a later run
        reuses against inputs it never really saw.
        """
        if self.table is None or not output:
            return
        for out_type, fingerprint, parts in (
            (self.output_type, self.down_fp, self.down_parts),
            (self.upstream_type, self.up_fp, self.up_parts),
        ):
            if fingerprint:
                _gc.store_entry(self.table, self.coach_id, out_type, fingerprint, output, today, parts=parts)
