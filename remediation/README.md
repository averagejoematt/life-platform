# remediation/

The remediation agent (ADR-064; shadow permanently per the ADR-129 amendment of 2026-08-30,
#2833). **Kept, load-bearing:** `agent.py` triages CloudWatch alarms / failed CI / DLQ depth /
QA-smoke results, opens PRs a human merges, and sends the one curated needs-human email;
`drift_report.py` renders the weekly infra-drift + Actions-quota status into that email;
`track_record.py` derives the public track record from the audit log. The deterministic
auto-merge gate (`automerge.py`) and the auto-earn marker were retired with `auto` mode —
there is no self-merge path. Driven by `.github/workflows/remediation-agent.yml`
(Mon/Wed/Fri + urgent dispatch). See `docs/REMEDIATION_TAXONOMY.md` and `docs/REPO_STRUCTURE.md`.
