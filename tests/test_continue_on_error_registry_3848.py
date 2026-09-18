"""Every `continue-on-error` site in .github/workflows/ carries a written verdict (3848).

`continue-on-error: true` converts a failing step into a `success` conclusion. On
2026-09-16 that turned a syft install failure into two green steps and no SBOM, with a
`::warning::` on a *different* step as the only surface trace.

The fix for that one step is in ci-lint.yml. This guard is the SET half: it walks the
workflow YAML (not a grep — so `True`, an expression form, and a job-level swallow are all
caught) and asserts every live site has a row in docs/CI_CONTINUE_ON_ERROR_REGISTRY.md,
and that no non-RESOLVED row has rotted past its site.

Mutation control for this guard lives in `test_registry_guard_detects_an_unregistered_site`
below, which writes a real extra site into a copy of a real workflow file and asserts its
own mutation changed the text before reading the verdict (a macOS `sed -i ''` exits 0 on no
match, and a silently no-op control reports the guard working).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO = Path(__file__).resolve().parent.parent
WORKFLOWS = REPO / ".github" / "workflows"
REGISTRY = REPO / "docs" / "CI_CONTINUE_ON_ERROR_REGISTRY.md"

VALID_VERDICTS = {"COVERED", "ACCEPTED", "RESIDUAL", "RESOLVED"}


def _is_swallow(value: object) -> bool:
    """True when a continue-on-error value is anything other than a plain false.

    An `${{ ... }}` expression is treated as a swallow: it can evaluate true at runtime,
    so it needs a verdict just as much as a literal.
    """
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in ("false", "no", "off", "")


def _sites_in(path: Path) -> list[str]:
    """Registry keys for every swallowed step (and job) in one workflow file."""
    doc = yaml.safe_load(path.read_text())
    if not isinstance(doc, dict):
        return []
    found: list[str] = []
    for job_name, job in (doc.get("jobs") or {}).items():
        if not isinstance(job, dict):
            continue
        if _is_swallow(job.get("continue-on-error")):
            found.append(f"{path.name} :: job:{job_name}")
        for idx, step in enumerate(job.get("steps") or []):
            if not isinstance(step, dict) or not _is_swallow(step.get("continue-on-error")):
                continue
            name = step.get("name")
            assert name, (
                f"{path.name}: job {job_name!r} step #{idx} sets continue-on-error but has no `name:`. "
                "An unnamed swallowed step cannot be registered or reasoned about — name it (3848)."
            )
            found.append(f"{path.name} :: {name}")
    return found


def live_sites() -> list[str]:
    sites: list[str] = []
    for wf in sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml")):
        sites.extend(_sites_in(wf))
    return sites


def registry_rows() -> dict[str, str]:
    """key -> verdict, parsed from the fenced table in the registry."""
    text = REGISTRY.read_text()
    body = text.split("<!-- registry:begin -->", 1)[1].split("<!-- registry:end -->", 1)[0]
    rows: dict[str, str] = {}
    for line in body.splitlines():
        m = re.match(r"^\|\s*`([^`]+)`\s*\|\s*`([A-Z]+)`\s*\|", line)
        if m:
            rows[m.group(1)] = m.group(2)
    return rows


def test_registry_is_parseable_and_uses_known_verdicts() -> None:
    rows = registry_rows()
    assert rows, f"no rows parsed from {REGISTRY} — the table shape changed and this guard went blind"
    bad = {k: v for k, v in rows.items() if v not in VALID_VERDICTS}
    assert not bad, f"unknown verdict(s) in the registry: {bad} (allowed: {sorted(VALID_VERDICTS)})"


def test_every_live_continue_on_error_site_has_a_verdict() -> None:
    rows = registry_rows()
    missing = [s for s in live_sites() if s not in rows]
    assert not missing, (
        "continue-on-error site(s) with no verdict in docs/CI_CONTINUE_ON_ERROR_REGISTRY.md:\n  "
        + "\n  ".join(missing)
        + "\n\nAdd a dated row (COVERED / ACCEPTED / RESIDUAL) — a swallowed step with no written "
        "reason is how 3848's SBOM went missing for a build while both steps reported success."
    )


def test_no_non_resolved_row_has_rotted() -> None:
    """A row claiming a live swallow must still describe one; otherwise mark it RESOLVED."""
    sites = set(live_sites())
    stale = [k for k, v in registry_rows().items() if v != "RESOLVED" and k not in sites]
    assert not stale, (
        "registry row(s) whose workflow site no longer exists: "
        + ", ".join(stale)
        + " — if the swallow was removed, change the verdict to RESOLVED; if the step was renamed, "
        "update the key."
    )


def test_sbom_step_is_no_longer_swallowed() -> None:
    """The founding instance: ci-lint.yml's SBOM step must not be continue-on-error (3848)."""
    doc = yaml.safe_load((WORKFLOWS / "ci-lint.yml").read_text())
    steps = doc["jobs"]["lint"]["steps"]
    sbom = [s for s in steps if "Generate SBOM" in (s.get("name") or "")]
    assert len(sbom) == 1, f"expected exactly one Generate SBOM step, found {len(sbom)}"
    assert not _is_swallow(sbom[0].get("continue-on-error")), (
        "ci-lint.yml's Generate SBOM step is swallowed again — a syft failure would report success "
        "and the build would ship with no provenance artifact (3848)"
    )
    upload = [s for s in steps if "Upload SBOM artifact" in (s.get("name") or "")]
    assert len(upload) == 1
    assert upload[0]["with"]["if-no-files-found"] == "error", (
        "the SBOM upload is back on `warn` — a missing provenance artifact must not degrade to a " "warning on a green step (3848)"
    )


def test_registry_guard_detects_an_unregistered_site(tmp_path: Path) -> None:
    """Mutation control: plant a real extra swallowed step and assert the guard fails.

    The mutation asserts its OWN text changed before the verdict is read — a control that
    silently no-ops reports the guard working when it is not.
    """
    src = WORKFLOWS / "ci-lint.yml"
    before = src.read_text()
    anchor = "      - name: Generate SBOM (syft"
    assert anchor in before, "anchor for the mutation control not found — the control cannot run"

    planted_name = "MUTATION CONTROL 3848 — unregistered swallowed step"
    after = before.replace(
        anchor,
        f"      - name: {planted_name}\n        continue-on-error: true\n        run: exit 1\n\n" + anchor,
        1,
    )
    assert after != before, "mutation control did not change the text — refusing to read a no-op verdict"

    work = tmp_path / "workflows"
    work.mkdir()
    (work / "ci-lint.yml").write_text(after)

    mutated_sites = _sites_in(work / "ci-lint.yml")
    assert f"ci-lint.yml :: {planted_name}" in mutated_sites, (
        "the YAML walk did not see the planted swallowed step — the guard cannot detect what it " "is supposed to detect"
    )
    assert planted_name not in registry_rows(), "the planted step must not be in the real registry"

    # And the real tree is clean: the planted site exists only in the temp copy.
    assert f"ci-lint.yml :: {planted_name}" not in live_sites()
