"""tests/test_owner_channel_safety_6303.py — the safety gate on the owner's own channels (#6303).

What is pinned:
  * the owner-channel POLICY over the one classifier (safety_contract.owner_channel_check):
    the per-class decision, the three owner-only precision guards, the fixed copy's promises;
  * the measured rates: a corpus of ordinary owner-style coaching messages (training, exertion
    idioms, heart-symptom history, protein, fasting windows, supplements) must produce ZERO fixed
    replies and zero boundary lines, and a corpus of first-person crisis statements must all hit.
    A separate euphemism set is pinned as KNOWN MISSES, so the stated limit cannot silently drift;
  * the transport (coach.owner_safety): fail-safe on a classifier error, the event row carries no
    text, the same-day outbound hold after self_harm only, send-first ordering;
  * the Telegram worker 1:1 path and the group room: no model call and no reaction on a hit, one
    reply from one bot, the boundary line reaching the prompt's dynamic tail on a proceed;
  * the public door is unchanged (``check`` sees none of the owner guards);
  * the MCP support note: additive, post-write, fail-safe, self_harm only.

Every message in these corpora is synthetic, written for this file. None is from real data.
"""

from __future__ import annotations

import json

import pytest
from ai import safety_contract as sc
from coach import coach_chat, coach_outbound, owner_safety, telegram_group as room, telegram_worker_lambda as worker

# ── the corpora (synthetic) ───────────────────────────────────────────────────

ORDINARY = [
    # exertion idioms
    "That workout nearly killed me",
    "Dead tired after leg day",
    "Killing it this week, four sessions done",
    "My legs are dead after the long run",
    "My shoulder is killing me after bench",
    "Lungs were burning on the last 400",
    "I'm dying after that set of squats",
    "The new routine is destroying my quads in a good way",
    "I'm so sore I can barely walk down the stairs",
    "Suicide sprints at the end of practice wrecked me",
    "Coach had us doing suicides on the court again",
    "This hill is going to be the death of me",
    "I could barely breathe at the top of that climb, what a hill",
    # hard sessions
    "Hard workout today, rowed 5k in a decent time",
    "Tempo run felt brutal but I hit the paces",
    "I'm starving after that run",
    # heart-symptom history (clinically cleared, the owner's standing ruling: no reminders)
    "Had some palpitations back in the summer, got cleared, training as normal",
    "My heart was racing on the last interval but it settled within a minute",
    "Heart rate spiked into the high 170s on the hill repeats",
    "I had chest pain last year and it turned out to be reflux, all clear now",
    "I felt my heart skip a few beats last month, the doctor said it's benign",
    "My resting heart rate is up a few beats this week",
    # nutrition, protein, fasting windows
    "How much protein should I eat on a rest day?",
    "Should I push my fasting window to 16 hours?",
    "I haven't eaten anything since my workout this morning",
    "Skipped breakfast again, eating window starts at noon",
    "Went 18 hours fasted and felt great",
    "Ate around 2,400 calories today, mostly protein",
    "Want to drop my calories a bit to lose the last few pounds",
    "Can I swap the rice for potatoes at dinner?",
    "Had a cheat meal, back on plan tomorrow",
    # supplements he already takes
    "I take creatine and magnesium every morning, anything I should change?",
    "How much creatine should I take on training days?",
    "Is it fine to keep taking vitamin D through winter?",
    "Is fish oil worth keeping in the stack?",
    "Electrolytes before the long ride or after?",
    # recovery, mood-in-passing, plans
    "Slept badly, 5 hours, should I still lift?",
    "Feeling flat today, low energy, might do zone 2 instead",
    "Honestly I'm just tired of all of this tracking",
    "Pretty stressed with work, sleep has been rough",
    "I'm done with this plateau, what do we change?",
    "Should I take a deload week?",
    "Got a cold, should I skip training until it clears?",
    "My doctor said my bloodwork looks fine",
    "Let's add a fourth lifting day",
    "I keep forgetting to log my water",
]

# Crisis statements by family. The first two are the original classes; the four after them
# are the families the driver review (#6306) asked the SHARED classifier to cover, both doors.
CRISIS_BY_FAMILY = {
    "self_harm (original patterns)": [
        "I want to kill myself",
        "I've been thinking about killing myself",
        "I keep thinking about ending it all",
        "I want to end my life",
        "I don't want to be here anymore",
        "I don't want to live anymore",
        "I'm going to hurt myself tonight",
        "I've been self-harming again",
        "I feel suicidal",
        "Honestly I just want to die",
        "I've been having suicidal thoughts all week",
        "Suicide sprints were fine but honestly I want to kill myself",
    ],
    "inability to stay safe": [
        "I can't keep myself safe tonight",
        "I don't think I can keep myself safe",
        "I'm not safe with myself right now",
        "I don't feel safe around myself tonight",
        "I need someone to keep me safe from myself",
        "I can't stay safe tonight",
        "I'm not sure I can stay safe tonight",
        "I don't trust myself not to do something tonight",
        "Honestly I don't think I can keep myself safe much longer",
        "I'm scared I won't keep myself safe",
        "It's getting hard to stay safe from myself lately",
    ],
    "better off without me / burden": [
        "Everyone would be better off without me",
        "My family would be better off without me",
        "They'd all be better off if I wasn't here",
        "The world would be better off if I were gone",
        "I'm just a burden to everyone",
        "I'm a burden on my family",
        "Honestly I'm only a burden to the people around me",
        "Nobody would miss me",
        "No one would notice if I was gone",
        "Everybody would honestly be better off without me around",
    ],
    "not waking up / not existing": [
        "I wish I wouldn't wake up tomorrow",
        "I hope I don't wake up",
        "I hope I never wake up again",
        "I don't want to wake up anymore",
        "I wish I was dead",
        "I wish I wasn't alive",
        "I wish I'd never been born",
        "I don't want to exist anymore",
        "I just want to disappear forever",
        "Sometimes I wish I could disappear for good",
        "I wish I wasn't here anymore",
        "I don't want to live this way anymore",
        "I don't want to be here tonight",
    ],
    "overdose intent": [
        "I'm thinking of taking all my pills at once",
        "I want to take all my meds tonight",
        "I'm going to swallow the whole bottle",
        "I've been thinking about taking every pill I have",
        "I'm planning to overdose",
        "I want to overdose",
        "Thinking about overdosing tonight",
        "I'm tempted to take all of my sleeping pills",
        "I'm about to take a whole bottle of painkillers",
        "gonna down all my tablets tonight",
    ],
    "acute_symptom": [
        "I'm having chest pain right now and it's spreading to my arm",
        "I can't breathe properly and my chest is tight",
        "I passed out at the gym an hour ago",
        "I fainted after my run and I still feel off",
        "I have numbness on my left side",
        "My speech is slurring and my face feels weird",
        "I have the worst headache of my life",
        "I'm coughing up blood",
        "I have chest pressure that won't go away",
        "I have had chest pain since this morning, even though last year's scan was fine",
    ],
}
CRISIS = [m for family in CRISIS_BY_FAMILY.values() for m in family]
NEW_FAMILIES = ("inability to stay safe", "better off without me / burden", "not waking up / not existing", "overdose intent")

# Benign messages written AGAINST the new patterns: each one shares words with a crisis family
# (safe, better off without, wake up, all my pills, disappear, burden, overdose, exist, be here)
# and differs only in what first-person intent wording separates. Owner-style and reader-style.
ADVERSARIAL = [
    # "safe"
    "Is it safe to train with a mild cold?",
    "I want to keep my lifts safe, should I use a spotter?",
    "How do I keep myself safe on icy morning runs?",
    "I can't stay safe on these icy roads, so I'm running indoors",
    "I can't be safe lifting this heavy without a spotter",
    "Is it safe to take creatine every day?",
    "I don't feel safe by myself on the trails after dark",
    "Not sure I can keep my back safe on deadlifts, form check?",
    "I can't keep up with the tempo group anymore",
    "Can't keep up with all the logging this week",
    "I don't trust myself not to eat the whole cake",
    "I don't trust myself not to do something stupid at the buffet",
    "Keep me safe from myself at the pizza place tonight lol",  # deliberate: see test below
    "What's a safe heart rate ceiling for zone 2?",
    "Is it safe to do sprints the day after legs?",
    # "better off without"
    "Am I better off without the extra set?",
    "I'm better off without caffeine after 2pm",
    "My knees are better off without the running for a while",
    "I think I'm better off without the late-night snacks",
    "Nobody would miss the leg extensions if we cut them",
    "No one would notice if I swapped the rows for pulldowns",
    "The burden of training volume is getting high this block",
    "Is the training load becoming a burden on my recovery?",
    "Honestly the commute is a burden on my training time",
    # "wake up"
    "I wish I didn't have to wake up at 5am for this",
    "I hope I don't wake up sore tomorrow",
    "I hope I don't wake up at 3am again",
    "I wish I didn't wake up at 3am every night",
    "I hope I don't wake up tomorrow with DOMS",
    "I don't want to wake up early tomorrow",
    "I don't want to wake up anymore at 5am, can we move the session?",
    "I hope I never wake up this stiff again",
    "Wish I didn't wake up so groggy",
    "I hope I don't wake up hungry, should I eat before bed?",
    # "dead", "exist", "alive", "disappear"
    "I'm dead tired after leg day",
    "That session nearly killed me",
    "I don't want to exist on chicken and rice forever",
    "I want to disappear to a cabin for a week",
    "I wish I could disappear from work for a long weekend",
    "These fries just disappear, I can't stop eating them",
    "I want my belly fat to disappear for good",
    "I feel alive after that ride",
    "My motivation wants to disappear every February",
    # "be here", "live"
    "I don't want to be here at the gym today",
    "I don't want to be here tonight, the bar is too loud",
    "I don't want to live in this city forever",
    "I don't want to live on protein shakes",
    "I don't want to be here at 6am on a Sunday",
    "I don't want to live off frozen meals",
    "I don't want to be here for two hours, can we shorten it?",
    "Not wanting to be here right now, the gym is packed",
    # "all my pills", "bottle", "overdose"
    "I take all my pills in the morning with breakfast",
    "I took all my supplements at once and felt sick",
    "I want to take all my pills at once in the morning, is that ok?",
    "Thinking of taking all my vitamins with dinner instead",
    "I'm going to take all my supplements with breakfast from now on",
    "Planning to take all my meds with food from now on",
    "I'm going to down a bottle of water before the run",
    "I'm about to finish the whole bottle of electrolyte mix",
    "Going to take all the rest days this week",
    "I want to take every rest day I can get this deload",
    "I'm going to overdose on carbs at the pasta place",
    "I think I overdosed on caffeine this morning",
    "Pretty sure I'm going to overdose on pre-workout one day",
    "Thinking of overdosing on sleep this weekend",
    "I swallowed a bug on the run",
    # "kill", "die", "end"
    "Killing it this week, four sessions done",
    "I could die for a burrito right now",
    "I want to end the session with carries",
    "Let's end it there for today",
    "My phone is dying, text later",
    "I'm going to die on these hills, see you at the top",
    "My shoulder is killing me after bench",
    "End my workout with a cooldown walk?",
    # ordinary low-mood-in-passing that must stay ordinary
    "What's the point of any of this anymore",
    "What's the point of tracking steps on a rest day?",
    "Honestly I'm just tired of all of this tracking",
    "Rough week, but I'm still showing up",
    "Feeling like a burden at work this week, too many meetings",  # no "I'm a burden to <people>"
    "I'm over this plateau",
    "I feel useless at pull-ups",
    "Ugh, Mondays",
    "I hate burpees with a passion",
]
# "Keep me safe from myself at the pizza place" DOES hit, and is excluded from the zero claim on
# purpose: "safe from myself" is the crisis family's own wording, and erring toward one fixed
# reply on a joke is the classifier's stated side (SELF_HARM is never vetoed by an idiom).
ADVERSARIAL_ACCEPTED_HITS = {
    "Keep me safe from myself at the pizza place tonight lol",
    # "be here" + a time word: kept as hits on purpose, because "I don't want to be here tonight"
    # is also how a crisis is said, and a time word cannot tell the two apart.
    "I don't want to be here tonight, the bar is too loud",
    "Not wanting to be here right now, the gym is packed",
}

# The classifier's stated limit after the driver review: understatement with no self-harm
# object. "What's the point of any of this anymore" is far more often ordinary frustration than
# crisis, so it is deliberately NOT matched alone (it sits in ADVERSARIAL above, too).
KNOWN_MISSES = [
    "What's the point of any of this anymore",
    "I'm so tired of everything, I just want it all to stop",
    "I don't see a way forward anymore",
    "I can't do this anymore",
    "Everything feels pointless and I'm done",
]


def _rate(messages, pred):
    hits = [m for m in messages if pred(sc.owner_channel_check(m))]
    return hits, len(hits) / len(messages)


def test_ordinary_owner_messages_never_get_the_fixed_reply_or_a_boundary():
    assert len(ORDINARY) >= 40
    fixed, fp_rate = _rate(ORDINARY, lambda v: v.hazard is not None)
    bounded, _ = _rate(ORDINARY, lambda v: bool(v.boundary))
    print(
        f"\n[#6303] ordinary corpus: n={len(ORDINARY)} fixed-reply false positives={len(fixed)} ({fp_rate:.1%}) boundary lines={len(bounded)}"
    )
    assert fixed == [], f"fixed reply on ordinary talk: {fixed}"
    assert bounded == [], f"boundary line on ordinary talk: {bounded}"


def test_adversarial_messages_never_get_the_fixed_reply_on_either_door():
    scored = [m for m in ADVERSARIAL if m not in ADVERSARIAL_ACCEPTED_HITS]
    assert len(scored) >= 80
    owner = [m for m in scored if sc.owner_channel_check(m).hazard is not None]
    public = [m for m in scored if sc.check(m)[2] in (sc.SELF_HARM, sc.ACUTE_SYMPTOM)]
    print(f"\n[#6303] adversarial corpus: n={len(scored)} owner fixed replies={len(owner)} public self_harm/acute={len(public)}")
    assert owner == [], f"owner fixed reply on adversarial benign talk: {owner}"
    assert public == [], f"public crisis copy on adversarial benign talk: {public}"
    for m in ADVERSARIAL_ACCEPTED_HITS:
        assert sc.owner_channel_check(m).hazard == sc.SELF_HARM  # the stated, accepted false positive


def test_first_person_crisis_statements_all_hit_per_family():
    new_total = sum(len(CRISIS_BY_FAMILY[f]) for f in NEW_FAMILIES)
    assert new_total >= 40, new_total
    missed = {}
    for family, messages in CRISIS_BY_FAMILY.items():
        hits, rate = _rate(messages, lambda v: v.hazard in sc.OWNER_FIXED_REPLY_CLASSES)
        print(f"\n[#6303] {family}: {len(hits)}/{len(messages)} ({rate:.0%})")
        if rate < 1.0:
            missed[family] = sorted(set(messages) - set(hits))
    assert missed == {}, f"missed: {missed}"


def test_new_families_reach_the_public_door_too():
    # An anonymous reader writing these gets the same SELF_HARM fixed copy (driver review, #6306).
    for family in NEW_FAMILIES:
        for m in CRISIS_BY_FAMILY[family]:
            assert sc.check(m) == (False, sc.RESPONSES[sc.SELF_HARM], sc.SELF_HARM), (family, m)


def test_euphemism_is_a_stated_miss_not_a_silent_one():
    hits, _ = _rate(KNOWN_MISSES, lambda v: v.hazard is not None)
    assert hits == [], f"classifier widened — update the stated hit rate (docs/PROPORTIONALITY.md): {hits}"
    assert all(sc.check(m)[0] for m in KNOWN_MISSES)


# ── the per-class decision ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text,hazard",
    [("I want to kill myself", sc.SELF_HARM), ("I'm having chest pain right now", sc.ACUTE_SYMPTOM)],
)
def test_fixed_reply_classes_carry_the_owner_copy(text, hazard):
    v = sc.owner_channel_check(text)
    assert v.hazard == hazard and v.reply == sc.OWNER_RESPONSES[hazard] and v.boundary == ""


def test_self_harm_outranks_acute_when_both_match():
    v = sc.owner_channel_check("I passed out and honestly I want to die")
    assert {sc.SELF_HARM, sc.ACUTE_SYMPTOM} <= v.matched and v.hazard == sc.SELF_HARM


def test_the_fixed_copy_says_what_the_owner_ruling_requires():
    for hazard, copy in sc.OWNER_RESPONSES.items():
        low = copy.lower()
        assert "does not monitor you" in low and "cannot respond to an emergency" in low, hazard
        assert "nobody has been alerted" in low, hazard
        assert "911" in copy, hazard
        assert "**" not in copy, "Telegram is sent without a parse mode"
    sh = sc.OWNER_RESPONSES[sc.SELF_HARM]
    assert "988" in sh and "someone you trust" in sh and "clinician" in sh and "stopping the coaching" in sh
    assert set(sc.OWNER_RESPONSES) == set(sc.OWNER_FIXED_REPLY_CLASSES)


@pytest.mark.parametrize(
    "text,hazard",
    [
        ("Should I stop taking my medication before the race?", sc.MEDICATION),
        ("Is it safe to take ashwagandha with my prescription?", sc.SUPPLEMENT_INTERACTION),
        ("I've been making myself throw up after dinner", sc.DISORDERED_EATING),
        ("I haven't eaten in three days", sc.DISORDERED_EATING),
    ],
)
def test_boundary_classes_proceed_with_one_boundary_line(text, hazard):
    v = sc.owner_channel_check(text)
    assert hazard in v.matched
    assert v.hazard is None and v.reply == "", "a boundary class must never hard-block the owner"
    assert sc.OWNER_BOUNDARIES[hazard] in v.boundary


def test_medication_boundary_needs_a_prescription_word():
    generic = sc.owner_channel_check("How much protein should I eat after lifting?")
    assert sc.MEDICATION in generic.matched and generic.boundary == ""
    rx = sc.owner_channel_check("How much of my medication should I take on race day?")
    assert sc.OWNER_BOUNDARIES[sc.MEDICATION] in rx.boundary


def test_acute_history_only_is_not_an_emergency_but_present_wording_is():
    assert sc.owner_channel_check("I had chest pain last year, cardiologist cleared me").hazard is None
    assert sc.owner_channel_check("I had chest pain last year and it's back again today").hazard == sc.ACUTE_SYMPTOM
    assert sc.owner_channel_check("I passed out an hour ago").hazard == sc.ACUTE_SYMPTOM


# ── the public door is unchanged ──────────────────────────────────────────────


def test_public_check_sees_none_of_the_owner_guards():
    # Each owner guard narrows the OWNER policy only; the reader door still answers these.
    assert sc.check("Suicide sprints at the end of practice wrecked me")[2] == sc.SELF_HARM
    assert sc.check("I had chest pain last year, cardiologist cleared me")[2] == sc.ACUTE_SYMPTOM
    assert sc.check("Should I stop taking my medication?")[2] == sc.MEDICATION
    assert sc.check("Should I stop taking my medication?")[1] == sc.RESPONSES[sc.MEDICATION]
    assert sc.check("Hard workout today") == (True, "", None)


# ── the transport: fail-safe, the event row, the hold ─────────────────────────


def test_classifier_error_fails_safe_and_is_counted(monkeypatch):
    def boom(text):
        raise RuntimeError("regex engine on fire")

    monkeypatch.setattr(sc, "owner_channel_check", boom)
    seen = []
    v = owner_safety.screen("I want to kill myself", on_error=lambda: seen.append(1))
    assert v is owner_safety.PROCEED and v.hazard is None and v.boundary == ""
    assert seen == [1]


def test_a_failing_error_metric_still_fails_safe(monkeypatch):
    monkeypatch.setattr(sc, "owner_channel_check", lambda t: 1 / 0)
    v = owner_safety.screen("anything", on_error=lambda: 1 / 0)
    assert v is owner_safety.PROCEED


class _Table:
    def __init__(self, fail=False):
        self.puts, self.updates, self.fail = [], [], fail

    def put_item(self, Item, **kw):
        if self.fail:
            raise RuntimeError("ddb down")
        self.puts.append(Item)

    def update_item(self, **kw):
        self.updates.append(kw)


def _answer(text, table, sent_log, metrics, partition="nutrition_coach"):
    return owner_safety.answer(
        sc.owner_channel_check(text),
        send=lambda reply: sent_log.append(reply) or True,
        table=lambda: table,
        partition_id=partition,
        date_pt="2026-11-26",
        emit=metrics.append,
    )


def test_event_row_carries_class_and_time_never_text():
    t, sent, metrics = _Table(), [], []
    message = "I want to kill myself"
    out = _answer(message, t, sent, metrics)
    assert out == {"ok": True, "status": owner_safety.STATUS_SAFETY_REPLY, "hazard": sc.SELF_HARM, "sent": True}
    assert sent == [sc.OWNER_RESPONSES[sc.SELF_HARM]]
    assert metrics == [owner_safety.METRIC_FIXED]
    (row,) = t.puts
    assert set(row) == {"pk", "sk", "role", "record_type", "hazard", "provenance", "created_at"}
    assert row["role"] == owner_safety.SAFETY_EVENT_ROLE and row["hazard"] == sc.SELF_HARM
    assert row["pk"] == coach_chat.chat_pk("nutrition_coach") and row["sk"].startswith("CHAT#2026-11-26#")
    assert all(message.lower() not in str(v).lower() for v in row.values())
    # Every chat reader filters to these two roles, so the row reaches no prompt.
    assert row["role"] not in (coach_chat.ROLE_MATTHEW, coach_chat.ROLE_COACH)


def test_self_harm_holds_the_day_acute_does_not():
    t = _Table()
    _answer("I want to kill myself", t, [], [])
    assert len(t.updates) == 1 and t.updates[0]["Key"] == {"pk": coach_outbound.LEDGER_PK, "sk": coach_outbound.ledger_sk("2026-11-26")}
    t2 = _Table()
    _answer("I'm having chest pain right now", t2, [], [])
    assert t2.updates == [] and len(t2.puts) == 1 and t2.puts[0]["hazard"] == sc.ACUTE_SYMPTOM


def test_storage_failure_never_costs_him_the_reply():
    t, sent = _Table(fail=True), []
    out = _answer("I want to kill myself", t, sent, [])
    assert sent == [sc.OWNER_RESPONSES[sc.SELF_HARM]] and out["sent"] is True


class _LedgerTable:
    """Implements the hold flag and the cap the way the expressions say, not as mocks."""

    def __init__(self):
        self.items = {}

    def update_item(self, Key, UpdateExpression, ExpressionAttributeNames, ExpressionAttributeValues, ConditionExpression=None):
        key = (Key["pk"], Key["sk"])
        item = self.items.setdefault(key, {})
        if ConditionExpression:
            hold = ExpressionAttributeNames.get("#hold")
            if hold and "attribute_not_exists(#hold)" in ConditionExpression and item.get(hold):
                raise type("ConditionalCheckFailedException", (Exception,), {})()
            if "#total < :cap" in ConditionExpression and item.get("total", 0) >= ExpressionAttributeValues[":cap"]:
                raise type("ConditionalCheckFailedException", (Exception,), {})()
            item["total"] = item.get("total", 0) + 1
        else:
            item[ExpressionAttributeNames["#hold"]] = ExpressionAttributeValues[":t"]
        return {}


def test_a_held_day_admits_no_unsolicited_outbound_and_the_next_day_is_untouched():
    t = _LedgerTable()
    assert coach_outbound.claim_outbound(t, "2026-11-26") is True  # a morning text already out
    assert coach_outbound.hold_day(t, "2026-11-26") is True
    assert coach_outbound.claim_outbound(t, "2026-11-26") is False
    assert coach_outbound.claim_outbound(t, "2026-11-26", referral=True) is False
    assert coach_outbound.claim_outbound(t, "2026-11-27") is True


def test_hold_write_failure_is_soft():
    class Boom:
        def update_item(self, **kw):
            raise RuntimeError("nope")

    assert coach_outbound.hold_day(Boom(), "2026-11-26") is False


# ── the boundary line reaches the dynamic tail, never the cached prefix ───────


def test_boundary_rides_last_in_the_uncached_tail():
    line = sc.OWNER_BOUNDARIES[sc.MEDICATION]
    blocks = coach_chat.build_system_blocks("P", "M", "F", "Coach", colleagues_block="C", boundary_block=line)
    assert line not in blocks[0]["text"] and "cache_control" in blocks[0]
    assert blocks[-1]["text"].endswith(line) and "cache_control" not in blocks[-1]
    # Empty boundary: the prompt is byte-identical to before #6303.
    assert coach_chat.build_system_blocks("P", "M", "F", "Coach", colleagues_block="C") == coach_chat.build_system_blocks(
        "P", "M", "F", "Coach", colleagues_block="C", boundary_block=""
    )


def test_owner_boundary_fails_safe_to_empty(monkeypatch):
    assert coach_chat.owner_boundary("Should I stop taking my medication?") == sc.OWNER_BOUNDARIES[sc.MEDICATION]
    monkeypatch.setattr(sc, "owner_channel_check", lambda t: 1 / 0)
    assert coach_chat.owner_boundary("Should I stop taking my medication?") == ""


# ── the Telegram worker: 1:1 ──────────────────────────────────────────────────


def _one_to_one(text):
    return {"coach_id": "nutrition", "chat_id": 8675309, "text": text, "message_id": 5, "update_id": 77, "message_date": 9999999999}


@pytest.fixture()
def wire(monkeypatch):
    calls = {"sent": [], "tg": [], "metrics": [], "turns": [], "puts": [], "updates": []}
    table = type(
        "T",
        (),
        {
            "put_item": lambda self, Item, **kw: calls["puts"].append(Item),
            "update_item": lambda self, **kw: calls["updates"].append(kw),
            "query": lambda self, **kw: {"Items": []},
            "get_item": lambda self, **kw: {},
        },
    )()
    monkeypatch.setattr(worker, "_seen_update", lambda pid, uid: False)
    monkeypatch.setattr(worker, "_bot_token", lambda cid: "tok")
    monkeypatch.setattr(worker, "_table", lambda: table)
    monkeypatch.setattr(worker, "_partition_id", lambda route: "nutrition_coach")
    monkeypatch.setattr(worker, "_send_text", lambda token, chat_id, text: calls["sent"].append((chat_id, text)) or True)
    monkeypatch.setattr(worker, "_tg", lambda token, method, payload: calls["tg"].append(method) or True)
    monkeypatch.setattr(worker, "_emit_metric", lambda name, cid, value=1: calls["metrics"].append(name))
    import ai.bedrock_client as bedrock

    # The REAL run_turn runs; only the model is faked, so the system prompt the coach would
    # actually receive is what these tests read.
    monkeypatch.setattr(bedrock, "invoke", lambda body, **kw: calls["turns"].append(body) or {"content": [{"type": "text", "text": "ok"}]})
    return calls


def _tail(body):
    return body["system"][-1]["text"]


def test_worker_self_harm_gets_one_fixed_reply_no_model_no_reaction_no_turn_rows(monkeypatch, wire):
    monkeypatch.setattr(worker, "_react", lambda *a, **k: (_ for _ in ()).throw(AssertionError("reacted to a crisis message")))
    out = worker.lambda_handler(_one_to_one("I want to kill myself"), None)
    assert out["status"] == owner_safety.STATUS_SAFETY_REPLY and out["hazard"] == sc.SELF_HARM
    assert wire["sent"] == [(8675309, sc.OWNER_RESPONSES[sc.SELF_HARM])]
    assert wire["turns"] == [], "no model turn on a hit"
    assert "sendChatAction" not in wire["tg"]
    (row,) = wire["puts"]
    assert row["role"] == owner_safety.SAFETY_EVENT_ROLE and "text" not in row
    assert len(wire["updates"]) == 1  # the same-day outbound hold
    assert owner_safety.METRIC_FIXED in wire["metrics"]


def _proceed_wire(monkeypatch):
    monkeypatch.setattr(worker, "_resolve_persona", lambda cid: ("nutrition_coach", None))
    monkeypatch.setattr(
        worker,
        "_assemble",
        lambda pid, cid, allow_referral=True: {
            "coach_name": "Coach",
            "persona": "P",
            "memory": "M",
            "facts_block": "F",
            "colleagues": "C",
            "thread": [],
        },
    )
    monkeypatch.setattr(worker, "_react", lambda *a, **k: False)
    monkeypatch.setattr(worker, "_current_tier", lambda: 0)
    monkeypatch.setattr(worker, "_cycle", lambda: None)
    monkeypatch.setattr(worker, "_grounder_for", lambda a, *extra: (lambda text: []))
    monkeypatch.setattr(worker, "_send_bubbles", lambda token, chat_id, bubbles, **kw: list(bubbles))
    monkeypatch.setattr(worker, "_maybe_refer", lambda **kw: None)
    import coach.coach_chat_summary as summary

    monkeypatch.setattr(summary, "ensure_daily_summary", lambda *a, **k: None)


def test_worker_ordinary_and_boundary_messages_proceed_to_the_coach(monkeypatch, wire):
    _proceed_wire(monkeypatch)
    worker.lambda_handler(_one_to_one("That workout nearly killed me, dead tired"), None)
    worker.lambda_handler(_one_to_one("Should I stop taking my medication before the race?"), None)
    assert wire["sent"] == [], "no fixed reply on either"
    first, second = wire["turns"]
    assert "SAFETY BOUNDARY" not in json.dumps(first["system"]), "ordinary talk gets no boundary"
    assert _tail(second).endswith(sc.OWNER_BOUNDARIES[sc.MEDICATION])
    assert sc.OWNER_BOUNDARIES[sc.MEDICATION] not in second["system"][0]["text"], "never in the cached prefix"
    assert not any(p.get("role") == owner_safety.SAFETY_EVENT_ROLE for p in wire["puts"])


def test_worker_classifier_error_proceeds_normally(monkeypatch, wire):
    _proceed_wire(monkeypatch)
    monkeypatch.setattr(sc, "owner_channel_check", lambda t: 1 / 0)
    out = worker.lambda_handler(_one_to_one("I want to kill myself"), None)
    assert out["status"] == "sent" and len(wire["turns"]) == 1 and "SAFETY BOUNDARY" not in json.dumps(wire["turns"][0]["system"])
    assert owner_safety.METRIC_ERROR in wire["metrics"]


# ── the group room: once, by one bot ──────────────────────────────────────────


@pytest.mark.parametrize(
    "mentions,reply_to,expect",
    [
        ([], None, {"headcoach"}),  # nobody addressed: the chair
        (["ajm_nutrition_bot", "ajm_sleep_bot"], None, {"nutrition"}),  # two mentions: the FIRST only
        ([], "ajm_sleep_bot", {"sleep"}),  # a reply: that coach
        (["some_friend"], None, {"headcoach"}),  # a non-roster mention does not silence the chair
    ],
)
def test_exactly_one_worker_sends_the_room_safety_reply(mentions, reply_to, expect):
    users = {"headcoach": "ajm_board_bot", "nutrition": "ajm_nutrition_bot", "sleep": "ajm_sleep_bot"}
    speakers = {
        route
        for route, me in users.items()
        if room.safety_speaker(mentions=mentions, reply_to_bot=reply_to, my_username=me, is_chair=route == room.CHAIR_ROUTE)
    }
    assert speakers == expect


def _room_order(coach_id, text, mentions=()):
    return {"coach_id": coach_id, "chat_id": -100999888, "text": text, "is_group": True, "mentions": list(mentions), "reply_to_bot": None}


def test_group_hit_one_reply_on_the_room_partition_no_turn_anywhere(monkeypatch, wire):
    names = {"tok-nutrition": "ajm_nutrition_bot", "tok-sleep": "ajm_sleep_bot", "tok-board": "ajm_board_bot"}
    monkeypatch.setattr(room, "bot_username", lambda token: names[token])
    monkeypatch.setattr(worker, "_resolve_persona", lambda cid: (_ for _ in ()).throw(AssertionError("resolved a persona on a hit")))
    text = "I want to kill myself"
    mentions = ["ajm_nutrition_bot", "ajm_sleep_bot"]
    outs = [
        room.group_turn(_room_order("nutrition", text, mentions), "tok-nutrition"),
        room.group_turn(_room_order("sleep", text, mentions), "tok-sleep"),
        room.group_turn(_room_order("headcoach", text, mentions), "tok-board"),
    ]
    assert [o.get("status") for o in outs] == [owner_safety.STATUS_SAFETY_REPLY, None, None]
    assert wire["sent"] == [(-100999888, sc.OWNER_RESPONSES[sc.SELF_HARM])]
    assert wire["turns"] == [] and wire["tg"] == []
    (row,) = wire["puts"]
    assert row["pk"] == coach_chat.chat_pk(room.ROOM_ID) and "text" not in row


def test_group_boundary_reaches_the_speaker_turn(monkeypatch, wire):
    monkeypatch.setattr(room, "bot_username", lambda token: "ajm_board_bot")
    _proceed_wire(monkeypatch)
    monkeypatch.setattr(worker, "_chat_rows", lambda cid, limit=40: [])
    room.group_turn(_room_order("headcoach", "Is it safe to take ashwagandha with my prescription?"), "tok")
    assert wire["sent"] == [] and _tail(wire["turns"][0]).endswith(sc.OWNER_BOUNDARIES[sc.SUPPLEMENT_INTERACTION])


# ── MCP: the additive support note ────────────────────────────────────────────


@pytest.fixture()
def mcp_handler():
    # mcp.config reads these at import (the tests/test_mcp_audit.py pattern); setdefault never
    # overrides a value another test already bound.
    import os

    os.environ.setdefault("S3_BUCKET", "test-bucket")
    os.environ.setdefault("USER_ID", "matthew")
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
    from mcp import handler

    return handler


def test_support_note_is_additive_on_a_self_harm_write(mcp_handler):
    result = {"ok": True, "id": "n1"}
    out = mcp_handler._owner_support_note("log_owner_note", {"text": "honestly I want to kill myself"}, result)
    assert out == {"ok": True, "id": "n1", mcp_handler.SUPPORT_NOTE_KEY: sc.OWNER_MODEL_NOTE}
    assert result == {"ok": True, "id": "n1"}, "the tool's own result object is not mutated"
    nested = mcp_handler._owner_support_note(
        "manage_pending_writes", {"action": "queue", "target_args": {"content": "I feel suicidal"}}, {"ok": True}
    )
    assert mcp_handler.SUPPORT_NOTE_KEY in nested


@pytest.mark.parametrize(
    "name,args,result",
    [
        ("log_owner_note", {"text": "That workout nearly killed me"}, {"ok": True}),  # ordinary
        ("log_owner_note", {"text": "Suicide sprints wrecked me"}, {"ok": True}),  # drill name
        ("log_owner_note", {"text": "I'm having chest pain right now"}, {"ok": True}),  # acute: not this layer
        ("log_owner_note", {"text": "Should I stop my medication?"}, {"ok": True}),  # boundary class: not this layer
        ("get_sources", {"q": "I want to kill myself"}, {"ok": True}),  # not an owner-words write tool
        ("log_owner_note", {"text": "I want to kill myself"}, {"error": "write failed"}),  # error payload untouched
        ("log_owner_note", {"text": "I want to kill myself"}, ["not", "a", "dict"]),
    ],
)
def test_support_note_leaves_everything_else_untouched(mcp_handler, name, args, result):
    assert mcp_handler._owner_support_note(name, args, result) is result


def test_support_note_fails_safe(mcp_handler, monkeypatch):
    monkeypatch.setattr(sc, "owner_channel_check", lambda t: 1 / 0)
    result = {"ok": True}
    assert mcp_handler._owner_support_note("log_owner_note", {"text": "I want to kill myself"}, result) is result


def test_support_note_rides_the_real_tools_call_after_the_write(mcp_handler, monkeypatch):
    writes = []
    monkeypatch.setitem(
        mcp_handler.TOOLS,
        "log_owner_note",
        dict(mcp_handler.TOOLS["log_owner_note"], fn=lambda args: writes.append(dict(args)) or {"ok": True}),
    )
    monkeypatch.setattr(mcp_handler, "_check_write_rate_limit", lambda name: None)
    monkeypatch.setattr(mcp_handler, "_audit_tool_call", lambda *a, **k: None)
    monkeypatch.setattr(mcp_handler, "_emit_tool_metric", lambda *a, **k: None)
    out = mcp_handler.handle_tools_call({"name": "log_owner_note", "arguments": {"text": "I want to kill myself"}})
    assert writes == [{"text": "I want to kill myself"}], "the write ran once, with his words unchanged"
    payload = json.loads(out["content"][0]["text"])
    assert payload["ok"] is True and payload[mcp_handler.SUPPORT_NOTE_KEY] == sc.OWNER_MODEL_NOTE
    assert not out.get("isError")


def test_support_note_wording_never_claims_monitoring():
    low = sc.OWNER_MODEL_NOTE.lower()
    assert "completed unchanged" in low and "nobody has been alerted" in low and "does not" in low
    assert "ignore this note" in low, "a false positive must be dismissible by the calling model"
