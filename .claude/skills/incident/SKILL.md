---
name: incident
description: "Turn an incident into procedure that prevents it, not just a memory of it — an INCIDENT_LOG row, a class-level tracker, and an edit to the skill or agent that would have caught it. Use right after something breaks, is diagnosed, or is worked around, and whenever a fix is 'done' but nothing would stop the next instance."
user-invocable: true
argument-hint: "[what broke]"
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, TodoWrite
---

The lesson-to-procedure pipeline. Without it, incidents become *recall* instead of
*enforcement*, and the same class returns.

## Why this exists

The memory system holds ~365 files, ~90 of them review-discipline entries — the most
expensive knowledge this project owns. Almost none of it is encoded in any procedure.
Three of the most costly lessons — the GitHub **event swallow**, the **vacuous negative
control**, and **fixture must be the wire** — appeared in *zero* skill files. And
`.claude/agents/finding-verifier.md`, which exists *because* first-pass subagent findings
are ~50% false positives, went untouched for seven weeks while ninety lessons accumulated
after it.

A memory file is read when someone happens to recall it. A skill is read when the work
happens. Only the second one prevents anything.

## The three artifacts — all of them, or the incident is not closed

**1. The `docs/INCIDENT_LOG.md` row.** Date, severity, what broke, time-to-detect, and —
the field that matters most — **was it silent?** 51 of 184 rows were, with 2.4× the
median TTD and twice the odds of running past a day. Every mitigation that has actually
moved the numbers works by making a silent class loud.

**2. A tracker for the CLASS, not the symptom.** Per `docs/CONVENTIONS.md` §8b, a class
with a live residual keeps an **open** tracker with a dated, measured acceptance.

*Paid for:* 312 issues filed and 311 closed in fourteen days while the open corpus held
~50 — the board churned and did not drain. `#2978` exists only because five closed
per-symptom issues read as class closure while the failure rate got *worse*. Eight
incidents of QA rolling back a healthy deploy, while every named structural issue read
CLOSED. And an epic judged by child count booked a phantom: zero open children, eight
unchecked acceptance boxes.

**3. The procedure edit — the one that is always skipped.** Name the skill or agent that
*should* have caught this, and change it. If none would have, that is the finding: the
procedure has a hole, and the hole is the deliverable.

Ask, in order:
- Which skill was running when this happened? Add the rule where that skill will read it.
- Would `finding-verifier` have refuted the belief that led here? If not, add the lens.
- Would `prove-it` have caught the instrument? If not, add the question.
- Is the rule *structural*, or does it match a phrase? Every phrase-matched member of the
  #2959/#3003/#3199 demotion family has failed in the field — three in one session, one
  of them gating main. **Structural, or it will fail too.**

## Then check the class is really covered

Ask the honest metric from epic #2799: **"would a recurrence be caught today?"** Not
"is it fixed" — *caught*. If the answer is no, the tracker stays open and says why.

Guard the **set**, not the instance: a rule pinned to the one path that broke will miss
the eleventh. `#953` fixed in-repo worktree pollution by naming one directory; a second
in-repo worktree root reproduced it exactly, and the by-name skip read as coverage.
