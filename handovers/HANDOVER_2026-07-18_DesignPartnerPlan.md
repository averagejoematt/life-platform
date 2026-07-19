# HANDOVER — Design partner pipeline: Claude Design ⇄ Claude Code + UI/UX v5.1 backlog — 2026-07-18 (late evening, plan-only)

> Instruction thread: "/plan — this session is plan-only (a parallel session owns execution);
> averagejoematt.com needs generally better UI/UX — visuals, art, animations, avatars, colors,
> deliberate user journeys — with a litmus test that it never reads as an 'obvious AI-built
> website / AI slop / looks like all other Claude websites.' Set up Claude Design
> (claude.ai/design) as a configured design partner to Claude Code — a pipeline/skill so I can
> ask Design for upgraded elements, partial or full redesigns, and send them to Code."

## What this session did (NO code shipped — plan + filed backlog only)

- **Discovery that shapes everything:** Claude Code has a native **`DesignSync` tool** (reads/
  writes claude.ai/design design-system projects: `list_projects/list_files/get_file/
  finalize_plan/write_files/delete_files`, incremental, permission-gated, base64 binary uploads
  so fonts ship). Zero repo wiring exists. Matthew already owns a design project —
  **"AverageJoeMatt Design System"** (2026-06-01) — but it's a **stale pre-v4 snapshot** (old IA
  slugs, journal-amber/signal-green palette, JSX ui_kits). Its `design_handoff_frontpage_rework/`
  folder is the proven one-shot precedent for the design→code round trip (the 4-variation
  Live-page rework). Plan: create a NEW "AverageJoeMatt Design System v5" project; old = archive.
- **The pipeline (plan artifact `~/.claude/plans/hashed-spinning-gem.md`):**
  `scripts/design_sync_bundle.py` exports the real v5 system (tokens.css §1–13, 5 woff2, 22-icon
  sprite, component previews w/ `@dsCard` markers, chart/confidence-grammar galleries, reference
  pages) → `/design-sync` pushes incrementally → Matthew designs against real tokens under a
  synced `BRIEF.md` contract (north-star distillation + hard constraints + **the Slop Litmus**,
  the ~10-point "not an obvious AI site" checklist) → proposals land in `proposals/<slug>/`
  (HTML/CSS on synced tokens + NOTES.md + token-deltas.css) → `/design-implement <slug>` pulls
  to a worktree, site conventions, litmus gate, render-QA 1280+390, PR. "Design proposes, Code
  ships" (ADR-106 posture); taste swings still pause for Matthew's screenshot pick.
- **Filed (label `review:design-2026-07-18`, all verified via `gh issue view`):**
  - **Epic #1460** — the pipeline (area:claude-workflow): #1462 bundle builder (Now, opus) ·
    #1463 `/design-sync` (Now, sonnet) · #1464 DESIGN_PARTNER_BRIEF + Slop Litmus v1 (Now,
    fable) · #1465 `/design-implement` (Now, opus) · #1466 litmus → DESIGN_SYSTEM_V5 § +
    advisory visual_ai_qa lens (Next) · #1467 reference-capture refresh (Next).
  - **Epic #1461** — deliberate journeys + visual identity v5.1 (area:site-ux,
    wedge:build-in-public): #1468 four-audience journey map + loop-forward CTAs (Now) · #1469
    home first-screen choreography = the round-trip PILOT (Now, PM-override recorded) · #1470
    tonality/paper-elevation pass · #1471 art layer for narrative surfaces (links #1379/#1114,
    not duplicates) · #1472 micro-interaction grammar v2 · #1473 utility-page de-templating ·
    #1474 CLS skeleton paydown (links #1435) · #1475 wayfinding (Later).

## Verified

- All 16 issues re-read post-create; milestones/labels spot-checked via
  `gh issue list --label review:design-2026-07-18`. Dedup swept against all 300 open issues —
  adjacents linked in bodies (#1080/#1114/#1372/#1379/#1381/#1429/#1435), none duplicated.
- **Zero working-tree writes** by this session (plan-only invariant held; parallel session owned
  the tree all evening).

## Gotchas hit

- **Shared tree carries the parallel session's in-flight fix**: `lambdas/web/site_api_social.py`
  has an uncommitted 7+/3− diff making the `evening_ritual`/`private_intake` write pks static
  literals so the orphan-partition gate can resolve the writer. **Do not stage, stash, or revert
  it** — it belongs to the executing session. This wrap commit stages only handovers/ + CLAUDE.md.
- The old design project must NOT be synced over in place — v5 cards mixed with the 2026-06
  palette would mislead design sessions. New-project decision is recorded in #1463's body.

**Build beat:** none — plan-only session; nothing merged or deployed.
**Docs:** none needed — no shipped surfaces; backlog + plan artifact only (doc work is inside the
stories themselves: #1464/#1466 own the DESIGN_SYSTEM_V5/brief additions).
**Main:** red — `test_no_unlisted_orphan_read_partitions`: site-API reads `SOURCE#evening_ritual`
with no statically-resolvable writer (entered with the #1405/#1403 merges, run 29666976126 at
4e886736); the parallel session's fix is already in the working tree (see gotcha above), lands
with its next push — not this session's to ship.

## Next picks

1. **#1462 → #1463 → #1464** (all Now, one session's worth): build the bundle, first sync to the
   new v5 project, ship the brief + litmus. Then prove the loop end-to-end on **#1469** (home
   choreography pilot — 2–3 Design variations, Matthew picks from screenshots).
2. Unchanged attended queue from prior sessions: prereg publish, Sunday restart_verify (cycle 8
   genesis 2026-07-19), #1319 approval-gate posture, #1114 portrait pick.
3. Memory topic: `project_design_pipeline_2026_07_18` (indexed under Active Work).
