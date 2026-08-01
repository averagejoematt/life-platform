# HANDOVER — epic #1890's live-honesty defects: four shipped, and the deploy machinery that fought back — 2026-07-29/30 (Day-3/4 session)

> Instruction thread: continue from the #1653 handover's queue — **#1891 first** (a real
> public clinician named as a pillar owner on a live page, top of the stored rank), then
> the reset-leak cluster **#1895 → #1898 → #1894** as one wave. Explicitly NOT a Fable
> session (the banked `/fullreview` partial's delta review is due on/after 2026-08-02).
> Standing approval given in-session for merges and the deploy-gate approval.

## Shipped (all merged AND live-verified)

- **#1891** (PR **#1903**) — `/method/game/` no longer presents **Dr. Peter Attia**, a real
  non-consenting clinician, as a platform pillar owner. Now Dr. Amara Patel / Dr. Nathan
  Reeves. The durable half: **nothing coupled the coach roster to that page**, so they
  drifted a full cycle. Two fail-closed render-time guards now do — `assert_cast_current`
  (owner must be on `persona_registry.operational_personas()` + lead) and
  `assert_no_real_figures` (the page now passes `privacy_guard`, the same gate AI content
  passes — being *generated*, it had never passed it in its life).
- **#1895** (PR **#1910**) — the restart tombstone is honoured at every read, not
  per-surface. The reported leak was **one of four**; scanning for the class found three
  more, two of them live: `/api/ask`'s grounding read the same tombstoned snapshot **into
  the model's prompt**, and `/api/pillar_coupling` had **no phase filter at all** — 118 of
  122 `character_sheet` records tombstoned, yet the home constellation published 14 edges
  (`r=-0.87, n=47, p=0.0, significant`) computed over a wiped cycle.
- **#1898** (PR **#1912**) — the wiped pilot's **190 g** protein target reconciled to the
  sealed prereg's **170 g** across three configs plus a fourth copy the issue missed: a
  hardcoded `.get("target_grams", 190)` fallback in `character_engine.py` that only applies
  when the key is absent, so it failed silently. **Behaviour change, stated plainly:**
  `target_grams` is a scoring target, so protein now grades against the pre-registered plan.
- **#1894** (PR **#1913**) — a stale weigh-in can no longer be narrated as today's weight.
  Each weight fact now carries its own reading date + age + staleness flag, and a
  WEIGHT DATA RECENCY prompt rider forbids attaching a day label to it.
- **Doc re-verifies** (PRs **#1906**, **#1914**) — two post-merge repairs of the engine-doc
  source-drift gate. Both re-verified rather than date-bumped, and **both found real drift**.

## What the class-level framing bought

Every one of the four was filed as an instance. Treating each as a *class* found defects the
issues did not name:

| Issue | Reported | Actually found |
|---|---|---|
| #1895 | 1 leaking read | **4** (2 live, incl. one feeding the model) |
| #1898 | 3 stale literals | **4** (the 4th fails silently) |
| #1894 | 1 stale figure | + the `weight_change_4wk` label spanning 2 days |
| #1891 | 2 stale owners | + the missing roster↔page coupling |

**Why #1895's class kept recurring (this was the third time: #946 → #1085 → #1197).** The
invariant already existed — `singleton_visible`, whose own docstring says *"every
STATE#current-style singleton reader must apply this predicate"* — and
`test_singleton_tombstone_guards.py` was thorough. But **every guard in it was a
hand-written test for a reader someone remembered.** Nothing asserted the set was complete,
so when #1654 split `ledger`/`what_changed` into a new module it escaped silently. The fix
is a derived **closure test** that AST-scans `lambdas/web/` and fails on any unguarded
singleton read. It immediately found the `/api/ask` instance I had missed by reading.

## Gotchas hit (the expensive ones)

- **The site smoke's `exit 28` is NOT transient — I mislabelled it twice.** Both firings died
  at the *same* point: last `✅ /api/horizons`, then exit 28 exactly 10s later. The failing
  request is the next api_dep, **`/api/inference_receipt`** (~1.6s warm from a dev machine —
  **15× its neighbours' 0.11s**). It auto-rolled-back #1891 (putting a real clinician's name
  back on a live page for ~15 min) and later #1895's front-end. Filed **#1911**.
- **A docs-only merge during a rollback-recovery re-run silently strands the deploy.** The
  supersede check skips when `HEAD != origin/main`, justified by "the newer commit has its
  own queued run" — **false when the newer commit doesn't touch `site/**`** (path filter).
  Net: site stays on the rolled-back tree, both runs green, nothing alarms. I was one merge
  from triggering it. Filed **#1907**.
- **The engine-doc gate fired THREE times in two days** (#1900 yesterday, #1906, #1914) and
  each time re-verifying found *real* drift, not a stale date — today `PILLAR_COMPUTERS`
  had genuinely moved `character_engine.py:1684-1693 → :1690-1697` (the old range now lands
  on a comment header). **Two independent overnight traps cause it:** the squash commit is
  stamped at MERGE time (so a PR committed one day and merged the next post-dates its doc),
  and `sync_doc_metadata` stamps *today's* date (so the literal gate reds after midnight).
  **Prefer same-day commit+merge.** My #1914 miss was mine: I checked the coupling for
  #1894's files and never re-ran `--strict` after committing #1898.
- **A docs-only fix cannot clear the CI/CD gate it fixes** — `docs/**` isn't in the path
  filter, so `check_main_green.py` keeps reading the old failure until a manual
  `workflow_dispatch`, which costs a production approval. Filed **#1908**.
- **Both module size gates fired on #1894 and both were mine** (`qa_smoke_lambda` 1196/1200,
  `ai_expert_analyzer` 1972/2000 — any real addition crossed them). Grandfathering code I'd
  just written would be exactly what the gate exists to prevent, so I did the cohesive split
  it asks for: `operational/weight_truth_qa.py` (both weight-truth assessors together;
  qa_smoke 1196 → **1166**, real headroom rather than shaving to exactly 1200) and
  `intelligence/weight_recency.py` (analyzer 1972 → **1975**, +3 for a whole feature).
- **`privacy_guard` false-positives on research citations.** A live sweep of 13 surfaces
  found only `/api/challenges` and `/api/experiments`, both legitimate (`"Attia, Outlive;
  WHO guidelines"`). Extending the #1891 guard site-wide would break them — which is why it
  is scoped to the one page verified to contain no citations. Recorded on #1891.

## Three diagnoses I had to correct mid-flight

Each was wrong in a way that would have hardened into repo lore:

1. The `--strict` failure is **squash-merge re-dating**, not a timezone effect (both stamps
   were `-0700`; git evidence in #1906).
2. **#1898 does not conflict** with #1903 — the `protocols` block doesn't render on that page.
3. The smoke failure is **deterministic**, not transient — two identical timestamps apart.

## Verified

- **Full suite 8,124 passed / 0 failed**; both size gates green; `verify_bundle_boot.py`
  293 modules / 0 import failures; black/ruff clean; `check_doc_index.py --strict` green.
- **Live**: `/method/game/` → `owner Dr. Amara Patel` + `target grams 170`;
  `/api/pillar_coupling` → `honest_null: true, 0 edges`; `/api/what_changed` →
  `honest_null: true`; `privacy_guard` run over the **live bytes** of `/method/game/` → zero
  violations. All four S3 config copies re-synced and read back.
- Every guard is **negative-tested** — reverting each fix fails a distinct, precisely-named
  test. `#1894`'s fixtures derive from the analyzer's own clock, so they don't rot at midnight.
- **Coach tier cold-start (the #1653 residual): CLOSED.** 5 of the tier cold-started clean on
  the packaged bundle (`Init Duration: 679 ms`), zero `ImportModuleError`, and all 9 coaches
  resolve by name in live output — the `repo_config` slice-4 risk is clear in production.

**Build beat:** `2026-07-30-the-four-that-were-really-eleven`
**Docs:** `docs/engines/CHARACTER.md` re-verified twice (#1906 for the #1891 cast change,
#1914 for #1898's plan literal + the drifted `PILLAR_COMPUTERS` citation);
`docs/INCIDENT_LOG.md` +2 rows; `docs/TESTING.md` + `site_api_common.py` literals via doc-sync.
**Decisions:** none needed — four defect fixes and two guard extensions; no
architecture/data/deploy-posture choice was made that isn't already covered by ADR-099/103/104.
**Main:** green (`f557be45`) — full pipeline: Deploy → Smoke → visual+AI QA → I1/I2/I5, rollback skipped.
**Incidents:** 2 rows added — the 2026-07-29 and 2026-07-30 site auto-rollbacks, both
spurious (`exit 28` on `/api/inference_receipt`), the first re-exposing a real clinician's
name for ~15 min.
**Stash/hooks:** clean
**Closures:** #1891, #1895, #1898, #1894 commented with ADR-099 outcome verdicts
**Backlog:** Now live at 9 actionable; no promotion needed.

## Residual / next picks

1. **The deploy-machinery block — #1911, #1907, #1908.** Take these together next; they
   compound. #1911 has now auto-reverted correct merged work **twice**; #1907 means a recovery
   re-run can be silently stranded with every run green; #1908 is what made today's three
   doc-gate reds expensive. This is the highest-leverage remaining work in the session's view.
2. **#1909** — `/api/status` publicly reports "627% of budget, red" against a hardcoded
   `budget = 15.0` unconnected to the real $85/$115 ceiling, while the engine is correctly at
   tier 2. Verify a fix across the **2026-08-01** ceiling revert, not just today's numbers.
3. **#1904** — 5 off-roster fictional recommenders across 46 catalog entries, rendered live.
4. **#1905** — `/legacy` serves four real clinicians as *"voice shaped by"* attributions
   (noindex, unlinked). Framed as a three-way owner decision, not a bug; my recommendation is
   in the issue: leave it.
5. **#1892, #1893, #1896, #1897** — the remaining epic #1890 items (citation resolution, the
   calibration denominator, the two ai-integrity defects). **#1896** is still a plausible
   descendant of the #1653 live-Bedrock finding.
6. **Budget ceiling reverts $115 → $85 on 2026-08-01** — `not-work — a dated ADR-133
   auto-revert, no deploy needed.` Spend projects ~$103, i.e. **above** the reverted ceiling,
   so expect a tier jump that pauses reader-facing AI. Expected, not an incident.
7. **Fable delta review due on/after 2026-08-02** — `not-work — a scheduling constraint.` Do
   not let another model finish the banked `/fullreview` partial.
8. **Worktree prune** — `not-work — housekeeping, no issue warranted.` Still ~130, many stale
   and in-repo under `.claude/worktrees/`.
9. **Standing alarms (#1329 checklist)** — `not-work — checked, nothing outstanding.` No
   digest-routed freshness alarm or manual-rotation secret reminder is aging; next MCP-bridge
   key rotation is 2026-10-05.
10. **Owner-gated, unchanged** — `not-work — owner decisions, not session-startable:` OSS
    publish one-liner, vocal backfill, #1738 / #1571 / #1114, Dependabot.
