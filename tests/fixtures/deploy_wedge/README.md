# deploy-wedge fixtures (#2052)

Real GitHub Actions API payloads for the four in-flight deploy states, trimmed to the
fields `scripts/check_deploy_wedge.py` reads. Provenance for each is recorded in the
fixture's own `_provenance` key.

Why real payloads matter here: three of these states are **byte-identical at the
single-run level** (`run.status=pending`, `Deploy` job `status=pending`,
`pending_deployments=[]`). A hand-written fixture would have quietly encoded the
wrong discriminator — which is exactly the mistake the five recurrences kept making.

| Fixture | State | Captured |
|---|---|---|
| `awaiting_approval.json` | gate OPEN, young | live, 2026-08-03 |
| `stranded_approval.json` | gate OPEN, aged past the threshold | live capture, clock advanced |
| `queued_behind.json` | Deploy blocked, a real holder exists | live, 2026-08-03 |
| `phantom_wedge.json` | Deploy blocked, **no** holder | 2026-08-02 recurrence |
