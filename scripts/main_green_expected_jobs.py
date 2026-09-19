#!/usr/bin/env python3
"""scripts/main_green_expected_jobs.py — the EXPECTED-job derivation for #3608 box 2.

NOT a gate, and deliberately not named like one: `check_*`, `verify_*`,
`*_guard`, `*_gate` and `*_audit` are the shapes `scripts/gate_census.py`
recognises, and this module mints no verdict and exits nothing. It answers two
questions for `scripts/check_main_green.py`, which owns the verdict:

  * WHICH jobs should a push to main have produced? (from ci-cd.yml's own jobs
    block)
  * Is this commit in scope at all? (from deploy/sentinel_github.py's
    PUSH_TRIGGER_GLOBS)

It lives in its own file because `check_main_green.py` reached 1114 logical
lines against the #1665 hard ceiling of 1000, and the sanctioned payment for
that is extraction, not a baseline entry. The split is along the real seam: a
derivation over two source-of-truth files on one side, the classifier and its
operator-facing recovery prose on the other.

#3608 box 2 — the EXPECTED job set, and the absence nobody could see.

Every verdict in `check_main_green.py` classifies a job that RAN. A job that never ATTACHED — a
path-filter miss, a job-level `if:` that stopped evaluating true, a workflow
edit that deleted the job — produces no record to classify, so the run rolls
up `success` and this gate reported GREEN. Session W lost hours to exactly
that shape (a Deploy that was stranded rather than failed): absence reads as
"no signal", and no signal reads as fine.

The derivation is `deploy/sentinel_github.py`'s PUSH_TRIGGER_GLOBS (parity-
tested against the live workflow filters in tests/test_drift_sentinel.py) for
"is this commit in scope at all", and ci-cd.yml's OWN job block for "which
jobs should therefore exist". Both are read from the tree, never typed here:
a job added to ci-cd.yml is expected from the moment it is added.

Which jobs count as expected, stated honestly:
  * a job with a job-level `if:` is EXCLUDED — it is conditional by
    construction (deploy, post-deploy-checks, the two rollback/notify jobs),
    and a conditional job that does not attach is the design working.
  * a job WITHOUT an `if:` is expected unconditionally. `needs:`-chaining does
    not excuse it: when an upstream job is skipped, GitHub still emits the
    downstream job with conclusion `skipped`, so it is PRESENT in the jobs
    list. Absence therefore means the job never entered the run at all.
  * a job that `uses:` a reusable workflow reports as `<job-id> / <inner job
    name>` (this is why the live name is `test / Unit Tests`, not `test`), so
    presence is matched on the `<job-id> / ` PREFIX as well as on equality."""

from __future__ import annotations

import os
import re
import sys

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(_SCRIPTS_DIR)

# ci-cd.yml is the workflow whose job set this module derives. Kept as a module
# constant (rather than imported from check_main_green) so the dependency runs
# one way: the classifier imports the derivation, never the reverse.
CI_CD_WORKFLOW_FILE = "ci-cd.yml"


def ci_cd_push_paths(yaml_text: str) -> list[str]:
    """The push `paths:` filter from ci-cd.yml's own trigger block. Pure —
    parses YAML text the caller supplies (never reads the file itself, so this
    is independently testable against a frozen fixture).

    NB: PyYAML's default (YAML 1.1) resolver reads the bare `on:` key as the
    boolean `True`, not the string `"on"` — a real gotcha every workflow-
    parsing script in this repo (`gate_census.py`, `apply_branch_protection.py`)
    has to account for. Both spellings are checked so this does not silently
    return `[]` if PyYAML's behavior ever changes.
    """
    import yaml  # local: keeps the module importable where PyYAML is absent

    try:
        doc = yaml.safe_load(yaml_text) or {}
    except yaml.YAMLError:
        return []
    on = doc.get("on")
    if on is None:
        on = doc.get(True)
    push = (on or {}).get("push") or {}
    return [p for p in (push.get("paths") or []) if isinstance(p, str)]


def _pattern_to_regex(pattern: str) -> re.Pattern:
    """Translate ONE GitHub Actions path-filter glob to a regex. Not a general
    glob engine — covers exactly the constructs ci-cd.yml's filter actually
    uses: `dir/**` (any depth under dir, including nothing), a bare `*` within
    one path segment, and literal filenames/extensions."""
    parts = []
    i, n = 0, len(pattern)
    while i < n:
        if pattern.startswith("**", i):
            parts.append(".*")
            i += 2
        elif pattern[i] == "*":
            parts.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            parts.append("[^/]")
            i += 1
        else:
            parts.append(re.escape(pattern[i]))
            i += 1
    return re.compile("^" + "".join(parts) + "$")


def path_matches_ci_filter(changed_paths: list[str], patterns: list[str]) -> bool:
    """True iff any changed path matches any of ci-cd.yml's `paths:` globs. Pure.

    An EMPTY `patterns` list means "could not read the filter" (not "the
    filter matches nothing") — fail toward treating the push as IN-SCOPE, so a
    parse failure can never manufacture a false path-filter-skip.
    """
    if not patterns:
        return True
    regexes = [_pattern_to_regex(p) for p in patterns]
    return any(rx.match(path) for path in changed_paths for rx in regexes)


def ci_cd_expected_jobs(yaml_text: str) -> dict[str, str]:
    """{job_id: display name} for every job ci-cd.yml declares WITHOUT a
    job-level `if:`.

    The display name matters: a job with a `name:` key reports under THAT
    string, not under its id (`reconcile` reports as "Reconcile derived
    artifacts"), so a matcher that only knew ids would call every named job
    absent and red every run. Both spellings are carried and both are accepted
    by `absent_expected_jobs`. Pure — parses
    caller-supplied YAML text so it is testable against a frozen fixture, the
    same discipline `ci_cd_push_paths` above uses (including its `on:`-is-True
    gotcha, which does not arise here but would if this ever read triggers)."""
    import yaml  # local: keeps the module importable where PyYAML is absent

    try:
        doc = yaml.safe_load(yaml_text) or {}
    except yaml.YAMLError:
        return {}
    jobs = doc.get("jobs") or {}
    if not isinstance(jobs, dict):
        return {}
    out: dict[str, str] = {}
    for job_id, spec in jobs.items():
        if not isinstance(spec, dict) or spec.get("if"):
            continue
        name = spec.get("name")
        out[str(job_id)] = str(name) if isinstance(name, str) and name else str(job_id)
    return out


def load_ci_cd_expected_jobs(repo_root: str | None = None) -> dict[str, str]:
    """`ci_cd_expected_jobs` over the real workflow file. Returns an empty set
    if the file is unreadable — the caller treats an empty expected set as "no
    absence claim", never as "nothing is expected, so everything is fine"."""
    path = os.path.join(repo_root or REPO_ROOT, ".github", "workflows", CI_CD_WORKFLOW_FILE)
    try:
        with open(path, encoding="utf-8") as f:
            return ci_cd_expected_jobs(f.read())
    except OSError:
        return {}


def commit_is_in_push_trigger_scope(changed_paths: list[str]) -> bool:
    """True if any changed path matches a push-workflow trigger glob — the
    #3608 derivation the issue names, read from deploy/sentinel_github.py's
    PUSH_TRIGGER_GLOBS rather than restated here.

    Since #3378 ci-cd.yml carries no `paths:` filter, so it contributes the
    universal `**` glob and this is True for every real commit. That is the
    POINT: with ci-cd unfiltered, "the job is absent" can no longer be excused
    as an ordinary path-filter skip. It is kept as a function (rather than
    assumed) so that reintroducing a filter on ci-cd.yml narrows this gate
    automatically instead of turning it into a false-alarm generator.
    """
    if not changed_paths:
        return False
    sys.path.insert(0, os.path.join(REPO_ROOT, "deploy"))
    try:
        import sentinel_github  # noqa: E402
    except ImportError:
        return True  # cannot derive → do not suppress the absence check
    return any(sentinel_github._matches_push_trigger(p) for p in changed_paths)


def absent_expected_jobs(jobs: list[dict] | None, expected: dict[str, str] | None) -> list[str]:
    """Expected jobs with NO record in the run's job list, by job id.

    `jobs` is the `gh api .../jobs` shape (each entry has a `name`). An expected
    job is PRESENT if some job's name equals its id, equals its declared display
    name, or begins `"<id> / "` (how a job that `uses:` a reusable workflow
    renders — `test / Unit Tests`). `None` for either argument means "not
    probed" → no claim, which is deliberately different from "probed and found
    nothing": a gate that cannot see must not mint a verdict.
    """
    if not expected or jobs is None:
        return []
    names = [(j.get("name") or "") for j in jobs]
    missing = []
    for job_id, display in sorted(expected.items()):
        if any(n == job_id or n == display or n.startswith(f"{job_id} / ") for n in names):
            continue
        missing.append(job_id)
    return missing
