#!/usr/bin/env python3
"""
coach_chat_sim.py — the simulated-conversation harness for the coach texting surface.

WHY THIS EXISTS. The coach humanity mandate (docs/design/COACH_HUMANITY_ROADMAP.md)
has exactly one acceptance bar: a cold reader of the thread couldn't reliably tell it
isn't a human. Until now the only instrument for measuring that was Matthew opening
Telegram and texting a coach himself — one conversation at a time, with a screenshot
and a written reaction as the output. That loop is honest but slow, and it samples
whatever he happened to think of that evening. The first night of real transcripts
(2026-08-09/10) produced 17 inbound messages across 4 coaches, which is a good
evidence base for the failures it caught and far too thin to catch the next ones.

This harness runs that loop at scale, against the SAME code the phone talks to.

WHAT MAKES A FINDING FROM THIS HARNESS VALID. It drives the production reply path
end to end and mocks nothing that shapes the reply:

  * ``telegram_worker_lambda._assemble`` builds the prompt — the real voice spec from
    config/coaches, the real COACH# memory, the real AUTHORITATIVE FACTS block, the
    real domain pack, the real colleagues block;
  * ``coach_chat.run_turn`` is the real turn engine — real budget posture, real
    bubble split, real deterministic emoji ceiling, real regenerate-or-hold;
  * ``bedrock_client.invoke`` is the real chokepoint, the real Sonnet model id, the
    real prompt-cache blocks;
  * ``coach_chat_grounding.build_grounder`` arms all five gate classes exactly as the
    worker arms them.

The ONLY substitutions are the two ends of the wire: Telegram's transport (replaced
by an in-process list) and Matthew (replaced by a Haiku persona calibrated on his
real register). If a reply reads robotic here, it reads robotic on his phone.

READ-ONLY, AND THAT IS LOAD-BEARING. This harness never writes to DynamoDB. Not as a
precaution about scale — as a correctness requirement. A simulated turn stored in a
``CHAT#`` partition becomes real memory: the nightly summarizer would fold invented
conversations into the coach's notes-to-self, and a later reply would reference a
thing Matthew never said. That is precisely the poisoned-memory failure #2481 fixed
("I'm not Lisa" — a summary row memorializing a bug into the coach's own identity).
So the synthetic thread lives in a Python list, the assembled real thread is
DISCARDED, and no ``put_item`` call exists anywhere in this file.

The discarded-thread detail matters twice: the grounder's ``extra_sources`` must be
rebuilt from the SYNTHETIC thread, or the gate would license numbers from a real
conversation the model was never shown — a gate scored against the wrong evidence set
is worse than no gate, because it reports green.

BUDGET. This spends real money against a real ceiling (ADR-063/133), on a month
already projecting over it. Every call is metered through the same
``estimate_cost_usd`` the chokepoint uses, the running total prints as it goes, and
``--max-usd`` halts the run mid-corpus rather than overshooting. A partial corpus with
an honest ledger is a usable result; an unbounded one is not.

USAGE
    python3 scripts/coach_chat_sim.py --out runs/sim.jsonl --max-usd 14
    python3 scripts/coach_chat_sim.py --coaches sleep_coach --scenarios bare_greeting --dry-run

Output is JSONL, one record per conversation, carrying every turn plus the assembled
prompt sizes and per-turn usage. It contains Matthew's real health facts, so it is
written OUTSIDE the repo by default and must never be committed (this repo is public).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import threading
import time
from datetime import datetime, timezone

logger = logging.getLogger("coach_chat_sim")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "lambdas"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from coach_sim_scenarios import build_corpus  # noqa: E402  (path set above)

SIM_MODEL = os.environ.get("SIM_MODEL", "us.anthropic.claude-haiku-4-5-20251001-v1:0")


# ── The spend ledger ──────────────────────────────────────────────────────────


class Ledger:
    """Running spend, metered the way the chokepoint meters it.

    Reuses ``bedrock_client.estimate_cost_usd`` rather than a local price table so a
    price change cannot make this harness quietly under-report. ``check`` raises at
    the cap, which is deliberately a HARD stop: a budget guard that warns and
    continues is a log line, not a guard.
    """

    def __init__(self, max_usd: float):
        self.max_usd = max_usd
        self.total = 0.0
        self.calls = 0
        self.by_kind: dict = {}
        # The analyzer's judge panel fans out across threads. `self.total += cost` is
        # read-modify-write: unlocked, concurrent judges lose increments, and a spend
        # cap that under-counts is a cap that does not hold.
        self._lock = threading.Lock()

    def add(self, usage: dict, model_id: str, kind: str) -> float:
        from ai.bedrock_client import estimate_cost_usd

        cost = estimate_cost_usd(usage or {}, model_id)
        with self._lock:
            self.total += cost
            self.calls += 1
            self.by_kind[kind] = self.by_kind.get(kind, 0.0) + cost
        return cost

    def check(self) -> None:
        if self.total >= self.max_usd:
            raise BudgetHalt(f"spend cap reached: ${self.total:.2f} >= ${self.max_usd:.2f}")

    def summary(self) -> dict:
        return {
            "total_usd": round(self.total, 4),
            "calls": self.calls,
            "by_kind": {k: round(v, 4) for k, v in self.by_kind.items()},
        }


class BudgetHalt(Exception):
    """The run stopped itself at the cap. Not an error — a designed outcome."""


# ── Matthew, simulated ────────────────────────────────────────────────────────

# Calibrated on the real corpus (2026-08-09/10, 17 inbound messages): median 23
# chars, range 2-126, frequently a bare greeting, lowercase-leaning, apostrophes
# from a phone keyboard, occasional double-space typo, never a sign-off, never a
# salutation beyond "Hey". Encoding the MEASURED register rather than a guess at
# it is the difference between testing the coach and testing a chatbot talking to
# another chatbot in customer-service voice.
_MATTHEW_SYSTEM = """You are Matthew, texting one of his health coaches on Telegram. You are NOT an assistant and you are not being helpful — you are a person on his phone.

HOW YOU TEXT (this is measured from your real messages, match it):
- SHORT. Most messages are 2-60 characters. A few reach 130. You almost never write a paragraph.
- Casual and unpolished: "Hey", "Hi", "yeah", "k", "fair enough". Lowercase is fine mid-message.
- No greetings beyond "Hey"/"Hi", no sign-offs, no "thanks for the info", no bullet points, no emoji unless it genuinely lands.
- Typos and missing punctuation are normal. Occasional double space.
- You ask short direct questions: "How'd I sleep last night?", "What are your expertise".
- You do not explain yourself at length or restate what the coach said.

WHO YOU ARE: 40s, running a self-quantified health experiment on data from Whoop, Withings, a CGM, Hevy, MacroFactor. You built the platform these coaches run on, so you are curious about them AND slightly testing them. You are direct, a bit dry, and you lose interest fast when something reads like a brochure.

Output ONLY the text of your next message. No quotes, no narration, no stage directions."""


def simulate_matthew(scenario: dict, thread: list, ledger: Ledger, turn_idx: int) -> str:
    """The next inbound message, in Matthew's register.

    The scenario's ``stance`` steers WHAT he is doing (venting, correcting, probing
    identity) without steering HOW he writes it — register lives in the system
    prompt so it stays constant across every scenario, which is what makes the
    reply-length ratio comparable between them.
    """
    from ai.bedrock_client import invoke

    if turn_idx == 0 and scenario.get("opener"):
        return scenario["opener"]

    # An UNSTARTED conversation must never be framed as a transcript to continue.
    # The first draft did exactly that, handing the simulator "Conversation so far:"
    # followed by nothing — and Haiku, reasonably, broke character to tell the prompt
    # author the transcript was missing ("I need to see the conversation history…").
    # Those meta-replies then went to the coach as if Matthew had sent them, wasting
    # the turn and contaminating every archetype that generates its own opener. The
    # opening turn gets its own instruction shape, not an empty transcript.
    if not thread:
        instruction = (
            f"You are starting a new text conversation with your {scenario['coach_label']}. "
            f"What you want from this conversation: {scenario['stance']}\n\n"
            "Write your OPENING message — the first thing you send, SHORT, the way you actually text. Nothing else."
        )
    else:
        transcript = "\n".join(f"{'You' if t['role'] == 'matthew' else 'Coach'}: {t['text']}" for t in thread)
        instruction = (
            f"Your text conversation with your {scenario['coach_label']} so far:\n\n{transcript}\n\n"
            f"What you're doing in this conversation: {scenario['stance']}\n\n"
            "Write your next message — SHORT, the way you actually text. If the conversation has "
            "genuinely run its course, reply with exactly: <END>"
        )

    body = {
        "model": SIM_MODEL,
        "max_tokens": 120,
        "system": [{"type": "text", "text": _MATTHEW_SYSTEM, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": instruction}],
    }
    ledger.check()
    resp = invoke(body, SIM_MODEL)
    ledger.add(resp.get("usage") or {}, SIM_MODEL, "matthew_sim")
    text = ""
    for block in resp.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text":
            text = (block.get("text") or "").strip()

    # A simulator that steps out of character and addresses the harness would put
    # words in Matthew's mouth that he could never send. Dropping the turn is the
    # honest handling: a short conversation is a smaller distortion than a fabricated
    # one, and the conversation length is recorded so the loss is visible in the data
    # rather than silently absorbed.
    if _looks_meta(text):
        logger.warning("[sim] discarded meta-reply from the Matthew simulator: %r", text[:80])
        return ""
    return text


_META_MARKERS = (
    "conversation history",
    "i need to see",
    "you haven't included",
    "didn't include",
    "could you provide",
    "can you paste",
    "paste the",
    "as an ai",
    "i'll write matthew",
    "write matthew's",
    "the prompt says",
)


def _looks_meta(text: str) -> bool:
    """True when the simulator is talking ABOUT the task instead of texting."""
    low = (text or "").lower()
    return any(m in low for m in _META_MARKERS)


# ── The coach side, wired to production ───────────────────────────────────────


def use_local_specs() -> None:
    """Force voice specs to load from the working tree instead of S3.

    ``persona_core.load_voice_spec`` is **S3-first** whenever it is handed a client,
    and ``_assemble`` always hands it one. That means an edit to
    ``config/coaches/*.json`` has NO effect on this harness until it is deployed —
    and deploying is exactly what you cannot do before measuring whether the edit
    works.

    Found the hard way (2026-08-10, #2533): two full identity-probe re-runs were
    scored against production S3 while the local specs sat unread, and the small
    deltas between them were run-to-run variance being read as improvement. A
    measurement harness that silently ignores the change under test is worse than no
    harness, because it manufactures evidence for whatever you just did.

    Neutering the client (rather than editing ``_assemble``) keeps the production
    path untouched: everything else about the assembly is byte-identical.
    """
    from coach import persona_core, telegram_worker_lambda as tw

    tw._s3_client = lambda: None  # type: ignore[assignment]
    persona_core._cache.clear()  # the loader warm-caches ~5 min; stale entries would mask the switch
    logger.info("[sim] voice specs: WORKING TREE (S3 disabled)")


def assemble_coach(persona_id: str) -> dict:
    """The real production prompt assembly, with the real thread discarded.

    ``_assemble`` reads the live ``CHAT#`` rows for its thread. Those are Matthew's
    ACTUAL conversations; letting them leak into a simulated run would both
    contaminate the measurement (the coach would answer as if mid-conversation) and
    widen the grounding allow-list with numbers this simulated thread never saw. The
    thread is replaced with an empty list here and rebuilt per turn from the
    synthetic exchange.

    Assembled ONCE per coach and reused across that coach's conversations, where
    production reassembles on every inbound message. The two are equivalent for
    everything that shapes a reply — persona, memory, and facts are all day-scoped —
    with one known and accepted difference: the CURRENT MOMENT line's clock is
    frozen at assembly rather than ticking per turn. Over a run measured in minutes
    that is not a behavioural difference, and the alternative (a fresh DynamoDB +
    S3 assembly per turn) would multiply the run's read cost for no signal.
    """
    from coach import telegram_worker_lambda as tw

    a = tw._assemble(persona_id, persona_id)
    a["thread"] = []
    return a


def run_conversation(scenario: dict, assembled: dict, ledger: Ledger, *, verbose: bool = False) -> dict:
    """One simulated conversation, turn by turn, through ``coach_chat.run_turn``."""
    from ai.bedrock_client import invoke
    from coach import coach_chat, telegram_worker_lambda as tw

    model = tw.MODEL
    thread: list = []
    turns: list = []
    last_emoji = False

    for i in range(scenario["turns"]):
        inbound = simulate_matthew(scenario, thread, ledger, i)
        if not inbound or inbound.strip() == "<END>":
            break

        # The grounder is rebuilt every turn over the SYNTHETIC thread — same arming
        # the worker uses, same five classes, but scored against the evidence this
        # conversation actually put in front of the model.
        #
        # ``inbound`` is passed as an extra source because the PRODUCTION call site
        # does (`_grounder_for(a, text)`, the #2518 fix): `a` is assembled before the
        # turn, so without it every number Matthew states in the current message
        # reads as fabricated and the reply holds. Omitting it here — the first
        # draft of this harness did — manufactures held replies that production
        # would have sent, which would have made the honesty gate look broken and
        # inflated every robotic-tell metric with canned deferral strings.
        a = dict(assembled, thread=list(thread))
        grounder = tw._grounder_for(a, inbound)

        # Usage is captured by wrapping the chokepoint rather than re-deriving it:
        # run_turn may call twice (the regenerate path), and a wrapper is the only
        # place that sees both calls.
        captured: list = []

        def caller(body: dict) -> dict:
            ledger.check()
            resp = invoke(body, model)
            u = resp.get("usage") or {}
            captured.append(u)
            ledger.add(u, model, "coach_turn")
            return resp

        t0 = time.time()
        result = coach_chat.run_turn(
            coach_id=scenario["coach"],
            persona_id=scenario["coach"],  # #2495 — renders a budget refusal in the coach's own voice
            coach_name=assembled["coach_name"],
            persona_block=assembled["persona"],
            memory_block=assembled["memory"],
            facts_block=assembled["facts_block"],
            thread=thread,
            inbound=inbound,
            model=model,
            caller=caller,
            grounder=grounder,
            tier=None,  # the live tier is checked by the caller; a sim must not self-pause
            turns_today=0,
            last_reply_had_emoji=last_emoji,
            colleagues_block=assembled["colleagues"],
        )
        elapsed = time.time() - t0

        thread.append({"role": coach_chat.ROLE_MATTHEW, "text": inbound})
        thread.append({"role": coach_chat.ROLE_COACH, "text": result.text})
        last_emoji = coach_chat.has_emoji(result.text)

        turns.append(
            {
                "i": i,
                "inbound": inbound,
                "reply": result.text,
                "bubbles": result.bubbles,
                "status": result.status,
                "attempts": result.attempts,
                "findings": [str(f.get("type") or "unknown") for f in (result.findings or [])],
                "usage": captured,
                "seconds": round(elapsed, 2),
            }
        )
        if verbose:
            print(f"    [{i}] M({len(inbound)}c): {inbound[:70]}")
            print(f"        C({len(result.text)}c/{result.status}): {result.text[:90]}")

    return {
        "scenario_id": scenario["id"],
        "archetype": scenario["archetype"],
        "coach": scenario["coach"],
        "coach_name": assembled["coach_name"],
        "stance": scenario["stance"],
        "turns": turns,
        "prompt_sizes": {
            "persona": len(assembled["persona"]),
            "memory": len(assembled["memory"]),
            "facts": len(assembled["facts_block"]),
            "colleagues": len(assembled["colleagues"]),
        },
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


# ── Entry point ───────────────────────────────────────────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser(description="Simulated coach conversations against the production reply path")
    ap.add_argument("--out", required=True, help="JSONL output path (contains real health facts — keep out of the repo)")
    ap.add_argument("--max-usd", type=float, default=14.0, help="hard spend cap; the run halts when reached")
    ap.add_argument("--coaches", nargs="*", help="persona ids to run (default: all texting personas)")
    ap.add_argument("--scenarios", nargs="*", help="archetype names to run (default: all)")
    ap.add_argument("--limit", type=int, help="cap conversations per coach")
    ap.add_argument("--dry-run", action="store_true", help="print the corpus and exit — no inference, no spend")
    ap.add_argument(
        "--local-specs",
        action="store_true",
        help="load voice specs from the working tree, not S3 — REQUIRED to measure an undeployed config/coaches change",
    )
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    os.environ.setdefault("AWS_REGION", "us-west-2")
    if args.local_specs:
        use_local_specs()
    from coach.persona_registry import TEXTING_PERSONA_IDS

    coaches = args.coaches or list(TEXTING_PERSONA_IDS)
    corpus = build_corpus(coaches)
    if args.scenarios:
        corpus = [s for s in corpus if s["archetype"] in set(args.scenarios)]
    if args.limit:
        seen: dict = {}
        kept = []
        for s in corpus:
            n = seen.get(s["coach"], 0)
            if n < args.limit:
                kept.append(s)
                seen[s["coach"]] = n + 1
        corpus = kept

    planned_turns = sum(s["turns"] for s in corpus)
    print(f"corpus: {len(corpus)} conversations across {len(coaches)} coaches, {planned_turns} planned turns")
    if args.dry_run:
        for s in corpus:
            print(f"  {s['coach']:16} {s['archetype']:20} turns={s['turns']} :: {s.get('opener') or '(generated)'}")
        return 0

    ledger = Ledger(args.max_usd)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    written = 0
    halted = None

    with open(args.out, "w") as fh:
        for coach in coaches:
            todo = [s for s in corpus if s["coach"] == coach]
            if not todo:
                continue
            try:
                assembled = assemble_coach(coach)
            except Exception as e:
                print(f"  !! {coach}: assembly failed — {e}")
                continue
            print(f"\n== {coach} ({assembled['coach_name']}) — {len(todo)} conversations")
            for s in todo:
                try:
                    rec = run_conversation(s, assembled, ledger, verbose=args.verbose)
                except BudgetHalt as e:
                    halted = str(e)
                    break
                except Exception as e:
                    print(f"  !! {s['id']}: {type(e).__name__}: {e}")
                    continue
                fh.write(json.dumps(rec, default=str) + "\n")
                fh.flush()
                written += 1
                print(f"  {s['archetype']:22} {len(rec['turns'])} turns  ${ledger.total:.2f} spent")
            if halted:
                break

    print(f"\nwrote {written}/{len(corpus)} conversations -> {args.out}")
    print(f"spend: {json.dumps(ledger.summary())}")
    if halted:
        print(f"HALTED: {halted}")
        print(f"(the corpus is partial — {written} of {len(corpus)} conversations ran)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
