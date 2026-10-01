"""Guard for #2920 — the bundled-config deploy-trigger registry.

`deploy/build_bundle.py`'s `stage_tree()` copies a handful of files from
OUTSIDE `lambdas/` into every Lambda bundle: `config/food_vocabulary.json`,
`config/personas.json`, `config/coaches/*.json`, `redirects.map`. Before this
issue, CI's Plan job (`.github/workflows/ci-cd.yml`) decided whether one of
those files changing should trigger a fleet deploy via a SEPARATE, hand-typed
pathspec — and it only covered `food_vocabulary.json`. `config/personas.json`
had no trigger at all, so commit `ac185e1c` (a WCAG AA contrast fix) went
green with `Deploy: skipped` and production kept serving the old value.

The fix: `build_bundle.bundled_extra_paths()` is now the ONE place that
enumerates "files stage_tree() copies from outside lambdas/", and CI's Plan
job derives its git-diff pathspec by shelling out to
`build_bundle.py --print-bundled-config-paths` instead of re-typing a subset
by hand (charter primitives 1+2 — registry, not enumeration).

This module proves the registry (`bundled_extra_paths()` +
`GENERATED_BUNDLE_EXEMPTIONS`) actually stays in correspondence with what
`stage_tree()` produces, and that CI's workflow reads it from the derivation
rather than re-introducing a hand-typed special case.
"""

import os
import sys

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEPLOY_DIR = os.path.join(REPO_ROOT, "deploy")

sys.path.insert(0, DEPLOY_DIR)
import build_bundle  # noqa: E402


def _read(*parts):
    with open(os.path.join(REPO_ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def _staged_extra_files(staged_dir):
    """Every file inside a staged bundle that is NOT part of the lambdas/
    tree copy — i.e. everything stage_tree() adds beyond
    `shutil.copytree(lambdas/, ...)`. lambdas/ itself never contains a
    config/ dir, food_vocabulary.json, redirects.map, build_info.json, or
    qa_coverage_stats.json at its root, so this is exactly the "extras" set
    stage_tree()'s own docstring enumerates.
    """
    extra_root_names = {"food_vocabulary.json", "redirects.map", build_bundle.BUILD_INFO_NAME, "qa_coverage_stats.json"}
    extras = []
    for root, _dirs, files in os.walk(staged_dir):
        for fname in files:
            rel = os.path.relpath(os.path.join(root, fname), staged_dir).replace(os.sep, "/")
            if rel in extra_root_names or rel.startswith("config/"):
                extras.append(rel)
    return sorted(extras)


def _staged_path_to_registry_entry(staged_rel):
    """Map a staged "extra" file back to what the registry should say about
    it: either a source path expected in bundled_extra_paths(), or a
    (generated-exemption-key) sentinel. Returns None if the mapping itself is
    unknown — which is the failure mode the mutation-proof test exercises.
    """
    if staged_rel == "food_vocabulary.json":
        return ("source", "config/food_vocabulary.json")
    if staged_rel in build_bundle.GENERATED_BUNDLE_EXEMPTIONS:
        return ("exempt", staged_rel)
    if staged_rel == "redirects.map" or staged_rel.startswith("config/"):
        return ("source", staged_rel)
    return None


def _assert_bundle_extras_registered(staged_dir):
    """The correspondence check both the real-bundle test and the
    mutation-proof test share: every "extra" file a staged bundle contains
    must be either a registered deploy-trigger source path
    (build_bundle.bundled_extra_paths()) or a dated generated exemption
    (build_bundle.GENERATED_BUNDLE_EXEMPTIONS). Raises AssertionError
    otherwise — that raise IS the guard going red.
    """
    trigger_paths = set(build_bundle.bundled_extra_paths())
    exemptions = set(build_bundle.GENERATED_BUNDLE_EXEMPTIONS)

    for staged_rel in _staged_extra_files(staged_dir):
        mapping = _staged_path_to_registry_entry(staged_rel)
        assert mapping is not None, (
            f"staged bundle contains {staged_rel!r}, which no mapping in this guard recognizes at all — "
            "a new class of bundled extra needs a case in _staged_path_to_registry_entry()"
        )
        kind, key = mapping
        if kind == "exempt":
            assert key in exemptions, f"{staged_rel!r} claims a generated exemption but is not in GENERATED_BUNDLE_EXEMPTIONS"
            continue
        assert key in trigger_paths, (
            f"staged bundle contains {staged_rel!r} (source {key!r}) but build_bundle.bundled_extra_paths() does not "
            "list it — this file would ship to every Lambda with NO CI deploy trigger (the #2920 class). Register it "
            "in bundled_extra_paths(), or add a dated entry to GENERATED_BUNDLE_EXEMPTIONS with a reason."
        )


# ══════════════════════════════════════════════════════════════════════════
# 1. The registry matches what a REAL staged bundle actually contains.
# ══════════════════════════════════════════════════════════════════════════


def test_real_staged_bundle_extras_are_all_registered(tmp_path):
    out = build_bundle.stage_tree(str(tmp_path / "stage"))
    _assert_bundle_extras_registered(out)  # must not raise


def test_bundled_extra_paths_includes_known_files():
    paths = build_bundle.bundled_extra_paths()
    assert "config/food_vocabulary.json" in paths
    assert "config/personas.json" in paths, "personas.json is exactly the file #2920 found missing a trigger"
    assert "redirects.map" in paths
    assert any(p.startswith("config/coaches/") for p in paths), "config/coaches/*.json should be discovered, not hand-listed"
    # Derived, not hand-typed: every coach path on disk must be present.
    coaches_dir = os.path.join(REPO_ROOT, "config", "coaches")
    on_disk = {f"config/coaches/{name}" for name in os.listdir(coaches_dir) if name.endswith(".json") and not name.endswith("_stance.json")}
    assert on_disk <= set(paths), f"missing from bundled_extra_paths(): {on_disk - set(paths)}"


# ══════════════════════════════════════════════════════════════════════════
# 2. Mutation proof: an UNREGISTERED bundled path makes the guard RED.
# ══════════════════════════════════════════════════════════════════════════


def test_mutation_unregistered_bundled_extra_reds_the_guard(tmp_path):
    """Simulates the exact #2920 regression class: something starts shipping
    inside the bundle (as if a future stage_tree() edit added a copy) without
    a matching entry in bundled_extra_paths() or GENERATED_BUNDLE_EXEMPTIONS.
    The correspondence check MUST fail — proving the guard is not a tautology
    that always passes regardless of what's actually staged.
    """
    out = build_bundle.stage_tree(str(tmp_path / "stage"))
    rogue = os.path.join(out, "config", "rogue_unregistered_coach.json")
    with open(rogue, "w", encoding="utf-8") as f:
        f.write("{}")

    with pytest.raises(AssertionError, match="rogue_unregistered_coach"):
        _assert_bundle_extras_registered(out)


def test_mutation_new_real_coach_file_is_picked_up_without_code_change(tmp_path):
    """The flip side: dropping a NEW real coach json into a config/coaches/
    copy on disk must appear in bundled_extra_paths() with zero code changes
    — proving discovery is a directory listing, not a hand-typed enumeration
    that would need a matching edit every time a coach is added.
    """
    fake_root = tmp_path / "fake_repo"
    coaches = fake_root / "config" / "coaches"
    coaches.mkdir(parents=True)
    (coaches / "brand_new_coach.json").write_text("{}")
    (coaches / "brand_new_coach_stance.json").write_text("{}")  # excluded, same rule as stage_tree()

    paths = build_bundle.bundled_extra_paths(repo_root=str(fake_root))
    assert "config/coaches/brand_new_coach.json" in paths
    assert "config/coaches/brand_new_coach_stance.json" not in paths


# ══════════════════════════════════════════════════════════════════════════
# 3. CI derives its trigger pathspec from build_bundle.py — no re-typed list.
# ══════════════════════════════════════════════════════════════════════════


def test_ci_workflow_derives_bundled_config_trigger_from_build_bundle():
    workflow = _read(".github", "workflows", "ci-cd.yml")
    assert "build_bundle.py --print-bundled-config-paths" in workflow, (
        "ci-cd.yml's Plan job should derive its bundled-config trigger pathspec from "
        "build_bundle.py, not re-type a subset by hand (#2920)"
    )


def test_ci_workflow_no_longer_hand_types_food_vocabulary_special_case():
    workflow = _read(".github", "workflows", "ci-cd.yml")
    assert "VOCAB_CHANGED" not in workflow, (
        "the old food_vocabulary.json-only special case (VOCAB_CHANGED) should be removed, not left alongside the "
        "derived trigger set — two mechanisms for one fact is how config/personas.json got missed in the first place"
    )
    assert (
        "-- config/food_vocabulary.json 2>/dev/null" not in workflow
    ), "a hand-typed food_vocabulary.json pathspec still exists in ci-cd.yml"


def test_ci_workflow_warns_on_skipped_deploy_with_bundled_config_change():
    workflow = _read(".github", "workflows", "ci-cd.yml")
    assert "Deploy skipped but bundled config changed" in workflow, (
        "ci-cd.yml should emit a visible warning naming the file + ship command when Deploy would be "
        "skipped despite a bundled config path changing (independent safety net, #2920)"
    )


def test_bundled_extra_paths_cli_flag_matches_python_api():
    """The CLI surface ci-cd.yml actually shells out to must match the Python
    function this whole guard is built around."""
    import subprocess

    proc = subprocess.run(
        [sys.executable, os.path.join(DEPLOY_DIR, "build_bundle.py"), "--print-bundled-config-paths"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    cli_paths = sorted(line for line in proc.stdout.splitlines() if line.strip())
    assert cli_paths == build_bundle.bundled_extra_paths()


# ══════════════════════════════════════════════════════════════════════════
# 4. #4250 box 3 — the reconcile counter file is never a fleet trigger.
# ══════════════════════════════════════════════════════════════════════════


def _plan_fleet_loop() -> str:
    """The `for file in $CHANGED; do case … done` shared-module loop in plan's Detect step,
    read from the real ci-cd.yml."""
    import re

    workflow = _read(".github", "workflows", "ci-cd.yml")
    step = workflow.split("- name: Detect changes and build deploy plan", 1)[1]
    m = re.search(r'\n( *for file in \$CHANGED; do\n *case "\$file" in\n.*?\n *esac\n *done)\n', step, re.S)
    assert m, "plan's shared-module fleet loop not found in ci-cd.yml"
    return m.group(1)


def _fleet_for(changed: str) -> str:
    import subprocess

    script = 'FLEET_CHANGED="false"\n' + _plan_fleet_loop() + '\necho "FLEET=$FLEET_CHANGED"\n'
    env = {**os.environ, "CHANGED": changed, "LAMBDA_MAP_FILE": os.path.join(REPO_ROOT, "ci", "lambda_map.json")}
    out = subprocess.run(["bash", "-c", 'CHANGED="$CHANGED"\n' + script], env=env, capture_output=True, text=True, check=True).stdout
    return out.strip().splitlines()[-1]


@pytest.mark.skipif(__import__("shutil").which("jq") is None, reason="the plan loop shells out to jq")
def test_reconcile_counter_file_alone_never_triggers_a_fleet_deploy():
    """A reconcile-only push changes lambdas/web/platform_counts.py (plus docs). The plan
    loop, executed as ci-cd.yml spells it, must not set FLEET_CHANGED for it — and must
    still set it for a genuine unmapped shared module (the control)."""
    assert _fleet_for("lambdas/web/platform_counts.py") == "FLEET=false"
    assert _fleet_for("lambdas/web/platform_counts.py lambdas/common/constants.py") == "FLEET=true"
    assert _fleet_for("lambdas/emails/weekly_digest_lambda.py") == "FLEET=false", "a mapped handler is a per-function deploy"
