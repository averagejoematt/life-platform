# The Story Desk

> **Status:** live for the cycle-17 season rebuild; the weekly lambdas move onto it under #4535/#4536 · **Epic:** #4531 · **Owner:** Matthew

The chronicle (Elena's weekly post) and the Panel (the weekly podcast) report one continuous
season. A reader who starts at the prologue — or arrives cold at any week — should be able to
follow the experiment as if a journalist and a coaching panel were tracking it for the first
time: each installment picks up the last one's threads, reports what the data did that week,
and lets the coaches and Elena develop.

The desk is the pipeline that makes that hold without hand correction.

```
 week window ──► DOSSIER ──► DESK ──► story budget ──┬──► Elena's post ──► CHECKS ──► staged
 (Wed→Tue)       (code)      (1 LLM call,            │                    (1 rewrite)
                   ▲          structured)            └──► Panel script ──► CHECKS ──► staged
                   │             ▲                                          (1 rewrite)
                   │             │
              plan root      LEDGER (what the season has told) ◄──── written on publish
```

## The five pieces

| Piece | Module | What it guarantees |
|---|---|---|
| **Dossier** | `lambdas/content/story_dossier.py` | Every figure a writer may use, computed in code for exactly the week's dates. Plan targets come from the plan root (`experiment.plan_facts`), never `PROFILE#v1` (#4540), and `week_dossier` refuses a packet whose targets are not the plan root's (`plan_facts_findings`, #4532). Every source it reads has a watermark (`export_watermarks`: the last date it covers on or before the week's end, and when that row landed), so a date past a daily source's watermark reads as *not yet exported*, never as a behaviour. No row dated after the week's end is read. Every training session says whether it was a programmed routine and how it scored against the prescription. Vice names never enter; journal entries are counted, never read. |
| **Ledger** | `lambdas/content/story_ledger.py` | One `LEDGER#{date}` row per published installment: threads (open / advanced / resolved / retired), the Panel's bets and their results, who was featured, the leads and beats used, and an arc note per character. Read through `singleton_visible`, so a reset's tombstones can never become last week's memory. |
| **Desk** | `lambdas/content/story_desk.py` | One structured call returns the week's **story budget**: lead, secondary stories, omissions with reasons, a tone calibrated to the data, the coach to feature, last week's bet scored and the next one set, and an action for every open thread. The rubric is written in the module. Code then validates what a schema can't express. |
| **Writers** | `lambdas/content/story_writers.py` | Elena's long-form post and the Panel script, both written from the same budget, dossier and ledger, plus the previous installment. |
| **Checks** | `lambdas/content/story_checks.py` | Four checks. Completeness: `stop_reason`, the last sentence, the footer. The story door: no cycle or attempt counts, no off-record specifics, no machinery words, no export lag told as silence — its reader-surface half (`reader_surface`) is also run by the chronicle handler, the recap and the Panel at their own chokepoints, so a legacy writer cannot bypass it (#4538). The count rule is a structure (a number beside the restart vocabulary: "the 17th start", "16 earlier starts", "attempt 17", "started 16 times", "16 lost · 0 kept"), and a date, a year, a lift or a sleep-stage count beside the same words is not a finding. The recap cards keep their own rule for now; `reader_surface(..., constructed=True)` is the mode they would call. Number grounding against the dossier. The Panel renderer's spoken-word rules, run before staging rather than at render. A failure buys one corrective rewrite; a second failure stops the week. |

## The rubric, in one paragraph

Rank the week's candidate stories by **change**, then **a prediction tested**, then
**consequence**, **surprise** and **human interest**. Calibrate the tone to the data: an
encouraged week is reported as one. An **absence** is a story only when it is new this week
or the data shows a consequence, and it never leads two weeks running. Programmed training
volume is the programme being executed, not the subject's impatience. A thread may lead at
most two weeks running. A thread that hasn't moved in three installments is resolved or
retired by name. The coaches are characters with track records: who was right, who was
wrong, who changed their mind.

## Running it

```bash
# Rebuild weeks 0..N in order into a private staging dir (reads DDB, calls Bedrock, writes nothing to AWS)
python3 scripts/season_rebuild.py --through-week 4 --out <dir>
# One week, continuing from the ledger the previous week left in <dir>
python3 scripts/season_rebuild.py --weeks 5 --out <dir>
```

Publishing is a separate, owner-approved promote step. Staging never publishes.

## The audit gate (#4549)

No staged installment publishes without an adversarial raw-data audit. After staging, run the
`story-auditor` agent (`.claude/agents/story-auditor.md`) on the staging folder. It checks claims
against raw DynamoDB, not just the dossier, and writes `audit.json`. Then:

```bash
python3 scripts/season_promote.py --staging <dir>            # the plan + any AUDIT GATE refusals, nothing written
python3 scripts/season_promote.py --staging <dir> --apply    # exit 5 before any write unless the audit passes
```

`--apply` refuses when `audit.json` is missing, unreadable, not a JSON object, has a `blocking` list
that is absent, not a list or not empty, has a verdict other than `publishable`, falls under the
agent's floors (8 claims and 3 raw-verified per week), or is stale. Stale means the audit's
`staged_sha256` hash for any file that would publish (`wk{N}_chronicle.md`, `_episode.json`,
`_ledger.json`, `_dossier.json`) does not match the folder now. That ties the audit to the exact
content, so an audit of an earlier draft cannot pass a re-staged or repaired one. A timestamp
can't do that. `--audit-hashes` prints the map the auditor records.

## His answers also reach the front page (#4584)

Each answered question in a reply to the Monday email is written twice. The `STORYQA#W` row the
chronicle reads as `owner_voice` is unchanged. Then each answer is also written to the
owner-words store (`lambdas/content/owner_words.py`): one entry per answered question,
channel `email`, the question as its `prompt`, and the answer as he typed it. An unanswered
question writes nothing. An answer marked "off record" is stored and never served.

That store has one other door, the MCP tool `log_owner_note` (his Claude chat), and one way
out, `GET /api/owner_words`. The newest clean entry from the last seven days leads the
front page's `his_words` block, word for word. Any filter hit, an off-record marker, or a
vocabulary that could not be loaded holds the entry. A held entry is stored and never served.

The reply only lands if the address he replies from is in the parser's `ALLOWED_SENDERS`
(`cdk/stacks/operational_stack.py`). The questions are mailed to `EMAIL_RECIPIENT`, and a
reply from an address outside that list is dropped with a log line (#4546).

## The dead-men

`lambdas/operational/story_season_qa.py` (#4539) runs three checks inside the nightly
`life-platform-qa-smoke` invoke. A red one reaches the owner through `qa-smoke-failures`.

| Check | Reds when |
|---|---|
| `story_season:episode_or_hold` | A published week has no Panel episode 48 h after it published and no hold naming that week, or its hold is more than 7 days old. The hold is the public `pending` marker in `/panelcast/episodes.json`. A re-hold rewrites the marker's date, so the week's own overdue clock also counts. |
| `story_season:ledger_advanced` | A published week has no visible `LEDGER#{date}` row. The next installment would pick the season up from before that week. |
| `story_season:monday_questions` | Monday's `StoryQuestionsMonday` send (16:00 UTC) left no `STORYQ#W{n}` marker an hour later. |

A read that fails or comes back empty is a warn with no verdict, never a pass.

## What it does not do (yet)

- The weekly `wednesday-chronicle` and `coach-panel-podcast` lambdas still run their own
  prompts. Moving them onto the desk is #4535 / #4536. The Panel half waits on #4514
  (PR #4522) so two lanes don't edit one file.
- **The audit gate covers `season_promote.py` only.** The live weekly path publishes with no
  raw-data audit. `wednesday-chronicle` stores a draft, and `chronicle-approve` publishes it on
  the approve click or through its daily stale-draft sweep. A published week then async-invokes
  `coach-panel-podcast`, which publishes the episode. Running the same audit before the approval
  email and attaching its verdict is the live-path follow-up #4549 names.
- Count-claim predictions are still graded by slope upstream (#4541). The dossier carries that
  caveat to the writers.
