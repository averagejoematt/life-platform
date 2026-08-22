# The Proportionality Ledger — does this complexity earn its keep?

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-08-22

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
| Permanence archive (nightly public snapshot + continuity switch, #2572) | Load-bearing | S3 (~GBs), one nightly writer | The stolen-laptop/continuity contract in writing — the site survives its operator. Demote: if the nightly writer fails silently >7d with no alarm catching it, the machinery is theater — alarm it or fold it |
| Coach voice notes (Telegram sendVoice, #2552) | Experiment | Google TTS $ per note, budget-gated | Persona texture measured against real chat use. Demote: if <1 voice note/week is actually played by the owner over a month, retire the path |
| Outbound initiative pings (celebration + soft-concern, #2527) | Experiment | Bedrock $ within the 2/day outbound cap | The coaches text FIRST when the data moves — the #2490 priority ladder bounds volume. Demote: if the owner mutes/ignores >50% over a month, the initiative reads as notification spam and the classes retire |
| Gate census + can-it-fail proofs (epic #2578) | Load-bearing | CI seconds, session attention | 425 declared gates with measured error bars; the week's cannot-fail finds (#2746, #2754) came from it. Demote trigger: census derivation cost exceeding one CI minute, or two consecutive sessions with zero acted-on findings |
| Proportionality-ledger wrap gate (`check_proportionality_ledger.py`, #2380/#2761) | Load-bearing (small) | session attention (~1s per wrap) | Keeps THIS ledger a live inventory, not a snapshot — the prose-only #2380 version produced zero ledger commits in its first week while four standing systems shipped. Demote trigger: two consecutive quarterly reviews find the `**Ledger:**` line rubber-stamped (`none` while unledgered machinery shipped) — then the script measures nothing, redesign or fold it into the census |
| Kernel conformance guard (#2844) | Load-bearing | CI seconds (one AST sweep per unit-test run), mind (the ledger discipline) | The charter's standing rule 1 made executable — closes the missed-consumer class (the elite review's WS-A trace: SOCIAL_CHANNELS, _BROADCAST_SOURCES, ALL_LAMBDAS-at-40) by construction; the ledger (37 dated entries at birth, 2026-08-17) only shrinks. Demote trigger: two consecutive sessions where a red is resolved by loosening thresholds instead of deriving a site — that's the guard mis-tuned, re-scope its vocabularies |
| System model + drift gate (#2845) | Load-bearing | CI seconds (~30s regenerate+diff per unit-test run) | The kernel's second primitive artifact: one generated source of truth (lambdas/schedules/alarms/partitions/edges) with blast-radius lookup; subsumes the hand-prose DEPENDENCY_GRAPH that misled on the critical path (#2839). Demote trigger: two consecutive sessions where drift reds are resolved by regenerating without reading the diff — then the model isn't informing anyone, fold the doc rendering |
| Deploy-critical lane import guard (#2758) | Load-bearing | ~2s of every premerge + lane run | The #2699/#2732 collection-crash class (redded main twice in 48h) now fails premerge; self-protecting (deploy_critical-marked) with an in-suite mutation proof. Demote trigger: two consecutive quarters with zero catches AND the lane's dep set going unchanged — then fold into the census |
| expert-gate-infra-hold alarm (MetricFilter, #2763) | Watcher | CloudWatch ~$0, attention when red | Pages when the analyzer's grounding gate cannot RUN and holds (reader analyses stop refreshing; nothing wrong is served). Fire-proof: the twin-pinned filter literal. Demote: fold into a consolidated AI-hold alarm if a second hold class ships |
| between-chronicle scrub-failed alarm (MetricFilter + `between-chronicle-scrub-failed-closed`, #2654) | Watcher | CloudWatch (~$0), attention when red | Pages when the outbound privacy scrub fails CLOSED (nothing leaked; the digest went dark and silence must not be the only tell). Filter fire-proof recorded on #2654. Demote: if the fail-closed abort never fires in 12 months AND the vocabulary channel gains its own end-to-end canary, fold into the canary's alarm |
| 8-coach board + stance engine + orchestrator | Load-bearing | $, mind | The COACHING pillar — the product |
| Coach feedback loop (nudges #1382, docket #1386, dossier #1387, review pack #1698, calibration ADR-141) | Load-bearing | $, attention | The coaching layer's learning loop; first real-data cycle starts 2026-07-27 — findings-empty rule applies from Q4 |
| Budget governor + budget_guard | Load-bearing | attention | Enforces the ADR-063/133 ceiling; the reason rent class `$` stays bounded |
| Freshness / ingest-liveness / reconciliation detectors | Load-bearing | CI, attention | The silent-failure coverage class (the 44-day-Garmin lesson) |
| Character engine + sheet | Load-bearing | $, mind | Public flagship page |
| Deploy guardrails (clobber guard, postflight, drift checks, one-bundle rule) | Load-bearing | CI | Each earned by a real incident (see CONVENTIONS.md) |
| Weekly Panel podcast pipeline | Load-bearing (STORY) | $, surface | Live no-touch pipeline (ADR-135); #1737 performance epic in flight. **Dated re-check: TTS/dialogue-vendor landscape due 2026-10-27, owner Matthew** (ADR-087 amendment 2026-07-27 / #1741 — the previous monitor trigger carried no date and went two months unnoticed; record the result even when nothing changed) |
| Reading pillar (2 GSIs, tools, page) | Load-bearing (small) | mind | The owner's real instrument |
| MCP server (75 tools post-#395 prune) | Load-bearing | surface, mind | The instrument itself; tool removals ride the MCP_TOOL_AUDIT ratchet |
| Conversation channel (chat-journey ADR-141/142, journal quotes, intake) | Load-bearing | $, mind | The fourth ingestion surface; consent machinery is the fence |
| Paging channel (ADR-143, ≤5-alarm P1 set) | Load-bearing (small) | attention | Guard-tested ≤5 cap; 2 false pages/quarter reopens membership |
| Stats/forecast machinery (stats_core, hypothesis tester, calibration ledger) | Load-bearing | mind | The credibility moat (ADR-105) |
| personal-baselines monthly compute | Load-bearing | $ (small) | Bands from own variance (ADR-105 r4); retire only if banded verdicts stop |
| AI-vision QA (Bedrock semantic screenshots) | Load-bearing | $, CI | Gating CI since 2026-06-05 |
| Required pre-merge lane (ADR-148 + the structural-gate extension, #1662/#2372-adjacent) | Load-bearing | CI | Rent: ~3 min CI per PR. Earned same-fortnight: caught I5/SR1/I3/type-hints on the Telegram surface pre-merge and 3 union/size breaches on 2026-08-09 alone. Demote trigger: a quarter with zero pre-merge catches (2026-08-09) |
| Module-size ratchets ×2 (1200-line hard ceiling + BASELINE no-grow, #1665) | Load-bearing | CI | Self-justified by four same-day catches at BASELINE enforcement start (2026-08-09, incl. two on this very ledger's fortnight PRs); the #2373 coupling assertion is its named follow-up. Demote trigger: per the guard's own text — baselines only shrink |
| Recall corpus writer + freshness watcher (semantic_recall, #1384/ADR-150) | Load-bearing (small) | $ (embeddings, small), CI | Publish-time indexing + nightly link/existence QA; corpus froze 18 days when it had no automated writer — the watcher is the anti-recurrence. Demote/scope trigger: #2347's corpus-scope decision (2026-08-09) |
| SDLC review rituals (/fullreview, /platform-review, /site-review, /accuracy-review, /sdlc-review) | Load-bearing (rotating) | $ (~2–3M tokens/run), attention | Demote any ritual findings-empty twice consecutively (standing rule above) |
| golden-brief-eval workflow | Load-bearing | CI | Deterministic canary gating every push |
| Remediation agent (ADR-064/065) | **Portfolio** | CI, surface | In `shadow` (ADR-129); earns `auto` only via the 10-clean-run bar; earns Load-bearing only shipping real fixes monthly |
| fresh-eyes weekly survey workflow | Portfolio | $ (small) | Too new to grade; revisit at 3+ runs |
| Personal/Product deliberation boards (BOARDS.md) | Portfolio | none (no runtime) | Decision-quality tooling demonstrated in public |
| Social syndication poster (#1629, gated/unbuilt, ADR-140) | Portfolio | none yet | Dated retire trigger: 90 days live with no measured referral traffic |
| Daily-fingerprint broadcast payload (#1402, `content/fingerprint_broadcast.py` + the `og_moments` fingerprint sweep) | Portfolio | S3 (one dated PNG + shell/day) | No new service: the card is the unchanged #1379 render and the sweep is one more class in the existing moments pass. Human-post-only by ADR-140 rule 5. Retire trigger: **90 days with no manual fingerprint post** (`post_social.py --report`) → drop the sweep class, keep the page card |
| Social membrane inbound (youtube RSS ingestion, #1668) | Portfolio | surface (small) | Keyless by design; retire if no captures used by a public surface in 90 days |
| /legacy preserved v3 site | Portfolio (archive) | none | Zero maintenance; retire only if storage/privacy cost appears |
| State of Mind subsystem (HAE How-We-Feel) | Kept (load-bearing-pending-data) | mind | ADR-121: habit restart chosen over prune; flips to retire if habit not resumed by 2026-Q4 review |
| Reader-truth debt ledger (`tests/truth_baseline.json`, #2956) | **Load-bearing (small)** | one triaged entry per standing finding; an UNTRIAGED entry reds the unit suite | It is the only thing separating "this deploy broke truth" from "the site carries truth debt" — without it the armed gate rolled back 3 healthy deploys. **Demote when** the ledger reaches zero entries and stays there for a month: at that point the gate can go back to bare. |
| Chronicle / Weekly-Signal delivery dead-men (#2820) | Load-bearing (small) | 2 alarms + one metric emission per send | The subscriber promise is a *promise*; a silent no-send was previously invisible on every channel. **Demote when** delivery moves to a platform that reports its own failures. |
| Alarm flap detector in the wrap citation gate (#2912) | Load-bearing (small) | one `describe-alarm-history` read per wrap | Caught 3 invisible fired-and-cleared episodes on its first live run. **Demote when** alarm periods stop producing sliding-window flap (i.e. the Period=86400 alarms are re-cut). |
| Producer↔gate cron mirror check (#2818) | Load-bearing (small) | one AST diff per `cdk/**`/`lambdas/**` PR | A moved cron silently drifted the QA window for a full winter. **Demote when** QA windows are read from the schedule at runtime rather than mirrored. |
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
