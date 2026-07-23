# remediation/

The self-healing remediation agent (ADR-064/065). **Kept, load-bearing:** `agent.py` triages
CloudWatch alarms / failed CI / DLQ depth / QA-smoke results, and `automerge.py` is the
deterministic gate that merges only allowlisted safe-class fixes. Driven by
`.github/workflows/remediation-agent.yml` (Mon/Wed/Fri); current mode is `shadow` (ADR-129).
See `docs/REMEDIATION_TAXONOMY.md` and `docs/REPO_STRUCTURE.md`.
