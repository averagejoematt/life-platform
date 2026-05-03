# Handover — v6.8.4: PR 2 — Todoist daily cron + PR template + parity-debt label (TD-12/14/17)

**Date:** 2026-05-03
**Scope:** Three small housekeeping items from `docs/specs/TD_QUICK_DECISIONS.md`.

See [HANDOVER_v6.8.4.md](HANDOVER_v6.8.4.md) for full details.

## Summary

- **TD-12** [LOW]: Todoist EventBridge schedule dropped from `cron(15 14,2 * * ? *)` (2x daily) to `cron(0 14 * * ? *)` (1x daily, 6 AM PST / 7 AM PDT). Reality vs spec drift noted: spec said "every 4hr / 6 invocations/day" but CDK had 2x daily; intent (reduce invocation count) preserved.
- **TD-14** [MED]: `.github/PULL_REQUEST_TEMPLATE.md` added with a backfill ↔ live Lambda parity-check section. `parity-debt` GitHub label created (amber, `#FBCA04`).
- **TD-17** [LOW]: Matthew action item (disable Tier-2 feeds in Health Auto Export iOS app). No code change.

## Spec archived

`docs/specs/TD_QUICK_DECISIONS.md` → `docs/archive/TD_QUICK_DECISIONS_2026-05-02.md`

## Current State

| Metric | Value |
|--------|-------|
| Version | v6.8.4 |
| Lambda Layer | v42 (unchanged) |
| Lambdas | 66 |
| MCP Tools | 123 |
| Todoist invocations/day | 1 (was 2) |
