# model/

The generated system model (#2845, epic #2842) — `platform_model.json` is the
machine-readable source of truth for lambdas, schedules, alarms + routing, DDB
partitions (the ADR-077 census), and module→partition consumer edges.

**Never hand-edit.** Regenerate with `python3 scripts/generate_platform_model.py`
(also re-renders `docs/DEPENDENCY_GRAPH.md`); CI diffs both via
`tests/test_platform_model_drift.py`. Query with
`python3 scripts/blast_radius.py --touches <partition>` / `--feeds <module>`.
