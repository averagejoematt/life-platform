#!/usr/bin/env python3
"""scripts/ci_job_timeouts.py — the per-job `timeout-minutes` registry (#3678).

WHY THIS EXISTS
----------------
`Collect + deploy-critical + format` (`.github/workflows/pr-checks.yml`) carried
`timeout-minutes: 15` against an observed 13m57s-15m22s band — the ceiling sat
INSIDE the job's own noise band, so it killed healthy runs and GitHub rendered the
kill as `cancelled`, which reads as a supersession rather than a defect. The
config's own comment asked for a re-measurement before the number was trusted
again; #3678 is that instruction come due, and the FIX has to be a script, not
another comment, or the third instance of this class (after #3134's suite budget
and #3403's Unit-Tests budget-at-the-mean) lands silently too.

A script needs ONE thing neither `check_job_timeout_headroom.py` (the derivation
guard) nor `ci_run_verdicts.py` (the cancelled-run discriminator) should each grow
their own copy of: the declared `timeout-minutes` ceiling for every job, by the
NAME GitHub actually reports it under (the job's `name:` field — the check-run
name a driver reads, not the YAML job id). This module is that ONE registry, in
the same shape as `scheduled_workflow_registry.py`: derive from the workflow
files, never hand-type a ceiling here.

A job with no explicit `name:` reports under its YAML job id verbatim (GitHub's
own default) — `job_name` below falls back to the id in that case. A job whose
`name:` is a template (`${{ matrix.language }}` etc.) cannot be resolved to a
literal check-run name without knowing the matrix values, so it is reported with
`templated=True` and excluded from `timeout_minutes_by_job_name()` — asserting
against an unresolved template would be a false measurement in either direction,
never a real one.
"""

from __future__ import annotations

import os
import re
from typing import Any

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOW_DIR = os.path.join(REPO_ROOT, ".github", "workflows")

_TEMPLATE_RE = re.compile(r"\$\{\{.*\}\}")


def _load_yaml(text: str) -> dict:
    import yaml  # local import: keeps this module importable where PyYAML is absent

    doc = yaml.safe_load(text) or {}
    return doc if isinstance(doc, dict) else {}


def iter_job_timeouts(workflow_dir: str | None = None) -> list[dict[str, Any]]:
    """Every job declaring `timeout-minutes` across every workflow file, as a flat list.

    Each entry: `{file, job_id, job_name, timeout_minutes, templated}`.
    `job_name` is the literal GitHub check-run name (the `name:` field, or the
    job id when no `name:` is given) — `templated=True` when that name still
    contains an unresolved `${{ ... }}` expression.

    Pure over the files it reads; takes `workflow_dir` so tests can point it at a
    fixture directory instead of the real `.github/workflows/`.
    """
    directory = workflow_dir or WORKFLOW_DIR
    out: list[dict[str, Any]] = []
    if not os.path.isdir(directory):
        return out
    for entry in sorted(os.listdir(directory)):
        if not entry.endswith((".yml", ".yaml")):
            continue
        path = os.path.join(directory, entry)
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        doc = _load_yaml(text)
        jobs = doc.get("jobs")
        if not isinstance(jobs, dict):
            continue
        for job_id, job in jobs.items():
            if not isinstance(job, dict):
                continue
            timeout_minutes = job.get("timeout-minutes")
            if timeout_minutes is None:
                continue
            job_name = job.get("name") or job_id
            job_name = str(job_name)
            out.append(
                {
                    "file": entry,
                    "job_id": job_id,
                    "job_name": job_name,
                    "timeout_minutes": timeout_minutes,
                    "templated": bool(_TEMPLATE_RE.search(job_name)),
                }
            )
    return out


def timeout_minutes_by_job_name(workflow_dir: str | None = None) -> dict[str, float]:
    """`{job_name: timeout_minutes}` for every NON-templated job with a declared ceiling.

    Templated names are dropped here (see the module docstring) rather than
    resolved partially — a caller matching a real check-run name against this map
    gets either a real ceiling or nothing, never a guess.
    """
    return {e["job_name"]: e["timeout_minutes"] for e in iter_job_timeouts(workflow_dir) if not e["templated"]}


if __name__ == "__main__":  # pragma: no cover - manual/debug CLI
    import json
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--get-timeout":
        name = sys.argv[2]
        mapping = timeout_minutes_by_job_name()
        if name in mapping:
            print(mapping[name])
            sys.exit(0)
        sys.exit(1)
    print(json.dumps(iter_job_timeouts(), indent=2))
