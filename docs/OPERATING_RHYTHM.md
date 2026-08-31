# YOUR OPERATING RHYTHM — the user-mode plan

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-08-31

Written to you, Matthew, for the era that starts September 1st: the platform is built,
and from here you are its user. This page is the whole plan on one screen — what you do
each day, what arrives each week, what Claude is for now, and the three dated points
where you get to decide whether any of it should change.

Nothing here is a commitment device or a streak. If a day goes sideways, the pipeline
keeps ingesting and tomorrow's brief still lands. The rhythm below is what makes the
data mean something; it is not another thing to be good at.

---

## The daily loop

**Wake, then the scale.** The weigh-in is the one input the day genuinely hangs on —
weight feeds the trend, the trend feeds the adaptive mode, and the mode is what your
coaches and the brief reason from. Skip it and everything downstream degrades quietly
rather than loudly: you will still get a brief, it will just be reasoning from a stale
body. It takes eleven seconds. Do it before anything else touches your attention.

**The brief, mid-morning.** The daily brief email lands at 10:00 AM Pacific — the
schedule is fixed in UTC, so it becomes 9:00 AM when the clocks change in November.
It is pre-computed before it sends, which means it reads what the platform actually
knew this morning, not what it could improvise at send time. Read it once. It is
allowed to be boring; a boring brief on a steady week is the honest output.

**One cockpit visit.** [averagejoematt.com/cockpit/](https://averagejoematt.com/cockpit/)
is the live view — today's numbers, the trend, what moved. One visit a day is enough,
and a day you do not want to look is data too. If you find yourself opening it eleven
times, that is a finding for the 30-day checkpoint, not a virtue.

**Text a coach when something is on your mind.** All ten coaches are live Telegram
contacts. There is no ritual to this and no right time: if you are unsure about a
session, a meal, a stretch of bad sleep, or you just want to think out loud, message
the one whose domain it is. They read the same data the brief does. A question you
would have sat on for a week is exactly what they are there for.

**Log food and workouts where you always have.** MacroFactor and Hevy, as normal. The
platform ingests them; you do not enter anything twice, and you do not open a dashboard
to make a number appear. If a source stops arriving, that is a bug — see below.

---

## The weekly rhythm

**Wednesday morning — the chronicle.** It publishes to the site and arrives by email:
the week, written up. This is the reflective surface; the brief is the operational one.

**Sunday morning — the weekly signal.** The pattern read across the week rather than
the day. Between the two of them you get one short view and one long view every week,
which is the whole intent.

**A session with the coaches, when you want one.** `/speak-to-coaches` for a
conversation, `/team-meeting` when you want them to work a question together. These are
on demand by design — cadence them and they become a chore you attend; leave them on
demand and they stay something you reach for.

**Alerts.** Real problems page you. Everything else accumulates into the triage email
that arrives Monday, Wednesday and Friday morning. If nothing pages you, nothing needs
you — that is the arrangement, and it only holds because paging was kept expensive.

---

## What Claude is for in September

The build phase is over. The posture changed with it, and the change is the point:

- **Sessions are bug-fix-only.** Something is broken, a session fixes it, the session
  ends. Opus or lower is the working model; Fable is held in reserve for incidents,
  not spent on routine fixes.
- **No feature filings without you asking for one.** Not "while we're in here", not
  "this would be quick". The Now queue drains through September; it does not grow.
- **When something looks wrong, describe the symptom — do not debug it.** "The brief
  said my sleep was zero last night" is a better bug report than a diagnosis, and it
  costs you thirty seconds instead of an evening. Symptom, date, screenshot if you have
  one. The session does the rest.
- **The measure of a good September session is that it was short.** A month of small
  fixes and a quiet backlog is the outcome we are aiming at, not a month of shipping.

If a feature idea arrives anyway — and it will — write it down and let it wait for the
next checkpoint. An idea that still matters in four weeks has earned a filing; most
will not, and that is the useful part.

---

## The three checkpoints

Dated, on the operating calendar, with the dead-man watching them. Each one is yours to
run — they are owner-attended because every question in them is a judgment call.

**October 1 — 30 days: is the rhythm holding?** Not "did you do it perfectly" but what
actually happened. Which surfaces did you open, which did you ignore, which coaches did
you text and which have not heard from you once? Ignored is information: a surface you
never open is a candidate for deletion, not for a redesign. This is also the first
window in which a feature may be reconsidered at all.

**October 31 — 60 days: what did it cost, and what did it do?** September closes in the
cost tracker; read the number next to a list of specific things the platform did for you
that month. Named things — a decision it changed, a problem it caught, a question it
answered. If the honest list is short, say so and write it down. A cost you cannot put a
return next to is the finding, and it is more useful than a comfortable answer.

**November 30 — 90 days: what gets built next?** By then you will have three months of
lived usage, which is the smallest sample that can tell "I need this" apart from "I
imagined I would need this". The roadmap comes out of that, not out of anything either
of us thinks today. Anything on your written-down list gets judged here against what you
actually did, and most of it will lose — that is the mechanism working.

---

## Checkpoint log

Append one line per checkpoint when you run it. The operating calendar's dead-man reads
the dates on these exact lines (`scripts/operating_calendar.py --due`), so the line is
the record: no line, no run.

Format: `- <N>-day checkpoint: YYYY-MM-DD — what you found, what you decided.`

_None run yet. First due 2026-10-01; the calendar reports these three as SCHEDULED, not
overdue, until then._
