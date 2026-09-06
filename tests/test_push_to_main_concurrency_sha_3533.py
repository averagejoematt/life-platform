"""tests/test_push_to_main_concurrency_sha_3533.py — #3533: every push-to-main
workflow must keep its OWN verdict, never cancel a sibling push's run.

THE DEFECT: `docs-ci.yml` and `v4-gate.yml` both keyed their `concurrency.group`
on `${{ github.workflow }}-${{ github.ref }}` with `cancel-in-progress: true`.
For a `push` event `github.ref` is always `refs/heads/main` — IDENTICAL across
every push — so a follow-up push (the reconcile bot's auto-commit landing
seconds after a human's) cancelled the human commit's still-running run.
Measured: 16 of the last 40 Docs CI runs on `main` were `cancelled`, one of
them hiding a real `Literal-drift gate (sync_doc_metadata --check)` FAILURE
(run 33935174277, #3483) — every other gate in that run had already concluded
`success` before the cancel stamp landed. `cron-freshness.yml` carried the
identical shape (a bare `group: cron-freshness` static string, `cancel-in-
progress: true`, triggered ONLY on push-to-main by design).

THE FIX: a push-triggered run's concurrency group must be unique PER PUSH
(carry `github.sha` or `github.run_id`), so it can never again share a group
with — and therefore never be cancelled by — another push's run. `cancel-in-
progress` is scoped to `pull_request` only where a shared per-PR group still
wants the CI-minutes-hygiene cancel of a superseded commit (#1453's original
intent, preserved).

THE GUARD: derived from every `.github/workflows/*.yml` that declares a `push`
trigger on `branches: [main]` — a NEW workflow added later with this same
cancel-in-progress-on-a-shared-group shape fails here automatically; nobody
has to remember to list it.
"""

import glob
import os

import pytest

yaml = pytest.importorskip("yaml", reason="PyYAML parses the workflow documents under test")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_WORKFLOWS_DIR = os.path.join(_REPO, ".github", "workflows")


def _load(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _push_to_main_workflows():
    """Every workflow file that triggers on `push` to a branch list including
    `main` — the exact trigger shape #3533 was filed against. Derived by
    reading each file's own `on:` block, never hand-enumerated."""
    found = []
    for path in sorted(glob.glob(os.path.join(_WORKFLOWS_DIR, "*.yml"))):
        spec = _load(path)
        # PyYAML resolves the bare key `on:` to the boolean True (YAML 1.1).
        on = spec.get("on", spec.get(True))
        if not isinstance(on, dict):
            continue
        push = on.get("push")
        if not isinstance(push, dict):
            continue
        branches = push.get("branches") or []
        if "main" in branches:
            found.append((path, spec))
    return found


def _group_is_push_unique(group: str) -> bool:
    """A concurrency group string that CANNOT collide across two different
    pushes to the same branch — the only two GitHub-provided values that vary
    per push (`github.sha`) or per run (`github.run_id`)."""
    return "github.sha" in group or "github.run_id" in group


def _cancel_in_progress_excludes_push(value) -> bool:
    """`cancel-in-progress` never fires on a `push` event. Accepts a literal
    `false`, or a template expression that conditions on `github.event_name`
    away from `push` (e.g. `${{ github.event_name == 'pull_request' }}`)."""
    if value is False:
        return True
    if isinstance(value, str) and "event_name" in value and "pull_request" in value:
        return True
    return False


def test_at_least_one_push_to_main_workflow_exists():
    """A sanity floor on the derivation itself — if this collapses to zero, the
    sweep below would vacuously pass having checked nothing (#3477's class)."""
    assert len(_push_to_main_workflows()) >= 3, "expected several push-to-main workflows (ci-cd, docs-ci, v4-gate, ...)"


def test_no_push_to_main_workflow_can_cancel_a_sibling_push():
    """The structural #3533 guard, over the WHOLE set, not a named instance."""
    offenders = []
    for path, spec in _push_to_main_workflows():
        conc = spec.get("concurrency")
        if conc is None:
            continue  # no concurrency block at all -> GitHub applies none; structurally safe
        if not isinstance(conc, dict):
            continue  # a job-level-only concurrency string; not the workflow-level push race
        group = str(conc.get("group", ""))
        cancel = conc.get("cancel-in-progress", False)
        if _group_is_push_unique(group):
            continue  # every push gets its own group -> nothing to collide with
        if _cancel_in_progress_excludes_push(cancel):
            continue  # cancel-in-progress never fires for a push event
        offenders.append((os.path.basename(path), group, cancel))
    assert not offenders, (
        "#3533: these push-to-main workflows share a concurrency group across pushes AND can "
        f"cancel-in-progress on a push, so a later push can cancel an earlier push's own verdict: {offenders}"
    )


def test_docs_ci_and_v4_gate_group_includes_the_sha():
    """The two named specimens (#3533's own reproduction) — pinned directly, on
    top of the structural sweep above."""
    for name in ("docs-ci.yml", "v4-gate.yml"):
        spec = _load(os.path.join(_WORKFLOWS_DIR, name))
        conc = spec["concurrency"]
        assert "github.sha" in conc["group"], f"{name}: concurrency.group must include github.sha (#3533)"
        cancel = conc["cancel-in-progress"]
        assert (
            isinstance(cancel, str) and "pull_request" in cancel
        ), f"{name}: cancel-in-progress must be scoped to pull_request only (#3533) — got {cancel!r}"


def test_cron_freshness_group_includes_the_sha():
    """cron-freshness.yml has no `pull_request` trigger at all (push-to-main +
    workflow_dispatch only, by design) — its fix is group-uniqueness alone."""
    spec = _load(os.path.join(_WORKFLOWS_DIR, "cron-freshness.yml"))
    conc = spec["concurrency"]
    assert "github.sha" in conc["group"], "cron-freshness.yml: concurrency.group must include github.sha (#3533)"
