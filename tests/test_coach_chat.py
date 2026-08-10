"""tests/test_coach_chat.py — the conversational turn engine (#2364, epic #2363).

The engine is deliberately pure, so everything interesting is testable here with no
AWS: the grounding hold, the budget refusals, the thread assembly, and the storage
records. What is pinned is BEHAVIOUR a reader would notice — a coach that sends an
ungrounded number, a coach that goes silent, a coach that forgets what was said two
messages ago — not the shape of the prompt string.
"""

from __future__ import annotations

import pytest
from coach import coach_chat as cc

# ── Test doubles ──────────────────────────────────────────────────────────────


def reply(text):
    """A ``bedrock_client.invoke``-shaped response."""
    return {"content": [{"type": "text", "text": text}]}


class FakeCaller:
    """Returns each queued reply in turn; records every request it was given."""

    def __init__(self, *texts):
        self.texts = list(texts)
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        return reply(self.texts.pop(0) if self.texts else "")


def grounder_clean(_text):
    return []


def grounder_always_finds(_text):
    return [{"type": "night_scope", "detail": "HRV 42 ms is 2026-08-07's reading, presented as today's"}]


def grounder_on(*bad_substrings):
    """Finds a violation only in replies containing one of these substrings."""

    def _g(text):
        return [{"type": "fabricated_number", "detail": f"{s} is not in the facts"} for s in bad_substrings if s in text]

    return _g


def turn(caller, grounder, **kw):
    params = dict(
        coach_id="nutrition",
        coach_name="Dr. Marcus Webb",
        persona_block="VOICE: blunt, evidence first.",
        memory_block="You remember: he committed to 170g protein.",
        facts_block="FACTS: protein yesterday 148 g.",
        thread=[],
        inbound="how'd I do on protein yesterday?",
        model="claude-haiku-4-5-20251001",
        caller=caller,
        grounder=grounder,
    )
    params.update(kw)
    return cc.run_turn(**params)


# ── The honesty contract: regenerate ONCE, then hold ──────────────────────────


def test_a_grounded_reply_is_sent_on_the_first_attempt():
    r = turn(FakeCaller("148 g. Under the floor, but you logged it."), grounder_clean)
    assert r.status == "sent"
    assert r.grounded is True
    assert r.attempts == 1
    assert r.text == "148 g. Under the floor, but you logged it."


def test_an_ungrounded_reply_is_regenerated_and_the_clean_rewrite_is_sent():
    caller = FakeCaller("You averaged 165 g.", "148 g yesterday. Under the floor.")
    r = turn(caller, grounder_on("165"))
    assert r.status == "regenerated"
    assert r.grounded is True
    assert r.attempts == 2
    assert "165" not in r.text


def test_a_reply_ungrounded_twice_is_HELD_and_never_reaches_matthew():
    """The defect this exists to prevent: a wrong number in a trusted voice on his
    phone, which he will act on with no cockpit beside it to contradict."""
    caller = FakeCaller("You averaged 165 g.", "More like 170 g, roughly.")
    r = turn(caller, grounder_on("165", "170"))
    assert r.status == "held"
    assert r.grounded is False
    assert "165" not in r.text and "170" not in r.text
    assert r.text == cc._HELD_REPLY


def test_the_retry_is_not_keep_if_better_a_merely_improved_reply_is_still_held():
    """AIQ-2 in the 2026-08-09 review measured the expert analyzer publishing
    narratives whose finding count merely DROPPED (6 -> 2) — two ungrounded claims
    still shipped. Fewer findings is not zero findings."""

    def improving_grounder(text):
        n = 3 if "first" in text else 1  # strictly better, still not clean
        return [{"type": "fabricated_number", "detail": f"claim {i}"} for i in range(n)]

    r = turn(FakeCaller("the first answer", "the second answer"), improving_grounder)
    assert r.status == "held", "a reply with 1 remaining finding must not ship just because it beat 3"
    assert len(r.findings) == 1


def test_a_held_turn_still_answers_rather_than_going_silent():
    """Silence reads as the platform being broken, and an unanswered text is its own
    small lie. The deferral must be a real message."""
    r = turn(FakeCaller("bad", "also bad"), grounder_always_finds)
    assert r.text.strip(), "a held turn must still send something"
    assert len(r.text) > 40


def test_the_regeneration_prompt_names_the_offending_claim():
    """A blind re-roll is a coin flip. The second attempt has to be told what was
    wrong or it is not meaningfully a second attempt."""
    caller = FakeCaller("You averaged 165 g.", "148 g.")
    turn(caller, grounder_on("165"))
    assert len(caller.requests) == 2
    correction = caller.requests[1]["messages"][-1]["content"]
    assert "165 is not in the facts" in correction
    assert caller.requests[1]["messages"][-2]["role"] == "assistant"


def test_the_findings_that_caused_a_hold_are_carried_for_inspection():
    r = turn(FakeCaller("bad", "bad"), grounder_always_finds)
    assert r.findings and r.findings[0]["type"] == "night_scope"


def test_an_inference_error_holds_rather_than_sending_a_raw_exception():
    class Boom:
        def __call__(self, _request):
            raise RuntimeError("bedrock is having a day")

    r = turn(Boom(), grounder_clean)
    assert r.status == "error"
    assert r.grounded is False
    assert "bedrock" not in r.text.lower(), "an internal error must not leak into a text message"


def test_an_empty_model_reply_is_retried_then_held():
    r = turn(FakeCaller("", ""), grounder_clean)
    assert r.status == "held"
    assert r.attempts == 2


# ── Budget: refuse BEFORE inference, and say so ───────────────────────────────


def test_at_the_pause_tier_the_coach_refuses_without_touching_the_model():
    caller = FakeCaller("this must never be generated")
    r = turn(caller, grounder_clean, tier=2)
    assert r.status == "paused"
    assert caller.requests == [], "a paused turn must cost zero tokens"


def test_tier_three_also_pauses():
    r = turn(FakeCaller("x"), grounder_clean, tier=3)
    assert r.status == "paused"


def test_tier_one_still_answers_because_a_private_chat_outranks_a_reader_narrative():
    """Tier 1 pauses internal/dev AI and tier 2 reader narratives. A private coach
    chat is closer to the daily brief in priority, so it survives tier 1."""
    r = turn(FakeCaller("148 g."), grounder_clean, tier=1)
    assert r.status == "sent"


def test_an_unknown_tier_proceeds_rather_than_muting_every_coach_on_an_ssm_blip():
    r = turn(FakeCaller("148 g."), grounder_clean, tier=None)
    assert r.status == "sent"


def test_the_daily_cap_refuses_and_names_the_number():
    caller = FakeCaller("x")
    r = turn(caller, grounder_clean, turns_today=cc.DAILY_TURN_CAP)
    assert r.status == "capped"
    assert str(cc.DAILY_TURN_CAP) in r.text
    assert caller.requests == []


def test_one_turn_under_the_cap_still_answers():
    r = turn(FakeCaller("148 g."), grounder_clean, turns_today=cc.DAILY_TURN_CAP - 1)
    assert r.status == "sent"


def test_the_paused_and_capped_replies_explain_themselves_honestly():
    """A refusal a reader can't interpret is indistinguishable from a bug."""
    paused = cc.budget_refusal(3, 0)
    capped = cc.budget_refusal(0, cc.DAILY_TURN_CAP)
    assert "budget" in paused.lower() and "brief" in paused.lower()
    assert "budget" in capped.lower() and "tomorrow" in capped.lower()


# ── Thread assembly: the thing that makes it feel like a person ───────────────


def test_the_thread_reaches_the_model_oldest_first_in_alternating_roles():
    thread = [
        {"role": cc.ROLE_MATTHEW, "text": "morning"},
        {"role": cc.ROLE_COACH, "text": "Protein's the only thing I'd change."},
    ]
    caller = FakeCaller("Right — 148 yesterday.")
    turn(caller, grounder_clean, thread=thread)
    msgs = caller.requests[0]["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
    assert msgs[0]["content"] == "morning"
    assert msgs[-1]["content"] == "how'd I do on protein yesterday?"


def test_two_consecutive_messages_from_matthew_are_merged_not_dropped():
    """He texts twice before the coach answers — what a real person does. Anthropic
    requires alternating roles, and dropping one would silently discard something he
    said, which is the one resolution this platform cannot take."""
    thread = [
        {"role": cc.ROLE_MATTHEW, "text": "quick q"},
        {"role": cc.ROLE_MATTHEW, "text": "about yesterday's protein"},
    ]
    msgs = cc.format_thread(thread)
    assert len(msgs) == 1
    assert "quick q" in msgs[0]["content"] and "about yesterday's protein" in msgs[0]["content"]


def test_a_leading_coach_turn_is_dropped_from_the_prompt_but_not_from_memory():
    """When the coach texts first (the outbound story), the stored thread opens with
    an assistant turn — not a legal Anthropic opener. Dropping it is a protocol fix
    at the prompt layer only; storage is untouched."""
    thread = [
        {"role": cc.ROLE_COACH, "text": "You skipped logging again."},
        {"role": cc.ROLE_MATTHEW, "text": "I know"},
    ]
    msgs = cc.format_thread(thread)
    assert msgs[0]["role"] == "user"
    assert len(thread) == 2, "format_thread must not mutate the caller's list"


def test_the_thread_is_bounded_so_a_long_evening_does_not_inflate_cost_forever():
    thread = [{"role": cc.ROLE_MATTHEW if i % 2 == 0 else cc.ROLE_COACH, "text": f"m{i}"} for i in range(40)]
    msgs = cc.format_thread(thread)
    assert len(msgs) <= cc.MAX_THREAD_TURNS
    assert msgs[-1]["content"] == "m39", "the bound must keep the MOST RECENT turns"


def test_empty_turns_are_skipped_rather_than_sent_as_blank_messages():
    thread = [{"role": cc.ROLE_MATTHEW, "text": ""}, {"role": cc.ROLE_MATTHEW, "text": "real"}]
    assert [m["content"] for m in cc.format_thread(thread)] == ["real"]


# ── The system prompt carries the honesty rule ────────────────────────────────


def test_the_system_prompt_forbids_attaching_today_to_another_days_reading():
    """#2343's class stated in the prompt as well as enforced by the gate. The prompt
    is not the guarantee — prompt rules cannot guarantee structure — but a prompt
    that omits the rule makes the gate do work it shouldn't have to."""
    s = cc.build_system_prompt("VOICE", "MEM", "FACTS", "Dr. Marcus Webb")
    assert "do not attach today to a reading from another day" in s
    assert "say you don't have it" in s


def test_the_system_prompt_puts_the_stable_persona_before_the_daily_facts():
    """Cache-prefix discipline (COST-OPT-2): the volatile block last, or every day's
    facts invalidate the persona's cached prefix."""
    s = cc.build_system_prompt("PERSONA_MARKER", "MEM", "FACTS_MARKER", "X")
    assert s.index("PERSONA_MARKER") < s.index("FACTS_MARKER")


def test_the_coach_is_told_to_text_like_a_person_not_file_a_report():
    s = cc.build_system_prompt("V", "M", "F", "Dr. Marcus Webb")
    assert "text message" in s and "no salutation or sign-off" in s


# ── Formatting ────────────────────────────────────────────────────────────────


def test_a_long_reply_is_cut_on_a_sentence_boundary_not_mid_number():
    """A hard truncation can strand half a number — a NEW honesty defect invented by
    the formatter, after the grounding gate already passed the text."""
    body = "This is a full sentence about protein. " * 60
    out = cc.clip_reply(body + "Your average was 148.7 g.")
    assert len(out) <= cc.MAX_REPLY_CHARS
    assert out.endswith(".")
    assert "148." not in out or "148.7" in out


def test_a_reply_with_no_sentence_boundary_is_still_bounded():
    out = cc.clip_reply("x" * 5000)
    assert len(out) <= cc.MAX_REPLY_CHARS


def test_a_short_reply_is_untouched():
    assert cc.clip_reply("148 g. Under the floor.") == "148 g. Under the floor."


def test_an_overlong_inbound_message_is_clipped_before_it_is_stored_or_prompted():
    long = "a" * 9000
    caller = FakeCaller("ok")
    turn(caller, grounder_clean, inbound=long)
    sent = caller.requests[0]["messages"][-1]["content"]
    assert len(sent) == cc.MAX_INBOUND_CHARS
    recs = cc.turn_records("nutrition", "Dr. Marcus Webb", long, cc.TurnResult("ok", "sent"))
    assert len(recs[0]["text"]) == cc.MAX_INBOUND_CHARS, "storage and prompt must agree on what was said"


# ── Storage: the chat joins the memory the rest of the platform reads ─────────


def test_a_turn_writes_to_the_same_partition_family_the_dossier_reads():
    """Texting a coach must make that coach know Matthew better. A side channel would
    give him the FEELING of being known while the memory stayed empty."""
    recs = cc.turn_records("nutrition", "Dr. Marcus Webb", "hi", cc.TurnResult("hey", "sent"))
    assert all(r["pk"] == "COACH#nutrition_coach" for r in recs)
    assert all(r["sk"].startswith(cc.CHAT_SK_PREFIX) for r in recs)


def test_both_sides_of_the_exchange_are_stored_in_order():
    recs = cc.turn_records("nutrition", "Dr. Marcus Webb", "hi", cc.TurnResult("hey", "sent"))
    assert [r["role"] for r in recs] == [cc.ROLE_MATTHEW, cc.ROLE_COACH]
    assert recs[0]["text"] == "hi" and recs[1]["text"] == "hey"


def test_a_held_turn_is_stored_WITH_its_findings_so_the_gap_is_inspectable():
    """A later reader must see that the coach declined and why — not find a hole."""
    held = cc.TurnResult(cc._HELD_REPLY, "held", [{"type": "night_scope"}], 2)
    recs = cc.turn_records("nutrition", "Dr. Marcus Webb", "hrv?", held)
    assert recs[1]["status"] == "held"
    assert recs[1]["findings"] == ["night_scope"]


def test_a_grounded_turn_records_no_findings_key():
    recs = cc.turn_records("nutrition", "Dr. Marcus Webb", "hi", cc.TurnResult("hey", "sent"))
    assert "findings" not in recs[1]


def test_the_cycle_is_stamped_when_known_and_omitted_when_not():
    with_cycle = cc.turn_records("nutrition", "X", "hi", cc.TurnResult("y", "sent"), cycle=12)
    without = cc.turn_records("nutrition", "X", "hi", cc.TurnResult("y", "sent"))
    assert all(r["cycle"] == 12 for r in with_cycle)
    assert all("cycle" not in r for r in without)


def test_provenance_distinguishes_a_text_from_an_mcp_checkin():
    recs = cc.turn_records("nutrition", "X", "hi", cc.TurnResult("y", "sent"))
    assert all(r["provenance"] == "telegram" for r in recs)


# ── Id conventions must not fork from coach_checkin ───────────────────────────


@pytest.mark.parametrize("given", ["nutrition", "nutrition_coach", "  Nutrition_Coach  "])
def test_the_partition_is_the_same_whichever_id_form_arrives(given):
    assert cc.chat_pk(given) == "COACH#nutrition_coach"


def test_the_sk_is_date_ordered_so_a_days_thread_reads_back_in_order():
    sk = cc.new_chat_sk("2026-08-09", uid="abcdef12")
    assert sk.startswith("CHAT#2026-08-09#")


def test_two_turns_in_the_same_second_do_not_collide():
    a = cc.turn_records("nutrition", "X", "hi", cc.TurnResult("y", "sent"))
    b = cc.turn_records("nutrition", "X", "hi", cc.TurnResult("y", "sent"))
    assert {r["sk"] for r in a}.isdisjoint({r["sk"] for r in b})


def test_eli_marsh_chats_land_on_the_partition_every_other_surface_reads():
    """The lead's registry id carries no _coach suffix; blindly appending one
    (COACH#eli_marsh_coach) would strand his chats in a partition RELATIONSHIP#,
    the profile surface, and the evaluator never read. Fixed before any eli
    traffic existed, so no rows migrate."""
    assert cc.chat_pk("eli_marsh") == "COACH#eli_marsh"


def test_every_texting_persona_keys_chat_to_its_own_registry_partition():
    """Set-derived, not instance: for every persona that can text, the chat
    partition must be COACH#{persona_id} — the same partition the rest of the
    coach engine keys that persona by."""
    from coach.persona_registry import TEXTING_PERSONA_IDS

    for pid in TEXTING_PERSONA_IDS:
        assert cc.chat_pk(pid) == f"COACH#{pid}"


# ── The system message actually caches (the docstring is no longer a lie) ─────


def test_build_request_sends_system_as_blocks_with_a_cached_stable_prefix():
    req = cc.build_request(
        persona_block="PERSONA_MARKER",
        memory_block="MEM_MARKER",
        facts_block="FACTS_MARKER",
        coach_name="Dr. Lisa Park",
        thread=[],
        inbound="hey",
        model="m",
        colleagues_block="COLLEAGUES_MARKER",
    )
    blocks = req["system"]
    assert isinstance(blocks, list) and len(blocks) == 2
    assert blocks[0]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in blocks[1]
    # The stable identity lives in the cached prefix; everything volatile behind it.
    assert "PERSONA_MARKER" in blocks[0]["text"] and "COLLEAGUES_MARKER" in blocks[0]["text"]
    assert "MEM_MARKER" in blocks[1]["text"] and "FACTS_MARKER" in blocks[1]["text"]
    assert "HARD RULE" in blocks[1]["text"]


def test_the_blocks_and_the_flat_string_cannot_fork():
    """Both renderers derive from _system_parts — joined blocks must equal the
    string form byte-for-byte, or a future edit to one silently diverges the
    tested prompt from the shipped prompt."""
    args = dict(persona_block="P", memory_block="M", facts_block="F", coach_name="X", colleagues_block="C")
    joined = "\n\n".join(b["text"] for b in cc.build_system_blocks(**args))
    assert joined == cc.build_system_prompt(**args)


# ── The humanity rules from the first real transcripts (2026-08-10) ───────────


def test_the_rules_teach_register_matching_not_briefing():
    s = cc.build_system_prompt("V", "M", "F", "Dr. Lisa Park")
    assert "a bare 'hey' gets a bare hey back" in s
    assert "end on a statement" in s


def test_the_rules_ban_filler_questions_and_assistant_isms():
    s = cc.build_system_prompt("V", "M", "F", "Dr. Lisa Park")
    assert "What's on your mind?" in s  # named as the banned example
    assert "Honest answer:" in s  # named as the banned example
    assert "use his name sparingly" in s


def test_the_persona_outranks_a_poisoned_memory_about_identity():
    """The go-live corpus contains a summary row memorializing 'I'm not Lisa'
    from the pre-fix identity bug. The prompt must tell the coach its persona
    outranks remembered notes, or the poisoned row re-teaches the error."""
    s = cc.build_system_prompt("V", "M", "F", "Dr. Lisa Park")
    assert "authoritative over remembered notes" in s
    assert "never tell him he has your name wrong" in s


def test_the_rules_welcome_off_lane_conversation():
    """He should be able to text a coach about anything — a person first."""
    s = cc.build_system_prompt("V", "M", "F", "Dr. Lisa Park")
    assert "engage with it as yourself first" in s


# ── Time-gap awareness (#2489) — the memory-block seam this module owns ───────


def test_a_time_gap_line_in_memory_block_reaches_the_system_prompt_verbatim():
    """The gap line itself is assembled in coach_chat_summary.time_gap_line and
    folded into the memory_block string upstream (see that module's docstring
    for why); this module's only obligation is to carry whatever memory_block
    contains into the volatile tail untouched, same as any other memory
    content. Pinned here so a future change to the tail assembly can't silently
    drop or mangle it."""
    from coach import coach_chat_summary as ccs

    gap_line = (
        "TIME GAP: it has been 9 days since your last conversation with Matthew (you last texted on "
        "2026-08-01). That is a real quiet stretch, not an ongoing thread — acknowledge it naturally and briefly, "
        "the way a person notices time passed with someone they know ('hey, been a minute'), then move on to what "
        "he actually said. Never mention this, or any gap, when the thread has been active."
    )
    s = cc.build_system_prompt("V", gap_line, "F", "Dr. Lisa Park")
    assert gap_line in s
    assert ccs.QUIET_GAP_DAYS == 7  # the threshold this line's wording assumes
