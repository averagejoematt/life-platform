"""structured_json.py — JSON-shaped model calls return schema-valid JSON (#4276, epic #4249).

`bedrock_client.structured_output_config()` has existed since #1385, and no production
caller used it. Every JSON-shaped Haiku call hand-parsed free text instead: `json.loads`,
then the ```json fence, then any ``` fence, and otherwise the raw string. Five coach
modules carried five copies of that parse. A truncated or malformed verdict then came back
as a `str` or a partial dict, and each caller had its own way of noticing.

This module is the one door:

  * `call_json(call, body, schema=...)` attaches `output_config.format` when a schema is
    given, so Bedrock constrains the output to the schema. Verified live on 2026-09-29
    against `us.anthropic.claude-haiku-4-5-20251001-v1:0` (see the #4276 PR): the enum
    was honoured, `temperature` and `cache_control` were accepted alongside it, and a
    schema with `additionalProperties: true` was refused with a ValidationException.
  * If Bedrock refuses the SCHEMA (a ValidationException that names `output_config`),
    the call is re-sent once without it. That is the old path, and `STRUCTURED_OUTPUT
    fallback=schema_rejected` is logged, so an unsupported site degrades to today's
    behaviour and says so. It never fails the caller.
  * `parse_json_text(text)` is the old fence-tolerant parse, kept as the fallback
    (schema-less callers, a refusal, a `max_tokens` cut). It is now one copy instead of five.
  * `parse_json_span(text)` is the prose-tolerant salvage (first opener to last closer), for
    the text seams whose replies can carry prose after the JSON (the panelcast extractor).

Every call logs one `STRUCTURED_OUTPUT` line: the label, whether the schema was sent,
`stop_reason`, and whether the text parsed as a dict. That line is the ADR-105 read (#4276
box 4): the non-dict rate before and after, in the callers' own log groups.

Per-site support record (#4276 box 3). Every schema site below runs Haiku 4.5 on Bedrock
(`claude-haiku-4-5-20251001` default; read live 2026-10-02: no AI_MODEL / AI_MODEL_HAIKU / MODEL
override on any of their functions) except where a model is named. "Live-verified" features
(the #4464 check): closed objects, string enums, temperature + cache_control beside the schema.
Features used here that were NOT in that live check — integer enums, `anyOf [T, null]`, arrays
of closed objects, a per-call (roster) enum — are inside Bedrock's documented JSON-schema subset;
if Bedrock refuses one, `call_json` re-sends schema-less and logs `fallback=schema_rejected`,
so the first post-deploy log line per label is each site's support proof.

  call_json WITH a schema (label → module):
    coach_quality_gate · coach_state_updater · coach_narrative_orchestrator ·
    coach_ensemble_digest · coach_history_summarizer       coach/ (#4464, #4494)
    panelcast_qa_judge · panelcast_editor · panelcast_craft_judge (Sonnet) ·
    the podcast_script_v2 pass labels (Sonnet writer)      emails/ (#4501, #4514)
    ic3_analysis                ai/ai_calls.py::_run_analysis_pass
    reading_constellation · reading_enrich · reading_onboarding · reading_recall   reading/
    journal_enrichment · social_enrichment                 ingestion/
    conversation_enrichment     ai/conversation_enrichment.py
    coach_checkin               coach/coach_checkin.py
    voice_fidelity_judge        coach/voice_fidelity_harness.py (guess enum = the roster)
    intention_eval              compute/daily_insight_compute_lambda.py (array wrapped in an object)
    hypothesis_engine           compute/hypothesis_engine_lambda.py (metric slots enum SPEC_METRICS)
    elena_state_updater         emails/elena_state_updater.py
    challenge_generator         intelligence/challenge_generator_lambda.py (metric_targets omitted)
    coach_thread_extract        intelligence/intelligence_common.py
    field_notes                 intelligence/field_notes_lambda.py
    coherence_semantic          operational/coherence_sentinel_lambda.py
    ai_quality_canary_judge     operational/ai_quality_canary_lambda.py

  parsed in the door WITHOUT a schema (text seams — no request body to attach one to):
    ai_calls call_training_nutrition_coach / call_tldr_and_guidance (AI_MODEL; the
      `_ground_legacy_output` gate re-asks on raw TEXT through `call_anthropic`) → parse_json_text
    margaret_editor_pass critique (Haiku via call_anthropic_api, shared with a PROSE revision) → parse_json_text
    chronicle_recap (the chronicle's `call_anthropic` text seam) → parse_json_text
    coach_panel_podcast `_extract_json` (the `extract_json` dep of repair/craft/the script builders;
      the intro and weekly scripts are array-rooted) → parse_json_text, then parse_json_span
    rewrite_note.parse_edits · eyeball_calibration · review_pack_ranker (span grabs) → parse_json_span

  NOT yet through the door: the five span parsers in tests/test_bedrock_client.py's
  JSON_HAND_PARSE_LEDGER, each with the contract that keeps it out.
"""

from __future__ import annotations

import copy
import json
from typing import Any, Callable, Optional

LOG_TAG = "STRUCTURED_OUTPUT"


def parse_json_text(text: Any) -> Any:
    """The legacy parse: whole text, then a ```json fence, then a bare ``` fence; else the text."""
    text = str(text or "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for opener in ("```json", "```"):
        if opener in text:
            start = text.find(opener) + len(opener)
            end = text.find("```", start)
            if end > start:
                try:
                    return json.loads(text[start:end].strip())
                except json.JSONDecodeError:
                    pass
            break
    return text


_CLOSERS = {"{": "}", "[": "]"}


def parse_json_span(text: Any, openers: str = "{[") -> Any:
    """Salvage for a reply with prose around its JSON: the span from the first of `openers`
    to the last matching closer, parsed; None when there is no span or it does not parse.

    The same span the greedy, DOTALL `{...}`/`[...]` regex took in coach_panel_podcast's
    extractor (and the `find("{")`/`rfind("}")` slices elsewhere), moved here (#4276) so the
    salvage is one copy in the one door.
    """
    text = str(text or "")
    starts = [i for i in (text.find(o) for o in openers) if i != -1]
    if not starts:
        return None
    a = min(starts)
    b = max(text.rfind(_CLOSERS[o]) for o in openers)
    if b <= a:
        return None
    try:
        return json.loads(text[a : b + 1])  # noqa: E203
    except json.JSONDecodeError:
        return None


def decode_error(value: Any) -> str:
    """Why `value` (call_json's return) is not a JSON object: the decoder's message and position.

    A fence-wrapped reply cut at `max_tokens` has no closing fence, so the fence is stripped
    from the front only and the rest handed to the decoder; its position is into that remainder.
    """
    if isinstance(value, dict):
        return "parsed a JSON object"
    if not isinstance(value, str):
        return f"parsed a JSON {type(value).__name__}, not an object"
    text = value.strip()
    for opener in ("```json", "```"):
        if text.startswith(opener):
            text = text[len(opener) :]
            break
    text = text.rstrip().removesuffix("```")
    try:
        json.loads(text)
    except json.JSONDecodeError as e:
        return f"JSONDecodeError: {e.msg} line {e.lineno} col {e.colno} (char {e.pos} of {len(text)})"
    return "parsed JSON that is not an object"


def with_schema(body: dict, schema: dict) -> dict:
    """A copy of `body` whose `output_config` carries the JSON-schema format (other keys kept)."""
    from ai.bedrock_client import structured_output_config

    out = copy.deepcopy(body)
    oc = dict(out.get("output_config") or {})
    oc.update(structured_output_config(schema))
    out["output_config"] = oc
    return out


def _schema_rejected(exc: Exception) -> bool:
    msg = str(exc)
    return "output_config" in msg and ("ValidationException" in msg or "validation" in msg.lower() or "400" in msg)


def _text_of(resp: Any) -> str:
    for block in (resp or {}).get("content") or []:
        if isinstance(block, dict) and block.get("type", "text") == "text":
            return str(block.get("text") or "")
    return ""


def call_json(call: Callable[[dict], dict], body: dict, schema: Optional[dict] = None, label: str = "") -> Any:
    """Send `body` through `call` (e.g. `retry_utils.call_anthropic_raw`) and return parsed JSON.

    With `schema`, the request carries `output_config.format`. A schema refusal falls back
    once to the schema-less request. Returns a dict/list when the text parses, else the raw text
    (the callers' existing non-dict handling is unchanged).
    """
    sent_schema = schema is not None
    fallback = ""
    if sent_schema:
        try:
            resp = call(with_schema(body, schema))
        except Exception as e:  # noqa: BLE001 — only a schema refusal is absorbed; all else re-raises
            if not _schema_rejected(e):
                raise
            fallback = "schema_rejected"
            print(f"[{LOG_TAG}] label={label} fallback=schema_rejected detail={str(e)[:200]}")
            resp = call(body)
    else:
        resp = call(body)
    parsed = parse_json_text(_text_of(resp).strip())
    print(
        f"[{LOG_TAG}] label={label} schema={'yes' if sent_schema and not fallback else 'no'} "
        f"stop_reason={(resp or {}).get('stop_reason')} parsed={'dict' if isinstance(parsed, dict) else type(parsed).__name__}"
        + (f" fallback={fallback}" if fallback else "")
    )
    return parsed
