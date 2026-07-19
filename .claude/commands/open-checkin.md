Free-form conversation with no queue to work — Matthew just talks about whatever's on his
mind, and this command's job is entirely the CLOSE: routing whatever came up to the right
write tool before the session ends. See `docs/coaching/CHAT_MODES.md` for the full
route-the-takeaways contract this command implements.

## Arguments: $ARGUMENTS

None expected — this mode has no scoped topic. If Matthew passes a topic anyway, treat it
as a conversation starter, not a constraint; the point of this mode is that it can go
anywhere.

## Instructions

### 1. Just talk

No queue to pull, no fixed question list. Let Matthew lead — respond as his coach/board
would (see `docs/coaching/COACH_SESSION.md` for the persona and Personal Board lenses if
the conversation turns into training/nutrition territory; pull live data with the read
tools — `get_freshness_status`, `get_coach_thread`, `get_readiness_score`,
`get_nutrition`, `get_mood`, etc. — whenever grounding a response in his actual numbers
would help, same freshness-paranoia discipline as the other modes: a green/empty read is
a hypothesis to verify, not a fact).

Don't force the conversation toward any particular write tool while it's happening — this
mode's value is that Matthew can just talk without being steered into a template. Take
mental note (or actual notes in your own scratch context) of anything that sounds like it
belongs in the table below, but don't interrupt to log it mid-thought unless it's a
literal check-in answer he's clearly delivering in response to something you asked him.

### 2. At the close: route everything

Before ending the session, walk back through what was said and route each distinct
takeaway to its tool, per the CHAT_MODES.md contract:

| What Matthew said (shape) | Route to |
|---|---|
| An insight, hypothesis, or pattern worth tracking and following up on | `save_insight(text, tags?, source="chat")` — capture the `insight_id` if you'll want `update_insight_outcome` later |
| A decision — followed or overrode platform/coach advice, and why | `log_decision(decision, followed?, override_reason?, source="mcp", pillars?)` |
| Durable context that should compound — a failure pattern, what worked, a calibration correction, a journey milestone | `write_platform_memory(category, content, date?)` — pick the category from the 7-value enum; don't force a fit, skip this row if nothing durable came up |
| An answer to an open coach check-in question, if one happened to come up | `log_coach_checkin(checkin_id, answer, ...)` VERBATIM — only if you actually pulled `get_coach_checkin_queue` and asked; don't invent a checkin_id |
| A habit why/trigger/reward, if he volunteered one | `log_habit_reflection(habit, trigger?, reward?, why_missed?, context?)` |
| An evening drinks count, if mentioned | `log_evening_intake(count, date?)` |
| Something that's really a journal entry (a day's narrative, not a discrete takeaway) | Point Matthew at `/journal-interview` rather than trying to compose a Notion page from inside this command — this mode isn't the journal-writing path (Notion is the sole SOT; see CHAT_MODES.md) |

Not every conversation produces every row — most sessions will only hit one or two.
Don't manufacture a write to fill the table; an open check-in with nothing durable to log
is a fine outcome, just say so.

### 3. Confirm what got logged

Before ending, state plainly what you wrote (which tool, with what) so Matthew has a
record of what's now durable versus what was just talk. If something he said was
ambiguous about which bucket it belongs in, ask him rather than guessing — a wrongly
routed takeaway (e.g. a passing comment logged as a formal `log_decision`) is worse than
asking one clarifying question.
