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
| **Dossier** | `lambdas/content/story_dossier.py` | Every figure a writer may use, computed in code for exactly the week's dates. Plan targets come from the plan root (`experiment.plan_facts`), never `PROFILE#v1` (#4540). Each batch-exported source has a watermark, so a date past it reads as *not yet exported*, never as a behaviour. Every training session says whether it was a programmed routine and how it scored against the prescription. Vice names never enter; journal entries are counted, never read. |
| **Ledger** | `lambdas/content/story_ledger.py` | One `LEDGER#{date}` row per published installment: threads (open / advanced / resolved / retired), the Panel's bets and their results, who was featured, the leads and beats used, and an arc note per character. Read through `singleton_visible`, so a reset's tombstones can never become last week's memory. |
| **Desk** | `lambdas/content/story_desk.py` | One structured call returns the week's **story budget**: lead, secondary stories, omissions with reasons, a tone calibrated to the data, the coach to feature, last week's bet scored and the next one set, and an action for every open thread. The rubric is written in the module. Code then validates what a schema can't express. |
| **Writers** | `lambdas/content/story_writers.py` | Elena's long-form post and the Panel script, both written from the same budget, dossier and ledger, plus the previous installment. |
| **Checks** | `lambdas/content/story_checks.py` | Four checks. Completeness: `stop_reason`, the last sentence, the footer. The story door: no cycle or attempt counts, no machinery words, no export lag told as silence. Number grounding against the dossier. The Panel renderer's spoken-word rules, run before staging rather than at render. A failure buys one corrective rewrite; a second failure stops the week. |

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

## What it does not do (yet)

- The weekly `wednesday-chronicle` and `coach-panel-podcast` lambdas still run their own
  prompts. Moving them onto the desk is #4535 / #4536. The Panel half waits on #4514
  (PR #4522) so two lanes don't edit one file.
- The dead-men (a published week with no episode in 48h, a hold older than 7 days) are #4539.
- Count-claim predictions are still graded by slope upstream (#4541). The dossier carries that
  caveat to the writers.
