# The Ledger — Claude Code Implementation Spec
## Feature: Achievement-Linked Charitable Giving + Snake Fund Discovery Page
**Status:** Ready for implementation  
**Version:** 1.0 (Claude Code handoff)  
**Date:** 2026-03-30  
**Target version bump:** Next available minor (check CHANGELOG.md for current version)

---

## ⚠️ START HERE

**Before writing any code:**
1. Read `handovers/HANDOVER_LATEST.md` → follow the pointer → read the versioned file
2. Read this spec in full before starting Phase 0
3. **Stop after each phase and wait for Matthew's confirmation before proceeding**

---

## Concept

Every achievement earned, challenge passed/failed, and experiment concluded generates a real charitable donation. Successes → causes Matthew cares about. Failures → causes he doesn't (the Snake Fund). The page tracking all of this (`/ledger/`) is hidden in the footer under a link labeled "Snake Fund" — discoverable, not advertised.

The page has two views of the same data:
- **By Event** — badge wall of everything that happened (left = earned/passed, right = failed)
- **By Charity** — grouped by cause, with running totals and contributing badges

---

## Trigger Types

| Type | Success outcome | Failure outcome |
|---|---|---|
| **Achievement badge** | Bounty → earned cause | None (achievements cannot fail) |
| **Challenge** | Bounty → earned cause | Punishment → reluctant cause |
| **Experiment** | Bounty → earned cause | Punishment → reluctant cause |

---

## Data Model

### New optional fields on existing records

**`config/achievement_badges.json`** — add to any badge definition:
```json
{
  "id": "weight_280",
  "bounty_usd": 50,
  "cause_id": "food_bank_seattle"
}
```

**Challenge DynamoDB records** (`CHALLENGE#<id>`):
```
bounty_usd      number  optional — falls back to ledger.json default
punishment_usd  number  optional — falls back to ledger.json default
cause_id        string  optional — falls back to active_earned_cause in ledger.json
```

**Experiment DynamoDB records** (`EXP#<id>`):
```
bounty_usd      number  optional
punishment_usd  number  optional
cause_id        string  optional
```

### New S3 config: `config/ledger.json`

> Note: Use key `config/ledger.json` — NOT `site/config/ledger.json`.
> The MCP server reads from `config/`, site_api reads from `site/config/`.
> The MCP tool reads this file; site_api also reads it to merge metadata into API responses.
> Therefore use `config/ledger.json` for MCP access and also reference it from site_api.

```json
{
  "settings": {
    "default_bounty_usd": 50,
    "default_punishment_usd": 75,
    "show_amounts_on_source_badges": false,
    "active_earned_cause": "food_bank_seattle",
    "active_reluctant_cause_id": "snake_sanctuary"
  },
  "earned_causes": [
    {
      "id": "food_bank_seattle",
      "name": "Northwest Harvest",
      "short_description": "Pacific NW food bank",
      "url": "https://www.northwestharvest.org",
      "badge_color": "teal",
      "why_i_care": "Food insecurity in my backyard."
    }
  ],
  "reluctant_causes": [
    {
      "id": "snake_sanctuary",
      "name": "American Reptile Rescue",
      "short_description": "Snake and reptile sanctuary",
      "url": "https://americanreptilerescue.org",
      "badge_color": "gray",
      "joke_note": "I have funded this organization more than I care to admit.",
      "is_active": true
    }
  ]
}
```

Matthew will populate the real cause names/URLs/notes before Phase 0 starts.

### New DynamoDB partition: `USER#matthew#SOURCE#ledger`

**Transaction records:**
```
PK: USER#matthew#SOURCE#ledger
SK: LEDGER#<ISO-timestamp>   e.g. LEDGER#2026-03-30T14:22:01.000Z

Fields:
  ledger_id         string   ISO timestamp (SK suffix, no LEDGER# prefix)
  date              string   YYYY-MM-DD
  type              string   "bounty" | "punishment"
  amount_usd        number
  cause_id          string
  cause_name        string   denormalized for display
  source_type       string   "achievement" | "challenge" | "experiment"
  source_id         string   e.g. "weight_280" or "30_day_walk"
  source_name       string   human-readable, e.g. "280 Club"
  source_badge_icon string   emoji key, e.g. "🏆" "💪" "🔬"
  outcome           string   "earned" | "passed" | "failed" | "abandoned"
  notes             string   optional
  logged_by         string   "mcp" | "seed" | "backfill" — provenance tracking
  logged_at         string   ISO timestamp
```

**Running totals record (one record, updated on every transaction):**
```
PK: USER#matthew#SOURCE#ledger
SK: TOTALS#current

Fields:
  total_donated_usd       number
  total_bounties_usd      number
  total_punishments_usd   number
  bounty_count            number
  punishment_count        number
  cause_count             number
  by_cause                map    see structure below
  last_updated            string ISO timestamp
```

`by_cause` map structure (keep only last 10 transactions per cause — full history lives in LEDGER# records):
```json
{
  "food_bank_seattle": {
    "amount_usd": 150,
    "count": 3,
    "transactions": [
      {
        "date": "2026-03-15",
        "source_name": "280 Club",
        "source_type": "achievement",
        "source_badge_icon": "🏆",
        "amount_usd": 50,
        "outcome": "earned"
      }
    ]
  }
}
```

> **Design note:** The TOTALS#current record uses a fetch → mutate → put_item pattern (not conditional writes). This is intentionally non-atomic and acceptable because Matthew is the sole user and entries are logged manually one-at-a-time via MCP tool. Do not "improve" this with conditional expressions — the simpler pattern is correct for this use case.
```

---

## Stake Resolution Logic

When `log_ledger_entry` is called with `(source_type, source_id, outcome)`:

```
1. Fetch source record from DDB (challenge/experiment) 
   OR badge config entry from achievement_badges.json (achievement)

2. Resolve amount:
   - If outcome is success/earned → use bounty_usd from record, else default_bounty_usd
   - If outcome is failed/abandoned → use punishment_usd from record, else default_punishment_usd

3. Resolve cause_id:
   - If outcome is failed/abandoned → ALWAYS active_reluctant_cause_id (no override allowed)
   - If outcome is success/earned → cause_id from record, else active_earned_cause

4. Write LEDGER#<ISO> transaction record

5. Update TOTALS#current:
   - Increment global counters
   - Append transaction to by_cause[cause_id].transactions
   - Increment by_cause[cause_id].amount_usd and count
```

---

## API Response: `GET /api/ledger`

Returns both views in one call. No second fetch needed by the page.

```json
{
  "totals": {
    "total_donated_usd": 275,
    "total_bounties_usd": 150,
    "total_punishments_usd": 125,
    "bounty_count": 3,
    "punishment_count": 2,
    "cause_count": 2
  },
  "by_event": {
    "earned": [
      {
        "ledger_id": "2026-03-15T14:22:01.000Z",
        "date": "2026-03-15",
        "source_type": "achievement",
        "source_id": "weight_280",
        "source_name": "280 Club",
        "source_badge_icon": "🏆",
        "outcome": "earned",
        "amount_usd": 50,
        "cause_id": "food_bank_seattle",
        "cause_name": "Northwest Harvest"
      }
    ],
    "reluctant": [
      {
        "ledger_id": "2026-01-10T09:00:00.000Z",
        "date": "2026-01-10",
        "source_type": "experiment",
        "source_id": "glucose_exp_3",
        "source_name": "Glucose Experiment #3",
        "source_badge_icon": "🔬",
        "outcome": "abandoned",
        "amount_usd": 75,
        "cause_id": "snake_sanctuary",
        "cause_name": "American Reptile Rescue"
      }
    ]
  },
  "by_cause": {
    "earned_causes": [
      {
        "id": "food_bank_seattle",
        "name": "Northwest Harvest",
        "short_description": "Pacific NW food bank",
        "url": "https://...",
        "badge_color": "teal",
        "why_i_care": "Food insecurity in my backyard.",
        "total_usd": 150,
        "count": 3,
        "transactions": [...]
      }
    ],
    "reluctant_causes": [
      {
        "id": "snake_sanctuary",
        "name": "American Reptile Rescue",
        "joke_note": "I have funded this organization more than I care to admit.",
        "is_active": true,
        "total_usd": 125,
        "count": 2,
        "transactions": [...]
      }
    ]
  }
}
```

---

## Page Structure: `/ledger/index.html`

```
PAGE HEADER
  Title: "The Ledger"
  Subtitle: "A record of what I owe the world — and what I reluctantly owe the snakes."

SUMMARY STRIP (4 stats — use platform summary strip pattern from milestones/achievements pages):
  $XXX to causes I believe in  |  $XXX to causes I don't  |  XX events  |  XX charities

VIEW TOGGLE: [ By Event ]  [ By Charity ]   (default: By Event)

────────────────────────────────────────────────────────
VIEW A — By Event (default active tab)

  TWO COLUMNS:
  LEFT: "Things I fought for"         RIGHT: "Things that fought me"
  
  Each entry = one badge card:
  
  EARNED badge card:                  RELUCTANT badge card:
  ┌─────────────────────────┐         ┌─────────────────────────┐
  │ [icon]  Source Name     │         │ [icon]  Source Name     │
  │  subtitle (type+dates)  │         │  subtitle (type+dates)  │
  │                         │         │                         │
  │ → Cause Name   $50      │         │ → Snake Fund   $75      │
  │ Earned · Mar 15         │         │ Failed · Jan 10         │
  └─────────────────────────┘         └─────────────────────────┘
  
  Full color, warm accent border.     Muted/desaturated palette.
  var(--accent) left border.          var(--border) left border.
  
────────────────────────────────────────────────────────
VIEW B — By Charity (second tab, hidden by default)

  TWO COLUMNS:
  LEFT: "Causes I fought for"         RIGHT: "Causes I reluctantly helped"
  
  EARNED cause card:                  RELUCTANT cause card:
  ┌─────────────────────────────┐     ┌─────────────────────────────┐
  │ Cause Name                  │     │ Cause Name                  │
  │ short_description           │     │ short_description            │
  │                             │     │                             │
  │ $150 donated · 3 events     │     │ $125 donated · 2 failures   │
  │                             │     │                             │
  │ why_i_care quote            │     │ *joke_note in italic mono*  │
  │                             │     │                             │
  │ [280 Club] [Walk] [Exp #4]  │     │ [Glucose #3] [Sleep Proto] │
  │ (sub-badge chips)           │     │ (sub-badge chips, muted)    │
  │                             │     │                             │
  │ Earned · N=3                │     │ Despite myself · N=2        │
  └─────────────────────────────┘     └─────────────────────────────┘

  Sub-badge chips link to source pages (Milestones, Experiments, etc.)

────────────────────────────────────────────────────────
TRANSACTION LOG (collapsed by default, <details> element)
  Full chronological list — date | source | outcome | cause | amount

FOOTER NOTE (small, italic, centered):
  "Donations are real. The snake thing is real. The intent is genuine."
```

### Design tokens to use:
- Page follows platform CSS token system (`tokens.css`, `base.css`)
- Section headers: monospace with trailing dash lines (same as Milestones, Experiments pages)
- Summary strip: identical pattern to `/achievements/index.html` `.summary-strip` component
- Dark mode default (platform standard)
- Mobile: single column, earned first, `<hr>` with label "Then there's this column…", reluctant below

---

## Implementation Phases

---

### PHASE 0 — Config + MCP Tool

**Goal:** Data infrastructure in place. `log_ledger_entry` works from Claude Desktop.  
**Stop after this phase and confirm with Matthew before proceeding.**

#### Step 1: Create `config/ledger.json` in S3

Matthew will provide the real cause names before this step. Use placeholder values from the spec above until then.

```bash
# After creating the file locally at /tmp/ledger.json:
aws s3 cp /tmp/ledger.json s3://matthew-life-platform/config/ledger.json
```

#### Step 2: Add `tool_log_ledger_entry` to `mcp/tools_lifestyle.py`

**Add at the end of the file, after `tool_get_ruck_log`.**

Follow the exact same structure as `tool_log_decision` in `mcp/tools_decisions.py` — same import pattern, same `put_item` + update pattern.

Key implementation notes:
- PK: `f"USER#{_get_user_id()}#SOURCE#ledger"`
- Transaction SK: `f"LEDGER#{ts}"` where `ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"`
- Totals SK: `"TOTALS#current"`

**DynamoDB nested map update for `TOTALS#current`** — use this exact pattern for `by_cause`:

```python
from boto3.dynamodb.conditions import Attr

# Step 1: Fetch current totals
totals_pk = f"USER#{_get_user_id()}#SOURCE#ledger"
totals_sk = "TOTALS#current"
existing = table.get_item(Key={"pk": totals_pk, "sk": totals_sk}).get("Item", {})

# Step 2: Mutate in Python (safer than nested DDB UpdateExpression for map-of-maps)
by_cause = existing.get("by_cause", {})
if cause_id not in by_cause:
    by_cause[cause_id] = {"amount_usd": Decimal("0"), "count": 0, "transactions": []}

entry = by_cause[cause_id]
entry["amount_usd"] = entry.get("amount_usd", Decimal("0")) + Decimal(str(amount_usd))
entry["count"] = int(entry.get("count", 0)) + 1
entry.setdefault("transactions", []).append({
    "date": date,
    "source_name": source_name,
    "source_type": source_type,
    "source_badge_icon": badge_icon,
    "amount_usd": Decimal(str(amount_usd)),
    "outcome": outcome,
})
# Cap at 10 most recent transactions per cause (full history in LEDGER# records)
entry["transactions"] = entry["transactions"][-10:]

# Step 3: Write full updated totals record back
table.put_item(Item={
    "pk": totals_pk,
    "sk": totals_sk,
    "total_donated_usd": existing.get("total_donated_usd", Decimal("0")) + Decimal(str(amount_usd)),
    "total_bounties_usd": ...,  # increment bounty or punishment bucket
    "total_punishments_usd": ...,
    "bounty_count": ...,
    "punishment_count": ...,
    "cause_count": len(by_cause),
    "by_cause": by_cause,
    "last_updated": datetime.now(timezone.utc).isoformat(),
})
```

> **Why put_item instead of update_item?** The `by_cause` field is a map-of-maps-of-lists. Constructing a nested `UpdateExpression` with `if_not_exists` guards on all levels is error-prone. Fetch → mutate in Python → put_item is safer for this shape.

**Tool output confirmation message format:**
```
✅ Ledger entry logged
   Type: bounty
   Source: 280 Club (achievement)
   Outcome: earned
   Amount: $50 → Northwest Harvest
   Running totals: $150 earned for good causes / $75 to reluctant causes
```

#### Step 2b: Add `tool_get_ledger_summary` to `mcp/tools_lifestyle.py`

**Add immediately after `tool_log_ledger_entry`.**

Companion read tool so Matthew can check ledger state from Claude Desktop without visiting the website.

**Logic:**
- Fetch `TOTALS#current` from `USER#matthew#SOURCE#ledger`
- Fetch `config/ledger.json` from S3 for cause metadata
- If no TOTALS record exists: return `{"status": "empty", "message": "No ledger entries yet."}`
- Return formatted summary: total donated, earned vs reluctant breakdown, per-cause totals with last 3 transactions each
- Accept optional `cause_id` parameter to filter to one cause

**Output format:**
```
📒 Ledger Summary
   Total donated: $275
   For causes I believe in: $150 (3 entries)
   For the snakes: $125 (2 entries)

   EARNED CAUSES:
   → Northwest Harvest — $150 (3 entries)
     Most recent: 280 Club (Mar 15), Walk Challenge (Mar 10), Glucose Exp #4 (Feb 28)

   RELUCTANT CAUSES:
   → American Reptile Rescue — $125 (2 entries)
     Most recent: Glucose Exp #3 (Jan 10), Sleep Protocol (Dec 15)
```

#### Step 3: Register in `registry.py`

The `from mcp.tools_lifestyle import *` wildcard import at line 33 already covers new functions in that file. No new import line needed.

Add the TOOLS entry before the closing `}` on line 2647:

```python
    "log_ledger_entry": {
        "fn": tool_log_ledger_entry,
        "schema": {
            "name": "log_ledger_entry",
            "description": (
                "Record a charitable donation triggered by an achievement, challenge, or experiment outcome. "
                "Auto-resolves the bounty/punishment amount and cause from the source record config. "
                "Use for: 'I hit 280 lbs', 'completed the walking challenge', 'glucose experiment failed', "
                "'log a ledger entry', 'record a Snake Fund donation'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "source_type": {"type": "string", "enum": ["achievement", "challenge", "experiment"],
                                    "description": "Type of trigger."},
                    "source_id":   {"type": "string",
                                    "description": "ID of the achievement badge, challenge, or experiment. "
                                                   "e.g. 'weight_280', '30_day_walk', 'glucose_exp_3'."},
                    "outcome":     {"type": "string", "enum": ["earned", "passed", "failed", "abandoned"],
                                    "description": "Result. Achievements use 'earned'. Challenges/experiments use "
                                                   "'passed', 'failed', or 'abandoned'."},
                    "date":        {"type": "string",
                                    "description": "Date of outcome (YYYY-MM-DD). Defaults to today."},
                    "notes":       {"type": "string",
                                    "description": "Optional context about what happened."},
                },
                "required": ["source_type", "source_id", "outcome"],
            },
        },
    },
    "get_ledger_summary": {
        "fn": tool_get_ledger_summary,
        "schema": {
            "name": "get_ledger_summary",
            "description": (
                "View the current state of The Ledger — charitable giving totals, per-cause breakdowns, "
                "and recent transactions. "
                "Use for: 'show my ledger', 'how much have I donated', 'Snake Fund total', "
                "'ledger summary', 'what have I given to charity'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "cause_id": {"type": "string",
                                 "description": "Optional: filter to a specific cause ID."},
                },
                "required": [],
            },
        },
    },
```

#### Step 4: Update tool count bounds in `tests/test_mcp_registry.py`

Current: `EXPECTED_MAX_TOOLS = 115` and there are currently **112 tools** in registry.py.  
Adding 1 tool (log_ledger_entry) + 1 tool (get_ledger_summary) → 114 total. Still within bounds. **No change needed to the test file.**

> **If the test fails on R5 (tool count out of range):** Other tools may have been added since this spec was written. Bump `EXPECTED_MAX_TOOLS` to 125 in `tests/test_mcp_registry.py`.

#### Step 5: Run the registry test

```bash
python3 -m pytest tests/test_mcp_registry.py -v
```

All three rules must pass: R1 (imports resolve), R2 (fn references exist), R3 (schemas valid).

#### Step 6: Deploy MCP Lambda

```bash
ZIP=/tmp/mcp_deploy.zip
rm -f $ZIP
zip -j $ZIP mcp_server.py mcp_bridge.py
zip -r $ZIP mcp/ -x 'mcp/__pycache__/*' 'mcp/*.pyc'
aws lambda update-function-code --function-name life-platform-mcp --zip-file fileb://$ZIP --region us-west-2
```

#### Step 7: Smoke test from Claude Desktop

```
log_ledger_entry("achievement", "weight_280", "earned", notes="Hit 280 on the scale this morning")
```

Verify the response contains resolved cause name, amount, and running totals. Check DynamoDB that both `LEDGER#<ts>` and `TOTALS#current` records were written.

**→ STOP. Confirm with Matthew before Phase 1.**

---

### PHASE 1 — API Endpoint

**Goal:** `/api/ledger` returns valid JSON. Page can be built against it.  
**Stop after this phase and confirm with Matthew before proceeding.**

#### Step 1: Add `handle_ledger()` to `site_api_lambda.py`

**Pattern reference:** Follow the exact same structure as `handle_achievements()` (~line 2904, search for `def handle_achievements`).
- Use `table` (module-level DynamoDB resource — already initialized)
- Use `USER_PREFIX` (defined at line 73: `f"USER#{USER_ID}#SOURCE#"`)
- Use `_decimal_to_float()` on all DynamoDB responses
- Use `_ok(data, cache_seconds=3600)` for the response
- Use `_error(status, message)` for failures

**S3 config load pattern** (for reading `config/ledger.json`):
```python
import boto3
s3_client = boto3.client("s3", region_name=S3_REGION)
resp = s3_client.get_object(Bucket=S3_BUCKET, Key="config/ledger.json")
ledger_config = json.loads(resp["Body"].read())
```
`S3_BUCKET` and `S3_REGION` are already module-level constants — do not re-declare.

**Function logic:**
1. Fetch `TOTALS#current` record from `USER#matthew#SOURCE#ledger`
2. Fetch all `LEDGER#` records (query with `begins_with("LEDGER#")`, `ScanIndexForward=False`, `Limit=200`)
3. Fetch `config/ledger.json` from S3 (for display metadata: names, descriptions, joke_notes, etc.)
4. Build `by_event` structure from LEDGER# records (split earned vs reluctant by `type` field)
5. Build `by_cause` structure: merge `TOTALS#current.by_cause` with S3 config metadata
6. Return `_ok({"totals": ..., "by_event": ..., "by_cause": ...}, cache_seconds=3600)`

Handle missing data gracefully — if `TOTALS#current` doesn't exist yet, return empty structure with zeros.

#### Step 2: Register route in the `ROUTES` dict

The `ROUTES` dict starts at approximately line 5569 (search for `ROUTES = {`). Add the new route in the "Observatory pages" section near the bottom:

```python
    # BL-03: The Ledger / Snake Fund
    "/api/ledger":              handle_ledger,
```

#### Step 3: Deploy site-api Lambda

```bash
bash deploy/deploy_lambda.sh life-platform-site-api lambdas/site_api_lambda.py
```

#### Step 4: Invalidate CloudFront

```bash
aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE --paths "/api/ledger"
```

#### Step 5: Smoke test

```bash
curl -s "https://averagejoematt.com/api/ledger" | python3 -m json.tool
```

Confirm: `totals`, `by_event.earned`, `by_event.reluctant`, `by_cause.earned_causes`, `by_cause.reluctant_causes` all present.

**→ STOP. Confirm with Matthew before Phase 2.**

---

### PHASE 2 — The Ledger Page

**Goal:** `/ledger/` is live. The footer Snake Fund link exists.  
**Stop after this phase and confirm with Matthew before proceeding.**

#### Step 1: Create `site/ledger/index.html`

**Pattern reference:** Use `/achievements/index.html` as the closest structural match — it has a summary strip, a page header, and a badge grid. Copy the HTML shell, nav, and footer includes, then implement The Ledger content.

**Key implementation rules:**
- Use `tokens.css` and `base.css` — no inline design system overrides
- Fetch `/api/ledger` on page load; render both views but only show the active tab
- View toggle: two buttons side by side, `.active` class on selected, JS toggles visibility of view A / view B divs
- Default active view: **By Event** (View A)
- Badge cards: same `.badge-card` or `.milestone-card` pattern used in achievements page
- Earned badges: `var(--accent)` left border, full color
- Reluctant badges: `var(--border)` left border, muted — add `opacity: 0.75` to the badge icon
- Sub-badge chips (View B): small pill treatment, link to source page
- Transaction log: use `<details><summary>Full transaction log (N entries)</summary>` — collapsed by default
- Mobile: `@media (max-width: 768px)` → single column, earned then reluctant

**Fetch pattern** (follow existing pages):
```javascript
fetch('/api/ledger')
  .then(r => r.json())
  .then(data => renderLedger(data))
  .catch(() => showError());
```

**Page `<title>`:** `The Ledger — Matthew`  
**Meta description:** `"A record of what I fight for — and what I reluctantly fund."` 

#### Step 2: Add Snake Fund footer link to `components.js`

**Exact location:** `buildFooter()` function, `Internal` column object at line 232.

Add as the last item in the `Internal` links array (after the RSS Feed entry, before Privacy, or wherever Matthew directs — but keep it looking identical to other links, no special treatment):

```javascript
{ href: '/ledger/', text: 'Snake Fund' },
```

The full Internal block after the change:
```javascript
{ heading: 'Internal', links: [
  { href: '/status/', text: 'System Status', id: 'footer-status-link' },
  { href: 'https://dash.averagejoematt.com/clinical.html', text: 'Clinician View', locked: true, external: true },
  { href: '/accountability/', text: 'Buddy Dashboard' },
  { href: 'https://discord.gg/T4Ndt2WsU', text: 'Join the community', external: true, community: true },
  { href: '/rss.xml', text: 'RSS Feed' },
  { href: '/ledger/', text: 'Snake Fund' },
  { href: '/privacy/', text: 'Privacy' },
]},
```

#### Step 3: S3 sync + CloudFront invalidation

```bash
aws s3 sync site/ledger/ s3://matthew-life-platform/site/ledger/ --exclude "*.DS_Store"
aws s3 cp site/assets/js/components.js s3://matthew-life-platform/site/assets/js/components.js
aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE --paths "/ledger/*" "/assets/js/components.js"
```

#### Step 4: Smoke test

1. Navigate to `https://averagejoematt.com/ledger/` directly — page loads, data renders
2. Scroll to footer of any page — "Snake Fund" link visible under Internal
3. Click "Snake Fund" — navigates to `/ledger/`
4. Toggle between "By Event" and "By Charity" views — both render
5. Transaction log collapses by default, expands on click

**→ STOP. Confirm with Matthew before Phase 3.**

---

### PHASE 3 — Challenge & Experiment Card Linkage

**Goal:** Challenge/experiment cards that have ledger entries show a subtle stake indicator.  
**Scope: minimal. Do not redesign cards. Add one small note only.**

On challenge/experiment cards where `ledger_linked: true` is set (or where the source has entries in the ledger), add a single small line:

```html
<span class="ledger-hint">This carries a stake → <a href="/ledger/">The Ledger</a></span>
```

Styled small, muted — `font-size: var(--text-xs); color: var(--text-muted);`

**No dollar amounts shown on source cards** — amounts are only visible on The Ledger page itself.

**→ STOP. Confirm with Matthew before Phase 4.**

---

### PHASE 4 — Achievement Badge Indicator

**Goal:** Milestones page earned badges that are ledger-linked show a subtle indicator.

On `/achievements/index.html`, for badges where `bounty_usd` is set in the config:

- Add a small `→` or `↗` icon to the earned badge card linking to `/ledger/`
- Same small muted treatment as Phase 3
- No dollar amount visible on the badge

---

## Pattern References (exact file locations)

> **Line numbers are approximate** — this file changes frequently. Always search for the function/pattern name rather than jumping to a line number.

| What | File | Search for | Notes |
|---|---|---|---|
| MCP tool function structure | `mcp/tools_decisions.py` | `def tool_log_decision` | Exact pattern to follow |
| MCP TOOLS dict entry structure | `mcp/registry.py` | `"log_decision":` | Entry structure to copy |
| TOOLS dict closing brace | `mcp/registry.py` | Last `}` in file (~line 2647) | Add new entry before `}` |
| tools_lifestyle.py end | `mcp/tools_lifestyle.py` | `def tool_get_ruck_log` | Append new tools after this |
| `from tools_lifestyle import *` | `mcp/registry.py` | `from mcp.tools_lifestyle` (~line 33) | Already covers new tools in that file |
| site_api handler structure | `lambdas/site_api_lambda.py` | `def handle_achievements` (~line 2904) | Closest structural match |
| ROUTES dict | `lambdas/site_api_lambda.py` | `ROUTES = {` (~line 5569) | Add `/api/ledger` entry here |
| `_ok()` helper | `lambdas/site_api_lambda.py` | `def _ok(` (~line 274) | `_ok(data, cache_seconds=N)` |
| `USER_PREFIX` constant | `lambdas/site_api_lambda.py` | `USER_PREFIX =` (line 73) | `f"USER#{USER_ID}#SOURCE#"` |
| `_decimal_to_float()` | `lambdas/site_api_lambda.py` | `def _decimal_to_float` (~line 239) | Use on all DDB responses |
| S3 config read pattern | `lambdas/site_api_lambda.py` | `experiment_library.json` (~line 455) | S3 config load pattern |
| Footer Internal links array | `site/assets/js/components.js` | `heading: 'Internal'` (line 232) | Add Snake Fund to this array |
| Summary strip HTML/CSS | `site/achievements/index.html` | `.summary-strip` class | Copy pattern for ledger page |
| Badge card design | `site/achievements/index.html` | Badge grid section | Copy card structure |

---

## Exact Deploy Commands (copy-paste ready)

**MCP Lambda:**
```bash
ZIP=/tmp/mcp_deploy.zip
rm -f $ZIP
zip -j $ZIP mcp_server.py mcp_bridge.py
zip -r $ZIP mcp/ -x 'mcp/__pycache__/*' 'mcp/*.pyc'
aws lambda update-function-code --function-name life-platform-mcp --zip-file fileb://$ZIP --region us-west-2
```

**site-api Lambda:**
```bash
bash deploy/deploy_lambda.sh life-platform-site-api lambdas/site_api_lambda.py
```

**S3 sync (Phase 2):**
```bash
aws s3 sync site/ledger/ s3://matthew-life-platform/site/ledger/ --exclude "*.DS_Store"
aws s3 cp site/assets/js/components.js s3://matthew-life-platform/site/assets/js/components.js
```

**CloudFront invalidations:**
```bash
# Phase 1 (API)
aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE --paths "/api/ledger"

# Phase 2 (page + footer)
aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE --paths "/ledger/*" "/assets/js/components.js"
```

---

## Version & Changelog

When the session ends, bump to the **next available minor version** (check the top entry of `CHANGELOG.md` for the current version, then increment the minor) and add to `CHANGELOG.md`:

```markdown
## vX.Y.0 — 2026-MM-DD
### Added
- BL-03: The Ledger / Snake Fund — achievement-linked charitable giving
  - `log_ledger_entry` + `get_ledger_summary` MCP tools (mcp/tools_lifestyle.py)
  - `SOURCE#ledger` DynamoDB partition (transaction + TOTALS records)
  - `config/ledger.json` S3 config (causes, defaults, active reluctant cause)
  - `GET /api/ledger` site-api endpoint (by_event + by_cause views)
  - `/ledger/` page with By Event / By Charity view toggle
  - "Snake Fund" footer link under Internal
```

Run `python3 deploy/sync_doc_metadata.py --apply` after updating CHANGELOG.

---

## Handoff Prompt for Claude Code

Copy-paste this exactly to start the Claude Code session:

```
Read handovers/HANDOVER_LATEST.md first, then follow the pointer to the versioned 
handover file and read it fully. Then read docs/LEDGER_SPEC_FINAL.md in full.

Build Phase 0 only: create config/ledger.json in S3 (use placeholder cause values 
from the spec — Matthew will update the real names), add tool_log_ledger_entry and 
tool_get_ledger_summary to mcp/tools_lifestyle.py following the log_decision pattern 
in mcp/tools_decisions.py, register both in mcp/registry.py before the closing brace, 
and run:

  python3 -m pytest tests/test_mcp_registry.py -v

All tests must pass before deploying. If R5 (tool count range) fails, bump 
EXPECTED_MAX_TOOLS to 125 in the test file and re-run. Then deploy the MCP Lambda 
using the exact zip commands in the spec. Stop after Phase 0 is tested and confirmed 
working. Do not start Phase 1 without Matthew confirming Phase 0 looks correct.
```

---

## Pre-Build Checklist (Matthew completes before handing to Claude Code)

- [ ] Provide real earned cause names, URLs, and `why_i_care` text for `ledger.json`
- [ ] Provide real reluctant cause name, URL, and `joke_note` for `ledger.json`
- [ ] Confirm default amounts: $50 bounty / $75 punishment (or adjust)
- [ ] Confirm which achievement badge IDs to ledger-link first (e.g. weight milestones only)
- [ ] Decide: seed any retroactive entries before launch, or start fresh?
- [ ] Copy this spec file to `docs/LEDGER_SPEC_FINAL.md` in the project repo
