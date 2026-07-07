# HANDOVER — ARCH-01: the shared layer is retired (#781/ADR-131) + #791/#792 closed — 2026-07-06

> Instruction: "Read memory and handover to plan for next session and all the issues paid
> down from backlog in an efficient manner" → "I also approve you to do merges deploys etc."
> Plan chose #781 first because it shrinks/retires downstream work (#791, #792).

## What shipped (PR #833, merged + deployed + live-verified)

**#781 (ARCH-01, effort L) — one code-distribution channel.** The three channels
(full-tree CDK asset shadowing the pinned layer · hand-curated `build_layer.sh`
allowlist · per-script partial zips) collapsed into ONE: the staged full-tree bundle
from the new **`deploy/build_bundle.py`** (lambdas/ tree + `food_vocabulary.json` at
root; the MCP shape adds `mcp_server.py` + `mcp/`). Every path stages through it:

- **CDK**: `lambda_helpers.staged_tree_asset()`; layer resource + `SHARED_LAYER_VERSION`
  deleted (old versions ≤v118 stay published, RETAIN, unreferenced); garth/pillow
  dependency layers kept.
- **`deploy_lambda.sh`**: always full-bundle — the single-file-strips-siblings class is
  dead; MCP no longer rejected (mcp-shaped bundle automatic).
- **NEW `deploy_fleet.sh`**: shared-module change → one zip → S3 → every function, with a
  live-handler-resolves-in-bundle guard (protects e.g. the us-east-1 email-subscriber).
- **`deploy_site_api.sh`**: same bundle, layer-attach block gone.
- **CI**: layer checks inverted to ONE invariant — **zero functions reference
  `life-platform-shared-utils`** (plan job + `test_i2_shared_layer_retired` +
  session_postflight + drift_sentinel). Any changed `lambdas/` file with no per-function
  mapping → automatic fleet deploy (closes the silent unmapped-helper gap). CI's MCP step
  had been shipping WITHOUT `reading/` (the known boot-break trap) — now ships the full
  bundle. `cdk_only` import-skips removed.

**Deployed**: all 8 stacks (consumers first, Core last) + `deploy_site_api.sh`.
**Verified live**: zero shared-utils references fleet-wide · MCP boots (401 = healthy) ·
site-api 200 on /api/status · qa-smoke 0 failed · hevy-restamp's zip (previously
v115-layer-dependent) now carries all 206 modules + vocab.

**#791 (FABLE-01) closed by scope-down**: the weekly sentinel already runs (remediation
workflow, Mondays) feeding the one curated report; #781 retired its layer lens; the missing
**doc-literals lens** shipped (sentinel `check_doc_literals`: live CloudWatch alarm count vs
`PLATFORM_FACTS` — the R22 110-vs-122 gap now self-reports weekly). **#792 closed as
superseded** (I2 rewritten). Retired incident classes: March-9 stale-layer P2, #697
personal_baselines omission, #535/#538 site-api partial zips, MCP-missing-reading/.

## ⚠️ Main was briefly red post-merge — wrap commit fixes it
The doc-drift gate reds on `site_api_common.py` `test_count` (2455 → 2456; the sentinel
test added after the doc sync). The fix is in the wrap commit alongside this handover.

## New reflexes (CONVENTIONS §1 rewritten; deploy.md updated)
- Shared-module change → `bash deploy/deploy_fleet.sh` or `cdk deploy --all`. No layer
  bump, no build_layer.sh, no consumer list, no version pin.
- `restart_pipeline.py` no longer bumps/builds a layer (step 4 is just cdk deploy).
- A regression re-attaching the old layer reds CI (plan job) and pytest I2.

## 🔴 #780 (SEC-02) — api-key ROTATED; Function URL rotation PARKED for a laptop window
Escalated this session. **api-key: rotated + verified** (old bearer→401, new→200; claude.ai
re-auths transparently; Matthew confirmed the local bridge is dead so nothing else breaks).
**But while verifying I proved SEC-01 did NOT close the exposure:** `/authorize` issues a code
to any anonymous caller and the attacker brings their own PKCE pair, so anonymous
`/authorize→/token→tools/list` = 200 / 143 tools (ran against prod). The only gate is the
Function URL secrecy — and that URL is in **18 tracked files / 44 commits of the PUBLIC repo**.
So all private health data is readable by anyone browsing GitHub, RIGHT NOW.
**Containment = rotate the Function URL (delete+recreate → new url-id) + scrub it + never commit.**
There is NO non-breaking interim fix (any gate that stops the anonymous dance stops claude.ai too).
It breaks Matthew's claude.ai connector until he pastes the new URL in — **he was on his phone, so
it's parked for a laptop window.** Full reproduction + the exact rotation runbook + the (c) scrub
list are in PRIVATE memory `security-r22-mcp-token-exposure` (NOT here — repo is public).
**Next action when Matthew is at a laptop: run the runbook, hand him the new URL, verify his
access, then scrub + commit.** Also worth filing: the URL-possession model is the root weakness
(SEC-01's PKCE is theater without a real per-request gate or a CI "never commit the URL" rule).
- **#788/#789** (static-render /now/ + friends-family surface) — batch as one opus site
  session, optionally + #804 (Next, same pattern). **#790** COST-01 (alarm + secrets
  consolidation; pairs with #808/#809 from Next).
- Older pending Matthew decisions: #417 re-stamp timing/format · LifePlatformIngestion/HAE
  deploy call (session-17) · #740 essay edit pass.
- `docs/reviews/REVIEW_BUNDLE_2026-07-06.md` still untracked in the working tree
  (generated scratch — commit or delete, Matthew's call).

Prior session's handover archived at `handovers/HANDOVER_2026-07-06_R22-build-paydown.md`.
