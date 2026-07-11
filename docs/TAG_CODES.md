# Tag-Code Legend

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-06-07

This codebase labels work with short tag-codes in **commits, code comments, `docs/BACKLOG.md`, and `docs/CHANGELOG.md`** (e.g. `IC-3`, `PG-10`, `SEC-02`, `COST-OPT-1`, `R17-04`). They come from successive audit / backlog / sprint cycles. This file decodes the **families**; for any specific item, see "How to decode a specific tag" at the bottom.

> **Rule going forward:** prefer a documented family below, or an `ADR-###`. Don't invent a new prefix without adding it here.

## Decision & architecture
| Tag | Meaning | Lives in |
|---|---|---|
| **ADR-###** | Architecture Decision Record (001–078). The authoritative "why". | `docs/DECISIONS.md` |
| **CONF-##** | Config / constants centralization refactor (CDK `constants.py`, env-var wiring). | `cdk/stacks/` |

## Initiatives (cross-cutting programs)
| Tag | Meaning |
|---|---|
| **SIMP-1 / SIMP-2** | Ingestion-framework initiative — shared extract/validate/write for data-source Lambdas (adopt for new; existing exempt). ADR-056/060. |
| **COST-OPT-1** | Secret caching (15-min Lambda TTL → ~90% fewer Secrets Manager calls). |
| **COST-OPT-2** | Prompt caching (cached system blocks, ~90% discount) + model tiering. ADR-049. |
| **COST-A / COST-B** | Cost-cleanup sweeps — `COST-A` CloudWatch-alarm consolidation; `COST-B` Secrets-Manager consolidation. |
| **IC-# (e.g. IC-3)** | "Intelligence" AI passes — `IC-3` is the chain-of-thought analysis pass (Haiku) run before coaching output. |

## Backlog families (work items, tracked in `docs/BACKLOG.md` → shipped in `docs/CHANGELOG.md`)
| Prefix | Domain |
|---|---|
| **PG-##** | **Product & Growth** — the 2026-06-07 Product/Personal summit backlog (ADR-078). |
| **P#.#** | V2-audit phase/plan items (e.g. `P2.4`, `P4.1`) — see `docs/archive/V2_AUDIT_PLAN.md`. |
| **N-##** | New work surfaced post-V2. |
| **S-##** | Site / public-website (v4) follow-ups. |
| **D-##** | Data / deploy items. |
| **B-##** | Bug-fix backlog. |
| **L-##** | Lower-priority / docs / library items. |
| **F-##** | Character-engine statistical-review findings. |
| **TD-##** | Tech-debt items (e.g. `TD-20` = `platform_logger` fix). |

## Engineering work-request families (mostly in code comments + commits)
| Prefix | Domain |
|---|---|
| **R17-##** | "Round 17" hardening batch (e.g. `R17-04` = separate site-api Anthropic key via CDK env). |
| **WR-##** | Work Request (e.g. `WR-40` = question safety-filter on `/api/ask`). |
| **SEC-##** | Security work (e.g. `SEC-02` = CDK-owned WAF association — since **removed**, WAF deleted 2026-06). |
| **OBS-##** | Observability (e.g. `OBS-03` = EMF metric on rate-limit hit). |
| **BS-##** | Subscriber/email backend (e.g. `BS-03` = the email-subscriber Lambda). |
| **HP-##** | Home-page / share-card work (e.g. `HP-13` = OG share card). |
| **TB#-##** | Tech-backlog (e.g. `TB7-25` = auto-rollback on smoke-test failure). |
| **A11Y** | Accessibility (see `docs/A11Y_BASELINE.md`). |
| **lv#** | A test-name shorthand from the retired layer-consistency suite (the suite was removed with the layer, #781; the invariant is now `test_i2_shared_layer_retired`). |

## How to decode a specific tag
1. **Shipped?** → `grep "<TAG>" docs/CHANGELOG.md` (what landed + when).
2. **Open?** → `grep "<TAG>" docs/BACKLOG.md` (the item's why/acceptance).
3. **A decision?** → `docs/DECISIONS.md` for `ADR-###`.
4. **In code?** → `grep -rn "<TAG>" lambdas/ cdk/ mcp/` (the comment usually states the intent inline).

Most tags are historical work-tracking, not load-bearing identifiers — they exist so a change can be traced back to the decision that motivated it.
