#!/usr/bin/env python3
"""build_lambda_layer.py — reproducible builds for the binary dependency layers (#2099).

WHY THIS EXISTS
---------------
Three Lambda *layers* ship third-party code into running functions (the Lambda
*source* tree is stdlib-only): `pillow-layer`, `garth-layer`, `lameenc-layer`.
Until #2099 two of the three had **no build tooling in the repo at all** — they
were hand-built offline years ago and the only surviving record of what went in
was the pinned manifest under `lambdas/requirements/`, which had itself drifted
(corrected against the live layers by #2098).

The consequence measured in #2099: `pillow-layer:1` carries 25 live Pillow CVEs
and `garth-layer:2` carries 6, and *neither was fixable by editing a manifest* —
Dependabot bumps files that deploy nothing. This script is the missing half: a
pinned, repeatable, deterministic build for each layer, plus a drift check that
keeps `lambdas/requirements/*.txt` honest about what is actually deployed.

THE THREE-FILE CONTRACT
-----------------------
For each layer there are three artifacts and one direction of truth:

  1. ``LAYERS[key].requirements``      — the TARGET pins. What the next build installs.
                                          Hand-edited here; this is the upgrade knob.
  2. ``deploy/layers/<key>.deployed.json`` — the DEPLOYED state. What the live layer
                                          version actually contains, measured. Written
                                          by ``--promote`` after an owner deploy.
  3. ``lambdas/requirements/<manifest>``  — DERIVED, byte-for-byte, from (1)+(2) by
                                          ``render_manifest()``. Never hand-edit.

``--check-manifest`` asserts (3) == ``render_manifest()`` and that (2)'s layer
version matches ``cdk/stacks/constants.py``. So a rebuild that isn't reflected in
the manifest — or a ``*_LAYER_VERSION`` bump that isn't reflected in the deployed
record — fails the check instead of silently drifting. That is the #2098 accuracy
posture made mechanical (issue #2099 acceptance box 3).

RUNTIME / ARCH (read from the live functions, not guessed)
----------------------------------------------------------
og-image-generator, reading-cover-pipeline, garmin-data-ingestion and
coach-panel-podcast are all **python3.12 / x86_64**. Verified read-only with
``aws lambda get-function-configuration --query '{Runtime:Runtime,Arch:Architectures}'``.
If a function is ever moved to arm64, its layer spec's ``arch``/``platforms`` must
move with it — a layer built for the wrong arch imports as ``ImportError: ... invalid
ELF header`` at runtime, not at build time.

PLATFORM TAGS
-------------
The build is docker-free: ``pip install --platform ... --only-binary=:all: --target``
downloads Linux wheels on any host. Each spec lists **several** platform tags because
projects migrate manylinux baselines: Pillow 12.x publishes
``manylinux_2_27/manylinux_2_28`` wheels and no longer publishes ``manylinux2014``
(= manylinux_2_17), so a single hardcoded ``manylinux2014_x86_64`` — what
``deploy/build_lameenc_layer.sh`` uses — silently fails to resolve Pillow 12.
manylinux_2_28 needs glibc >= 2.28; the python3.12 managed runtime is Amazon Linux
2023 (glibc 2.34), so it is satisfied. (It would NOT be on the retired AL2-based
python3.8/3.9 runtimes.)

DOCKER FALLBACK
---------------
If a future pin has no wheel for a listed platform, ``--only-binary=:all:`` fails
loudly rather than quietly building a macOS-native artifact. Build it in the AWS
SAM build image instead, then re-run with ``--from-dir``:

    docker run --rm --platform linux/amd64 -v "$PWD/out":/out \\
      public.ecr.aws/sam/build-python3.12:latest \\
      pip install --target /out/python --no-compile <pins...>

USAGE
-----
    python3 deploy/build_lambda_layer.py --list
    python3 deploy/build_lambda_layer.py --check-manifest              # offline drift gate
    python3 deploy/build_lambda_layer.py build pillow                  # build zip + sidecar
    python3 deploy/build_lambda_layer.py build --all --out deploy/zips
    python3 deploy/build_lambda_layer.py --promote pillow \\
        --from-build deploy/zips/pillow-layer.build.json --layer-version 2

PUBLISHING IS A SEPARATE, OWNER-GATED STEP. This script never mutates AWS. After a
build, the owner publishes and rewires:

    aws lambda publish-layer-version --layer-name pillow-layer \\
      --compatible-runtimes python3.12 --compatible-architectures x86_64 \\
      --zip-file fileb://deploy/zips/pillow-layer.zip --region us-west-2
    # then bump PILLOW_LAYER_VERSION in cdk/stacks/constants.py,
    #      cdk deploy LifePlatformOperational,
    #      --promote to re-derive the manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CONSTANTS_PATH = REPO_ROOT / "cdk" / "stacks" / "constants.py"
DEPLOYED_DIR = REPO_ROOT / "deploy" / "layers"
REQUIREMENTS_DIR = REPO_ROOT / "lambdas" / "requirements"
DEFAULT_OUT_DIR = REPO_ROOT / "deploy" / "zips"

# Fixed zip timestamp so two builds of the same resolved set are byte-identical.
# (1980-01-01 is the zip epoch — the earliest value the format can store.)
_ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)


@dataclass(frozen=True)
class LayerSpec:
    """One binary dependency layer: its target pins and how to package them."""

    key: str  # short name, must match the `layer:<key>-layer:` ARN in constants.py
    layer_name: str
    version_constant: str  # the `*_LAYER_VERSION` int in cdk/stacks/constants.py
    manifest: str  # filename under lambdas/requirements/
    requirements: tuple[str, ...]  # TARGET top-level pins the next build installs
    attached_to: tuple[str, ...]  # Lambda function names that mount this layer
    purpose: str
    python_version: str = "312"
    arch: str = "x86_64"
    platforms: tuple[str, ...] = ("manylinux2014_x86_64", "manylinux_2_28_x86_64")
    stack: str = "LifePlatformOperational"
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def runtime(self) -> str:
        return f"python3.{self.python_version[1:]}"

    @property
    def zip_name(self) -> str:
        return f"{self.layer_name}.zip"

    @property
    def deployed_path(self) -> Path:
        return DEPLOYED_DIR / f"{self.key}.deployed.json"

    @property
    def manifest_path(self) -> Path:
        return REQUIREMENTS_DIR / self.manifest


# ── The registry ──────────────────────────────────────────────────────────────
# Guard the SET, not the instance: every `*_LAYER_ARN` short-name in
# cdk/stacks/constants.py must appear here, and check_manifests() enforces that —
# so a fourth layer added to constants.py without build tooling fails the check
# rather than repeating the #2099 blind spot.
LAYERS: dict[str, LayerSpec] = {
    "pillow": LayerSpec(
        key="pillow",
        layer_name="pillow-layer",
        version_constant="PILLOW_LAYER_VERSION",
        manifest="pillow.txt",
        # TARGET: Pillow 12.3.0 is the first release that is pip-audit clean — it clears
        # all 25 advisories open against the deployed 11.3.0 (the highest `Fix Versions`
        # across that set is 12.3.0). Pillow has no runtime dependencies, so the layer is
        # exactly one wheel.
        requirements=("Pillow==12.3.0",),
        attached_to=("og-image-generator", "reading-cover-pipeline"),
        purpose="Pillow — PNG/WebP share-card rendering and book-cover processing.",
        notes=(
            "Pillow 12.x publishes manylinux_2_27/_2_28 wheels only — a manylinux2014-only",
            "build resolves nothing. Both tags are listed; glibc 2.34 on the AL2023-based",
            "python3.12 runtime satisfies manylinux_2_28.",
        ),
    ),
    "garth": LayerSpec(
        key="garth",
        layer_name="garth-layer",
        version_constant="GARTH_LAYER_VERSION",
        manifest="garmin.txt",
        # TARGET (#2101): garminconnect 0.3.8 — the first line that is OUTSIDE
        # PYSEC-2026-3467 (CVE-2026-54447), whose affected range is `< 0.3.5` (measured
        # from OSV, 2026-08-06). The prior note here said the fix was "code-incompatible";
        # that was measured against the OLD lambda. #2101 made lambdas/ingestion/
        # garmin_lambda.py generation-agnostic, so the incompatibility is gone: 0.3.x
        # renamed the transport seam `Garmin.garth` -> `Garmin.client`, and all 13 reads
        # this lambda makes funnel through one `connectapi(path, **kwargs)` call that
        # garth 0.6.3's Client already satisfies.
        #
        # garth stays pinned and stays in the layer. 0.3.x no longer declares it, but the
        # lambda still authenticates through it: 0.3.x's own DI token family is NOT
        # derivable from the OAuth1/OAuth2 bundle in Secrets Manager (measured — its
        # `Client.loads()` rejects the garth bundle outright), and re-minting one needs an
        # interactive re-auth against a vendor mid anti-automation crackdown (ADR-074).
        # 0.6.3 is retained rather than raised so this rebuild changes exactly one thing.
        requirements=("garminconnect==0.3.8", "garth==0.6.3"),
        attached_to=("garmin-data-ingestion",),
        purpose="garminconnect + garth — Garmin Connect OAuth and biometric/activity pulls.",
        stack="LifePlatformIngestion",
        notes=(
            "PYSEC-2026-3467 is live on the DEPLOYED 0.2.40 and clears on the next rebuild",
            "(#2101). Its threat model is a world-readable garmin_tokens.json on a SHARED",
            "multi-user host, written by a `Client.dump(path)` this lambda never calls (it",
            "holds tokens in Secrets Manager and sets no tokenstore path), so the exposure",
            "does not apply — the rebuild is hygiene, not incident response.",
            "",
            "0.3.x adds three transitive packages the 0.2.x line did not carry —",
            "curl_cffi, cffi, ua-generator — and drops the pydantic/oauthlib set. All",
            "resolve to cp312 manylinux2014 wheels (checked 2026-08-06), so the platform",
            "tags above still suffice. Expect the promoted package list below to change",
            "shape, not just versions.",
            "",
            "REBUILD SEQUENCE (owner, one sitting — the code side already merged):",
            "  1. python3 deploy/build_lambda_layer.py build garth",
            "  2. aws lambda publish-layer-version --layer-name garth-layer ...",
            "  3. bump GARTH_LAYER_VERSION in cdk/stacks/constants.py",
            "  4. bash deploy/cdk_deploy.sh LifePlatformIngestion",
            "  5. python3 deploy/build_lambda_layer.py --promote garth --from-build",
            "     <build.json> --layer-version <N>   (re-derives this manifest)",
            "  6. aws lambda invoke --function-name garmin-data-ingestion --payload",
            "     '{\"healthcheck\": true}'   — Garmin stays PAUSED (ADR-074); do not add",
            "     an EventBridge rule. A real data run needs the whoop-style re-auth first.",
        ),
    ),
    "lameenc": LayerSpec(
        key="lameenc",
        layer_name="lameenc-layer",
        version_constant="LAMEENC_LAYER_VERSION",
        manifest="lameenc.txt",
        requirements=("lameenc==1.8.4",),
        attached_to=("coach-panel-podcast",),
        purpose="lameenc — LAME MP3 encoder for spoken-word compression of Panel TTS audio.",
        stack="LifePlatformEmail",
        notes=(
            "Adopted into this registry by #2099 so the layer SET is covered, not just the",
            "two layers with CVEs. Supersedes deploy/build_lameenc_layer.sh, which hardcodes",
            "a single manylinux2014 tag and publishes in the same breath as it builds.",
        ),
    ),
}


# ── Manifest rendering (the ONE source of the derived manifests) ──────────────


def _rel(p: Path) -> str:
    """Repo-relative path for messages, degrading to the absolute path off-tree (tests)."""
    try:
        return str(p.relative_to(REPO_ROOT))
    except ValueError:
        return str(p)


def _canonical(name: str) -> str:
    """PEP 503 canonical distribution name (pip and pip-audit both normalize to this)."""
    return re.sub(r"[-_.]+", "-", name).lower()


def load_deployed(spec: LayerSpec) -> dict:
    """Load the recorded live-layer state, or a well-formed 'never measured' stub."""
    if not spec.deployed_path.is_file():
        return {"layer_version": None, "measured": None, "packages": {}}
    return json.loads(spec.deployed_path.read_text())


def render_manifest(spec: LayerSpec, deployed: dict | None = None) -> str:
    """Render `lambdas/requirements/<manifest>` from the spec + the deployed record.

    The output stays a valid pip requirements file: the scheduled
    lambdas/operational/pip_audit_lambda.py scans the uncommented pins, which are the
    DEPLOYED versions — so the CVEs it reports are the ones actually running, not the
    ones the next build would ship. That is deliberate. (The BLOCKING CI pip-audit gate
    in ci-lint.yml scans only requirements-dev.txt + cdk/requirements.txt, so listing a
    layer's real contents here surfaces them in the scheduled report without red-walling
    main on an advisory no rebuild can clear.)
    """
    d = deployed if deployed is not None else load_deployed(spec)
    pkgs = d.get("packages") or {}
    ver = d.get("layer_version")
    lines: list[str] = []
    a = lines.append

    a(f"# {spec.layer_name} — binary dependency layer ({spec.runtime}, {spec.arch})")
    a("#")
    a("# GENERATED — do not hand-edit. Regenerate with:")
    a(f"#   python3 deploy/build_lambda_layer.py --promote {spec.key} --from-build <build.json> --layer-version <N>")
    a(f"# Spec: deploy/build_lambda_layer.py::LAYERS['{spec.key}'] · drift gate: --check-manifest (#2099)")
    a("#")
    a(f"# {spec.purpose}")
    a(f"# Attached to: {', '.join(spec.attached_to)} (CDK stack: {spec.stack}).")
    a(f"# Layer ARN: cdk/stacks/constants.py::{spec.version_constant.replace('_VERSION', '_ARN')}.")
    a("#")
    a("# WHY THIS FILE EXISTS (#1336): third-party code reaches a running Lambda ONLY via")
    a("# these binary layers — no deploy path pip-installs from lambdas/requirements/. So")
    a("# this manifest is the sole surface pip-audit can scan for the layer's contents, and")
    a("# editing it does NOT change what is deployed (#1778/#1780). A real upgrade is:")
    a(f"#   build_lambda_layer.py build {spec.key} -> publish-layer-version -> bump")
    a(f"#   {spec.version_constant} -> cdk deploy {spec.stack} -> --promote back to here.")
    a("#")
    a("# ── BUILD TARGET — top-level pins the next build installs (spec, hand-edited there)")
    for req in spec.requirements:
        a(f"#   layer-build-target: {req}")
    a(f"#   layer-build-platform: {' '.join(spec.platforms)} · cp{spec.python_version}")
    a("#")
    if spec.notes:
        for n in spec.notes:
            a(f"# {n}")
        a("#")
    a("# ── DEPLOYED — the full resolved contents of the LIVE layer version below.")
    if ver is None:
        a("#   NOT YET MEASURED — run --promote after the next publish.")
    else:
        a(f"#   {spec.layer_name}:{ver}, measured {d.get('measured')} read-only via")
        a("#   `aws lambda get-layer-version-by-arn` + inspection of the returned zip's")
        a("#   *.dist-info. Ground truth, not an estimate. Transitive packages are listed")
        a("#   explicitly so pip-audit sees the WHOLE layer, not just its top-level pins.")
    a("")
    for name in sorted(pkgs):
        a(f"{_canonical(name)}=={pkgs[name]}")
    return "\n".join(lines) + "\n"


def check_manifests(keys: list[str] | None = None) -> list[str]:
    """Offline drift gate. Returns a list of human-readable problems ([] == clean).

    Four assertions, all cheap and network-free:
      1. every `*_LAYER_ARN` short-name in constants.py has a LayerSpec (the SET check);
      2. each deployed record's layer_version == the `*_LAYER_VERSION` in constants.py;
      3. each deployed record's top-level packages are present (a build sanity check);
      4. each manifest is byte-identical to render_manifest() — the anti-drift assertion.
    """
    problems: list[str] = []
    specs = [LAYERS[k] for k in (keys or sorted(LAYERS))]

    if keys is None:
        try:
            constants_text = CONSTANTS_PATH.read_text()
        except OSError as e:
            return [f"cannot read {CONSTANTS_PATH}: {e}"]
        arn_names = sorted({m.group(1) for m in re.finditer(r"layer:([a-z0-9_-]+?)-layer:", constants_text)})
        for name in arn_names:
            if name not in LAYERS:
                problems.append(f"{name}-layer is referenced in constants.py but has no LayerSpec in build_lambda_layer.py (#2099)")

    for spec in specs:
        deployed = load_deployed(spec)
        declared = _constant_int(spec.version_constant)
        if deployed.get("layer_version") != declared:
            problems.append(
                f"{spec.key}: deployed record says {spec.layer_name}:{deployed.get('layer_version')} "
                f"but constants.py {spec.version_constant} = {declared} — run --promote after publishing"
            )
        pkgs = {_canonical(n) for n in (deployed.get("packages") or {})}
        for req in spec.requirements:
            top = _canonical(re.split(r"[=<>!~]", req, maxsplit=1)[0])
            if pkgs and top not in pkgs:
                problems.append(f"{spec.key}: top-level pin {top!r} is missing from the deployed record")
        expected = render_manifest(spec, deployed)
        actual = spec.manifest_path.read_text() if spec.manifest_path.is_file() else ""
        if actual != expected:
            problems.append(f"{spec.key}: {_rel(spec.manifest_path)} has drifted from render_manifest() — run --promote")
    return problems


def _constant_int(name: str) -> int | None:
    """Read an int constant literal out of cdk/stacks/constants.py without importing CDK."""
    try:
        text = CONSTANTS_PATH.read_text()
    except OSError:
        return None
    m = re.search(rf"^{re.escape(name)}\s*=\s*(\d+)\s*$", text, re.MULTILINE)
    return int(m.group(1)) if m else None


# ── Build ─────────────────────────────────────────────────────────────────────


def _resolve(spec: LayerSpec, target: Path) -> None:
    """pip-install the target pins for the Lambda platform into `target` (the python/ dir)."""
    cmd = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--target",
        str(target),
        "--python-version",
        spec.python_version,
        "--implementation",
        "cp",
        "--only-binary",
        ":all:",
        "--no-compile",  # .pyc bytecode is host-specific and defeats determinism
        "--upgrade",
        "--no-cache-dir",
        "--disable-pip-version-check",
    ]
    for p in spec.platforms:
        cmd += ["--platform", p]
    cmd += list(spec.requirements)
    print(f"  $ {' '.join(cmd[cmd.index('install'):])}\n")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stderr.write(proc.stdout + proc.stderr)
        raise SystemExit(
            f"\nERROR: pip could not resolve {spec.layer_name} as pure Linux wheels.\n"
            f"       --only-binary=:all: fails LOUDLY here on purpose: a host-native fallback\n"
            f"       would produce a layer that imports fine locally and ImportErrors in Lambda.\n"
            f"       Fix the platform tags in LAYERS['{spec.key}'].platforms, or build in the SAM\n"
            f"       image (see the docker fallback in this file's docstring)."
        )


def _installed_packages(target: Path) -> dict[str, str]:
    """Map distribution name -> version from the staged tree's *.dist-info directories."""
    out: dict[str, str] = {}
    for d in sorted(target.glob("*.dist-info")):
        name, _, version = d.name[: -len(".dist-info")].rpartition("-")
        if name:
            out[_canonical(name)] = version
    return out


def _write_deterministic_zip(stage: Path, dest: Path) -> str:
    """Zip `stage` (which contains python/) with fixed mtimes + sorted entries. Returns sha256."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    paths = sorted(p for p in stage.rglob("*") if p.is_file() or p.is_dir())
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in paths:
            rel = p.relative_to(stage).as_posix()
            if p.is_dir():
                info = zipfile.ZipInfo(rel + "/", date_time=_ZIP_EPOCH)
                info.external_attr = (0o755 | 0o040000) << 16
                info.create_system = 3
                z.writestr(info, b"")
                continue
            mode = 0o755 if os.access(p, os.X_OK) else 0o644
            info = zipfile.ZipInfo(rel, date_time=_ZIP_EPOCH)
            info.external_attr = (mode | 0o100000) << 16
            info.create_system = 3
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, p.read_bytes())
    return hashlib.sha256(dest.read_bytes()).hexdigest()


def build(spec: LayerSpec, out_dir: Path, from_dir: Path | None = None) -> dict:
    """Build one layer zip. Returns the build record (also written next to the zip)."""
    print(f"\n=== {spec.layer_name} — {spec.runtime} / {spec.arch} ===")
    print(f"  target pins : {', '.join(spec.requirements)}")
    print(f"  platforms   : {', '.join(spec.platforms)}")
    workdir = Path(tempfile.mkdtemp(prefix=f"{spec.key}-layer-"))
    try:
        stage = workdir / "stage"
        target = stage / "python"  # the layer layout Lambda expects
        target.mkdir(parents=True)
        if from_dir is not None:
            print(f"  using pre-built tree: {from_dir}")
            shutil.copytree(from_dir, target, dirs_exist_ok=True)
        else:
            _resolve(spec, target)
        packages = _installed_packages(target)
        if not packages:
            raise SystemExit(f"ERROR: no *.dist-info under {target} — nothing was installed.")
        zip_path = out_dir / spec.zip_name
        sha = _write_deterministic_zip(stage, zip_path)
        record = {
            "layer_name": spec.layer_name,
            "runtime": spec.runtime,
            "architecture": spec.arch,
            "platforms": list(spec.platforms),
            "target_pins": list(spec.requirements),
            "packages": packages,
            "zip": str(zip_path),
            "zip_sha256": sha,
            "zip_bytes": zip_path.stat().st_size,
        }
        (out_dir / f"{spec.layer_name}.build.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")

        top = {_canonical(re.split(r"[=<>!~]", r, maxsplit=1)[0]) for r in spec.requirements}
        print(f"\n  packaged {len(packages)} distributions into {zip_path.name}:")
        for name in sorted(packages):
            marker = "*" if name in top else " "
            print(f"    {marker} {name}=={packages[name]}")
        print("    (* = top-level pin; the rest are transitive and MUST be listed in the manifest")
        print("       or pip-audit sees only part of the layer — that gap hid 3 CVEs in #2099.)")
        print(f"\n  zip    : {zip_path} ({record['zip_bytes'] / 1e6:.1f} MB)")
        print(f"  sha256 : {sha}")
        print(f"  record : {out_dir / (spec.layer_name + '.build.json')}")
        print("\n  NOT PUBLISHED. Next (owner):")
        print(f"    aws lambda publish-layer-version --layer-name {spec.layer_name} \\")
        print(f"      --compatible-runtimes {spec.runtime} --compatible-architectures {spec.arch} \\")
        print(f"      --zip-file fileb://{zip_path} --region us-west-2")
        print(f"    # bump {spec.version_constant} in cdk/stacks/constants.py, then")
        print(f"    bash deploy/cdk_deploy.sh {spec.stack}")
        print(f"    python3 deploy/build_lambda_layer.py --promote {spec.key} \\")
        print(f"      --from-build {out_dir / (spec.layer_name + '.build.json')} --layer-version <N>")
        return record
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def promote(spec: LayerSpec, build_record: Path, layer_version: int, measured: str) -> None:
    """Record a build as DEPLOYED and re-derive the manifest from it."""
    record = json.loads(build_record.read_text())
    if record.get("layer_name") != spec.layer_name:
        raise SystemExit(f"ERROR: build record is for {record.get('layer_name')}, not {spec.layer_name}")
    deployed = {
        "layer_name": spec.layer_name,
        "layer_version": layer_version,
        "measured": measured,
        "runtime": record["runtime"],
        "architecture": record["architecture"],
        "platforms": record["platforms"],
        "target_pins": record["target_pins"],
        "zip_sha256": record.get("zip_sha256"),
        "packages": record["packages"],
    }
    spec.deployed_path.parent.mkdir(parents=True, exist_ok=True)
    spec.deployed_path.write_text(json.dumps(deployed, indent=2, sort_keys=True) + "\n")
    spec.manifest_path.write_text(render_manifest(spec, deployed))
    print(f"promoted {spec.layer_name}:{layer_version}")
    print(f"  wrote {_rel(spec.deployed_path)}")
    print(f"  wrote {_rel(spec.manifest_path)}")
    print(f"  reminder: {spec.version_constant} in cdk/stacks/constants.py must equal {layer_version}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", nargs="?", choices=["build"], help="build the layer zip(s)")
    ap.add_argument("layer", nargs="?", help=f"layer key ({', '.join(sorted(LAYERS))})")
    ap.add_argument("--all", action="store_true", help="apply to every registered layer")
    ap.add_argument("--out", default=str(DEFAULT_OUT_DIR), help="output directory for zips (default deploy/zips)")
    ap.add_argument("--from-dir", help="skip pip; package this already-built python/ tree (docker fallback)")
    ap.add_argument("--list", action="store_true", help="list the registered layers and exit")
    ap.add_argument("--check-manifest", action="store_true", help="offline drift gate; non-zero exit on drift")
    ap.add_argument("--render", metavar="LAYER", help="print the derived manifest for LAYER and exit")
    ap.add_argument("--promote", metavar="LAYER", help="record a build as deployed + re-derive its manifest")
    ap.add_argument("--from-build", help="path to the <layer>.build.json produced by `build` (with --promote)")
    ap.add_argument("--layer-version", type=int, help="the published layer version (with --promote)")
    ap.add_argument("--measured", help="ISO date for the deployed record (default: today, UTC)")
    args = ap.parse_args(argv)

    if args.list:
        for k in sorted(LAYERS):
            s = LAYERS[k]
            d = load_deployed(s)
            print(f"{k:9s} {s.layer_name}:{d.get('layer_version')}  {s.runtime}/{s.arch}  -> {', '.join(s.attached_to)}")
            print(f"{'':9s} target: {', '.join(s.requirements)}  manifest: lambdas/requirements/{s.manifest}")
        return 0

    if args.render:
        sys.stdout.write(render_manifest(LAYERS[args.render]))
        return 0

    if args.check_manifest:
        problems = check_manifests()
        if problems:
            print("LAYER MANIFEST DRIFT (#2099):")
            for p in problems:
                print(f"  - {p}")
            return 1
        print(f"clean — {len(LAYERS)} layer manifests match their deployed records and constants.py")
        return 0

    if args.promote:
        if not args.from_build or args.layer_version is None:
            ap.error("--promote requires --from-build and --layer-version")
        import datetime

        measured = args.measured or datetime.datetime.now(datetime.timezone.utc).date().isoformat()
        promote(LAYERS[args.promote], Path(args.from_build), args.layer_version, measured)
        return 0

    if args.command != "build":
        ap.print_help()
        return 2

    keys = sorted(LAYERS) if args.all else [args.layer]
    if keys == [None]:
        ap.error("build needs a layer key or --all")
    for k in keys:
        if k not in LAYERS:
            ap.error(f"unknown layer {k!r}; known: {', '.join(sorted(LAYERS))}")
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    for k in keys:
        build(LAYERS[k], out_dir, Path(args.from_dir) if args.from_dir else None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
