# Handover — Story Desk: the season rebuilt and the desk live (2026-10-01 → 10-03 ~05:30Z, Opus 5.5, owner on hand)

**Driving instruction:** the owner asked for an editorial continuity review of the chronicle and The Panel. That became: correct all of it, then build it so it stays correct (epic #4531). He then asked for a red team for compelling, fact-true and in the spirit of the experiment, and for a reply-by-email question loop. On 10-02 he approved: publish the season; mirror/2-10 material public; keep the prologue; drop "Dr."; wire the desk into the live lambdas; deploy; move `ELENA_PREQUEL_BRIEF.md` off-repo. Either `ALLOWED_SENDERS` address is fine for replies.

## Shipped: 4 PRs merged, all deployed (main green at 9f4b6947; 3efc4b8f is docs-only)
- **#4542** — the Story Desk (`lambdas/content/story_{dossier,ledger,desk,writers,checks,craft,questions,pipeline}.py`): dossier → season ledger → desk budget → writers → gates → code-rendered dek/scoreboard.
  - Wired into wednesday-chronicle (`STORY_DESK=on`, 900 s, `MAX_REWRITES=1`) and coach-panel-podcast (`emails/panelcast_desk.py`); chronicle-approve commits `LEDGER#`.
  - Reply desk: Monday 16:00Z `StoryQuestionsMonday` → SES Reply-To `insight@aws.mattsusername.com` → `insight-email-parser` → `STORYQA#W` rows → `owner_voice`.
  - Publishing requires a fresh audit (`.claude/agents/story-auditor.md`, `scripts/season_promote.py`). CDK `LifePlatformEmail` deployed by hand ✅.
- **#4565** — a question with a false premise never reaches the owner: absolute claims and ungrounded figures are dropped in code. The desk logs when it declines a date, and a rehearsal can name its week (`{"dry_run": true, "desk_week_end": "YYYY-MM-DD"}`).
- **#4566** — Bedrock refused `BUDGET_SCHEMA` ("compiled grammar is too large"). The desk now re-sends schema-less and checks the shape in code (`structured_json.schema_findings`). The attribution rubric follows his own account of the training volume.
- **#4567** — `docs/content/ELENA_PREQUEL_BRIEF.md` is now a pointer stub. The full brief is at `~/Documents/Claude/private/` (sha-verified copy). The old text is still in git history; that is the repo-privacy plan's scope.
- **Season published (owner act, 10-01/02):** prologue + weeks 1–4 rewritten with correction notes. The July "Night Before Everything" is unlisted. 5 Panel episodes are MP3 and in the feed. Panel `STATE#current`/`SHOW#memory` were reseeded for cycle 17. The recap was corrected.
- **CDK `LifePlatformOperational` (10-03):** the parser's `raw/inbound_email/*` read grant. SES `insight-capture` writes there, so without it every reply would have AccessDenied.

## Verified live
- Lambda dry run of the desk path, week 4: log `[#4535] story desk wrote week 4: 'The Instruments Push Back'`, then `Week 4 built (1108 words) — nothing stored`. The grammar fallback fired in-Lambda.
- Monday questions dry run: Week 5, 5 questions. One false premise was found ("never missed a protein day"; raw: 7/26 days ≥170 g, mean 147 g) → #4565 drops it (replayed on the live dossier).
- Deployed bundle sha 9f4b6947 (`build_info.json`) carries both fixes. wednesday-chronicle: 900 s, desk on; the Monday rule is ENABLED.

## Gotchas
- **A strict JSON schema can be too big for Bedrock**, and the refusal message does not mention `output_config`. `structured_json._schema_rejected` therefore misses it for the 19 #4555 sites. Recorded on #4276.
- **Off-Wednesday the desk declines** (the legacy window ends "yesterday", not a week end). Prove it with `desk_week_end`.
- **A Monday-rule `Lambda::Permission` makes Email OWNER-REQUIRED at CI's IAM gate.** Use `bash deploy/cdk_deploy.sh <Stack> -- --require-approval never` from main. Without that flag, a non-TTY run stops at the security confirmation.
- **Local direct-zip uploads to us-east-1 (email-subscriber, progress-viewer) drop every time from this network** (3/3). CI's deploy updates them fine; they are current.
- **`season_promote` writes chronicle rows directly**, bypassing approve's recall indexer. The nightly self-healed it (qa-smoke-warnings `recall:corpus_freshness`).

## Residual / next picks
- The week-4 on-air bet (recovery ≤60% by the morning of Oct 6) must be scored by name in week 5 — #4535 (the desk carries open bets; verify the 10-07 draft does).
- Wednesday 2026-10-07: the first live desk week. Read the draft's `desk_findings_json` before approving — #4535.
- `structured_json._schema_rejected` should also absorb the grammar refusal — #4276.
- "Dr." removal site-wide — #4564.
- Story Desk dead-men (incl. a missed Monday send) — #4539.
- Profile targets 1800/190 vs the plan's 1500/170 — #4540.
- Nightly pre-draft failed 10-03 ("not readable back") — #4568.
- Nutrition coach cites 166 g vs engine 146.5 g — #4569.

**Build beat:** 2026-10-02-the-story-gets-a-copy-desk
**Docs:** docs/content/STORY_DESK.md, docs/CONVENTIONS.md §9, docs/PROPORTIONALITY.md, docs/ARCHITECTURE.md (shipped in #4542); docs/content/ELENA_PREQUEL_BRIEF.md → stub (#4567); docs/alarm_citations.json (this wrap)
**Decisions:** none needed — the desk's rules live in docs/content/STORY_DESK.md and the PROPORTIONALITY row; no governance change
**Main:** green (9f4b6947)
**Incidents:** none — the grammar refusal and the false-premise question were caught in rehearsal, before any reader saw them
**Stash/hooks:** clean
**Closures:** none — no issues closed this session (every PR used Refs) · DoD: scanned=0 hits=0
**Backlog:** Now live at 14 (opus 14 startable); Later sweep — unverified, GitHub connection reset during the run
**Alarms:** 3 lit, all re-cited to their live causes — nightly-predraft-missing → #4568, qa-smoke-failures → #4569, qa-smoke-warnings → dated self-clearing (recall re-indexed after the season promote)
**CI warnings:** 6 — 1 Operational additive IAM diff (this session's parser grant; deployed by `cdk_deploy.sh LifePlatformOperational` this wrap); 5 playwright-skip notices (standing, owned by #3640, no action)
**Ledger:** Story Desk row added (in #4542)
