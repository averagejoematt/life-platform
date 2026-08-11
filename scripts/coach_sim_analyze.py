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
  balanced_clauses  the WIDER class "not X, but Y" is only one member of (#2537).
                    Rhetorical symmetry was the #1 judge tell — 25% of 2,404
                    free-text tells — while the narrow regex above matched 9 times
                    in 536 replies. A detector that undercounts the corpus's
                    loudest signal by two orders of magnitude is a guard that
                    guards nothing, so the class is now five NAMED patterns (the
                    original frame, the "X, not Y" verdict, comparative antithesis,
                    parallel construction, the closing flourish) reported per coach
                    so a spec that legitimately asks for symmetry can be told apart
                    from the model's habit. Advisory only: it counts, never rewrites.
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


# ── The balanced-clause class (#2537) ─────────────────────────────────────────
#
# WHY THIS IS FIVE PATTERNS AND NOT ONE. The blind panel's 2,404 free-text tells
# put rhetorical symmetry at 25% — the single loudest signal in the corpus — and
# `_NOT_X_BUT_Y` above found 9 instances in 536 replies. The regex was not wrong;
# it was answering a narrower question than the judges were asking. The judges
# flag a family, and a family needs members that can be counted separately,
# because "symmetry is up 40%" is unactionable while "the closing flourish is up
# 40%" names the sentence to cut.
#
# ADVISORY, DELIBERATELY (the coach_repetition_detector posture). This is a
# measuring instrument: pure functions, corpus passed in, no mutation of any
# reply, and no verdict from a sample too small to carry one. The mutating
# enforcement path (#2555's style gate) is a different module on purpose — an
# instrument that can rewrite the thing it measures cannot be trusted to report
# on it.
#
# Each pattern below is anchored to a span the judges actually cited, quoted in
# `docs/design/COACH_SIM_FINDINGS_2026_08_10.md` and in #2537.

# "That's signal, not alarm." — the balanced two-clause verdict. The negated
# appositive must CLOSE the sentence: mid-sentence ", not " is ordinary
# qualification ("I'd rest today, not because you're weak, but because…" is
# caught by _NOT_X_BUT_Y instead), while a sentence that lands on it is the
# aphorism shape.
_BAL_X_NOT_Y = re.compile(r"[^.,;!?—]{3,60},\s*not\s+[^.,;!?]{2,40}(?=\s*[.!?]|\s*$)", re.I)

# "The number itself is less important than what it's doing over time" —
# antithesis with no `not` anywhere. The comparand after `than` must be a CLAUSE,
# not a noun phrase: "your sleep is more consistent than last month" is a data
# statement and must stay silent, while "…than what it's doing" opposes two ideas.
_BAL_COMPARATIVE = re.compile(
    r"\b(?:is|are|was|were|isn't|aren't|matters?|feels?|reads?|counts?|means?|says?|tells?)\s+"
    r"(?:a\s+lot\s+|much\s+|far\s+|way\s+|rather\s+)?(?:less|more)\s+[\w'’-]+(?:\s+[\w'’-]+){0,2}\s+than\s+"
    r"(?:what|how|whether|why|who|where|(?:[\w'’-]+\s+){0,3}(?:is|are|was|were|does|do|did|has|have|can|could|would|will))\b"
    r"|\bless\s+about\s+[^.;!?]{2,50}\bthan\s+about\b"
    r"|\bnot\s+so\s+much\s+[^.;!?]{2,50}\bas\b",
    re.I,
)

# "Which is either reassuring or unsettling depending on how you look at it." —
# the summarising flourish that closes a reply too neatly. Scored on the FINAL
# sentence only: the same construction mid-reply is a thought, at the end it is a
# bow tied on the paragraph, and the judges cited the ending specifically
# ("poetic construction that wraps up the advice too neatly").
_BAL_FLOURISH = re.compile(
    r"^which\b"
    r"|\beither\s+[^.;!?]{2,60}\bor\b"
    r"|\bdepending on (?:how|what|which|who|whether)\b"
    r"|\bnot because\s+[^.;!?]{2,60}\bbut because\b"
    r"|\bwhich is (?:both|either|why|what|the)\b",
    re.I,
)

# Clause boundaries for parallel construction. The em-dash and the colon are
# boundaries too: "I don't exist between conversations — no background
# processing, no waiting around, no boredom" is a run of THREE `no` clauses only
# if the dash splits; on commas alone it reads as two and the tell is missed.
_CLAUSE_SPLIT = re.compile(r"\s*[,;:—–]\s*|\s+-\s+")

# Anaphora needs three limbs to be rhetoric rather than coincidence: two clauses
# opening on the same word happens constantly in ordinary prose, three is a
# deliberate figure. Stated as a tunable so the bar is visible, not buried.
PARALLEL_MIN_LIMBS = 3
# Each limb must be more than a bare connective, or "and, and, and" would score.
PARALLEL_MIN_WORDS_PER_LIMB = 2

# The five members, in report order. Named so a per-coach rate can be attributed
# to a construction rather than to an undifferentiated "symmetry" number.
BALANCED_CLAUSE_CLASSES = (
    "not_x_but_y",
    "x_not_y",
    "comparative_antithesis",
    "parallel_construction",
    "closing_flourish",
)

# Below this many replies a per-coach rate is noise, so no verdict is issued —
# absence, never a green "this coach is fine" (ADR-104/105).
MIN_REPLIES_FOR_COACH_VERDICT = 20
# A platform baseline drawn from fewer coaches than this cannot support a
# mean+std threshold, so the per-coach verdicts stay None.
MIN_COACHES_FOR_BASELINE = 4
# Flag a coach whose rate exceeds the platform mean by this many standard
# deviations of the per-coach rate distribution (personal-variance threshold,
# ADR-105 — not a guessed constant).
BASELINE_K = 1.0


def _sentences(text):
    return [s.strip() for s in _SENTENCE_SPLIT.split((text or "").strip()) if s.strip()]


def _first_word(segment):
    m = re.match(r"[\"“‘'(]*([\w'’-]+)", segment or "")
    return m.group(1).lower() if m else ""


def _parallel_construction_hits(reply):
    """Anaphora: PARALLEL_MIN_LIMBS+ consecutive clauses opening on the same word.

    Two shapes count. Within a sentence — "No background processing, no waiting
    around, no boredom." Across sentences — consecutive sentences sharing their
    first two words, which is the rhythm the judges called "identical shape every
    time" ("validate feeling, reframe as information, ask clarifying question").
    """
    hits = []
    sents = _sentences(reply)

    for sent in sents:
        limbs = [seg for seg in _CLAUSE_SPLIT.split(sent) if seg.strip()]
        run_word, run_len, run_start = None, 0, 0
        for i, limb in enumerate(limbs):
            word = _first_word(limb)
            long_enough = len(limb.split()) >= PARALLEL_MIN_WORDS_PER_LIMB
            if word and long_enough and word == run_word:
                run_len += 1
            else:
                run_word, run_len, run_start = (word if long_enough else None), 1, i
            if run_len == PARALLEL_MIN_LIMBS:
                hits.append(", ".join(limbs[run_start : i + 1])[:120])

    # Sentence-level anaphora: two consecutive sentences is already a figure at
    # this granularity, because a whole sentence repeating an opening is far less
    # likely to be accidental than a clause is.
    for a, b in zip(sents, sents[1:]):
        wa, wb = a.split(), b.split()
        if len(wa) >= 4 and len(wb) >= 4:
            head_a = " ".join(w.lower().strip(".,;:!?\"'") for w in wa[:2])
            head_b = " ".join(w.lower().strip(".,;:!?\"'") for w in wb[:2])
            if head_a and head_a == head_b:
                hits.append(f"{a[:60]} / {b[:60]}")
    return hits


def balanced_clause_hits(reply):
    """The balanced-clause / antithesis family in one reply (#2537).

    Pure function over one string — no corpus fetch, no model, no mutation.
    Returns {class_name: [matched spans]} containing only the classes that fired,
    so an empty dict is a genuine zero rather than five zeroes to filter.
    """
    text = (reply or "").strip()
    if not text:
        return {}
    found = {}

    def add(name, spans):
        spans = [s.strip()[:120] for s in spans if s and s.strip()]
        if spans:
            found[name] = spans

    add("not_x_but_y", _NOT_X_BUT_Y.findall(text))
    add("x_not_y", [m.group(0) for m in _BAL_X_NOT_Y.finditer(text)])
    add("comparative_antithesis", [m.group(0) for m in _BAL_COMPARATIVE.finditer(text)])
    add("parallel_construction", _parallel_construction_hits(text))

    sents = _sentences(text)
    if sents and _BAL_FLOURISH.search(sents[-1]):
        add("closing_flourish", [sents[-1]])
    return found


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
    balanced = balanced_clause_hits(reply)
    return {
        "chars": len(reply),
        "words": words,
        "char_ratio": round(len(reply) / max(1, len(inbound)), 2),
        "word_ratio": round(words / in_words, 2),
        "questions": reply.count("?"),
        "closes_on_question": reply.rstrip().endswith("?"),
        "em_dashes": reply.count("—"),
        "not_x_but_y": len(_NOT_X_BUT_Y.findall(reply)),
        # The wider family (#2537). `not_x_but_y` above is kept unchanged as its
        # own number so the widening is auditable against the 9-in-536 baseline
        # rather than silently absorbed into a bigger one.
        "balanced_classes": sorted(balanced),
        "balanced_spans": balanced,
        "balanced_hits": sum(len(v) for v in balanced.values()),
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
        # Carried so the panel's per-scenario verdicts and tells can be joined back
        # to the deterministic rows — without it the judge tells cannot be used as
        # labelled data, which is what #2537 asks the detector to be validated on.
        "scenario_id": convo.get("scenario_id"),
    }
    if not per:
        # A zero-turn conversation is a real outcome (the simulator ended it, or the
        # run halted mid-scenario). It keeps its identity fields so the by-coach
        # rollup can still see that the scenario was attempted and produced nothing.
        return dict(
            base,
            empty=True,
            assistant_isms=[],
            stat_recital={},
            not_x_but_y=0,
            balanced_classes=[],
            balanced_hits=0,
            balanced_replies=0,
            formatting_hits=0,
            name_uses=0,
            per_turn=[],
        )

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
        "balanced_hits": sum(m["balanced_hits"] for m in per),
        "balanced_replies": sum(1 for m in per if m["balanced_classes"]),
        "balanced_classes": [c for m in per for c in m["balanced_classes"]],
        "assistant_isms": [i for m in per for i in m["assistant_isms"]],
        "formatting_hits": sum(m["formatting_hits"] for m in per),
        "name_uses": sum(m["name_uses"] for m in per),
        "stat_recital": recited,
        "statuses": dict(statuses),
        "first_reply": turns[0]["reply"][:120],
        "per_turn": per,
    }


def symmetry_by_coach(metrics_rows: list) -> dict:
    """Per-coach balanced-clause rate, advisory, with n on every claim (#2537).

    WHY PER COACH. Platform-wide "symmetry: 9" told nobody what to change. Per
    coach it becomes attributable: a persona whose spec asks for the labelled
    interpretation may legitimately run high, while the same rate on a spec that
    says "Plain, complete sentences" is the model's habit leaking through. None of
    the eight specs currently asks for symmetry, so today every point of this is
    habit — but the report has to be able to tell them apart before any spec does.

    The flag threshold is derived from the measured per-coach distribution
    (mean + BASELINE_K·std), not a guessed constant. It is a RELATIVE reading and
    says so: it finds the outlier coaches, and a platform where all eight are
    equally symmetric produces no flags at all, which is why the platform rate is
    reported alongside.

    Returns {"coaches": [...], "platform": {...}}. A coach with fewer than
    MIN_REPLIES_FOR_COACH_VERDICT replies, or a platform with fewer than
    MIN_COACHES_FOR_BASELINE comparable coaches, gets verdict None and a stated
    reason — never a green "typical".
    """
    per_coach = defaultdict(lambda: {"replies": 0, "flagged": 0, "classes": Counter(), "name": None})
    for row in metrics_rows or []:
        bucket = per_coach[row.get("coach")]
        bucket["name"] = bucket["name"] or row.get("coach_name")
        for m in row.get("per_turn") or []:
            bucket["replies"] += 1
            if m.get("balanced_classes"):
                bucket["flagged"] += 1
            for cls in m.get("balanced_classes") or []:
                bucket["classes"][cls] += 1

    total_replies = sum(b["replies"] for b in per_coach.values())
    total_flagged = sum(b["flagged"] for b in per_coach.values())
    platform = {
        "n_replies": total_replies,
        "n_flagged": total_flagged,
        "rate": round(total_flagged / total_replies, 3) if total_replies else 0.0,
        "by_class": dict(sum((b["classes"] for b in per_coach.values()), Counter())),
    }

    rows = []
    for coach, b in per_coach.items():
        rows.append(
            {
                "coach": coach,
                "coach_name": b["name"] or coach,
                "n_replies": b["replies"],
                "n_flagged": b["flagged"],
                "rate": round(b["flagged"] / b["replies"], 3) if b["replies"] else 0.0,
                "by_class": dict(b["classes"]),
            }
        )

    eligible = [r for r in rows if r["n_replies"] >= MIN_REPLIES_FOR_COACH_VERDICT]
    if len(eligible) < MIN_COACHES_FOR_BASELINE:
        reason = (
            f"{len(eligible)} coaches have >= {MIN_REPLIES_FOR_COACH_VERDICT} replies; "
            f"{MIN_COACHES_FOR_BASELINE} are needed to state a cross-coach threshold, "
            "so no per-coach verdict is issued (ADR-105)"
        )
        for r in rows:
            r["verdict"] = None
            # Two different reasons can block a verdict and they are not
            # interchangeable: "this coach has 3 replies" is fixed by running more
            # of that coach, "the platform has 2 comparable coaches" is fixed by
            # running more coaches. Saying only the second would send an operator
            # to the wrong lever.
            r["reason"] = (
                f"{r['n_replies']} replies; minimum {MIN_REPLIES_FOR_COACH_VERDICT} for a rate verdict"
                if r["n_replies"] < MIN_REPLIES_FOR_COACH_VERDICT
                else reason
            )
        platform["threshold"] = None
        platform["threshold_reason"] = reason
        return {"coaches": sorted(rows, key=lambda r: -r["rate"]), "platform": platform}

    rates = [r["rate"] for r in eligible]
    mean = statistics.mean(rates)
    std = statistics.pstdev(rates)
    threshold = round(mean + BASELINE_K * std, 3)
    platform["threshold"] = {
        "threshold": threshold,
        "baseline_mean": round(mean, 3),
        "baseline_std": round(std, 3),
        "baseline_k": BASELINE_K,
        "n_coaches": len(eligible),
        "derivation": (
            f"mean+{BASELINE_K}*std of the per-coach balanced-clause rate over "
            f"n={len(eligible)} coaches with >= {MIN_REPLIES_FOR_COACH_VERDICT} replies each"
        ),
    }
    for r in rows:
        if r["n_replies"] < MIN_REPLIES_FOR_COACH_VERDICT:
            r["verdict"] = None
            r["reason"] = f"{r['n_replies']} replies; minimum {MIN_REPLIES_FOR_COACH_VERDICT} for a rate verdict"
        else:
            r["verdict"] = "elevated" if r["rate"] > threshold else "typical"
    return {"coaches": sorted(rows, key=lambda r: -r["rate"]), "platform": platform}


# The judges' own vocabulary for this tell, taken from the free-text they wrote
# ("balanced", "rhetorical symmetry", "parallel structure", "wraps up too
# neatly"). It labels TELLS, not replies — deliberately narrow, because widening
# it into the neighbouring themes (over-polish, templating) would let the
# detector score credit for catching a different finding.
_SYMMETRY_TELL_VOCAB = re.compile(
    r"\b(?:symmetr\w*|balanc\w*|antithe\w*|parallel\w*|chiasm\w*|cadence|aphoris\w*|epigram\w*)\b"
    r"|\bnot\s+x\b.{0,6}\bbut\s+y\b"
    r"|\b(?:too\s+)?neatl?y?\b"
    r"|\bwraps?\s+up\b",
    re.I,
)


def validate_against_judge_tells(payload: dict) -> dict:
    """Score the detector against the panel's free-text tells as labelled data.

    The panel wrote 2,404 tells over the corpus and 25% of them cite this class.
    Those tells are the only independent labels that exist, so this joins them to
    the deterministic rows by `scenario_id` and reports the confusion matrix:
    a conversation is LABELLED positive when any judge tell uses the symmetry
    vocabulary, and PREDICTED positive when any of its replies fires a
    balanced-clause pattern.

    Precision/recall here are against a noisy label — three judges reading a whole
    transcript, not a span-level annotation — so this is a correlation check, and
    the returned dict says so rather than dressing it as accuracy. It is the
    measurement that decides whether widening worked: the pre-#2537 detector fired
    on 9 replies of 536 against a 25%-of-tells label, which no threshold could
    rescue.

    Pure: the payload is passed in (the `--json-out` file of a previous run).
    Returns verdict None when too few conversations carry panel labels.
    """
    rows = (payload or {}).get("metrics") or []
    panel = (payload or {}).get("panel") or {}
    by_id = {r.get("scenario_id"): r for r in rows if r.get("scenario_id")}

    tp = fp = fn = tn = 0
    n_tells = 0
    n_symmetry_tells = 0
    for scenario_id, verdict in panel.items():
        row = by_id.get(scenario_id)
        if row is None:
            continue
        tells = [str(t) for t in (verdict.get("tells") or [])]
        n_tells += len(tells)
        hits = [t for t in tells if _SYMMETRY_TELL_VOCAB.search(t)]
        n_symmetry_tells += len(hits)
        labelled = bool(hits)
        predicted = bool(row.get("balanced_replies"))
        if labelled and predicted:
            tp += 1
        elif labelled and not predicted:
            fn += 1
        elif predicted and not labelled:
            fp += 1
        else:
            tn += 1

    n = tp + fp + fn + tn
    base = {
        "n_conversations_joined": n,
        "n_tells": n_tells,
        "n_symmetry_tells": n_symmetry_tells,
        "label": "any judge tell citing the symmetry vocabulary (conversation-level, noisy)",
        "advisory": True,
    }
    if n < MIN_REPLIES_FOR_COACH_VERDICT:
        return {
            **base,
            "verdict": None,
            "reason": (
                f"{n} conversations carry both deterministic rows and panel tells; "
                f"minimum {MIN_REPLIES_FOR_COACH_VERDICT} to state a correlation (ADR-105)"
            ),
        }
    labelled_pos = tp + fn
    return {
        **base,
        "verdict": "measured",
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
        "true_negative": tn,
        "recall_on_labelled": round(tp / labelled_pos, 3) if labelled_pos else None,
        "precision": round(tp / (tp + fp), 3) if (tp + fp) else None,
        "labelled_positive_rate": round(labelled_pos / n, 3),
        "predicted_positive_rate": round((tp + fp) / n, 3),
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


_MENU_QUESTION = re.compile(r"\?[\s\"']*$")
# The menu question — "the tracking, the whole project, or something else?" — is the
# template's signature move. The span between the first comma and the "or" routinely
# contains further commas, so it must not be excluded from the middle class.
_OR_LIST = re.compile(r",[^?]{2,80}\bor\b[^?]{2,40}\?")

# A leading discourse particle ("Yeah.", "Ha.", "Fair.") is punctuation with a
# vocabulary — it carries no move. It used to be classified as its own opening class,
# which meant a coach could bolt "Yeah." onto the front of the template and register as
# a DIFFERENT shape from a coach running the identical template without it. Measured
# 2026-08-10 on venting_no_question: two of the eight "distinct" shapes differed from
# another coach's by exactly that one word. The particle is stripped before the opening
# move is read, so it can no longer manufacture distinctness.
# A bubble break IS a sentence break on this surface. ``_SENTENCE_SPLIT`` only breaks
# after . ! ?, and a coach who fires two bubbles without terminal punctuation —
# "rough ones have a way of landing on day 1" / "eaten anything yet?" — reads as ONE
# sentence that happens to end in a question mark, so its opening move fingerprints as
# a question when the first thing he actually sent was a statement. Measured: 2 of 8
# off_lane openers were misread this way.
_SENTENCE_OR_BUBBLE = re.compile(r"(?<=[.!?])\s+|\n+")
_DISCOURSE_PARTICLE = re.compile(
    r"^(?:yeah|yep|yup|ok|okay|ha+h?|oh|ah|fair|right|hm+|mm+|sure|ugh|well|honestly|god)\b[\s,.!?…—–-]*", re.I
)
_GREETING_OPEN = re.compile(r"^(?:hey|hi|hello|morning|evening|afternoon)\b", re.I)
# Elided first person — "Don't have that.", "No idea." — is a statement about what the
# COACH has, not an imperative. Reading it as a directive puts every honest-absence
# opener in the wrong class, which is the class this issue is measuring.
_ELIDED_SELF = re.compile(
    r"^(?:no idea\b|not sure\b|(?:don'?t|can'?t|couldn'?t|won'?t|haven'?t|didn'?t|doesn'?t)\s+(?:have|know|see|think|remember|get|track|recall)\b)",
    re.I,
)
_SELF_OPEN = re.compile(r"^(?:i|i'?m|i'?d|i'?ve|i'?ll|my|me)\b", re.I)
_HIS_STATE_OPEN = re.compile(r"^(?:that|this|it|there|those|these|you|you'?re|you'?ve|your|sounds like)\b", re.I)
_DIRECTIVE_OPEN = re.compile(
    r"^(?:skip|take|go|leave|stop|drop|eat|sleep|rest|call|keep|put|let|give|forget|don'?t|do|try|hold|park|text|ask|check)\b", re.I
)


def _opening_move(first_sentence: str) -> str:
    """Which of five moves the reply OPENS with — who the first clause is about.

    The axis this replaced read grammatical FORM: "does the reply start with a
    demonstrative pronoun". That works exactly until the demonstrative is banned, at
    which point every reply falls into one residual OPEN_STATEMENT bucket and the
    fingerprint stops discriminating precisely on the corpus it was built for. The
    axis is about STANCE instead — the thing that actually differs between Lisa Park
    sitting with it, Steve Brooks naming the load, and Nora Vale declining to
    interpret — and it is checked in a fixed order because the classes overlap.
    """
    s = (first_sentence or "").strip()
    if not s:
        return "OPEN_PARTICLE"
    if _GREETING_OPEN.match(s):
        return "OPEN_GREETING"
    if s.endswith("?"):
        return "OPEN_QUESTION"
    if _ELIDED_SELF.match(s) or _SELF_OPEN.match(s):
        return "OPEN_SELF"  # what the coach has / thinks / will do
    if _HIS_STATE_OPEN.match(s):
        return "ACK_HIS_STATE"  # the template's move 1 — naming his state back at him
    if _DIRECTIVE_OPEN.match(s):
        return "OPEN_DIRECTIVE"  # a call, delivered as an instruction
    return "OPEN_FACT"  # a third-person statement about the data, the week, the world


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

    THREE AXES, and the space got SMALLER when they were revised (#2536): 4 opening
    classes x 2 echo x 3 close x 3 sentence-count buckets = 72 cells before, 7 x 2 x 3
    = 42 now. That direction is deliberate. A fingerprint that gains cells can report
    "more distinct shapes" for a change that did nothing, so the sentence-count bucket
    — a LENGTH proxy, already measured exactly by ``reply_metrics``, and the axis on
    which a one-word "Yeah." bubble split a cluster in two — came out in the same pass
    that gave the opening move its three extra stance classes.
    """
    r = (reply or "").strip()
    if not r:
        return "EMPTY"
    body = _DISCOURSE_PARTICLE.sub("", r).strip() or r
    first = next((x for x in _SENTENCE_OR_BUBBLE.split(body) if x.strip()), "").strip()
    parts = [_opening_move(first)]

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
    return "|".join(parts)


def structural_collapse(convos: list) -> list:
    """Per archetype: how many DISTINCT reply shapes did the eight personas produce?

    Eight distinct signatures means eight voices. One or two means the personas are
    decoration on a single template, and the fix belongs in the engine (or in what
    the voice specs are asked to differentiate), not in one coach's config.

    ``dominant_coaches`` names the cluster. The count alone says a template is running;
    it does not say whose specs to open, and a metric that reports a problem without
    reporting where it lives gets read once and then ignored.
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
                "dominant_coaches": sorted(c for c, s in by_coach.items() if s == top_sig),
                "collapse_ratio": round(top_n / len(by_coach), 2),
            }
        )
    return sorted(rows, key=lambda r: -r["collapse_ratio"])


# The absence cues an honest coach reaches for. Deliberately a cue list rather than a
# phrase blacklist: what is being measured is not WHETHER a coach admits it has no
# data (it must — ADR-104) but whether eight of them admit it in the same words.
_ABSENCE_CUE = re.compile(
    r"(i (?:don'?t|do not) (?:have|know|track)|don'?t have|no idea|not tracked|don'?t track|no data|nothing (?:on|in|that far)|"
    r"let me check|can'?t (?:see|pull|tell)|isn'?t (?:something|in) )",
    re.I,
)


def _stem(text: str, n: int) -> str:
    """First n words, lowercased, stripped of punctuation, leading particle removed."""
    body = _DISCOURSE_PARTICLE.sub("", (text or "").strip()).strip() or (text or "").strip()
    words = [w.strip("\"“”‘’'.,;:!?—–-…()") for w in body.lower().split()]
    return " ".join([w for w in words if w][:n])


def _collisions(stems_by_coach: dict, min_coaches: int) -> list:
    rows = [
        {"stem": stem, "coaches": sorted(coaches), "n_coaches": len(coaches), "uses": uses}
        for stem, (coaches, uses) in stems_by_coach.items()
        if len(coaches) >= min_coaches and stem
    ]
    return sorted(rows, key=lambda r: (-r["n_coaches"], -r["uses"]))


def opening_construction_collisions(convos: list, stem_words: int = 3, min_coaches: int = 3) -> list:
    """Opening CONSTRUCTIONS shared across coaches — the three-word stem, not the phrase.

    ``opener_collisions`` keys on the first FOUR words, which is one word too many to
    see this failure: "that kind of tired", "that kind of monday" and "that kind of
    day" are three different keys and one construction. Measured on the same corpus,
    the four-word key reported 3 coaches and the three-word stem reported 6 — and 6 is
    the number in the finding this metric exists to close.
    """
    stems: dict = defaultdict(lambda: (set(), 0))
    for c in convos:
        turns = c.get("turns") or []
        if not turns:
            continue
        stem = _stem(turns[0]["reply"], stem_words)
        coaches, uses = stems[stem]
        coaches.add(c["coach"])
        stems[stem] = (coaches, uses + 1)
    return _collisions(stems, min_coaches)


def absence_phrasing_collisions(convos: list, stem_words: int = 3, min_coaches: int = 3) -> list:
    """How the roster says "I don't have that" — one stem per absence sentence.

    Honest absence is REQUIRED (ADR-104) and is not the defect; sounding like one
    person doing it is. Every sentence carrying an absence cue contributes the stem it
    opens with, across every turn rather than the first — a refusal is usually the
    answer to his second or third message, so a first-turn-only measure cannot see it.
    """
    stems: dict = defaultdict(lambda: (set(), 0))
    for c in convos:
        for t in c.get("turns") or []:
            for sentence in _SENTENCE_OR_BUBBLE.split(t.get("reply") or ""):
                if _ABSENCE_CUE.search(sentence):
                    stem = _stem(sentence, stem_words)
                    coaches, uses = stems[stem]
                    coaches.add(c["coach"])
                    stems[stem] = (coaches, uses + 1)
    return _collisions(stems, min_coaches)


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
    ap.add_argument("--runs", help="directory of *.jsonl sim outputs")
    ap.add_argument("--report", help="markdown report output path")
    ap.add_argument(
        "--validate-from",
        help="re-score the balanced-clause detector against the judge tells already captured in an existing --json-out payload; no spend, no re-run",
    )
    ap.add_argument("--json-out", help="machine-readable metrics output path")
    ap.add_argument("--max-usd", type=float, default=3.0)
    ap.add_argument("--no-panel", action="store_true", help="deterministic metrics only — no spend")
    ap.add_argument("--workers", type=int, default=6, help="concurrent judge conversations")
    args = ap.parse_args()

    if args.validate_from:
        with open(args.validate_from) as fh:
            prior = json.load(fh)
        print(json.dumps(validate_against_judge_tells(prior), indent=2))
        print(json.dumps((prior.get("symmetry_by_coach") or symmetry_by_coach(prior.get("metrics") or []))["platform"], indent=2))
        return 0

    if not args.runs or not args.report:
        ap.error("--runs and --report are required unless --validate-from is given")

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
    opening_constructions = opening_construction_collisions(convos)
    absence_phrasings = absence_phrasing_collisions(convos)

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
        "symmetry_by_coach": symmetry_by_coach(metrics),
        "opening_constructions": opening_constructions,
        "absence_phrasings": absence_phrasings,
        "panel": panel,
        "panel_spend": ledger.summary() if ledger else None,
    }
    # Graded against the panel's own tells in the same run, so the widened
    # detector never reports a rate without the check on whether that rate tracks
    # what the judges independently flagged (#2537).
    payload["symmetry_validation"] = validate_against_judge_tells(payload)
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
        f"| balanced clauses, all 5 constructions (total) | {sum(r.get('balanced_hits', 0) for r in m)} |",
        f"| replies with >=1 balanced clause | {sum(r.get('balanced_replies', 0) for r in m)} |",
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

    sym = p.get("symmetry_by_coach") or {}
    if sym.get("coaches"):
        plat = sym.get("platform") or {}
        thr = plat.get("threshold")
        lines += [
            "",
            "## Balanced clauses / rhetorical symmetry, by coach (#2537)",
            "",
            f"**{plat.get('n_flagged', 0)} of {plat.get('n_replies', 0)} replies "
            f"(rate {plat.get('rate', 0)})** contain at least one balanced-clause construction. "
            "Advisory: this counts, it does not rewrite. No voice spec currently asks for symmetry, "
            "so a coach above the derived threshold is showing the model's habit, not its character.",
            "",
        ]
        lines.append(
            f"Threshold: {thr['threshold']} — {thr['derivation']}."
            if thr
            else "No threshold derived — too few coaches with enough replies."
        )
        lines += [
            "",
            "| coach | replies (n) | flagged | rate | verdict | top class |",
            "|---|---|---|---|---|---|",
        ]
        for r in sym["coaches"]:
            top = max(r["by_class"].items(), key=lambda kv: kv[1])[0] if r["by_class"] else "—"
            lines.append(
                f"| {r['coach_name']} | {r['n_replies']} | {r['n_flagged']} | {r['rate']} | "
                f"{r['verdict'] or 'no verdict (n too small)'} | {top} |"
            )
        if plat.get("by_class"):
            lines += ["", "| construction | hits |", "|---|---|"]
            lines += [f"| `{k}` | {v} |" for k, v in sorted(plat["by_class"].items(), key=lambda kv: -kv[1])]

    val = p.get("symmetry_validation") or {}
    if val:
        lines += ["", "### Does it track what the judges flagged?", ""]
        if val.get("verdict") is None:
            lines.append(f"No verdict — {val.get('reason')}")
        else:
            lines += [
                f"Joined **n={val['n_conversations_joined']}** conversations "
                f"({val['n_symmetry_tells']} of {val['n_tells']} judge tells cite this class). "
                f"Recall on judge-labelled conversations **{val['recall_on_labelled']}**, "
                f"precision **{val['precision']}** "
                f"(TP {val['true_positive']} · FP {val['false_positive']} · "
                f"FN {val['false_negative']} · TN {val['true_negative']}).",
                "",
                "The label is conversation-level and noisy — three judges reading a whole "
                "transcript, not span annotation — so this is a correlation check, not accuracy.",
            ]

    if p.get("structural_collapse"):
        lines += [
            "",
            "## Voice collapse — distinct reply SHAPES per archetype",
            "",
            "Eight personas answering the same message. `distinct shapes` counts how many "
            "structurally different replies they produced; `collapse` is the share landing on "
            "the single most common shape. A high collapse ratio is one model wearing eight name tags.",
            "",
            "| archetype | coaches | distinct shapes | collapse | dominant shape | who shares it |",
            "|---|---|---|---|---|---|",
        ]
        lines += [
            f"| {r['archetype']} | {r['coaches']} | {r['distinct_shapes']} | {r['collapse_ratio']} | `{r['dominant_shape']}` "
            f"| {', '.join(r.get('dominant_coaches') or [])} |"
            for r in p["structural_collapse"]
        ]

    for key, title, blurb in (
        (
            "opening_constructions",
            "Opening CONSTRUCTIONS shared across coaches (3-word stem)",
            "The three-word stem of the first reply. `that kind of` is one construction whether it "
            "lands on tired, Monday or day — which is the collision a four-word opener key cannot see.",
        ),
        (
            "absence_phrasings",
            "Honest-absence phrasing shared across coaches (3-word stem)",
            "Admitting there is no data is required (ADR-104). Eight coaches admitting it in the same "
            "three words is the defect: one person doing the honest thing eight times.",
        ),
    ):
        rows = p.get(key) or []
        if rows:
            lines += ["", f"## {title}", "", blurb, "", "| stem | coaches | uses |", "|---|---|---|"]
            lines += [f"| `{r['stem']}` | {r['n_coaches']} — {', '.join(r['coaches'])} | {r['uses']} |" for r in rows[:20]]

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
