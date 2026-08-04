"""#2099 — binary-layer build tooling + manifest-accuracy drift gate.

Sibling of tests/test_pip_audit_layer_coverage.py (#1336). That one proves every deployed
layer HAS a scanning manifest; this one proves the manifest still says the TRUTH about what
is deployed, and that a rebuild can't land without the manifest moving with it.

All offline — no pip resolution, no network, no AWS.
"""

import json
import pathlib
import re
import sys

import pytest

_REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "deploy"))

import build_lambda_layer as blb  # noqa: E402

CONSTANTS = _REPO / "cdk" / "stacks" / "constants.py"


# ── The live tree must be clean ───────────────────────────────────────────────


def test_live_tree_has_no_manifest_drift():
    """The whole point: lambdas/requirements/*.txt == render_manifest() for every layer.

    Fails if someone hand-edits a manifest, bumps a *_LAYER_VERSION without promoting a
    build, or rebuilds a layer and forgets to re-derive the manifest.
    """
    problems = blb.check_manifests()
    assert problems == [], "layer manifest drift:\n  " + "\n  ".join(problems)


def test_every_layer_arn_in_constants_has_build_tooling():
    """Guard the SET, not the instance — derive the layer list from constants.py.

    A fourth binary layer added to constants.py without a LayerSpec re-creates exactly the
    #2099 blind spot (a deployed layer with no rebuild path), so it fails here.
    """
    names = sorted({m.group(1) for m in re.finditer(r"layer:([a-z0-9_-]+?)-layer:", CONSTANTS.read_text())})
    assert names, "no *_LAYER_ARN literals found — the regex or constants.py moved"
    missing = [n for n in names if n not in blb.LAYERS]
    assert missing == [], f"deployed layers with no build spec in deploy/build_lambda_layer.py: {missing}"


@pytest.mark.parametrize("key", sorted(blb.LAYERS))
def test_deployed_record_matches_constants_version(key):
    """The recorded deployed layer version tracks the CDK constant, both directions."""
    spec = blb.LAYERS[key]
    assert spec.deployed_path.is_file(), f"no deployed record for {key}"
    recorded = json.loads(spec.deployed_path.read_text())["layer_version"]
    assert recorded == blb._constant_int(spec.version_constant), f"{spec.version_constant} and {spec.deployed_path.name} disagree"


@pytest.mark.parametrize("key", sorted(blb.LAYERS))
def test_manifest_is_a_valid_pip_requirements_file(key):
    """pip-audit must still be able to scan it — the manifest is derived, not decorative."""
    body = blb.LAYERS[key].manifest_path.read_text()
    pins = [ln.strip() for ln in body.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    assert pins, f"{key}: manifest has no scannable pins"
    for pin in pins:
        assert re.fullmatch(r"[a-z0-9][a-z0-9-]*==[0-9][^\s]*", pin), f"{key}: unscannable requirement line {pin!r}"


@pytest.mark.parametrize("key", sorted(blb.LAYERS))
def test_manifest_states_the_build_target(key):
    """Every target pin is echoed into the manifest, so the file shows both states.

    The manifest's uncommented pins are what is DEPLOYED (that's what pip-audit should
    alarm on); the `layer-build-target:` comments are what the next build installs. #1778
    and #1780 were both closed because a bot edited the deployed pins believing that
    shipped something — the two states are now visibly distinct in the file itself.
    """
    spec = blb.LAYERS[key]
    body = spec.manifest_path.read_text()
    for req in spec.requirements:
        assert f"layer-build-target: {req}" in body, f"{key}: manifest does not declare target {req}"
    assert f"deploy/build_lambda_layer.py::LAYERS['{key}']" in body


# ── The check itself must actually fire (a green gate that can't go red is decoration) ──


def _spec_into(tmp_path, monkeypatch, key="pillow"):
    """Point the module's paths at a tmp tree holding a copy of one real spec's artifacts."""
    monkeypatch.setattr(blb, "DEPLOYED_DIR", tmp_path / "layers")
    monkeypatch.setattr(blb, "REQUIREMENTS_DIR", tmp_path / "requirements")
    (tmp_path / "layers").mkdir()
    (tmp_path / "requirements").mkdir()
    spec = blb.LAYERS[key]
    deployed = json.loads((_REPO / "deploy" / "layers" / f"{key}.deployed.json").read_text())
    spec.deployed_path.write_text(json.dumps(deployed, indent=2, sort_keys=True) + "\n")
    spec.manifest_path.write_text(blb.render_manifest(spec, deployed))
    return spec, deployed


def test_check_is_clean_on_a_freshly_rendered_tree(tmp_path, monkeypatch):
    spec, _ = _spec_into(tmp_path, monkeypatch)
    assert blb.check_manifests([spec.key]) == []


def test_check_fires_on_a_hand_edited_manifest(tmp_path, monkeypatch):
    """The #1778/#1780 failure mode: a bot bumps the pin in the manifest. Must go RED."""
    spec, _ = _spec_into(tmp_path, monkeypatch)
    spec.manifest_path.write_text(spec.manifest_path.read_text().replace("pillow==11.3.0", "pillow==12.3.0"))
    problems = blb.check_manifests([spec.key])
    assert any("drifted" in p for p in problems), problems


def test_check_fires_when_the_layer_version_is_bumped_without_a_promote(tmp_path, monkeypatch):
    """A published+wired rebuild whose manifest was never re-derived. Must go RED."""
    spec, deployed = _spec_into(tmp_path, monkeypatch)
    deployed["layer_version"] = deployed["layer_version"] + 1
    spec.deployed_path.write_text(json.dumps(deployed, indent=2, sort_keys=True) + "\n")
    spec.manifest_path.write_text(blb.render_manifest(spec, deployed))
    problems = blb.check_manifests([spec.key])
    assert any(spec.version_constant in p for p in problems), problems


def test_check_fires_when_a_top_level_pin_vanishes_from_the_deployed_record(tmp_path, monkeypatch):
    spec, deployed = _spec_into(tmp_path, monkeypatch)
    deployed["packages"].pop("pillow")
    deployed["packages"]["something-else"] = "1.0"
    spec.deployed_path.write_text(json.dumps(deployed, indent=2, sort_keys=True) + "\n")
    spec.manifest_path.write_text(blb.render_manifest(spec, deployed))
    problems = blb.check_manifests([spec.key])
    assert any("top-level pin" in p for p in problems), problems


def test_promote_round_trips_a_build_record(tmp_path, monkeypatch):
    """`build` -> `--promote` is the post-deploy loop; it must produce a self-consistent tree."""
    spec, _ = _spec_into(tmp_path, monkeypatch, key="garth")
    record = {
        "layer_name": spec.layer_name,
        "runtime": "python3.12",
        "architecture": "x86_64",
        "platforms": list(spec.platforms),
        "target_pins": list(spec.requirements),
        "zip_sha256": "0" * 64,
        "packages": {"garminconnect": "0.2.40", "garth": "0.6.3", "urllib3": "2.7.0"},
    }
    build_json = tmp_path / "garth-layer.build.json"
    build_json.write_text(json.dumps(record))
    monkeypatch.setattr(blb, "_constant_int", lambda name: 3)
    blb.promote(spec, build_json, layer_version=3, measured="2026-08-04")
    assert blb.check_manifests([spec.key]) == []
    assert "urllib3==2.7.0" in spec.manifest_path.read_text()


# ── Transitive coverage — the gap that hid 3 CVEs ────────────────────────────


def test_garth_manifest_lists_the_full_transitive_closure():
    """Before #2099 garmin.txt pinned 2 of the 14 packages in garth-layer:2, so pip-audit
    never saw idna/urllib3 — 3 fixable CVEs were structurally invisible. The manifest must
    keep listing everything the layer actually contains."""
    pins = [ln.strip() for ln in blb.LAYERS["garth"].manifest_path.read_text().splitlines() if ln.strip() and not ln.startswith("#")]
    names = {p.split("==")[0] for p in pins}
    assert {"garminconnect", "garth", "urllib3", "idna", "requests", "pydantic"} <= names, names


# ── CDK wiring: a rebuilt layer must be able to reach the functions ──────────


def test_no_stack_hardcodes_a_layer_arn_outside_constants():
    """#2099: operational_stack hardcoded `pillow-layer:1`, so bumping PILLOW_LAYER_VERSION
    deployed nothing. Derive the check over every stack file rather than that one instance."""
    offenders = []
    for path in sorted((_REPO / "cdk" / "stacks").glob("*.py")):
        if path.name == "constants.py":
            continue
        for i, line in enumerate(path.read_text().splitlines(), 1):
            if re.search(r'["\']arn:aws:lambda:[^"\']*:layer:', line):
                offenders.append(f"{path.name}:{i}: {line.strip()}")
    assert offenders == [], "hardcoded layer ARN literal — use the *_LAYER_ARN constant:\n  " + "\n  ".join(offenders)


def test_operational_stack_mounts_pillow_from_the_constant():
    src = (_REPO / "cdk" / "stacks" / "operational_stack.py").read_text()
    assert "PILLOW_LAYER_ARN" in src
    for fn in blb.LAYERS["pillow"].attached_to:
        assert f'function_name="{fn}"' in src, f"{fn} is declared as a pillow-layer consumer but is not in operational_stack"
