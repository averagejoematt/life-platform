# model/

The generated system model (#2845, epic #2842) — `platform_model.json` is the
machine-readable source of truth for lambdas, schedules (one row per lambda×cron with a
UTC clock), alarms + routing (the full #795 inventory incl. composites, routing traced
through factories/helpers/composites — #3314), privacy tiers (from
`lambdas/privacy/field_tiers.py`), DDB partitions (the ADR-077 census, each stamped with
its privacy tier), producer/consumer contracts, and module→partition consumer edges.

**The boot contract (#3314):** `scripts/boot_brief.py` renders what a session or routine
reads from this model at boot (`BOOT_CONTRACT`); `scripts/hooks/session_preflight.py`
prints it on every SessionStart, and `tests/test_boot_contract_3314.py` pins that the
brief is derived, that a hand-edited model renders STALE, and that prose never disagrees.

**Never hand-edit.** Regenerate with `python3 scripts/generate_platform_model.py`
(also re-renders `docs/DEPENDENCY_GRAPH.md`); CI diffs both via
`tests/test_platform_model_drift.py`. Query with
`python3 scripts/blast_radius.py --touches <partition>` / `--feeds <module>` /
`--alarm <name>` / `--at <HH>` / `--privacy <source>` / `--lambda <name>`.
