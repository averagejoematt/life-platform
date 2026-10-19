"""tests/test_workflow_size_ratchet_4885.py — a down-only size ratchet on .github/workflows (#4885, D5).

ci-cd.yml grew 1440 -> 1748 lines with 831 inline ``run:`` lines and nothing policed it. This records,
per workflow, the physical line count and the inline ``run:`` line count, and FAILS on growth in
either. Shrinking is always allowed (tighten the number — that is the ratchet doing its job). A new
workflow has no entry and so is held to its measured size by being added here in the same PR.

The fix for a red is to move the shell into a tested ``scripts/`` or ``deploy/`` entrypoint (the
precedent: deploy/validate_lambda_map.sh), not to raise a number.
"""

import pathlib

import yaml

_REPO = pathlib.Path(__file__).resolve().parent.parent
_WF = _REPO / ".github" / "workflows"

# workflow -> (physical lines, inline run: lines). Down-only. Named *_COUNTS: a *_BASELINE name is
# read as a gate registry by the census.
WORKFLOW_SIZE_COUNTS: dict = {
    "ci-cd.yml": (1732, 783),
    "ci-lint.yml": (451, 168),
    "ci-test.yml": (439, 124),
    "citation-network-check.yml": (78, 21),
    "codeql.yml": (137, 0),
    "config-drift.yml": (280, 154),
    "cron-freshness.yml": (149, 3),
    "dependabot-automerge.yml": (105, 37),
    "deploy-wedge-watch.yml": (153, 46),
    "docs-ci.yml": (296, 14),
    "eval-harvest.yml": (79, 10),
    "fresh-eyes.yml": (96, 11),
    "golden-brief-eval.yml": (199, 39),
    "hae-webhook-ingress-drift.yml": (77, 5),
    "operating-calendar.yml": (67, 13),
    "pii-endpoint-sweep.yml": (119, 17),
    "panel-rubric-gate.yml": (82, 4),  # #5072: the panel rubric gate (owner-approved workflow)
    "pr-checks.yml": (414, 44),
    "raw-kms-readability.yml": (112, 15),
    "remediation-agent.yml": (184, 33),
    "secret-scan.yml": (89, 13),
    "served-coach-facts.yml": (80, 15),
    "site-deploy.yml": (650, 152),
    "surface-drift.yml": (51, 1),
    "v4-gate.yml": (170, 31),
    "visual-qa.yml": (326, 107),
    "webkit-mobile-qa.yml": (179, 26),
    "wrap-nightly.yml": (116, 10),
}


def measure(path: pathlib.Path) -> tuple:
    text = path.read_text(encoding="utf-8")
    lines = len(text.splitlines())
    doc = yaml.safe_load(text) or {}
    run_lines = 0
    for job in (doc.get("jobs") or {}).values():
        for step in (job or {}).get("steps") or []:
            run = step.get("run") if isinstance(step, dict) else None
            if isinstance(run, str):
                run_lines += len(run.splitlines())
    return lines, run_lines


def offenders(counts: dict, root: pathlib.Path = _WF) -> list:
    out = []
    for path in sorted(root.glob("*.yml")):
        lines, run_lines = measure(path)
        if path.name not in counts:
            out.append(f"{path.name}: not in WORKFLOW_SIZE_COUNTS (measured {lines} lines / {run_lines} run lines)")
            continue
        max_lines, max_run = counts[path.name]
        if lines > max_lines:
            out.append(f"{path.name}: {lines} lines > recorded {max_lines}")
        if run_lines > max_run:
            out.append(f"{path.name}: {run_lines} inline run lines > recorded {max_run}")
    return out


def test_workflows_do_not_grow():
    bad = offenders(WORKFLOW_SIZE_COUNTS)
    assert not bad, (
        "workflow size grew (#4885) — extract inline shell to a tested scripts/ or deploy/ entrypoint "
        "(see deploy/validate_lambda_map.sh) instead of raising a number:\n  " + "\n  ".join(bad)
    )


def test_mutation_appended_lines_go_red(tmp_path):
    """Control: appending lines to a workflow, with no reduction elsewhere, must be reported."""
    wf = tmp_path / "ci-cd.yml"
    src = _WF / "ci-cd.yml"
    wf.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    counts = {"ci-cd.yml": measure(wf)}
    assert offenders(counts, tmp_path) == []
    wf.write_text(wf.read_text(encoding="utf-8") + "# padding\n", encoding="utf-8")
    assert any("lines >" in o for o in offenders(counts, tmp_path))
    # and inline run growth is caught independently of file length
    text = src.read_text(encoding="utf-8")
    marker = "        run: bash deploy/validate_lambda_map.sh\n"
    assert marker in text
    wf.write_text(
        text.replace(marker, marker.replace("bash deploy/validate_lambda_map.sh", "|\n          echo a\n          echo b")),
        encoding="utf-8",
    )
    assert any("inline run lines" in o for o in offenders(counts, tmp_path))


def test_extracted_block_stays_extracted():
    text = (_WF / "ci-cd.yml").read_text(encoding="utf-8")
    assert "run: bash deploy/validate_lambda_map.sh" in text
