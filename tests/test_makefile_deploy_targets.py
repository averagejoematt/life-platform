"""tests/test_makefile_deploy_targets.py — the Makefile is a second entry-point
system alongside deploy/*.md and .claude/commands/deploy.md (#1323, SDLC review
2026-07-18). It rots the same way docs do: a script gets deleted or renamed and
a `make <target>` line still shells out to the corpse.

This is the trivial regression guard the issue names: every `deploy/*.sh` path
referenced anywhere in the Makefile must exist on disk. It's deliberately dumb
(a path existence check, not an argument-count or region check) so it stays
cheap and catches the "deleted script" class specifically — `make layer` →
deploy/build_layer.sh and `make deploy-sprint7` → deploy/deploy_sprint7_tier0.sh
were both this exact failure mode before the #1323 fix.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAKEFILE = ROOT / "Makefile"

# Matches `deploy/<anything ending in .sh>` anywhere on a recipe line —
# covers `bash deploy/foo.sh`, `deploy/foo.sh`, etc.
_DEPLOY_SH_RE = re.compile(r"deploy/[A-Za-z0-9_./-]+\.sh")


def _referenced_deploy_scripts() -> set[str]:
    text = MAKEFILE.read_text(encoding="utf-8")
    return set(_DEPLOY_SH_RE.findall(text))


def test_every_makefile_deploy_script_path_exists_on_disk():
    """Fails on the pre-#1323 tree: `layer` referenced the deleted
    deploy/build_layer.sh and `deploy-sprint7` referenced the deleted
    deploy/deploy_sprint7_tier0.sh."""
    referenced = _referenced_deploy_scripts()
    missing = sorted(path for path in referenced if not (ROOT / path).exists())
    assert not missing, f"Makefile references deploy/*.sh path(s) that don't exist on disk: {missing}"


def test_gate_is_not_vacuous():
    """The regex must actually find references in the live Makefile — an empty
    match set would make the existence check above pass vacuously."""
    referenced = _referenced_deploy_scripts()
    assert referenced, "no deploy/*.sh references found in Makefile — regex or fixture drifted"
    assert "deploy/deploy_fleet.sh" in referenced
    assert "deploy/deploy_site_api.sh" in referenced


def test_deploy_lambda_sh_targets_pass_two_args():
    """deploy/deploy_lambda.sh exits 1 on `$# -lt 2` (see deploy/deploy_lambda.sh).
    A Makefile recipe line invoking it must supply both a function name AND a
    source-file argument — the exact one-arg shape that made deploy-mcp/
    deploy-anomaly/deploy-daily-brief dead-on-arrival before #1323."""
    text = MAKEFILE.read_text(encoding="utf-8")
    for line in text.splitlines():
        stripped = line.strip()
        if "deploy_lambda.sh" not in stripped or not stripped.startswith("bash deploy/deploy_lambda.sh"):
            continue
        # tokens after the script path are the args passed to it
        args = stripped.split("deploy_lambda.sh", 1)[1].split()
        assert len(args) >= 2, f"deploy_lambda.sh invoked with < 2 args (dead on arrival): {stripped!r}"


def test_deploy_site_api_does_not_use_single_file_deploy_lambda_sh():
    """ci/lambda_map.json marks lambdas/web/site_api_lambda.py cdk_only=True — its
    sibling imports (web.site_api_*, hevy_common, …) break under a single-file
    deploy_lambda.sh invocation. The Makefile's site-api target must use the
    dedicated full-tree script instead (see deploy/deploy_site_api.sh, docs/
    .claude/commands/deploy.md 'Special case — life-platform-site-api')."""
    text = MAKEFILE.read_text(encoding="utf-8")
    # isolate the deploy-site-api recipe block
    match = re.search(r"^deploy-site-api:.*?\n((?:\t.*\n?)+)", text, re.MULTILINE)
    assert match, "deploy-site-api target not found in Makefile"
    recipe = match.group(1)  # the tab-indented recipe lines only, not the target/comment header
    assert "deploy_site_api.sh" in recipe
    assert "deploy_lambda.sh" not in recipe
