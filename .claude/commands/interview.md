Run the milestone deep interview (#1576) — the longform, biographical, unfiltered
session that produced the platform's best source material (the March 2026 interview →
STORY_DRAFTS_v1 / the Elena prequel brief) — as a repeatable ritual. Claude is the
interviewer; Matthew talks. See `docs/coaching/CHAT_MODES.md` for the route-the-takeaways
contract and verbatim rules.

## Arguments: $ARGUMENTS

Optional: the occasion (`day-30`, `genesis-eve`, `cycle-9 close`, or a theme like
`the relapse years`). Empty: pick the occasion from live state (see cadence below).

## PRIVACY — read before anything else

**The repo is PUBLIC (2026-07-20 flip). The issue's original "brief lands in
docs/content/" AC is dead — an unfiltered biographical brief must NEVER be committed to
git while the repo is public.** The brief's home is private S3:
`s3://matthew-life-platform/raw/matthew/interviews/YYYY-MM-DD-<slug>-brief.md`
(the raw/ prefix is delete-protected and never publicly served). From Claude Code, write
the file locally in the scratchpad and `aws s3 cp` it there. From claude.ai (no S3
access), compose the brief in-chat and hand it to Matthew to file — never suggest
committing it. If the repo ever flips private again, the docs/content/ pattern may
return via an explicit decision, not by default.

## Instructions

### 1. The occasion

If `$ARGUMENTS` is empty, ground the occasion in state: day number of the current cycle
(`get_daily_snapshot`), an approaching/passed milestone (day 30, a cycle close), a
felt-probe divergence, or a signal worth honoring carefully. If nothing is live, monthly
cadence is reason enough. Name the occasion in one sentence and start — no ceremony.

### 2. The interview — longform, his words

This is NOT the journal interview (daily texture) and NOT a coach check-in. It's
biography: where this attempt sits in the arc of the previous six, what the relapse
cycle felt like from inside, what's different this time, what he's afraid of, what the
readers never see. Craft rules:

- Open with one genuinely curious question about the occasion, then FOLLOW him — the
  best material comes from the second and third follow-up, not the question list.
- One question at a time. Silence and short answers are answers; don't fill them.
- Go where he signals depth; retreat instantly where he signals a wall. Skipping any
  thread is always valid and never revisited in-session.
- 45-90 minutes of conversational depth when he has it; a 15-minute version is still
  worth filing. He can stop at any point and the partial brief still gets written.

### 3. The brief — the ELENA_PREQUEL_BRIEF structure, verbatim quotes preserved

Compose ONE dated markdown brief with exactly these sections:

1. **Header** — date, occasion, cycle/day, and the standing guardrail line:
   *"PRIVATE source material — not for verbatim publication. Quotes clear through
   Matthew individually."*
2. **Unfiltered timeline/narrative** — the session's substance in chronological or
   thematic order. Matthew's framing, not a Claude gloss.
3. **Key quotes** — his exact words (ADR-104 verbatim rule), each with enough context
   to survive being read months later. No tidying beyond pure filler.
4. **What-to-abstract editorial notes** — for each sensitive thread: what a public
   essay could carry (the shape, the lesson) vs what stays private (names, specifics,
   substances/vices per the sensitive-content policy). This section is what makes the
   brief publication-ready-WITH-guardrails.

Store it (S3 path above). Confirm the upload out loud with the exact key.

### 4. Close — cross-links, all optional

- **V2 essay offer (#1563):** "want me to draft the public essay from this?" — if yes,
  the essay generator works from the WHAT-TO-ABSTRACT section, never the unfiltered one;
  publishing stays gated on Matthew regardless.
- **Quote nomination:** flag 1-3 quotes that could someday be public, for his explicit
  clearance — cleared ones go in the brief's editorial section as pre-approved.
- **Coach context:** one `write_platform_memory` line (allude tier — "milestone
  interview <date>, themes: <3-5 words>"; no quotes, no substance) so coaches know the
  ritual happened without reading it.
- Log the ritual itself via `log_decision` if the interview produced a call, or
  `save_insight` if it surfaced a pattern.

### 5. Cadence + triggers

Monthly by default, plus cycle events: genesis eve, day 30, a cycle close, a felt-probe
divergence, a relapse-risk signal. Data-triggered suggestions surface via
`get_capture_queues` when that wiring lands (#1578) — until then this file's cadence
note is the trigger. NEVER forced: a suggestion declined disappears without residue.
