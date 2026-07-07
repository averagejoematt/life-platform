# HANDOVER — R22 build & backlog paydown: 7 Now-milestone issues shipped — 2026-07-06

> Instruction: "start building and paying down our backlog" → "do #779/#780 first out-of-band"
> → "I approve edits, merges, and deploys this session" → "do your next picks and then once
> deployed write documentation and handover so I can clear."

## What shipped (7 issues, all off the Now milestone)

| # | Ref | What | State |
|---|-----|------|-------|
| **#779** | SEC-01 | MCP `/token` unauth exposure — real OAuth 2.1: `/authorize` issues single-use PKCE-bound codes (DDB, 10-min TTL, redirect allowlist); `/token` only exchanges a server-issued code, PKCE-verified | **deployed (cdk LifePlatformMcp) + live-verified** |
| **#782** | DEBT-02 | `personal_baselines.py` added to `build_layer.sh` **and** `lambda_map.json` `shared_layer.modules` — #697 recurrence closed structurally | merged (preventive; lands on next layer rebuild) |
| **#783** | BUG-01 | `latest_weight` given avatar_weight's 14d→30d fallback so the ADR-104 grounding gate covers weight during routine weigh-in gaps | **deployed (cdk LifePlatformCompute) + live-verified** |
| **#784** | CLAUDE-01 | Removed blanket `Bash(*)`; committed `.claude/settings.json` `ask`-rules for git push / gh pr merge / cdk deploy / lambda update / s3 sync·cp·rm / secret+SSM writes / deploy scripts / `--no-verify` / pre-commit disable | merged |
| **#785** | CLAUDE-02 | `black --check` + `ruff` folded into the git pre-commit hook (`scripts/install_hooks.sh`), CI-parity, fail-open | merged + verified (blocks a bad staged .py) |
| **#786** | CONTENT-01 | Recap "where we are now" stamped with its own as-of week/date + "N weeks ago" | **deployed (site) + live-verified (build 7d73cf3a)** |
| **#787** | CONTENT-02 | Each coach's read stamped with its own `generated_at` date — staggered-regen vitals no longer read as one contradictory "today" | **deployed (site) + live-verified** |

PRs: **#826 → #827 → #828** (SEC-01, three rounds), **#829** (#782+#783), **#830** (#784+#785), **#831** (#786+#787).

## ⚠️ STILL OPEN — #780 (SEC-02), needs Matthew's call
#779 closed the *minting* path; #780 is the residual-risk closer (a bearer that could have leaked
while the hole was open stays valid until the api_key rotates). It's the one item that can disrupt
Matthew's own claude.ai access, so it was deliberately **not** done. Three parts, in order:
1. **Rotate `life-platform/mcp-api-key`** — invalidates the leaked deterministic bearer; claude.ai
   re-auths transparently through the now-hardened flow. **Risk:** breaks the legacy **local Claude
   Desktop bridge** (`handle_bridge_invoke`, raw `x-api-key`) *if still used*. **OPEN QUESTION for
   Matthew: do you still use the local bridge?** If not, this half is safe to do now.
2. **Rotate the Function URL** — removes the known committed endpoint; **breaks the claude.ai
   connector until Matthew re-adds the new URL.** Schedule for a window he can immediately reconnect.
3. **Stop committing the URL** — redact from `cdk/stacks/mcp_stack.py`, `operational_stack.py`,
   `cdk.json`, docs, `tests/test_integration_aws.py`. Cosmetic without (2) — git history still leaks it.

Full detail + the reproduction chain live in **private** operator memory
`security-r22-mcp-token-exposure` (NOT in the repo — it's public).

## New guardrails now in effect (from #784/#785)
- **Deploy/merge/push now prompt** instead of running silently. The `.claude/settings.json` `ask`
  rules become fully durable from **next session** (settings-watcher only reloads a brand-new
  settings.json on session start / `/hooks`); the `Bash(*)` removal in settings.local.json is
  already live this session.
- **Pre-commit format gate**: `bash scripts/install_hooks.sh` once per clone installs black+ruff.
  It fail-opens if the tools are missing. `--no-verify` now prompts (it's in the `ask` list).

## Gotchas learned this session (durable → also in memory)
- **Green unit tests missed two LIVE-only bugs in SEC-01** — the MCP role's `DeleteItem` is
  deliberately scoped (LeadingKeys) away from the OAuth partition, and `consumed` is a DynamoDB
  reserved word. **Validate a DDB-shaped change against real DynamoDB (admin creds) before trusting
  the FakeDdb-backed suite.** Consume the OAuth code via conditional `UpdateItem`, never DeleteItem.
- **MCP deploy = `cdk LifePlatformMcp`** (not `deploy_mcp_split.sh`). Compute = `cdk LifePlatformCompute`
  (shared asset ripples ~15 AI lambdas; same-hash-for-all confirms one code delta). Site = `bash
  deploy/sync_site_to_s3.sh` (content-hashed modules; verify the served hashed URL carries the change).
- **Both #786/#787 were front-end only** — the APIs already returned the dates; nothing surfaced them.

## Next-session picks (remaining Now)
- **#780** rotation (once Matthew answers the local-bridge question).
- **#781** ARCH-01 — collapse the three shared-code distribution channels (the layer-drift root cause). The big one.
- **#788/#789** UX (static-render `/now/`, "is he okay this week?" surface) · **#790** COST-01 (June breached $75) · **#791** FABLE-01 (weekly drift-reconciler agent).

Prior session's handover archived at `handovers/HANDOVER_2026-07-06_R22-review.md`.
