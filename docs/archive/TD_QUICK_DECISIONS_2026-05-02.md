# Quick Decisions — TD-12, TD-14, TD-17

**Status:** Decision recommendations, ready for Matthew confirmation
**Source:** `handovers/HANDOVER_v6.8.1.md`

These three TD items are decisions, not engineering. Each gets a recommendation and a rationale. Matthew picks; Claude Code (or a future small task) executes the choice.

---

## TD-12 [LOW] — Todoist phantom no-op invocations every 4hr

### Problem

Todoist ingestion Lambda runs every 4 hours via cron, but has a no-op gate that returns early if no changes since last run. Net effect: 6 invocations/day where 5 do nothing. Cost is trivial; signal-to-noise in CloudWatch is annoying.

### Options

**A. Reduce cron schedule to daily (e.g. 6am PT)**
- Pro: simplest. One-line change to EventBridge schedule. Drops to 1 invocation/day. Existing Lambda code unchanged.
- Con: latency between Todoist updates and DDB freshness can be up to 24h. For a personal accountability platform, this is probably fine — Matthew isn't refreshing a dashboard hoping his task additions appear in real-time.

**B. Switch to Todoist webhooks**
- Pro: real-time. Best correctness. Best end-state.
- Con: requires standing up a webhook receiver Lambda + Function URL, validating Todoist's webhook signing, handling out-of-order delivery. Probably 4–6 hours of work to do correctly. Adds a moving part.

**C. Add EventBridge throttle / dynamic schedule**
- Pro: keeps schedule responsive but reduces invocations
- Con: more complex than A, less correct than B. Worst of both worlds.

### Recommendation: A

Reduce to daily for now. Plan B for a future "source-webhook initiative" where multiple sources move to webhook-driven ingestion together (Notion already has webhook semantics; Habitify might; Whoop has webhooks). Don't do webhook migration one source at a time — too much per-source ceremony.

### Implementation if A is approved

```bash
# EventBridge rule update
aws events put-rule --region us-west-2 \
  --name <todoist-rule-name> \
  --schedule-expression "cron(0 14 * * ? *)"   # 14 UTC = 6am PT (adjust for DST as needed)
```

Verify rule name from `ci/lambda_map.json` or `aws events list-rules` first. Update `RUNBOOK.md` to reflect new cadence.

### Implementation if B is approved (deferred)

Spin out as its own spec: `docs/specs/SOURCE_WEBHOOK_MIGRATION.md`. Don't do in this batch.

---

## TD-14 [MED] — Backfill scripts drift from live Lambdas

### Problem

`backfill_apple_health_export_v16.py` has the source-priority fix; the live HAE Lambda doesn't (TD-15). Same root cause. The pattern: a fix gets developed in a backfill script, lands cleanly there, and the live Lambda doesn't get the same fix because nobody remembers to port it.

This isn't really a code problem — it's a process problem. Code-only fixes will be temporary if the process keeps producing this drift.

### Recommendation

**Establish a discipline rule and enforce it via PR template + code review.**

Rule: *Any backfill script that introduces a fix to data interpretation, parsing, normalization, or schema must port the same fix to the corresponding live Lambda in the same PR. If porting is non-trivial and being deferred, the deferral must be tracked as a labeled TD item linked from the PR description.*

### Implementation

1. **Add to `.github/PULL_REQUEST_TEMPLATE.md`** (create if doesn't exist):

```markdown
## Backfill / Lambda parity check

If this PR modifies a `backfill/` script:
- [ ] Equivalent fix is in the corresponding live Lambda in this PR, OR
- [ ] A TD item is filed for the deferred port (link below) and labeled `parity-debt`

If this PR modifies a Lambda that has a corresponding `backfill/` script:
- [ ] Equivalent fix is in the backfill script in this PR, OR
- [ ] A TD item is filed (link below)

Linked TD items (if applicable):
- [ ] None
```

2. **Establish naming convention:** if a Lambda has a related backfill script, name them with a shared prefix. E.g. `health-auto-export-webhook` Lambda ↔ `backfill/backfill_apple_health_export_v*.py`. The shared prefix makes the parity relationship discoverable by greppability.

3. **Add `parity-debt` label** to GitHub Issues / TD tracker. Filter on it during periodic cleanup.

4. **Once-quarterly audit:** grep `backfill/*.py` for unique parsing/normalization functions, then grep the corresponding Lambdas for the same functions. Mismatches are TD candidates.

### Cost of the rule

Modest — adds a checklist item per PR. Primary cost is the discipline of actually doing the parity port instead of skipping it.

### Cost of not having the rule

The drift compounds. v16 has 2 fixes the live Lambda doesn't; v17 will have 3; eventually backfill is the only correct ingestion path and live data is just unreliable. This is exactly how TD-15 became HIGH.

### Note on this batch

TD-15 is the first concrete cleanup of accumulated drift. After that PR ships, TD-14 process change has a recent example to point at.

---

## TD-17 [LOW] — HAE Tier 2 feeds (HR/RHR/SpO2) drop 100% of payloads

### Problem

Whoop is the source of truth for heart-rate, resting-heart-rate, and SpO2 data. The live HAE Lambda correctly filters these out (writes nothing). But the upstream iOS Health Auto Export app keeps sending them, wasting Lambda invocations on payloads that have no useful content. Cosmetic, not correctness.

### Options

**A. Disable those feeds in the iOS Health Auto Export app config**
- Pro: zero code change. Stops the wasted invocations at the source.
- Con: requires Matthew to open the iOS app and toggle settings.

**B. Add a fast-reject path in the Lambda**
- Pro: no manual phone fiddling. Defensive — if iOS config drifts back on, Lambda still rejects fast.
- Con: pollutes Lambda code with an explicit drop list. Treats a config issue as a code issue.

**C. Both A and B**
- Pro: belt and suspenders.
- Con: maintenance overhead on a low-priority cosmetic issue.

### Recommendation: A

Cleaner. Fewer moving parts. The "what if config drifts back on" scenario is real but the cost of the drift is just slightly elevated Lambda invocations — same state we're in today. Not worth code complexity.

### Implementation if A

Matthew action — no Claude Code work:
1. Open Health Auto Export iOS app
2. Settings → Automations → find the active automation feeding the webhook
3. In the metric list, untoggle Heart Rate, Resting Heart Rate, SpO2 (and any other Whoop-canonical metric)
4. Save

After the change, watch CloudWatch for ~24 hours and confirm Lambda invocation count drops.

### If A is rejected and B is preferred

Add to `health-auto-export-webhook` Lambda:

```python
# At the top of the handler, before any processing
TIER_2_REDUNDANT_METRICS = {
    "heart_rate", "resting_heart_rate", "blood_oxygen_saturation",
    # add others as needed
}

def handler(event, context):
    payload = parse_event(event)
    # Fast-reject: if all metrics in payload are tier-2 redundant, return early
    incoming_metrics = {m["name"] for m in payload.get("metrics", [])}
    if incoming_metrics and incoming_metrics.issubset(TIER_2_REDUNDANT_METRICS):
        return {"statusCode": 200, "body": json.dumps({"skipped": "tier_2_redundant"})}
    # ... continue with normal processing
```

Document in `RUNBOOK.md` under "Known no-op patterns."

---

## Decision summary

| TD | Recommendation | Action owner | Effort |
|---|---|---|---|
| TD-12 | Option A: daily cron | Claude Code (one-line EventBridge change) | 5 min |
| TD-14 | Add PR template + naming convention + parity-debt label | Claude Code (template), Matthew (process discipline) | 15 min one-time |
| TD-17 | Option A: disable in iOS app | Matthew (phone settings) | 2 min |

All three are sub-30-minute fixes once decided. **Matthew confirms the recommendations and these can ship as a tiny housekeeping PR alongside the HAE batch (TD-15/16/18/20) or independently — whichever is cleaner.**

---

## Open questions for Matthew

1. **Confirm A for TD-12 (daily cron, defer webhooks)?**
2. **Confirm A for TD-17 (disable in iOS app)?**
3. **Anything to add to the TD-14 PR template before it lands?**
4. **Bundle these with the TD-15/16/18/20 PR, or separate?** Recommendation: separate, because TD-12 and TD-17 don't touch HAE Lambda. TD-14 is a meta-process change and should be its own clean commit for findability.
