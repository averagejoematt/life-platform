"""#3419: the board panel's PARALLEL persona pass — extracted sibling of
site_api_ai_lambda (module-size guard: the host file is baselined at 1700
lines; the panel machinery lives here, like _req/_sess/the prompt module).

Why parallel: sequentially, ~5s/persona meant the panel sizes the rate
arithmetic allows were undeliverable in wall time — the 2026-09-02 live probe
of a 5-persona panel hit the Lambda's own 30s ceiling (Status: timeout, the
5th persona never reached). Division of labor:

  * MAIN thread (before): every DDB context read (stance/memory/episodic +
    the persona system block) — boto3 resources are not thread-safe.
  * WORKERS: Bedrock invokes + the pure-text grounding gate + at most one
    corrective rewrite (bedrock_client's lazy clients are creation-locked for
    this). Each persona is its own prompt-cache entry, so parallel calls
    don't disturb COST-OPT-2 caching.
  * MAIN thread (after): metric emission, eval retention, episodic
    write-back, the #3414 observer, response assembly — in request order.

Seam contract: every collaborator is called THROUGH the host module (`ai`),
passed in by `convene()` — so the existing test/canary seams (monkeypatched
attributes on web.site_api_ai_lambda) keep gating the real path, and this
module imports nothing back from the host (no cycle).
"""

import json
from concurrent.futures import ThreadPoolExecutor


def _prepare(ai, personas: list, question: str, facts: str) -> tuple[list, dict]:
    """Main-thread prep: all DDB context reads + the per-persona user turn."""
    _phase_blk = ai._phase_context_block()
    prepared = []
    prep_failed: dict = {}
    for pid in personas:
        try:
            # #531: one mind per coach — the board self loads the same memory the
            # daily-brief self reasons from (stance + compressed state), plus its
            # own recent board answers (episodic). All volatile → user turn, so
            # the persona system block stays byte-stable for the prompt cache.
            stance = ai._coach_stance_bits(pid)
            memory = ai._coach_memory_bits(pid)
            episodic = ai._coach_recent_interactions(pid)
            user_msg = (
                f"CURRENT DATA (authoritative — cite only these numbers): {facts}\n"
                # #1086: the phase block rides the user turn (volatile), never
                # the cached persona system block — COST-OPT-2.
                + f"{_phase_blk}\n"
                + (f"YOUR CURRENT READ (your own published stance): {stance}\n" if stance else "")
                + (f"YOUR MEMORY (the compressed history your weekly summarizer maintains): {memory}\n" if memory else "")
                + (
                    f"YOUR RECENT BOARD ANSWERS (reference them when relevant — never silently contradict them):\n{episodic}\n"
                    if episodic
                    else ""
                )
                + f"READER QUESTION: {ai.wrap_untrusted_reader_text(question)}"  # R22-SEC-04 (#811)
            )
            prepared.append((pid, user_msg, ai._coach_system(pid)))
        except Exception as e:
            prep_failed[pid] = str(e)
    return prepared, prep_failed


def _generate(ai, pid: str, user_msg: str, _sys_txt: str) -> dict:
    """Worker: ONE persona's generation — Bedrock calls and the pure-text
    grounding gate ONLY (no other boto3 use; see the module docstring).
    Returns everything the main thread needs to run the side effects
    afterward; `findings` is non-None iff the grounding gate fired."""
    out = {"pid": pid, "txt": "", "grounded": True, "draft": None, "findings": None, "usages": [], "error": None}
    try:
        req_body = json.dumps(
            {
                "model": ai.AI_MODEL_HAIKU,
                # #531 follow-up: 300 → 450. The voice-core selves write
                # longer analytical sentences; at 300 the closing sentence
                # was truncating mid-thought on the public page.
                "max_tokens": 450,
                "system": [
                    {
                        "type": "text",
                        "text": _sys_txt,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                "messages": [{"role": "user", "content": user_msg}],
            }
        )
        # ADR-062 (2026-05-27): Bedrock invoke_model (was urllib → api.anthropic.com).
        # No retry wrapper — board_ask makes one call per persona; a transient
        # Bedrock error on persona N degrades cleanly to "[name] temporarily
        # unavailable" for that persona. bedrock_client is bundled in
        # /var/task via Code.from_asset, so it imports even though site-api-ai
        # runs without the shared layer.
        from ai.bedrock_client import invoke as _bedrock_invoke

        result = _bedrock_invoke(json.loads(req_body))
        out["usages"].append(result.get("usage", {}))
        _txt = ai._scrub_blocked_terms("".join(b["text"] for b in (result.get("content") or []) if b.get("type") == "text"))

        # ADR-104 grounding gate (reader-facing → fail-closed, no regen —
        # board_ask already costs one paid call per persona): any number the
        # coach states must exist in its system context, the facts, its
        # stance, or the question. Ungrounded → an honest in-voice refusal,
        # never a fabricated figure served to a reader.
        try:
            from ai import grounded_generation as _gg

            _gf = ai.board_grounding_findings(_sys_txt, user_msg, _txt)
            if _gf:
                out["draft"] = _txt  # #812/#744: keep the flagged draft for retention
                out["findings"] = _gf
                ai.logger.warning(f"[board_ask] {pid} ungrounded: {[f['detail'] for f in _gf][:3]}")
                out["grounded"] = False
                _refusal = (
                    "I'd want to answer that with numbers I can actually stand behind, and I can't "
                    "ground them in today's record — ask me about something the current data covers."
                )
                # #531 follow-up (live drill 2026-07-04): ONE corrective
                # rewrite before falling back to the refusal — the same
                # discipline the daily-brief self gets (regen-once). Bounded:
                # at most one extra Haiku call per flagged persona, inside
                # the board rate limit.
                try:
                    _corr_body = json.loads(req_body)
                    _corr_body["messages"] = [{"role": "user", "content": user_msg + "\n\n" + _gg.correction_prompt(_gf)}]
                    _retry = _bedrock_invoke(_corr_body)
                    out["usages"].append(_retry.get("usage", {}))
                    _txt2 = ai._scrub_blocked_terms("".join(b["text"] for b in _retry.get("content", []) if b.get("type") == "text"))
                    if _txt2.strip() and not ai.board_grounding_findings(_sys_txt, user_msg, _txt2):
                        _txt = _txt2
                        out["grounded"] = True
                        ai.logger.info(f"[board_ask] {pid} corrected once — grounded on retry")
                    else:
                        _txt = _refusal
                except Exception as _rt_e:
                    ai.logger.warning(f"[board_ask] {pid} correction retry failed: {_rt_e}")
                    _txt = _refusal
        except ImportError:
            pass  # helper not bundled — serve as before
        except Exception as _gg_e:
            ai.logger.warning(f"[board_ask] {pid} grounding gate error (fail-open): {_gg_e}")

        out["txt"] = _txt
    except Exception as e:
        out["error"] = str(e)
    return out


def convene(ai, personas: list, question: str, facts: str) -> tuple[dict, dict]:
    """The whole panel pass: prep (main thread) → parallel generation →
    side effects + assembly (main thread, request order). Returns
    (responses, threads) exactly as the host handler consumed them inline."""
    prepared, prep_failed = _prepare(ai, personas, question, facts)

    if len(prepared) > 1:
        with ThreadPoolExecutor(max_workers=min(len(prepared), 8)) as _pool:
            results = {r["pid"]: r for r in _pool.map(lambda args: _generate(ai, *args), prepared)}
    else:
        results = {r["pid"]: r for r in (_generate(ai, *args) for args in prepared)}

    # #3413: the ADR-108 quality gate used to run in the loop, synchronously.
    # It is off the reader path now — see #3413 for the measurement. Grounding
    # (fail-closed) already ran in the workers above.
    responses: dict = {}
    threads: dict = {}  # #546: opening transcript per coach that actually answered
    for pid in personas:
        p = ai.COACH_ROSTER[pid]
        _r = results.get(pid)
        if _r is None:
            ai.logger.error(f"[board_ask] {pid} failed: prep error {prep_failed.get(pid, 'missing result')}")
            responses[pid] = f"[{p['name']} is temporarily unavailable]"
            continue
        for _u in _r["usages"]:
            # V2 follow-up: emit per-persona token metrics (was dark)
            ai._emit_token_metrics(_u, endpoint="api_board_ask")
        if _r["error"] is not None:
            ai.logger.error(f"[board_ask] {pid} failed: {_r['error']}")
            responses[pid] = f"[{p['name']} is temporarily unavailable]"
            continue
        _txt = _r["txt"]
        _grounded = _r["grounded"]
        if _r["findings"] is not None:
            ai._retain_board_flag(pid, "flagged_corrected" if _grounded else "flagged_refused", _r["draft"], _txt, _r["findings"])
        # #531: the answer enters the coach's own memory (fail-soft).
        ai._write_board_interaction(pid, question, _txt, grounded=_grounded)
        # #3414: async voice-verdict capture — grounded answers only (a
        # refusal is canned text; judging its voice would pollute the rate).
        if _grounded:
            ai._observe_board_verdict(pid, _txt)
        responses[pid] = _txt
        # #546: seed a follow-up thread for every coach that gave a real
        # answer (an unavailable stub carries nothing to build on).
        if _grounded:
            threads[pid] = [{"q": question, "a": _txt}]
    return responses, threads
