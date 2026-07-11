<!--
Life Platform PR template — added 2026-05-03 (TD-14).

The Backfill / Lambda parity check exists because the platform repeatedly
hits the same drift pattern: a fix gets developed in a backfill script,
lands cleanly there, and the live Lambda doesn't get the same fix because
nobody remembers to port it. TD-15 (HAE Lambda missing source-priority
fix that v16.1 backfill had) was the most expensive recent example.
-->

## Summary

<!-- 1–3 sentences. What changed and why. -->

## Backfill / Lambda parity check

If this PR modifies a `backfill/` script:
- [ ] Equivalent fix is in the corresponding live Lambda in this PR, OR
- [ ] A TD item is filed for the deferred port (link below) and labeled `parity-debt`

If this PR modifies a Lambda that has a corresponding `backfill/` script:
- [ ] Equivalent fix is in the backfill script in this PR, OR
- [ ] A TD item is filed (link below)

If neither applies (e.g., docs-only, infra-only, new feature with no backfill counterpart):
- [ ] Not applicable to this PR

Linked TD items (if applicable):
- [ ] None

## Docs impact (wiki contract — CONVENTIONS §8)

<!-- One of the two MUST be checked. If this PR retires something load-bearing
     (a script, a service, a pattern), also add a rule to docs/_lint/tombstones.txt
     in the SAME PR — that's what keeps every other page from teaching the dead path. -->
- [ ] **Docs updated:** <pages touched>
- [ ] **Docs: none needed** — <one-clause reason>

## Test plan

<!-- How was this validated? Pytest output, manual smoke, CloudWatch logs, etc. -->

## Deploy notes

<!-- Anything operationally visible? Step-count drops, schedule changes, IAM grants, etc. -->
