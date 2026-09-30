# deploy/archive/onetime/

Completed one-time deploy scripts + dead reference files. Do not delete — kept as a
record of what was run and when (`deploy/README.md` "Archive Policy"). Entries below
predate this index; only the dated batch each file's own move is recorded going forward.

## 2026-09-27 (#4258 — the harness-audit onetime-scripts sweep)

The prior mover, `archive_onetime_scripts.sh`, hardcoded its batches by name and had not
run since 2026-03 (v3.7.12) — new one-off scripts kept landing in `deploy/` uncaught. This
batch was found instead by a repo-wide zero-reference sweep: for each candidate,
`git grep -l <basename> -- . ':(exclude)deploy/archive' ':(exclude)docs/reviews'`
returned only the file itself (or, for `MANIFEST.md`, only files that already described it
as deprecated). `archive_onetime_scripts.sh` itself is archived alongside them — its
hardcoded-batch method is superseded by this sweep, which is repeated ad hoc rather than
run on a fixed cadence.

| File | What it was | Why it's here |
|------|-------------|----------------|
| `canary_policy.json` | a proposed IAM canary policy document | zero references outside `docs/reviews/` |
| `hero_snippet_bs02.html` | a one-off hero-section HTML snippet draft | zero references outside `docs/reviews/` |
| `test_subscribe.sh` | a manual curl smoke script for the subscribe endpoint | zero references outside `docs/reviews/` |
| `capture_baseline.sh` | a one-off baseline-capture helper | zero references outside `docs/reviews/` |
| `download_barlow_condensed.sh` | a one-time font-download helper (Barlow Condensed) | zero references outside `docs/reviews/` |
| `create_hevy_secret.sh` | a one-time Secrets Manager setup script for the Hevy API key | zero references outside `docs/reviews/` |
| `rebaseline_milestone_ledger_1807.py` | #1807 one-time milestone-ledger rebaseline | zero references anywhere |
| `vet_plan_on_record_leadin.py` | a one-off plan-on-record leadin vetting script | zero references anywhere |
| `backfill_2643_eightsleep_absence.py` | #2643 one-time Eight Sleep absence backfill | zero references anywhere |
| `backfill_eightsleep_stage_pct.py` | a one-time Eight Sleep stage-percentage backfill | zero references anywhere |
| `build_recap_posting_pack.py` | a one-off recap social-posting pack builder | zero references anywhere |
| `generate_rss_pre_v4_chronicle.py` (was `deploy/generate_rss.py`) | the pre-v4 RSS generator, reading the old `site/journal/posts/*` path | superseded by `scripts/v4_build_rss.py` (wired into `sync_site_to_s3.sh`); renamed on archive to avoid colliding with the older `generate_rss.py` snapshot already here |
| `MANIFEST.md` (was `deploy/MANIFEST.md`) | the pre-#1322 Lambda→handler→zip inventory | self-declared deprecated since 2026-02-28; superseded by `docs/ARCHITECTURE.md` + `ci/lambda_map.json` + `.claude/skills/deploy/SKILL.md` (`deploy/README.md` "Lambda inventory") |
| `archive_onetime_scripts.sh` (was `deploy/archive_onetime_scripts.sh`) | the hardcoded-batch mover, last run 2026-03 (v3.7.12) | superseded by the repo-wide sweep this index describes |
