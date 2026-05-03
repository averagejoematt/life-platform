# TD Batch — HAE Lambda + platform_logger fixes

**Severity:** Mixed (one HIGH, three LOW)
**Status:** Ready for Claude Code execution
**Includes:** TD-15 (HIGH), TD-16 (MED, subsumed), TD-18 (LOW), TD-20 (LOW)
**Source handover:** `handovers/HANDOVER_v6.8.1.md`

These four items are batched because three of them touch the same Lambda (`health-auto-export-webhook`) and the fourth (TD-20) is a tiny one-line fix in a shared utility. One PR, one HAE deploy, one shared-layer build if needed.

---

## TD-15 [HIGH] — Port SOURCE_PRIORITY to live HAE Lambda

### Context

`backfill/backfill_apple_health_export_v16.py` v16.1 has source-priority logic that picks one canonical writer per metric type when iOS Health export.xml has duplicates (iPhone + Garmin both writing step counts; "My Water" + MacroFactor both writing dietary water). The live `health-auto-export-webhook` Lambda doesn't have this fix. **Today's webhook traffic is silently inflating step counts and miscalculating water.**

### Fix

Port the `SOURCE_PRIORITY` dict and the priority-selection logic from v16.1 backfill into the live Lambda.

**Reference implementation:** `backfill/backfill_apple_health_export_v16.py`. Find the `SOURCE_PRIORITY` constant and the function that uses it. Mirror that logic into the Lambda's metric-processing code path.

### Acceptance criteria

- [ ] `SOURCE_PRIORITY` dict defined in the live Lambda module, identical structure to v16.1
- [ ] When the webhook payload contains the same metric from multiple sources, only the priority-1 source's value is written to DDB
- [ ] When only one source is present, behavior is unchanged from current
- [ ] Unit test: payload with iPhone steps + Garmin steps, both for same date → only Garmin (priority winner) writes; if priority is iPhone, only iPhone writes (verify which is canonical in the existing dict)

### Verification post-deploy

```bash
# Check today's webhook traffic post-deploy
aws logs tail /aws/lambda/health-auto-export-webhook --since 10m --region us-west-2

# Spot-check DDB row for today's apple_health
# Step count should match a single source, not the sum of two sources
# (Compare against Garmin's step count for same date — should now agree)
```

---

## TD-16 [MED] — Apple Health "Connect" inflates activity ~2x

**Subsumed by TD-15.** TD-16 is the same bug viewed through the Garmin-via-AppleHealth lens. Once `SOURCE_PRIORITY` is in the live Lambda, this is fixed automatically. No additional code.

### Acceptance criteria

- [ ] Verification: today's `apple_health` step count is no longer ~2x today's `garmin` step count

If TD-15 verification passes, TD-16 is done.

---

## TD-18 [LOW] — HAE weight feed name mismatch

### Context

The live HAE Lambda's `METRIC_MAP` expects `body_mass`. iOS export sends `weight_body_mass`. Weight is currently captured because it's the only feed where `weight_lbs_apple` is also written, but the field-mapping is fragile.

### Fix

Update `METRIC_MAP` in the HAE Lambda to recognize both keys. Either:

**Option A:** alias `weight_body_mass` to the same handler as `body_mass`:
```python
METRIC_MAP = {
    ...
    "body_mass": handle_weight,
    "weight_body_mass": handle_weight,  # iOS export.xml variant
    ...
}
```

**Option B:** normalize incoming keys before lookup:
```python
KEY_ALIASES = {"weight_body_mass": "body_mass"}
incoming_key = KEY_ALIASES.get(raw_key, raw_key)
```

**Recommendation:** Option A. Simpler, more discoverable when reading the code. Option B hides aliasing in a side dict.

### Acceptance criteria

- [ ] Both `body_mass` and `weight_body_mass` payloads write to DDB correctly
- [ ] Unit test: payload with `weight_body_mass` writes a weight record; previously this might have been ignored or fallen through to the redundant path

---

## TD-20 [LOW] — `platform_logger.py:103` TypeError

### Context

`platform_logger.py:103` in `formatException()` raises `TypeError: 'bool' object is not subscriptable` on every error log line where the original code calls `logger.error("...", exc_info=True)`. The handler is treating the `True` literal as if it were a `sys.exc_info()` tuple. Cosmetic — doesn't suppress the original error message — but pollutes log streams and obscures real errors.

### Fix

In `platform_logger.py`'s `formatException()` method, handle the `exc_info=True` case by calling `sys.exc_info()` to get the actual tuple:

```python
import sys

def formatException(self, exc_info):
    if exc_info is True:
        exc_info = sys.exc_info()
    if not exc_info or exc_info == (None, None, None):
        return ""
    # ...rest of existing logic that subscripts exc_info...
```

### Where this lives

`platform_logger.py` is likely in a shared layer or shared module — verify whether it's in:
- A Lambda layer (would need a layer rebuild + every Lambda using it gets the fix on next deploy)
- A repo-root module bundled into each Lambda zip (would need redeploy of every Lambda using it)
- The `mcp/` package (only MCP Lambda affected)

**Action:** grep the repo for `platform_logger` to find its install path before deciding deploy scope.

### Acceptance criteria

- [ ] `python3 -c "import platform_logger; ..."` (or equivalent test path) runs without raising
- [ ] A test that triggers an exception path no longer emits the secondary TypeError traceback
- [ ] Existing log output is unchanged for happy-path cases (no regressions in successful log lines)

### Verification post-deploy

```bash
# Trigger an error in any Lambda that uses platform_logger and check tail
aws logs tail /aws/lambda/<lambda-name> --since 5m --region us-west-2 | grep -A 3 "ERROR"
# Expected: no "TypeError: 'bool' object is not subscriptable" lines below the actual error
```

---

## Combined deploy plan

### Build order

1. Fix `platform_logger.py` first (TD-20) — it's a leaf dependency
2. If `platform_logger.py` is in a shared layer, rebuild the layer
3. Apply TD-15 + TD-18 changes to the HAE Lambda (TD-16 piggybacks on TD-15)
4. Deploy HAE Lambda via `deploy/deploy_lambda.sh`
5. If layer was rebuilt: deploy other Lambdas that depend on it, **10s wait between** (memory rule)

### Pre-deploy checks

```bash
# Memory rule: MCP registry sanity (only if mcp_server.py touched — it shouldn't be)
python3 -m pytest tests/test_mcp_registry.py -v

# Full test suite if exists
python3 -m pytest tests/ -v
```

### Single-PR scope guideline

All four fixes in one PR. Reasoning:
- TD-15 and TD-16 are the same fix
- TD-18 is in the same file, ~5 lines
- TD-20 is unrelated but tiny and shipping it separately wastes a deploy

PR description should list all four TD numbers in title or body for traceability.

### Doc updates

- `CHANGELOG.md` — list all four TD numbers
- `RUNBOOK.md` — if HAE behavior change is operationally visible (it is — step counts will drop ~50% on iPhone+Garmin overlap days), note this in the "Known surprising behaviors" section
- `MCP_TOOL_CATALOG.md` — no change (no tool changes)
- Move this file from `docs/specs/` to `docs/archive/` after merge

---

## Risk

The HAE behavior change in TD-15 will produce a visible step-count drop on days where iPhone + Garmin both wrote. Users (Matthew) might think the platform broke when in fact it just stopped double-counting. **Mitigate by adding a CHANGELOG note specifically calling out the expected drop.**

Backfilled data is already correct (v16.1 backfill applied source priority). Live data going forward will now match. The interim window — between the v16.1 backfill date and this fix's deploy date — has the bug. We can either backfill that window with v16.1 again, or accept the inflation as a known interim artifact. **Recommendation:** re-run v16.1 backfill for the interim window after this deploy. ~5 minutes of work.

---

## Open questions for Matthew

1. **Re-run v16.1 backfill for the post-backfill / pre-fix interim window?** Recommend yes.
2. **Are there other Lambdas using `platform_logger.py` that should be redeployed in this PR?** Depends on shared-layer arrangement — Claude Code will surface this in the PR description after grepping.
