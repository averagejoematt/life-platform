# will be overwritten immediately below
---

## ADR-025 — composite_scores vs computed_metrics: Consolidate into computed_metrics

**Status:** Active  
**Date:** 2026-03-14 (v3.7.22, R9 hardening)  
**Context:** Viktor Sorokin (R9) raised whether SOURCE#composite_scores (v3.7.20) duplicates SOURCE#computed_metrics. ~80% field overlap.

**Decision:** Consolidate into computed_metrics. Remove composite_scores. Execute before SIMP-1 Phase 2.

**Reasoning:** (1) No distinct access pattern — computed_metrics already serves this purpose. (2) Field overlap is a coherence liability with no tie-breaker rule. (3) Two writes for the same data risk temporal divergence. (4) computed_metrics is the established SOT since IC-8.

**Migration:** Remove write_composite_scores() from daily_metrics_compute_lambda.py. Redirect weekly_correlation_compute_lambda.py's composite fetch to computed_metrics. Update SCHEMA.md.

**Outcome:** Consolidate before Apr 13.

---

## ADR-026 — Local MCP Endpoint: AuthType NONE + In-Lambda Key Check (Accepted)

**Status:** Active  
**Date:** 2026-03-14 (v3.7.22, R9 hardening)  
**Context:** Local MCP Function URL uses AuthType NONE + x-api-key in-Lambda. Remote uses HMAC Bearer. Yael (R9) asked for explicit documentation.

**Decision:** Retain current model. Document as accepted design.

**Reasoning:** (1) Both endpoints require auth — local validates x-api-key before any processing. (2) IAM AuthType breaks Claude Desktop bridge (would need SigV4 signing). (3) Unguessable URL (~160-bit entropy) + in-Lambda auth is strong for a personal project. (4) HMAC Bearer consistency is cosmetic — no meaningful security gain.

**Outcome:** Document and accept. No migration planned.
