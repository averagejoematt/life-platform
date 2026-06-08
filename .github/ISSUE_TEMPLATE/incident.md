---
name: Incident
about: Production outage, data loss, security, or budget event
title: "incident: "
labels: incident, priority
---

## Summary
One line: what happened, when (UTC), current status.

## Severity
- [ ] SEV1 — data loss / security / budget tier-3 / site down
- [ ] SEV2 — degraded (one pillar/source down, AI paused)
- [ ] SEV3 — minor / cosmetic

## Timeline (UTC)
- Detected:
- Mitigated:
- Resolved:

## Impact
Sources / users / data affected.

## Detection
Alarm / canary / smoke / manual. (See `docs/MONITORING.md`.)

## Mitigation & root cause
What stopped the bleeding; the underlying cause.

## Follow-ups
Action items → link a PR or an ADR. Record the post-mortem in `docs/` (rca/ or INCIDENT_LOG).
