# CHAT_MODES.md — conversation as an ingestion channel

> **Status:** foundation doc, scoped to what's verified. `#1479` (chat-mode command
> library, same epic — `#1476` chat-journey: conversation as the 4th ingestion channel)
> will likely expand this with the actual per-mode prompts; this doc only covers the
> connector-capability findings `#1480` verified — it does not define the modes
> themselves.

## Why this exists

The revival plan for the Notion journal channel (the SOT for subjective data — it feeds
enrichment → PERMA flourishing → the Mind pillar) is Claude-interview entries: a
journal-interview chat mode that writes structured pages to the Notion journal database
via the Notion MCP connector (`notion-create-pages` / `notion-update-page`), rather than
Matthew hand-typing into Notion. This doc records what that connector can and can't set
on a page at creation time, verified against `lambdas/ingestion/notion_lambda.py`'s
actual parsing behavior (`tests/test_notion_mcp_page_guard_1480.py` pins the findings
below as regression tests).

## What the connector can set

Properties are passed to `notion-create-pages` as a flat JSON map: `property name →
string | number | null`. There is **no structural block** on setting a `select`
property (like `Template`) or a plain string/title/rich_text/number/checkbox property
at page-creation time, **provided**:
- the integration has write access to the target database, and
- the exact property name and a valid select-option name are used (e.g.
  `"Template": "Evening"` must match one of the database's actual select options —
  `Morning`, `Evening`, `Weekly Reflection`, `Stressor`, `Health Event`).

So: **`Template` does NOT need to be set by hand.** A journal-interview chat mode can
set it directly via the connector, and `notion_lambda.py`'s `parse_page()` recognizes it
through the canonical `TEMPLATE_SK` map exactly as if it had been picked from the Notion
UI — the ingest path is schema-flexible and doesn't distinguish creation method.

## The one gotcha: the Date property's expanded key syntax

**Date properties need an expanded key format, not a plain value.** A plain
`"Date": "2026-07-19"` is *not* the right shape — the Notion MCP tooling expects the
expanded key convention:

```
"date:Date:start": "2026-07-19"
"date:Date:end": null            (optional)
"date:Date:is_datetime": false   (optional)
```

This is documented explicitly on `notion-update-page`'s tool schema; `notion-create-pages`
uses the same underlying properties schema, but its (truncated) tool description doesn't
spell out the date-expansion convention as explicitly. **Flag this as the one thing worth
testing live before relying on it** — a malformed or omitted date key would silently
produce a page with no `Date` property set, not an error.

**Failure mode if the date key is wrong: degraded, not broken.** `notion_lambda.py`'s
`parse_page()` already tolerates a missing `Date` property — it falls back to the page's
`created_time`, converted to Pacific Time, to derive the entry's date
(`notion_lambda.py` ~L474–487). A malformed date key therefore doesn't lose the entry; it
just anchors it to "when the page was created" instead of an explicit (possibly
backdated) date. That matters if an entry is written the morning after the day it
describes — the created_time fallback would misdate it to the write day, not the day
being journaled about. `tests/test_notion_mcp_page_guard_1480.py` pins both the
happy path (explicit `Date` set) and the fallback path (created_time → PT date,
including the UTC-day-boundary case for late-night entries).

## Net effect

No property is structurally connector-blocked. The one operational caveat is getting
the Date property's expanded key syntax right — or accepting the created_time fallback,
which works but is less precise for backdated entries. This should be confirmed with one
live test page before a chat mode is relied on for daily journaling (see `#1480`'s PR
for the exact manual verification steps).

## Why this matters beyond the journal itself

The journal channel had gone dark for extended stretches with no alarm — the generic
per-source freshness check tolerates Notion for 14 days (a deliberately lenient
evening-nudge threshold for ad-hoc journaling, `#746`) and the `notion` source-registry
entry is `monitored: False`, which structurally excludes it from the freshness checker's
paging path at *any* staleness. `#1480` added a separate, tighter guard —
`check_notion_journal_staleness()` in `lambdas/emails/freshness_checker_lambda.py` —
that alerts when the journal goes dark for more than `NOTION_JOURNAL_DARK_ALERT_DAYS`
(default 7) days, because journaling is a daily practice and enrichment → PERMA
flourishing → the Mind pillar all go quiet with it. That guard's alert message points
back at this doc as the "what to do" — write an entry, or run a journal-interview chat
mode once one exists (`#1479`).
