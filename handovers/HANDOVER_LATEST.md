# Handover — v6.8.6: PR 4 — Function Health v2 (MCP + supplements page + labs v1.5)

**Date:** 2026-05-03
**Scope:** PR 4 (4a + 4b + 4c) — surface the FH 2026 lab draw through MCP tooling, the public site labs page, and a new private supplements protocol page.

See [HANDOVER_v6.8.6.md](HANDOVER_v6.8.6.md) for full details.

## Summary

- **PR 4a (MCP):** `get_lab_deltas` + `get_allergies` + `cadence_trackers` augment to `get_labs`. NfL=180d, Galleri=365d. Tool count 123 → 125. Galleri framing reworded per Technical Board ("No signal at 24-mo threshold" instead of raw "NO CANCER SIGNAL DETECTED").
- **PR 4b (Supplements):** `/supplements/protocol/` — new private page rendering the May 2026 supplement protocol v2 from S3. Auto-gated by site-wide `PRIVACY_MODE=true`. Habitify integration deferred until TD-11 ships.
- **PR 4c (Labs):** Additive v1.5 section on `site/labs/index.html` — IRS gauge, Cardio IQ panel summary, allergy chips, NfL+Galleri annual sentinel widgets. No refactor of v1 rendering. Trend charts deferred to future workstream.

## Spec archived

`docs/specs/FUNCTION_HEALTH_V2_HANDOFF.md` → `docs/archive/FUNCTION_HEALTH_V2_HANDOFF_2026-05-02_tonight.md`

## Current State

| Metric | Value |
|--------|-------|
| Version | v6.8.6 |
| MCP Tools | **125** (was 123) |
| Site pages | +1 |
