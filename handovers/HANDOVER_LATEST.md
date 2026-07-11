# HANDOVER — "Work the 6 that don't need me" became 8 shipped: MCP auth fully hardened (A+B), first DR restore drill, the Relationships pillar's social half wired — 2026-07-10

> Instruction (evolving): "read handover and memory so we can talk about what to work on"
> → "can you work on the 6 things that don't need me, i approve all merges and deploys"
> → (mid-session) "893, i am fine to do an actual authorize step if it's the right thing.
> And yes resolve that 902 bug" → "yes wrap". Standing authorization: all merges + deploys
> (in-session words unblock, per `feedback_prod_deploy_authorization`).

## The shape of the session

Picked up the "18 remaining issues" board and separated the genuinely-unblocked from the
Matthew-gated. Fanned out 3 worktree agents on the clean ones, took the delicate ones
(live AWS, security design) in the foreground. Two forks surfaced mid-session and Matthew
answered both live: **#893 option B** (yes, do a real /authorize approval step) and the
**#902 adjacent bug** (yes, wire the missing social signal). Net: **8 items shipped +
deployed + verified**, 1 deferred with receipts, 1 IAM apply executed by Matthew.

The recurring friction was **visibility**: Matthew kept hitting ESC to type "status,"
which *cancels the in-flight tool call* (that's why several live MCP reads showed as
"rejected" — not denials). Fix going forward: post a short heartbeat after each discrete
step so he never has to interrupt to know it's progressing. Saved as feedback memory.

## What shipped (all MERGED + DEPLOYED + VERIFIED)

- **#902 → PR #905** — revived `social_mood_correlation`'s mood half. Root cause was
  deeper than the issue: `merge_journal_view` (#890) never set `mood_avg` at all. Scale
  map `enriched_mood` 1–5 → 0–10 via `(m-1)/4*10`. Deployed `character-sheet-compute`,
  smoke-verified (200, clean).
- **#904 → PR #907** — `/gear/` page (first passive-monetization surface): every device
  from `source_registry.py`, cross-links to `/method/verify/`, **placeholder affiliate
  slots** (`data-affiliate="pending"` + FTC disclosure) that Matthew fills in the `GEAR`
  dict in `scripts/v4_build_gear.py`. Render-QA passed both themes. Site auto-deployed.
- **#755 → PR #908** — **first verifiably-exercised DDB PITR restore** (+ S3 versioned
  restore), both into isolated targets (`life-platform-dr-drill` table, `backups/dr-drill/`
  prefix), spot-checked against prod, torn down. Fixed the DR doc's stale "snapshot the
  layer" step (shared-utils layer retired #781). Prior to this only S3 versioning had ever
  been exercised (via the 2026-03-16 accident).
- **#893-A → PR #909** — `/token` mints a short-lived (24h), **revocable** session bearer
  (`lps_…`, DDB-backed `core.session_token_issue/valid/revoke`) instead of the permanent
  key-derived Desktop bearer. `_validate_bearer` accepts the static Desktop bearer OR a
  live session bearer; fail-closed. Deployed `life-platform-mcp`, **live-verified** (unauth
  401, static bearer 200, full OAuth flow → `lps_` token → 200).
- **#893-B → PR #912** — `/authorize` is no longer auto-approve: a **passcode consent
  form** (passcode = `HMAC(api_key,"life-platform-authorize-v1")`, derived so it's entered
  without exposing the key) + a signed **30-day remembered-browser cookie** (payload-2.0
  `cookies` array). URL possession alone now yields nothing. Deployed + **8/8 live checks**
  (form shown, wrong passcode 401, correct → code+cookie, session token works, cookie
  fast-path 302). Desktop path untouched throughout.
- **#910 → PR #911** — the #902 adjacent bug: `character_engine.compute_relationships_raw`
  read numeric `social_connection_score`/`enriched_social_connection` that *nothing writes*;
  the enrichment lambda emits categorical `enriched_social_quality`. Bridge maps
  alone/surface/meaningful/deep → 0/3.33/6.67/10 at read-time (works on historical data),
  averaged across a day's entries. Lights up the Relationships pillar's second component.
  Deployed `character-sheet-compute`, smoke-verified.
- **#903 → PR #906 (code) + live IAM apply EXECUTED by Matthew** — shed `IAMReadOnly` +
  `BedrockVisionQA` from the CI deploy role and narrowed CloudWatch to `DescribeAlarms`.
  Matthew ran `put-role-policy` + `verify_oidc_iam --strict` → **CLEAN (9 targets)**. The
  behavioral proof (no deploy-stage AccessDenied) comes on the next CI deploy; rollback
  snapshot saved.
- **Filed:** #910 (social bridge, done same session) + **#916** (Later — #893-B follow-up:
  refresh_token grant / cookie-TTL tuning, gated on observed passcode-re-entry friction).

## Deploys + verification

`character-sheet-compute` (×2: #905 then #911) · `life-platform-mcp` (×2: #893-A then
#893-B) — all via `deploy_lambda.sh` full-tree bundle (rollback artifacts saved). Live:
MCP 8/8 auth checks green, static Desktop bearer intact, session flow + passcode gate +
cookie fast-path all working. DR drill: restored item matched prod exactly. #906: live
role verified CLEAN by the strict verifier. Site: gear page auto-deployed green. Every
PR merged to main; `main == live` for the touched surfaces.

## Gotchas (new this session)

- **ESC to ask "status" cancels the in-flight tool call.** That's why live MCP reads
  showed as "rejected." Not denials — interruptions. Heartbeat after each step instead.
- **The auto-mode classifier correctly firewalls two protected-scope actions** even under
  "approve all merges and deploys": (1) live `iam:put-role-policy` on the deploy role, (2)
  a verify script that *prints* the key-derived passcode to the transcript. Both were
  handed to Matthew to run in his own shell (`!`/terminal) — "approve deploys" does not
  extend to IAM mutation or credential materialization. Right guardrail; hand off, don't
  work around.
- **`core.py`'s `secrets` is the boto3 SecretsManager client, not stdlib** — used
  `uuid.uuid4().hex` (the codebase's opaque-token idiom) for token randomness to avoid the
  name collision.
- **ruff bandit S105 fires on `SESSION_TOKEN_PREFIX = "lps_"`** (a token *label*, not a
  secret) in `mcp/core.py` — `mcp/handler.py` is S105-exempt in pyproject but core.py
  isn't; used a surgical `# noqa: S105` rather than blanket-exempting the file. CI's
  blocking ruff enforces S-codes (`select=[...,"S"]`, no `|| true`); its blocking flake8
  only selects `E9,F63,F7,F82` (F401 is informational).
- **Terminal line-wrap mangles pasted multi-line commands** — the passcode one-liner broke
  on `--region\n  us-west-2`; give copy-paste commands as a single unwrapped line.
- **Lambda Function URLs are payload format 2.0** — request cookies arrive in
  `event["cookies"]` (+ Cookie header); responses set cookies via the top-level `cookies`
  array, NOT a `Set-Cookie` header. Got this right in #893-B.

**Build beat:** 2026-07-10-mcp-auth-hardened

## Residual — waiting on Matthew (all optional / low-priority)

1. **claude.ai reconnect** — on its next token refresh (≤24h) the connector prompts for
   the passcode Matthew retrieved this session; he pastes it once per browser (~monthly via
   the cookie). Desktop needs nothing.
2. **#748 fulfillment story** — still gate-locked: needs ≥4 weeks of clean fulfillment data
   incl. a rough patch. #910 wired the social signal (a precondition); watch whether
   `enriched_social_quality` is actually populated on recent journal days before revisiting.
3. **#916** — #893-B refresh-friction follow-up; only act if the monthly passcode annoys.
4. **Still open from prior session:** PRE-13 privacy decisions, HN submission (#741), /verify/
   profile URLs, HAE straggler repoint, GitHub GC ticket (paused by Matthew).
5. **#902/#910 live effect** — spot-check a recent character-sheet compute for a non-None
   Relationships social component once journals carry `enriched_social_quality`.

## Watch

First natural CI deploy after the #906 shed (confirms no deploy-stage AccessDenied) ·
claude.ai's first post-#893-B refresh (passcode prompt appears as designed) · the
Relationships pillar's first real social signal on the next character-sheet compute ·
gear-page affiliate slots stay `pending` until Matthew signs up.

Prior session archived at `handovers/HANDOVER_2026-07-09_decision-sprint.md`.
