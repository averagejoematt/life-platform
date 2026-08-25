# Career artifact — submission kit (#741)

> **Status:** ready-to-paste copy only. Nothing here posts anything —
> submission is Matthew's explicit action per #741's own scope ("Matthew's
> action; explicit permission gates any posting"). This file exists so that
> when he decides to submit, the friction is "paste and click," not
> "draft from scratch." The essay prose itself is untouched and was
> approved as-is (#740).

**Live artifact:** [The Org Chart of One Human and N Agents](https://averagejoematt.com/journal/essays/org-chart-of-one/)
(canonical, `og:image`/Twitter/JSON-LD verified live) — the venue shortlist
below is from #740's approved plan; this file only adds the exact text for
each submission so nothing needs re-drafting under time pressure.

## 1. Hacker News (direct essay submission, not Show HN)

- **URL:** `https://averagejoematt.com/journal/essays/org-chart-of-one/`
- **Title (paste exactly — HN strips editorializing, so this is the essay's
  own title, unmodified):**
  `The Org Chart of One Human and N Agents`
- **Timing note:** submit early in the US morning (HN's front-page churn
  favors longer runway before the evening drop-off); avoid Friday/weekend.
- **No self-comment needed at submission** — the essay is receipts-first and
  doesn't need a "why I built this" preamble; if a top comment asks a
  clarifying question, the failure-reel section already has the honest
  answer inline.

## 2. LeadDev (written piece or CFP)

**One-line pitch (for the submission form's summary field):**

> How a solo engineer keeps a production AWS platform (104 Lambdas, 10 CDK stacks,
> a public website) running with AI agents as the entire engineering team —
> not by trusting the model more, but by building the org chart a model
> needs: shift handovers, deterministic merge gates, and a public failure
> log as the credibility layer.

**Angle framing (matches LeadDev's practitioner/engineering-leadership
audience):** lead with "coach the workflow, not the worker" — the gates,
handover ritual, and audit trail are process design, not prompt
engineering; that's the piece's management-of-process angle per the #740
venue shortlist.

## 3. The Pragmatic Engineer (guest/linked piece pitch)

**Cold-pitch opener (paste into the pitch email/DM):**

> Subject: A solo AI-agent-operated production platform, with the failures
> included
>
> I run a production AWS platform (Lambdas, CDK, a public website) largely
> through AI agent sessions rather than a team — and I've written up the org
> design that keeps it from falling over: deterministic merge gates (the
> gate is explicitly NOT an LLM), a public "wrong page" of caught AI errors,
> and a receipts-first failure reel. Full essay: [link]. Happy to expand any
> section for a guest piece if it's a fit.

## 4. AI Engineer Summit / World's Fair (20-min talk CFP)

**CFP abstract (150 words, matches the "org design for agents" 2026 track
theme per the #740 shortlist):**

> Most "AI agent org" talks are about capability — what the model can do.
> This one is about org design — what it takes to make an org of mortal,
> memory-wiped AI sessions *not fall over* in production. I run a live AWS
> platform (104 Lambdas, 10 CDK stacks, ~76 MCP tools) with one human and N
> Claude sessions as the entire engineering team. The talk walks through the
> five pieces that actually mattered: the handover ritual that survives
> total session amnesia, a deterministic (not LLM) merge gate that holds the
> only keys that can't be un-turned, budget-tier degradation instead of a
> surprise bill, and — the credibility section — a public log of every time
> the AI was wrong, because an org chart nobody audits is just vibes. Talk
> outline and full essay: [link].

**Speaker note:** the essay's existing "Outline (for the talk version)"
section (`docs/content/ESSAY_ORG_CHART_OF_ONE.md`) is already slide-shaped —
8 beats, one slide each — so the CFP abstract above maps directly onto it;
no separate outline needed if accepted.

## Recording the outcome (closes the #741 measurement loop)

There is currently no place that records *which* venue Matthew actually
submitted to, or whether it was accepted — only organic referrer travel is
tracked (`lambdas/operational/traffic_digest_lambda.py`'s Travel watch
section, `WATCHED_PAGES`). Until a submission is logged somewhere, "one
acceptance" has no mechanical way to be checked off. When a submission
happens, the simplest durable record is a dated line appended here:

```
### Submission log
- 2026-MM-DD — Hacker News — https://news.ycombinator.com/item?id=NNNNNNN — <status>
- 2026-MM-DD — LeadDev — <submission confirmation link or "submitted, no confirmation URL"> — <status>
```

No lambda/DB change is proposed for this — a hand-appended line in a public
markdown file is proportionate to "did Matthew submit, and what happened,"
and avoids adding new machinery (ADR-103 posture: this is a portfolio-level
concern, not load-bearing infrastructure) for an event that happens at most
a handful of times total.
