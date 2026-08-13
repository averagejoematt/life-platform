"""tests/test_bundle_boot_wiring_2632.py — the bundle-boot gate must stay wired.

#2632: scripts/verify_bundle_boot.py — the check the durable memory calls "the
real gate" — existed since #1653 and ran NOWHERE. The census (#2631) flagged it
`unreferenced-entrypoint`; grep confirmed the only occurrences of its name were
in its own docstring.

Wiring it is one diff. Keeping it wired is this file. The failure mode being
guarded is not "the script is broken" — the script was always fine — it is "the
call site quietly disappears again", which is exactly how it got here.

What each test pins:
  * the deploy path (deploy/build_bundle.py's CLI) invokes the gate and EXITS
    NONZERO when the gate reds — the load-bearing one, since a call site that
    cannot fail is the same defect in a new costume;
  * the gate runs BEFORE the zip, so a bundle that cannot boot never becomes a
    deployable artifact;
  * CDK's synth path (stage_tree/stage_mcp imported directly) is NOT gated, so
    synth stays fast;
  * the pre-merge lane carries its own copy;
  * the --compare baseline holds only probe-environment gaps, not parked defects.

Deliberately fast: every test here monkeypatches the probe. The real end-to-end
run (397 modules, ~4.5s) is the CI step and the deploy step, not this file.
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "deploy"))
sys.path.insert(0, str(ROOT / "scripts"))

import build_bundle  # noqa: E402
import verify_bundle_boot  # noqa: E402

BASELINE = ROOT / "deploy" / "bundle_boot_baseline.json"
PR_CHECKS = ROOT / ".github" / "workflows" / "pr-checks.yml"


@pytest.fixture
def staged(tmp_path, monkeypatch):
    """Neutralise the real staging + zip so only the WIRING is under test."""
    out = tmp_path / "stage"
    out.mkdir()

    def _fake_stage(out_dir):
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        return out_dir

    monkeypatch.setattr(build_bundle, "stage_tree", _fake_stage)
    monkeypatch.setattr(build_bundle, "stage_mcp", _fake_stage)
    monkeypatch.setattr(build_bundle, "zip_dir", lambda src, dst: Path(dst).write_text("zip") or dst)
    monkeypatch.delenv("SKIP_BUNDLE_BOOT_CHECK", raising=False)
    return out


def _argv(monkeypatch, *extra, out):
    monkeypatch.setattr(sys, "argv", ["build_bundle.py", "--out", str(out), *extra])


def _probe(monkeypatch, failures):
    monkeypatch.setattr(verify_bundle_boot, "probe_bundle", lambda root, workdir=None: (["a", "b"], dict(failures)))


# ══════════════════════════════════════════════════════════════════════════════
# The load-bearing assertion: the wiring can RED.
# ══════════════════════════════════════════════════════════════════════════════


def test_deploy_path_exits_nonzero_when_a_staged_module_fails_to_import(staged, monkeypatch, capsys):
    """A broken import inside the STAGED bundle must abort build_bundle.py.

    Every deploy script runs `python3 deploy/build_bundle.py ...` under `set -e`,
    so a nonzero exit here is what stops the deploy before its first AWS mutation.
    """
    _probe(monkeypatch, {"ingestion.whoop_lambda": "ModuleNotFoundError: No module named 'ai_calls'"})
    _argv(monkeypatch, out=staged)
    with pytest.raises(SystemExit) as exc:
        build_bundle.main()
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "NEW FAILURE" in out and "ingestion.whoop_lambda" in out


def test_deploy_path_is_green_when_the_bundle_boots(staged, monkeypatch):
    _probe(monkeypatch, {})
    _argv(monkeypatch, out=staged)
    build_bundle.main()  # no SystemExit


def test_a_broken_bundle_never_becomes_a_zip(staged, monkeypatch, tmp_path):
    """The gate runs before packaging — an unbootable bundle must not be shippable."""
    zip_path = tmp_path / "deploy.zip"
    _probe(monkeypatch, {"common.constants": "ImportError: boom"})
    _argv(monkeypatch, "--zip", str(zip_path), out=staged)
    with pytest.raises(SystemExit):
        build_bundle.main()
    assert not zip_path.exists(), "a bundle that cannot boot was still packaged"


# ══════════════════════════════════════════════════════════════════════════════
# The escape hatches are explicit and loud — never a silent default.
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("escape", ["flag", "env"])
def test_skipping_the_gate_requires_an_explicit_opt_out_and_says_so(staged, monkeypatch, capsys, escape):
    _probe(monkeypatch, {"common.constants": "ImportError: boom"})
    extra = ()
    if escape == "flag":
        extra = ("--no-verify-boot",)
    else:
        monkeypatch.setenv("SKIP_BUNDLE_BOOT_CHECK", "1")
    _argv(monkeypatch, *extra, out=staged)
    build_bundle.main()  # opted out, so no SystemExit
    assert "SKIPPED" in capsys.readouterr().out


def test_gate_is_on_by_default(staged, monkeypatch):
    """No flag, no env var: the check runs. Regression guard for a silent default flip."""
    called = {}

    def _spy(root, workdir=None):
        called["yes"] = True
        return ([], {})

    monkeypatch.setattr(verify_bundle_boot, "probe_bundle", _spy)
    _argv(monkeypatch, out=staged)
    build_bundle.main()
    assert called.get("yes"), "build_bundle.py ran without the #2632 bundle-boot gate"


# ══════════════════════════════════════════════════════════════════════════════
# CDK's synth path must stay ungated (it imports stage_tree/stage_mcp directly).
# ══════════════════════════════════════════════════════════════════════════════


def test_stage_functions_do_not_run_the_probe(tmp_path, monkeypatch):
    def _explode(*a, **k):
        raise AssertionError("stage_tree must not run the boot probe — CDK synth imports it directly")

    monkeypatch.setattr(verify_bundle_boot, "probe_bundle", _explode)
    build_bundle.stage_tree(str(tmp_path / "s"))


# ══════════════════════════════════════════════════════════════════════════════
# The pre-merge copy + the baseline's honesty.
# ══════════════════════════════════════════════════════════════════════════════


def test_premerge_lane_runs_the_bundle_boot_gate():
    text = PR_CHECKS.read_text(encoding="utf-8")
    assert "verify_bundle_boot.py" in text, "#2632: the pre-merge bundle-boot step is gone"
    assert "--compare deploy/bundle_boot_baseline.json" in text, "#2632: the pre-merge step must compare against the committed baseline"


def test_baseline_holds_only_probe_environment_gaps():
    """A baseline is a place to hide failures. Keep it small, documented, and PIL-only.

    Every entry must be a dependency that reaches the Lambda from a LAYER — never
    from the bundle — so it is structurally unfixable by a bundle change. If this
    test reds because someone parked a real failure here, unpark it.
    """
    data = json.loads(BASELINE.read_text(encoding="utf-8"))
    notes = [k for k in data if k.startswith("_")]
    entries = {k: v for k, v in data.items() if not k.startswith("_")}
    assert notes, "the baseline must carry its own justification"
    assert entries, "an empty baseline means --compare is a no-op; drop the flag instead"
    for module, err in entries.items():
        assert "No module named 'PIL'" in err, f"{module}: only layer-provided Pillow imports may be baselined, got {err!r}"
    assert len(entries) <= 6, f"baseline has grown to {len(entries)} entries — that is a ratchet, not a suppression list"


def test_baseline_loader_ignores_the_prose_keys():
    known = verify_bundle_boot.load_baseline(str(BASELINE))
    assert not any(k.startswith("_") for k in known)
    assert "web.og_image_lambda" in known
