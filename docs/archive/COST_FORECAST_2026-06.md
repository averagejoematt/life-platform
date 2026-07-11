# Cost Forecast — One-Pager (2026-06-16)

**The short answer:** steady-state run-rate is **~$70/mo all-in** (~$63 before tax). The AWS ">$75"
forecast is real for *June specifically* (~$90–100) — but that's **one-time work banked into this
month** (cycle-4 reset, the 558-agent elite review, podcast generation, this cost investigation),
not the recurring baseline. July regresses to ~$70.

**Why it crept from the $30 plan:** the $30 budget was the *pre-intelligence* platform — ingest,
store, static site. That layer is still **~$24/mo** and barely moved. Everything above $30 is the
**AI / coaching layer you added since** (~$38/mo). The creep is almost entirely the *product value*,
and it's controllable through the AI levers below — **not** by cutting infrastructure.

---

## 1. Where the money goes (trailing-7d run-rate → monthly)

### A. Infrastructure & platform fees — **~$24/mo** (always-on, independent of features)
| Line | ~/mo | Note |
|---|---|---|
| CloudWatch | $13 | logs + ~50 alarms ($5) + custom metrics. **Biggest infra lever.** |
| Secrets Manager | $7.2 | flat: ~18 secrets × $0.40/mo storage |
| Cost Explorer API | $2 → ~$1 | the governor's *own* polling — **halved today** (#138, 4h→8h) |
| KMS | $1 | key usage |
| S3 + DynamoDB | $0.8 | raw JSON + single-table; near-free |
| Route53 / CloudFront / API GW / Lambda | $0.1 | **the entire ingest→store→serve pipeline is ~$0** |

### B. Feature fees — **~$38/mo** (the AI / intelligence layer = the product)
| Driver | Model | ~/mo | Frequency |
|---|---|---|---|
| Coach board narratives + state/quality/ensemble | Haiku | ~$22 | **daily** — the dominant AI cost |
| Daily brief (executive summary / BoD) | Sonnet | ~$6 | daily |
| Compute intelligence (insight, adaptive, anomaly, hypothesis) | Haiku | ~$6 | daily / weekly |
| Weekly + monthly digests, Partner email | Sonnet | ~$3 | weekly / monthly |
| Weekly podcast (write + editor + gate) | Sonnet/Haiku | ~$1 | Fridays |
| Website AI (`/api/ask`, `/api/board_ask`) | Sonnet/Haiku | traffic | **currently paused (tier 2)** |

*(Bedrock service totals are exact from Cost Explorer: Haiku ~$28/mo, Sonnet ~$10/mo. The per-feature
split is a designed allocation — see telemetry gap in §3, guardrail G1.)*

**Tax** adds ~$7/mo proportionally (unavoidable).

---

## 2. What to lower / reduce / leave alone

### ✅ Safe to lower now (zero product impact) — ~$5–7/mo
- **CloudWatch log retention** — shorten/expire logs on chatty Lambdas. Most headroom in the $13 line.
- **Secrets consolidation** — bundle rarely-rotated secrets (18 → ~10) ≈ **−$3/mo**. *Needs its own
  careful PR* — a botched merge breaks ingestion auth.
- **CE polling** — **done** (#138, ~−$1/mo).

### ⚠️ Reduce only if you *want* the savings (feature trade-offs)
- **Change-gated coach narratives** — regenerate a coach only when its inputs moved meaningfully;
  reuse yesterday's otherwise. **Biggest single AI lever (~−$10/mo)**, small UX hit.
- **Model-tiering** weekly/monthly/Partner Sonnet→Haiku ≈ −$2–4/mo, minor quality risk.

### 🚫 Not recommended to change
- **Prompt caching** — can't re-enable; cross-region Bedrock (mandatory `us.` prefix) defeats it (D-01).
- **Daily-brief AI** — highest signal, small token cost. Leave on Sonnet.
- **Ingest→store→serve pipeline** — already ~$0; nothing to gain.
- **Budget-guard tiers** — that's the safety net; don't weaken it.
- **Ingestion failure / auth-liveness alarms** — they catch silent data-death; the $0.60/mo is cheap insurance.

---

## 3. Guardrails — protect against anomalies (dev-process)

The real risk isn't the steady $70 — it's an unnoticed *spike*. Recommended, highest-value first:

1. **(G1) Close the per-feature AI telemetry gap.** Today the token metrics capture only ~$1 of the
   ~$9/wk AI spend — most AI Lambdas don't emit `Anthropic*Tokens` dimensioned by `LambdaFunction`.
   **You currently can't tell which feature spiked from a query.** Make every `bedrock_client.invoke()`
   path emit tokens by feature. *Single most valuable fix.*
2. **(G2) Daily-spend anomaly alarm.** A CloudWatch anomaly-detection band on daily total cost →
   pages within *hours* of a 2× day, instead of discovering it at month-end forecast.
3. **(G3) Separate "dev/ops AI" from "production feature AI."** Resets, multi-agent reviews (the
   558-agent run was a real cost event), and bulk regen are what pushed June to ~$90. Tag/budget them
   so dev activity doesn't trip the production governor — and so the baseline stays legible.
4. **(G4) Finish the projection fix.** #137 put AI on a trailing window; **non-AI still uses lumpy
   MTD-linear**, so month-start fixed charges over-project the forecast. Extend the trailing window to
   non-AI (the "(B)" follow-up) so the governor's number is honest.
5. **(G5) Cost-allocation tags by feature** → Cost Explorer groups by feature natively, removing the
   §1.B allocation guesswork.

---

## 4. Bottom line
- **Recurring baseline: ~$70/mo**, of which ~$24 is unavoidable infra and ~$38 is the AI you'd never
  want to cut. Under the $75 ceiling.
- **June is a ~$90–100 outlier** from one-time work; it self-corrects July 1 (and the paused website
  AI un-pauses then automatically).
- **Easy wins ~$5–7/mo** (logs, secrets) with no product impact; **bigger AI savings exist** but cost
  product quality — only pull them if you want to.
- **The durable protection is G1+G2**: make spend attributable per-feature and alarm on daily
  anomalies, so the next creep is visible in hours, not at month-end.

*Figures: AWS Cost Explorer trailing-7d (Jun 9–16) × 30, by service; AI split by design + token telemetry.*
