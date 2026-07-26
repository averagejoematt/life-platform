# The Proportionality Ledger — does this complexity earn its keep?

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-07-26

> **The maintained home of the complexity-posture ledger** (ADR-103 established it;
> ADR-144 made it legible and moved it here). Consult BEFORE adding or removing
> machinery. Posture changes are one-line edits with a dated note; the quarterly
> review re-reads the whole table. **#1666 / epic #1648.**

## The standard (ADR-144)

A one-person platform runs systems at home in a mid-size org — deliberately: the
platform is both an instrument and a public demonstration of engineering practice
(the ADR-078 wedge-B frame). Proportionality is not "have less"; it is **every
standing subsystem names what it costs, what it earns, and what would demote it.**

- **Postures:** `Load-bearing` (product or safety depends on it) · `Portfolio`
  (publicly-demonstrated pattern, justified even at low utilization) ·
  `Retire-candidate` (named removal trigger, never an open-ended "someday") ·
  `Retired` (dated, with the removal record).
- **Rent classes** (what a standing subsystem pays — honest categories, not
  invented dollar figures; the platform's total AI+infra spend is governed
  separately by the ADR-063/133 ceiling): `$` AWS/AI spend is measurable on it ·
  `CI` it runs in or gates the pipeline · `attention` it emails/pages/asks a human ·
  `surface` it adds deploy/IAM/public attack surface · `mind` a successor must
  understand it to operate the platform.
- **The landing rule** (from ADR-103, unchanged): new enterprise-pattern
  infrastructure names its frame in its PR/ADR or it does not land. "Cool to
  have" is not a frame.
- **The demotion rule** (the ADR-129 worked precedent): a posture is earned by
  *measured output*, not design quality. The remediation agent — exemplary
  safety design, zero merged safe-class PRs in ~6 weeks — was demoted to
  `shadow`, and re-promotion carries a numeric bar (10 consecutive clean runs).
  That is the template: demotions cite a measurement, promotions cite a bar.
- **Cadence:** quarterly re-read (with `/platform-review` or `/sdlc-review`);
  any review that finds a subsystem findings-empty twice consecutively proposes
  a demotion row here.

## Active ledger

| Subsystem | Posture | Rent | Earns its keep by / demote trigger |
|---|---|---|---|
| Phase machinery (ADR-077 taxonomy + restart pipeline) | Load-bearing | mind, CI | The experiment's reset semantics; coverage-asserted. 11 cycles of worked use |
| Coherence sentinel + canonical-facts contracts | Load-bearing | CI, attention | The honesty moat's enforcement layer (ADR-104/105) |
| 8-coach board + stance engine + orchestrator | Load-bearing | $, mind | The COACHING pillar — the product |
| Coach feedback loop (nudges #1382, docket #1386, dossier #1387, review pack #1698, calibration ADR-141) | Load-bearing | $, attention | The coaching layer's learning loop; first real-data cycle starts 2026-07-27 — findings-empty rule applies from Q4 |
| Budget governor + budget_guard | Load-bearing | attention | Enforces the ADR-063/133 ceiling; the reason rent class `$` stays bounded |
| Freshness / ingest-liveness / reconciliation detectors | Load-bearing | CI, attention | The silent-failure coverage class (the 44-day-Garmin lesson) |
| Character engine + sheet | Load-bearing | $, mind | Public flagship page |
| Deploy guardrails (clobber guard, postflight, drift checks, one-bundle rule) | Load-bearing | CI | Each earned by a real incident (see CONVENTIONS.md) |
| Weekly Panel podcast pipeline | Load-bearing (STORY) | $, surface | Live no-touch pipeline (ADR-135); #1737 performance epic in flight |
| Reading pillar (2 GSIs, tools, page) | Load-bearing (small) | mind | The owner's real instrument |
| MCP server (75 tools post-#395 prune) | Load-bearing | surface, mind | The instrument itself; tool removals ride the MCP_TOOL_AUDIT ratchet |
| Conversation channel (chat-journey ADR-141/142, journal quotes, intake) | Load-bearing | $, mind | The fourth ingestion surface; consent machinery is the fence |
| Paging channel (ADR-143, ≤5-alarm P1 set) | Load-bearing (small) | attention | Guard-tested ≤5 cap; 2 false pages/quarter reopens membership |
| Stats/forecast machinery (stats_core, hypothesis tester, calibration ledger) | Load-bearing | mind | The credibility moat (ADR-105) |
| personal-baselines monthly compute | Load-bearing | $ (small) | Bands from own variance (ADR-105 r4); retire only if banded verdicts stop |
| AI-vision QA (Bedrock semantic screenshots) | Load-bearing | $, CI | Gating CI since 2026-06-05 |
| SDLC review rituals (/fullreview, /platform-review, /site-review, /accuracy-review, /sdlc-review) | Load-bearing (rotating) | $ (~2–3M tokens/run), attention | Demote any ritual findings-empty twice consecutively (standing rule above) |
| golden-brief-eval workflow | Load-bearing | CI | Deterministic canary gating every push |
| Remediation agent (ADR-064/065) | **Portfolio** | CI, surface | In `shadow` (ADR-129); earns `auto` only via the 10-clean-run bar; earns Load-bearing only shipping real fixes monthly |
| fresh-eyes weekly survey workflow | Portfolio | $ (small) | Too new to grade; revisit at 3+ runs |
| Personal/Product deliberation boards (BOARDS.md) | Portfolio | none (no runtime) | Decision-quality tooling demonstrated in public |
| Social syndication poster (#1629, gated/unbuilt, ADR-140) | Portfolio | none yet | Dated retire trigger: 90 days live with no measured referral traffic |
| Social membrane inbound (youtube RSS ingestion, #1668) | Portfolio | surface (small) | Keyless by design; retire if no captures used by a public surface in 90 days |
| /legacy preserved v3 site | Portfolio (archive) | none | Zero maintenance; retire only if storage/privacy cost appears |
| State of Mind subsystem (HAE How-We-Feel) | Kept (load-bearing-pending-data) | mind | ADR-121: habit restart chosen over prune; flips to retire if habit not resumed by 2026-Q4 review |
| chronicle-podcast season-1 lambda (unscheduled zombie) | **Retire-candidate** | surface | Delete after one further back-catalogue re-render window (2026-Q3 review) |

## Retired (the prunes are the proof)

| Subsystem | Retired | Record |
|---|---|---|
| ~105 unused MCP tools + 64-entry orphan allowlist | 2026-07-08 | #395/ER-04 — pruned 143→60 against 30-day EMF telemetry; `docs/MCP_TOOL_AUDIT.md` |
| apple_health XML import path | 2026-07-04 | #474/D-5 — latent clobber; lambda + role deleted |
| sleep-reconciler / sleep_unified merge | 2026-07-05 | #487, ADR-113 — promised merge never existed; removed with its API + panel |
| Eight Sleep bed-temperature pipeline (5 surfaces) | 2026-07-05 | #489, ADR-118 — 404'd every run for 4+ months; reactivation lead recorded |
| hevy-webhook FunctionURL lambda | 2026-07-06 | #756 — parked URL serving nothing; source kept in git for revival |
| /platform-review `sdlc` lens | 2026-07-18 | #1341 — superseded by /sdlc-review in depth |
| WAF | 2026-06 | Rate limiting moved entirely in-Lambda (DDB-backed) |
| Remediation agent `auto` mode | 2026-07-06 | ADR-129 — the worked demotion precedent; still runs in `shadow` |

## How to read this as a CIO

The platform prunes on measurement (every Retired row cites telemetry or a dead
fetch, not taste), demotes on yield (ADR-129), fences growth structurally
(guard-tested caps like the ≤5 paging set, ratchets like MCP_TOOL_AUDIT), and
prices every standing system in the rent classes above. The surface is large
because the demonstration is the product; it is right-sized because every row
has a trigger someone can pull.
