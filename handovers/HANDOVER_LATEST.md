# HANDOVER — Voice + Studio plan: his own words at scale + the Luna diary studio — 2026-07-19 (night)

> Instruction thread: "put a plan together to get better feedback into the website content
> based on my core Claude conversations with my coach team… amplified without overshadowing
> the core science… more real and true than just AI garbage around data. I have just
> purchased the Luna Insta360… Claude interviews me, relaying questions and reacting in
> real time… if it's huge friction the novelty wears off — 'Claude let's do a vlog'…
> feedback loop for analysis — character scoring, challenges, hypotheses, a new experiment
> card reacting to a journal entry or video diary… the third wall of content."
> Explicit session shape: **plan-only, concurrent with another live session — all issues
> filed in GitHub, zero production work, zero tree writes beyond this wrap.**

## Outcome — 15 issues filed (2 epics + 11 stories + 2 cross-links), batch `review:voice-studio-2026-07-19`

**Epic #1563 "The Voice"** — Matthew's own words become a first-class reader surface.
Survey finding: the his-words-vs-machine affordance already exists (Elena byline, "In my
own words" tab, Third Wall two-voice render) — the bottleneck is VOLUME (one essay ever,
because essays are hand-authored raw HTML). Stories: #1566 essay generator
(`v4_build_journal.py`, Now) · #1567 `/journal-interview publish` interview→approved
public essay (Now) · #1568 opt-in verbatim journal pull-quotes, consent-per-line (Next) ·
#1569 widen the Third Wall to per-experiment/per-decision "his call" (Next) · #1570
public diary cards, gate:owner anonymity (Later).

**Epic #1564 "The Diary Studio"** — video diaries with Claude as the live interviewer.
THE decisive survey finding: the feedback loop Matthew asked for ALREADY EXISTS for
journal text (notion_lambda → journal_enrichment ~25 fields → flourishing PERMA →
character_sheet signals + journal_analyzer → `HYPO_CANDIDATE#` → hypothesis engine) — so
a video diary influencing character pillars and seeding experiment cards is "make the
transcript land as a Notion journal page (new Template 'Video Diary')", NOT a new
pipeline. Stories: #1571 `/vlog` mode + format library + Matthew-side studio kit (Now) ·
#1572 transcript landing path through the existing pipeline, channel-tagged (Now) · #1573
solo-recording transcription, local Whisper, gate:owner on video-to-S3 cost (Next) ·
#1574 coach reactions to diary entries on lab-notes (Next).

**Ritual layer under existing epic #1476** (body edited, tiers appended): #1575
`/team-meeting` weekly all-hands, auto-agenda from predictions/experiments/queues (Now) ·
#1576 `/interview` milestone deep interview — the March-2026 format made repeatable
(Next) · #1577 conversational capture → numeric signal (enrichment over check-ins/
reflections; the confirmed gap: they're qualitative-only today) (Next) · #1578
checkpoint triggers — deterministic conditions propose rituals via `get_capture_queues`
(Later). **#1388** commented (left OPEN): Epic S supersedes its capture half; AC-map
AC1→#1572, AC2→#1574, AC3/4→#1570.

## Verified / load-bearing facts recorded in the issues

- `uploads/` has a 30-day expiration lifecycle — durable diary artifacts go to
  `raw/matthew/diary/` (delete-protected), never uploads/.
- Notion stays journal SOT (dual-SOT rejected in #1476) — diary transcripts enter AS
  Notion pages; chat-interview sessions need no speech-to-text (the conversation IS the
  transcript); transcription (#1573) is only for solo recordings.
- Chronicle is NOT the vehicle (Elena's deep-background never-quote rule untouched);
  verbatim surfaces need only content-policy scan, composed prose inherits ADR-104.
- Insta360 Luna (Leica gimbal series, Pro/Ultra): standard MP4 out, subject tracking,
  ~4h battery — capture friction is power-on + one sentence to Claude.
- Issue-filer deviations (deliberate): one `area:*` label per issue (spec's secondary
  areas dropped); score lines filed in the spec's `T×W/effort` form — normalize if
  tercile queries need the standard form.

## Gates

**Build beat:** none — plan-only session; issues filed, nothing merged/deployed.
**Docs:** none needed — plan lives in GitHub issues per ADR-099; no repo surface changed
(doc checkers run green at wrap; `sync_doc_metadata --apply` deliberately NOT run
mid-flight of the concurrent tree-owning session).
**Decisions:** none needed — the one governance item (privacy-tier ADR for
quote-with-consent vs allude-without-quoting) is deliberately deferred INTO stories
#1568/#1483, which require it before shipping.
**Main:** green (1ebbb905, latest completed CI/CD run, success). HEAD ad6aae62 (the
concurrent session's #1438 tests-only merge) has Docs CI + surface-drift-gate green and
NO CI/CD run — Actions provably alive for the sha, so this reads as path-filtering, not
the #1544 silent-death class; flagged for the tree-owning session to confirm at its wrap.
**Incidents:** none.
**Stash/hooks:** clean — stash list empty, hook freshness 🟢.

## Residual / next picks

- Build order (Now tier): #1566 → #1567 (Voice), #1571 → #1572 (Studio), #1575
  (team-meeting) — #1572's dry-run entry is the end-to-end proof the loop closes.
- Matthew: test claude.ai voice mode + MCP tools on the phone — decides whether Claude
  literally speaks the /vlog interview or questions render on-screen (feeds #1571;
  not-work — owner phone test, outcome recorded into the #1571 studio kit).
- Matthew: add Notion Template select value "Video Diary" (coordinated inside #1572).
- Matthew: anonymity form for public diary cards (#1570, gate:owner) and video-to-S3
  storage cost opt-in (#1573, gate:owner).
- Standing items carried from the Day-2 drain handover (unactioned, don't let them age):
  #1544 owner legs + GH_POSTURE_TOKEN PAT + Dependabot alerts toggle + #1319 fork +
  #1350 sign + #1329 rotation + SNS click + Withings weigh-in (all tracked in
  `handovers/HANDOVER_2026-07-19_Day2-drain.md` decision menu; not-work — owner actions,
  re-listed here only so the pointer survives the archive).
- Zero-build tonight: `/journal-interview evening` with the Luna rolling already works
  end-to-end (chat is the transcript, close writes Notion, pipeline fires) — #1571 just
  compresses it to one sentence (not-work — usable now, no code owed).
