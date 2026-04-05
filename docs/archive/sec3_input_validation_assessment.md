# SEC-3 Input Validation Depth Assessment
**Date:** 2026-03-15 (v3.7.27)
**Assessor:** Yael Cohen (Security seat)
**Scope:** MCP tool input validation — date parameters, string injection, type coercion

---

## Current State

MCP tools receive `args` dicts via the JSON-RPC `params` field from authenticated
callers. The current validation posture is:

**What exists:**
- Authentication: HMAC Bearer token check in `mcp/handler.py` — only authenticated callers reach tools
- Schema validation: each tool has a `inputSchema` in `registry.py` describing expected params and types
- Date usage: `args.get("start_date", ...)` with default fallbacks — no explicit format validation
- DynamoDB safety: all queries use parameterized `KeyConditionExpression` via boto3 — **no string interpolation into query syntax**

**What's missing:**
1. Date format validation before DDB query — a malformed date like `"; DROP TABLE"` flows into `query_source(start_date, end_date)` unchanged. DynamoDB will return an empty result (benign), but the string appears in CloudWatch logs unredacted.
2. Range limiting — no max window enforcement. `start_date="2020-01-01"` triggers a 6-year range scan that can consume significant DynamoDB RCUs.
3. S3 path inputs — `_load_cgm_readings(date_str)` constructs `f"raw/matthew/cgm_readings/{y}/{m}/{d}.json"` where `y, m, d = date_str.split("-")`. A value like `"../../config/board_of_directors"` would split to `["../..", "config/board_of_directors"]` — producing an S3 key that targets `raw/matthew/cgm_readings/../../config/board_of_directors.json`, which normalizes to `config/board_of_directors.json`. **This is the highest-severity finding.**

---

## Risk Assessment

| Finding | Severity | Exploitability | Impact |
|---|---|---|---|
| **S3 path traversal in `_load_cgm_readings`** | HIGH | Low (requires authenticated access) | Could read `config/board_of_directors.json` or other S3 objects via a malformed date string. Mitigation: validate date format strictly before constructing S3 key. |
| Unbounded date range scans | MEDIUM | Low (authenticated, on-demand billing) | Large scans increase DDB costs and Lambda execution time. Mitigation: cap `start_date` to ≤365 days before `end_date`. |
| Unvalidated string inputs in logs | LOW | Very low | Malformed inputs appear in CloudWatch logs; no code execution risk with DynamoDB parameterized queries. |
| Type coercion edge cases | LOW | Very low | `float(args.get("meal_gap_minutes", 30))` — if caller passes `"30; ..."`, Python `float()` raises ValueError, tool returns error. Benign. |

---

## Recommended Fixes

### Fix 1 (HIGH): Validate date_str before S3 key construction

In `mcp/tools_cgm.py`, `_load_cgm_readings`:

```python
import re

def _load_cgm_readings(date_str):
    # Validate before constructing S3 key — prevent path traversal
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', date_str):
        logger.warning("_load_cgm_readings: invalid date_str format: %r", date_str)
        return []
    try:
        datetime.strptime(date_str, "%Y-%m-%d")  # validate calendar validity
    except ValueError:
        return []
    # ... rest of function
```

Same validation needed in `tool_get_fasting_glucose_validation` anywhere `date_str` flows into S3 key construction.

### Fix 2 (MEDIUM): Add date range cap utility

In `mcp/core.py` or `mcp/utils.py`, add:

```python
MAX_LOOKBACK_DAYS = 365  # prevent multi-year RCU spikes

def validate_date_range(start_date: str, end_date: str, max_days: int = MAX_LOOKBACK_DAYS):
    """Validate date range inputs. Returns (start, end) or raises ValueError."""
    import re
    date_pattern = re.compile(r'^\d{4}-\d{2}-\d{2}$')
    for d in [start_date, end_date]:
        if not date_pattern.fullmatch(d):
            raise ValueError(f"Invalid date format: {d!r}. Expected YYYY-MM-DD.")
    try:
        s = datetime.strptime(start_date, "%Y-%m-%d")
        e = datetime.strptime(end_date, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(f"Invalid calendar date: {exc}") from exc
    if (e - s).days > max_days:
        raise ValueError(f"Date range {start_date}→{end_date} exceeds {max_days}-day limit.")
    return start_date, end_date
```

Call at the top of tools that accept `start_date`/`end_date` args.

### Fix 3 (LOW): Add a single input validation decorator / wrapper

For tools that accept date params, a thin wrapper that calls `validate_date_range` before
the tool body runs. This avoids scattering validation across every tool.

---

## Implementation Plan

These fixes are un-gated — no data or timing dependency. Recommended sequence:

1. **Fix 1 (S3 path traversal)** — 30 min. High severity, small change.
2. **Fix 2 (date range cap)** — 1h. Add `validate_date_range` to `mcp/utils.py`, call from the 8 tools that accept date ranges.
3. **Fix 3 (decorator)** — 2h. Optional but makes future tools secure by default.

Total estimated effort: ~3–4 hours. Recommend completing Fix 1 before R13.

---

## What This Is NOT

- SQL injection risk: zero. DynamoDB boto3 uses parameterized expressions — no string concatenation into query syntax.
- Remote code execution: zero. No `eval`, no subprocess, no shell execution of user inputs.
- Authentication bypass: zero. Bearer token check runs before any tool dispatch.
- PII exfiltration via MCP: bounded. The MCP server only reads `USER#matthew` data; multi-tenancy is not a concern at current scale.

---

## Board Verdict

Viktor: "Fix 1 is real. The S3 path traversal on a malformed date is a genuine issue even at low
exploitability — you don't want a configuration file leak behind an authenticated endpoint. Fix it
before R13. Fixes 2 and 3 are good hygiene but not urgent."

Yael: "Agree. The auth layer keeps exploitability low, but defense-in-depth means validating
inputs regardless of who's calling. One-line regex check eliminates the class of issue."
