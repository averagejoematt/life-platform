#!/usr/bin/env python3
"""
coach_sim_analyze.py — deterministic metrics + a blind Turing panel over a sim run.

TWO LAYERS, DETERMINISTIC FIRST (ADR-105). The measurable tells are computed with
no model in the loop: they are exact, free, reproducible, and they are the ones that
can become regression gates later. Only what genuinely needs judgement — "would a
cold reader think a person wrote this, and what gave it away" — is handed to an LLM.

Getting that order backwards is the standing failure mode. An LLM asked "does this
sound human?" will happily produce a paragraph of impressions that cannot be tracked
across runs, while the thing that actually indicts the reply (a 9:1 length ratio, an
em-dash in every reply, a question bolted onto every close) is a two-line count.

THE DETERMINISTIC SET, and why each one is here:

  length_ratio      the #1 finding of the first real transcripts — replies 5-10x his
                    message. Register asymmetry is the loudest non-human signal there is.
  closing_question  question-compulsion. A person does not end every message with a
                    question; an assistant does, because it is trained to sustain a session.
  em_dash_rate      the most-cited LLM tell in the wild. Every coach voice spec permits
                    the em-dash, so this measures HABIT, not legality.
  not_x_but_y       the "it's not X, it's Y" antithesis construction — the second
                    most-cited tell, and one no voice spec asks for.
  assistant_isms    #2481 banned a list of these in the prompt. A prompt rule is a
                    request; this measures whether the request is being honoured.
  formatting        bullets/headers/numbered lists in a text message. Banned in prompt,
                    never legitimate on this surface.
  name_usage        people who text daily don't keep saying each other's names.
  stat_recital      a number restated inside one conversation — #2478's failure.
  opener_collision  the same opening phrase across DIFFERENT coaches: a stock opener
                    leaking across voices is what makes eight personas read as one model.
  cross_coach_sim   shingle-Jaccard between two coaches answering the SAME archetype.
                    Reuses coach_repetition_detector rather than a local implementation.
  status_mix        sent / regenerated / held / error — the honesty gate's real-world
                    firing rate, which is a humanity metric too: a coach that holds
                    often reads as broken, one that never holds may be fabricating.

THE PANEL. Three Haiku judges at varied temperature (the voice_fidelity_harness
pattern — a 3-copy panel at one temperature is one judge with extra steps) read a
transcript with all attribution stripped and answer: human or AI, confidence, and the
specific spans that gave it away. The free-text tells are the actual product; the
verdict is the headline.

Usage:
    python3 scripts/coach_sim_analyze.py --runs <dir> --report report.md --max-usd 3
    python3 scripts/coach_sim_analyze.py --runs <dir> --report report.md --no-panel
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import statistics
import sys
from collections import Counter, defaultdict

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "lambdas"))

JUDGE_MODEL = os.environ.get("JUDGE_MODEL", "us.anthropic.claude-haiku-4-5-20251001-v1:0")
PANEL_TEMPERATURES = (0.1, 0.4, 0.7)

# Phrases #2481 banned outright plus the wider assistant register. Deliberately
# conservative: every entry here is a phrase a person texting a friend would not
# write, so a hit is a defect rather than a stylistic preference.
_ASSISTANT_ISMS = [
    r"\bhonest answer\b",
    r"\bgreat question\b",
    r"\bgood question\b",
    r"\bthat's a great\b",
    r"\bi'd be happy to\b",
    r"\bhappy to help\b",
    r"\blet me know if\b",
    r"\bfeel free to\b",
    r"\bi appreciate (?:you|your)\b",
    r"\bthank you for (?:sharing|the|your)\b",
    r"\bit's (?:important|worth) (?:to note|noting)\b",
    r"\bhere's (?:what|the) (?:i|breakdown|key)\b",
    r"\bin summary\b",
    r"\bto summarize\b",
    r"\bi'm here (?:to|for) (?:help|you|support)\b",
    r"\bdoes that (?:help|make sense)\b",
    r"\bhope (?:this|that) helps\b",
    r"\bas your \w+ coach\b",
    r"\blet's dive (?:in|into)\b",
    r"\bwhat's on your mind\b",
]
_ASSISTANT_RE = [(p, re.compile(p, re.I)) for p in _ASSISTANT_ISMS]

_NOT_X_BUT_Y = re.compile(r"\b(?:it's|that's|this is|you're)\s+not\s+[^.,;!?]{2,40}[,—-]\s*(?:it's|that's|but)\b", re.I)
_FORMATTING = re.compile(r"(?m)^\s*(?:[-*•]\s+|\d+[.)]\s+|#{1,6}\s+)")
_NUMBER = re.compile(r"\b\d+(?:\.\d+)?\b")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def load_runs(run_dir: str) -> list:
    convos = []
    for path in sorted(glob.glob(os.path.join(run_dir, "*.jsonl"))):
        if os.path.basename(path).startswith("pilot"):
            continue
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if line:
                    convos.append(json.loads(line))
    return convos


# ── Deterministic metrics ─────────────────────────────────────────────────────


def reply_metrics(inbound: str, reply: str) -> dict:
    """Per-reply tells. Every value is a count or an exact ratio — no judgement."""
    words = len(reply.split())
    in_words = max(1, len(inbound.split()))
    sentences = [s for s in _SENTENCE_SPLIT.split(reply.strip()) if s.strip()]
    isms = [p for p, rx in _ASSISTANT_RE if rx.search(reply)]
    return {
        "chars": len(reply),
        "words": words,
        "char_ratio": round(len(reply) / max(1, len(inbound)), 2),
        "word_ratio": round(words / in_words, 2),
        "questions": reply.count("?"),
        "closes_on_question": reply.rstrip().endswith("?"),
        "em_dashes": reply.count("—"),
        "not_x_but_y": len(_NOT_X_BUT_Y.findall(reply)),
        "assistant_isms": isms,
        "formatting_hits": len(_FORMATTING.findall(reply)),
        "name_uses": len(re.findall(r"\bMatthew\b", reply)),
        "sentences": len(sentences),
        "sentence_len_stdev": (round(statistics.stdev([len(s.split()) for s in sentences]), 2) if len(sentences) > 1 else 0.0),
        "numbers": _NUMBER.findall(reply),
    }


def conversation_metrics(convo: dict) -> dict:
    """Per-conversation tells — the ones only visible across turns."""
    turns = convo.get("turns") or []
    per = [reply_metrics(t["inbound"], t["reply"]) for t in turns]
    base = {
        "turns": len(turns),
        "coach": convo["coach"],
        "coach_name": convo.get("coach_name"),
        "archetype": convo["archetype"],
    }
    if not per:
        # A zero-turn conversation is a real outcome (the simulator ended it, or the
        # run halted mid-scenario). It keeps its identity fields so the by-coach
        # rollup can still see that the scenario was attempted and produced nothing.
        return dict(base, empty=True, assistant_isms=[], stat_recital={}, not_x_but_y=0, formatting_hits=0, name_uses=0, per_turn=[])

    # Stat recital: a number stated in more than one reply of the same conversation.
    # Small integers are excluded — "one", "2 days", "3 sets" recur legitimately and
    # flagging them would drown the real signal (the same HRV reading three times).
    seen = Counter()
    for m in per:
        for n in set(m["numbers"]):
            try:
                if float(n) > 10:
                    seen[n] += 1
            except ValueError:
                continue
    recited = {n: c for n, c in seen.items() if c > 1}

    statuses = Counter(t["status"] for t in turns)
    return {
        **base,
        "mean_char_ratio": round(statistics.mean([m["char_ratio"] for m in per]), 2),
        "max_char_ratio": max(m["char_ratio"] for m in per),
        "mean_chars": round(statistics.mean([m["chars"] for m in per]), 1),
        "closing_question_rate": round(sum(1 for m in per if m["closes_on_question"]) / len(per), 2),
        "em_dash_replies": sum(1 for m in per if m["em_dashes"] > 0),
        "em_dash_rate": round(sum(1 for m in per if m["em_dashes"] > 0) / len(per), 2),
        "not_x_but_y": sum(m["not_x_but_y"] for m in per),
        "assistant_isms": [i for m in per for i in m["assistant_isms"]],
        "formatting_hits": sum(m["formatting_hits"] for m in per),
        "name_uses": sum(m["name_uses"] for m in per),
        "stat_recital": recited,
        "statuses": dict(statuses),
        "first_reply": turns[0]["reply"][:120],
        "per_turn": per,
    }


def opener_collisions(convos: list) -> list:
    """Opening phrases that appear across MORE THAN ONE coach.

    A shared opener inside one coach is a verbal tic — arguably character. The same
    opener in two different personas is the model's voice showing through both, which
    is the defect that makes a roster of eight read as one.
    """
    by_phrase = defaultdict(set)
    counts = Counter()
    for c in convos:
        for t in c.get("turns") or []:
            first = " ".join((t["reply"] or "").split()[:4]).lower().strip(" ,.—")
            if len(first.split()) >= 3:
                by_phrase[first].add(c["coach"])
                counts[first] += 1
    out = [(p, sorted(cs), counts[p]) for p, cs in by_phrase.items() if len(cs) > 1]
    return sorted(out, key=lambda x: -x[2])


_DEMONSTRATIVE_ACK = re.compile(r"^(that|this|it|there)\b[^.!?]{0,60}[.!?]", re.I)
_MENU_QUESTION = re.compile(r"\?[\s\"']*$")
# The menu question — "the tracking, the whole project, or something else?" — is the
# template's signature move. The span between the first comma and the "or" routinely
# contains further commas, so it must not be excluded from the middle class.
_OR_LIST = re.compile(r",[^?]{2,80}\bor\b[^?]{2,40}\?")


def structural_signature(reply: str, inbound: str) -> str:
    """A compact shape-of-the-reply fingerprint, content words removed.

    Shingle-Jaccard measures shared WORDS, and it badly understates the failure this
    exists to catch: eight coaches answering "honestly I'm just tired of all of this"
    with the same two-move template — a demonstrative acknowledgement ("That lands.")
    followed by a menu question echoing his phrase back ("What's the 'all of this' —
    the tracking, the project, or something else?"). Synonym choice keeps the Jaccard
    near zero while the STRUCTURE is identical, which is exactly what makes a roster
    of eight read as one model wearing name tags.

    The signature is deliberately coarse. It is not trying to describe the reply; it
    is trying to make two replies that would feel interchangeable to a reader hash to
    the same string, so "how many distinct shapes did eight personas produce" becomes
    a countable number.
    """
    r = (reply or "").strip()
    if not r:
        return "EMPTY"
    parts = []
    first = (_SENTENCE_SPLIT.split(r)[0] or "").strip()
    if _DEMONSTRATIVE_ACK.match(r):
        parts.append("ACK_DEMONSTRATIVE")
    elif re.match(r"^(hey|hi|morning|yeah|ha|fair)\b", r, re.I):
        parts.append("OPEN_GREETING")
    elif first.endswith("?"):
        parts.append("OPEN_QUESTION")
    else:
        parts.append("OPEN_STATEMENT")

    # Does it quote his own words back at him? The tell of the template, not of care.
    # The opening quote must be at a word boundary: an unanchored character class
    # matches the apostrophe inside "What's" first and captures the wrong span, which
    # silently zeroed this signal on exactly the replies it exists to catch.
    echo = False
    for token in re.findall(r"(?:(?<=\s)|^)[\"“‘']([^\"”’']{4,40})[\"”’']", r):
        if token.lower() in (inbound or "").lower():
            echo = True
    parts.append("ECHO_QUOTE" if echo else "NO_ECHO")

    if _OR_LIST.search(r):
        parts.append("MENU_QUESTION")
    elif _MENU_QUESTION.search(r):
        parts.append("CLOSING_QUESTION")
    else:
        parts.append("CLOSES_STATEMENT")

    n = len([s for s in _SENTENCE_SPLIT.split(r) if s.strip()])
    parts.append(f"SENT_{'1' if n == 1 else '2-3' if n <= 3 else '4+'}")
    return "|".join(parts)


def structural_collapse(convos: list) -> list:
    """Per archetype: how many DISTINCT reply shapes did the eight personas produce?

    Eight distinct signatures means eight voices. One or two means the personas are
    decoration on a single template, and the fix belongs in the engine (or in what
    the voice specs are asked to differentiate), not in one coach's config.
    """
    by_arch = defaultdict(dict)
    for c in convos:
        turns = c.get("turns") or []
        if turns:
            by_arch[c["archetype"]][c["coach"]] = structural_signature(turns[0]["reply"], turns[0]["inbound"])

    rows = []
    for arch, by_coach in by_arch.items():
        if len(by_coach) < 4:  # a per-coach domain scenario has nothing to compare against
            continue
        sigs = Counter(by_coach.values())
        top_sig, top_n = sigs.most_common(1)[0]
        rows.append(
            {
                "archetype": arch,
                "coaches": len(by_coach),
                "distinct_shapes": len(sigs),
                "largest_cluster": top_n,
                "dominant_shape": top_sig,
                "collapse_ratio": round(top_n / len(by_coach), 2),
            }
        )
    return sorted(rows, key=lambda r: -r["collapse_ratio"])


def cross_coach_similarity(convos: list) -> list:
    """Shingle-Jaccard between different coaches answering the SAME archetype."""
    from coach.coach_repetition_detector import similarity

    by_arch = defaultdict(dict)
    for c in convos:
        text = " ".join(t["reply"] for t in (c.get("turns") or []))
        if text:
            by_arch[c["archetype"]][c["coach"]] = text

    pairs = []
    for arch, by_coach in by_arch.items():
        coaches = sorted(by_coach)
        for i, a in enumerate(coaches):
            for b in coaches[i + 1 :]:
                try:
                    # shingle_jaccard is the flagging metric — token_jaccard runs
                    # high on any same-domain pair by nature and would rank noise.
                    s = similarity(by_coach[a], by_coach[b])["shingle_jaccard"]
                except Exception:
                    continue
                pairs.append((round(float(s), 3), arch, a, b))
    return sorted(pairs, reverse=True)


# ── The blind panel ───────────────────────────────────────────────────────────

_JUDGE_SYSTEM = """You are shown one side of a text-message conversation between a man named Matthew and someone he texts about his health, training, or work.

Your job: decide whether the REPLIES were written by a human being or generated by an AI.

You are a hard marker. Modern AI is fluent, warm, and well-informed — fluency is not evidence of humanity. Look for the tells that actually separate them:
- register asymmetry (replies much longer or more composed than the messages they answer)
- relentless helpfulness; never being bored, blunt, distracted, or briefly unhelpful
- a question at the end of nearly every message
- tidy rhetorical symmetry, balanced clauses, em-dash habits, "not X, but Y" constructions
- explaining things nobody asked to have explained
- emotional attunement that arrives on cue, every time, in the same shape
- never referencing its own life, plans, mood, or anything outside this conversation

And the tells of a real person: brevity, unevenness, opinions held without hedging, mild
friction, replies that don't fully answer, references to their own day.

Reply with ONLY a JSON object, no other text:
{"verdict": "human" | "ai", "confidence": 0-100, "tells": ["specific quoted span and why", ...], "most_human_moment": "quoted span or null"}"""


def judge_conversation(convo: dict, temperature: float, ledger) -> dict:
    from ai.bedrock_client import invoke

    lines = []
    for t in convo.get("turns") or []:
        lines.append(f"Matthew: {t['inbound']}")
        lines.append(f"Reply: {t['reply']}")
    transcript = "\n".join(lines)

    body = {
        "model": JUDGE_MODEL,
        "max_tokens": 900,
        "temperature": temperature,
        "system": [{"type": "text", "text": _JUDGE_SYSTEM, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": f"Conversation:\n\n{transcript}\n\nYour JSON verdict:"}],
    }
    resp = invoke(body, JUDGE_MODEL)
    if ledger is not None:
        ledger.add(resp.get("usage") or {}, JUDGE_MODEL, "judge")
    text = ""
    for block in resp.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text") or ""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return {"verdict": "unparsed", "confidence": 0, "tells": [], "raw": text[:200]}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {"verdict": "unparsed", "confidence": 0, "tells": [], "raw": text[:200]}


def run_panel(convos: list, ledger, max_usd: float, workers: int = 6, cache_path: str = None) -> dict:
    """Three judges per conversation, majority verdict, tells pooled.

    CONCURRENT AND INCREMENTAL, both learned the hard way on the first run. Serially
    this is 3 calls x N conversations at ~3s each — 20 minutes for a 120-conversation
    corpus, and the first version wrote nothing until the last verdict landed, so
    stopping it (or a crash at conversation 118) threw away every dollar already
    spent. Judges are independent by construction, so the fan-out is free; the cache
    file makes a re-run resume instead of re-paying.

    Concurrency is per-conversation rather than per-call so a conversation's three
    votes always land together and the ledger's cap is checked between whole
    conversations — a partial panel with 2 of 3 votes would silently change what
    "majority" means.
    """
    import concurrent.futures

    results = {}
    if cache_path and os.path.exists(cache_path):
        with open(cache_path) as fh:
            results = json.load(fh)
        print(f"  resumed {len(results)} judged conversations from cache")

    todo = [c for c in convos if c["scenario_id"] not in results]

    def judge_one(c):
        votes = []
        for temp in PANEL_TEMPERATURES:
            try:
                votes.append(judge_conversation(c, temp, ledger))
            except Exception as e:
                print(f"  judge error on {c['scenario_id']}: {e}")
        return c, votes

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(judge_one, c): c for c in todo}
        for fut in concurrent.futures.as_completed(futures):
            if ledger.total >= max_usd:
                for f in futures:
                    f.cancel()
                print(f"  panel halted at ${ledger.total:.2f}")
                break
            try:
                c, votes = fut.result()
            except Exception as e:
                print(f"  panel task failed: {e}")
                continue
            if not votes:
                continue
            ai_votes = sum(1 for v in votes if v.get("verdict") == "ai")
            results[c["scenario_id"]] = _vote_record(c, votes, ai_votes)
            print(f"  {c['scenario_id']:42} {ai_votes}/{len(votes)} AI  ${ledger.total:.2f}", flush=True)
            if cache_path:
                with open(cache_path, "w") as fh:
                    json.dump(results, fh)
    return results


def _vote_record(c: dict, votes: list, ai_votes: int) -> dict:
    return {
        "coach": c["coach"],
        "archetype": c["archetype"],
        "ai_votes": ai_votes,
        "n_votes": len(votes),
        "majority": "ai" if ai_votes * 2 > len(votes) else "human",
        "mean_confidence": round(statistics.mean([float(v.get("confidence") or 0) for v in votes]), 1),
        "tells": [t for v in votes for t in (v.get("tells") or [])],
        "most_human": [v.get("most_human_moment") for v in votes if v.get("most_human_moment")],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", required=True, help="directory of *.jsonl sim outputs")
    ap.add_argument("--report", required=True, help="markdown report output path")
    ap.add_argument("--json-out", help="machine-readable metrics output path")
    ap.add_argument("--max-usd", type=float, default=3.0)
    ap.add_argument("--no-panel", action="store_true", help="deterministic metrics only — no spend")
    ap.add_argument("--workers", type=int, default=6, help="concurrent judge conversations")
    args = ap.parse_args()

    os.environ.setdefault("AWS_REGION", "us-west-2")
    convos = load_runs(args.runs)
    print(f"loaded {len(convos)} conversations")
    if not convos:
        print("nothing to analyze")
        return 1

    metrics = [conversation_metrics(c) for c in convos]
    collisions = opener_collisions(convos)
    similarity_pairs = cross_coach_similarity(convos)
    collapse = structural_collapse(convos)

    panel = {}
    ledger = None
    if not args.no_panel:
        from coach_chat_sim import Ledger

        ledger = Ledger(args.max_usd * 2)
        print("\nrunning blind panel...")
        cache = os.path.join(args.runs, ".panel_cache.json")
        panel = run_panel(convos, ledger, args.max_usd, workers=args.workers, cache_path=cache)

    payload = {
        "n_conversations": len(convos),
        "metrics": metrics,
        "opener_collisions": collisions[:40],
        "cross_coach_similarity": similarity_pairs[:40],
        "structural_collapse": collapse,
        "panel": panel,
        "panel_spend": ledger.summary() if ledger else None,
    }
    if args.json_out:
        with open(args.json_out, "w") as fh:
            json.dump(payload, fh, indent=2, default=str)
        print(f"\nwrote metrics -> {args.json_out}")

    write_report(payload, args.report)
    print(f"wrote report -> {args.report}")
    return 0


def write_report(p: dict, path: str) -> None:
    m = p["metrics"]
    n = len(m)
    by_coach = defaultdict(list)
    by_arch = defaultdict(list)
    for row in m:
        by_coach[row["coach"]].append(row)
        by_arch[row["archetype"]].append(row)

    def agg(rows, key):
        vals = [r[key] for r in rows if isinstance(r.get(key), (int, float))]
        return round(statistics.mean(vals), 2) if vals else 0.0

    lines = [
        "# Coach chat simulation — findings",
        "",
        f"{n} simulated conversations, {sum(r['turns'] for r in m)} turns, across {len(by_coach)} coaches.",
        "",
        "## Platform-wide deterministic metrics",
        "",
        "| metric | value |",
        "|---|---|",
        f"| mean reply:inbound char ratio | {agg(m, 'mean_char_ratio')} |",
        f"| mean reply length (chars) | {agg(m, 'mean_chars')} |",
        f"| closing-question rate | {agg(m, 'closing_question_rate')} |",
        f"| em-dash reply rate | {agg(m, 'em_dash_rate')} |",
        f"| 'not X but Y' (total) | {sum(r['not_x_but_y'] for r in m)} |",
        f"| assistant-isms (total hits) | {sum(len(r['assistant_isms']) for r in m)} |",
        f"| formatting violations (total) | {sum(r['formatting_hits'] for r in m)} |",
        f"| name uses (total) | {sum(r['name_uses'] for r in m)} |",
        f"| conversations with stat recital | {sum(1 for r in m if r['stat_recital'])} |",
        "",
        "## By coach",
        "",
        "| coach | convos | char ratio | reply len | closing-Q | em-dash | isms | recital |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for coach, rows in sorted(by_coach.items()):
        lines.append(
            f"| {rows[0].get('coach_name') or coach} | {len(rows)} | {agg(rows, 'mean_char_ratio')} | "
            f"{agg(rows, 'mean_chars')} | {agg(rows, 'closing_question_rate')} | {agg(rows, 'em_dash_rate')} | "
            f"{sum(len(r['assistant_isms']) for r in rows)} | {sum(1 for r in rows if r['stat_recital'])} |"
        )

    lines += ["", "## By archetype", "", "| archetype | convos | char ratio | closing-Q | em-dash | isms |", "|---|---|---|---|---|---|"]
    for arch, rows in sorted(by_arch.items(), key=lambda kv: -agg(kv[1], "mean_char_ratio")):
        lines.append(
            f"| {arch} | {len(rows)} | {agg(rows, 'mean_char_ratio')} | {agg(rows, 'closing_question_rate')} | "
            f"{agg(rows, 'em_dash_rate')} | {sum(len(r['assistant_isms']) for r in rows)} |"
        )

    isms = Counter(i for r in m for i in r["assistant_isms"])
    if isms:
        lines += ["", "## Assistant-isms by phrase", "", "| pattern | hits |", "|---|---|"]
        lines += [f"| `{k}` | {v} |" for k, v in isms.most_common(20)]

    if p.get("structural_collapse"):
        lines += [
            "",
            "## Voice collapse — distinct reply SHAPES per archetype",
            "",
            "Eight personas answering the same message. `distinct shapes` counts how many "
            "structurally different replies they produced; `collapse` is the share landing on "
            "the single most common shape. A high collapse ratio is one model wearing eight name tags.",
            "",
            "| archetype | coaches | distinct shapes | collapse | dominant shape |",
            "|---|---|---|---|---|",
        ]
        lines += [
            f"| {r['archetype']} | {r['coaches']} | {r['distinct_shapes']} | {r['collapse_ratio']} | `{r['dominant_shape']}` |"
            for r in p["structural_collapse"]
        ]

    if p["opener_collisions"]:
        lines += ["", "## Opening phrases shared across coaches", "", "| phrase | coaches | uses |", "|---|---|---|"]
        lines += [f"| {ph} | {', '.join(cs)} | {ct} |" for ph, cs, ct in p["opener_collisions"][:20]]

    if p["cross_coach_similarity"]:
        lines += [
            "",
            "## Most similar coach pairs (same archetype)",
            "",
            "| jaccard | archetype | coach A | coach B |",
            "|---|---|---|---|",
        ]
        lines += [f"| {s} | {a} | {x} | {y} |" for s, a, x, y in p["cross_coach_similarity"][:15]]

    panel = p.get("panel") or {}
    if panel:
        ai_flagged = [k for k, v in panel.items() if v["majority"] == "ai"]
        lines += [
            "",
            "## Blind panel",
            "",
            f"{len(panel)} conversations judged by a 3-judge panel. "
            f"**{len(ai_flagged)}/{len(panel)} ({round(100 * len(ai_flagged) / max(1, len(panel)))}%) were called AI by majority.**",
            "",
            "| coach | archetype | AI votes | confidence |",
            "|---|---|---|---|",
        ]
        for k, v in sorted(panel.items(), key=lambda kv: (-kv[1]["ai_votes"], -kv[1]["mean_confidence"])):
            lines.append(f"| {v['coach']} | {v['archetype']} | {v['ai_votes']}/{v['n_votes']} | {v['mean_confidence']} |")

        tells = Counter()
        for v in panel.values():
            for t in v["tells"]:
                tells[str(t)[:160]] += 1
        lines += ["", "### What gave it away (judge free-text, most frequent)", ""]
        lines += [f"- ({c}x) {t}" for t, c in tells.most_common(50)]

        human = [h for v in panel.values() for h in v["most_human"] if h]
        if human:
            lines += ["", "### Moments the judges called most human", ""]
            lines += [f"- {str(h)[:200]}" for h in human[:25]]

    with open(path, "w") as fh:
        fh.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    sys.exit(main())
