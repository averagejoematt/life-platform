#!/usr/bin/env python3
"""verify_bundle_boot.py — import every module out of a STAGED bundle, with the
same sys.path Lambda actually gives it.

Why this exists (#1653): tests/conftest.py adds lambdas/ AND each subpackage to
sys.path so legacy flat-name imports keep resolving. That is convenient for the
suite and actively dangerous for a packaging refactor — a stale `import ai_calls`
left behind after ai_calls.py moved to lambdas/ai/ still passes under pytest and
then raises ImportError in production. This checker removes that safety net: it
stages the real bundle via deploy/build_bundle.py and imports each module in a
subprocess whose sys.path is the bundle root and nothing else, which is exactly
/var/task at runtime.

This is the same failure class as the #697 personal_baselines outage (module
present in the repo, absent from what actually shipped).

WHERE THIS RUNS (#2632 — it used to run nowhere; grep found the string only in
this docstring):

  1. deploy/build_bundle.py's CLI `main()`, default-ON, on the bundle it just
     staged. That is the strongest placement available: the artifact actually
     exists at that moment, so the gate reads the real thing instead of a
     reconstruction, and it fires BEFORE the first AWS mutation in every caller
     (deploy_lambda.sh, deploy_fleet.sh, deploy_site_api.sh, deploy_mcp_split.sh
     — all `set -e`). Wiring it in `main()` rather than in each shell script is
     deliberate: a future deploy script inherits the gate instead of forgetting
     it. `stage_tree()`/`stage_mcp()` are NOT gated — CDK imports those directly
     at synth time and must stay fast.
     Escape hatch: SKIP_BUNDLE_BOOT_CHECK=1 (env, loud) or --no-verify-boot.

  2. .github/workflows/pr-checks.yml's fast lane — the pre-merge early warning,
     so the failure reaches a human before the merge rather than at deploy time.

BASELINE (`--compare`, used — not dropped). Measured 2026-08-13: the tree bundle
probes 397 modules and the mcp bundle 436, with **zero** failures on a workstation
that has Pillow installed. In a PIL-free environment (the pre-merge lane installs
only pytest/boto3/botocore/black/hypothesis/pyyaml/mypy/ruff) the same probe
reports 4 — the Pillow-importing modules, whose dependency arrives from a Lambda
LAYER and never from the bundle. Those 4 are a probe-environment gap, not a
bundle-shape defect, and without a baseline this gate would red on day one for a
reason nobody can fix and be `--skip`'d by day two. They are therefore recorded in
deploy/bundle_boot_baseline.json and suppressed BY NAME, with the suppression
count printed on every run so it cannot go quiet. Nothing else is suppressed;
adding an entry means editing a committed file in a reviewed diff.

Usage:
  python3 scripts/verify_bundle_boot.py                    # tree bundle
  python3 scripts/verify_bundle_boot.py --mcp              # tree + mcp/ bundle
  python3 scripts/verify_bundle_boot.py --bundle DIR       # probe an ALREADY-staged bundle
  python3 scripts/verify_bundle_boot.py --baseline out.json    # record current failures
  python3 scripts/verify_bundle_boot.py --compare out.json     # fail only on NEW failures

Exit 0 = no new import failures.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "deploy"))

# The committed suppression list the wired call sites compare against. See the
# BASELINE paragraph in the module docstring for why it is not empty.
DEFAULT_BASELINE = os.path.join(REPO, "deploy", "bundle_boot_baseline.json")

# Mirrors tests/conftest.py's hermetic env so an import-time AWS read cannot turn
# a network blip into a fake import failure.
HERMETIC_ENV = {
    "AI_VALIDATOR_AUTOLOAD": "off",
    "PANELCAST_ZEITGEIST": "off",
    "AWS_ACCESS_KEY_ID": "testing",
    "AWS_SECRET_ACCESS_KEY": "testing",
    "AWS_SESSION_TOKEN": "testing",
    "AWS_DEFAULT_REGION": "us-west-2",
    # Handlers that read required config at import time raise KeyError/RuntimeError
    # before any import problem can surface. Supplying placeholders keeps the
    # baseline at zero, so ANY failure this checker reports is a real one.
    "S3_BUCKET": "bundle-boot-probe",
    "USER_ID": "matthew",
    "EMAIL_RECIPIENT": "probe@example.invalid",
    "EMAIL_SENDER": "probe@example.invalid",
    "DIGEST_QUEUE_URL": "https://sqs.us-west-2.amazonaws.com/000000000000/probe",
}

PROBE = r"""
import importlib, json, sys, os
root = sys.argv[1]
mods = json.loads(sys.argv[2])
# Isolation is done by the PARENT: PYTHONPATH=<bundle root> and cwd set to an
# empty temp dir, so sys.path is ['', <bundle root>, <stdlib>, <site-packages>]
# and the repo working tree is nowhere on it. Do NOT clear sys.path here — that
# would take the stdlib with it and every module would "fail" on `import json`.
assert root in sys.path, "bundle root not on sys.path"
assert not any("wt-1653" in p or p.rstrip("/").endswith("/lambdas") for p in sys.path if p), sys.path
failures = {}
for m in mods:
    try:
        importlib.import_module(m)
    except BaseException as e:
        failures[m] = f"{type(e).__name__}: {e}"
print(json.dumps(failures))
"""


def module_names(bundle_root):
    """Every importable module in the staged bundle, as dotted names."""
    names = []
    for dp, dn, fn in os.walk(bundle_root):
        dn[:] = [d for d in dn if d != "__pycache__"]
        rel = os.path.relpath(dp, bundle_root)
        for f in sorted(fn):
            if not f.endswith(".py") or f == "__init__.py":
                continue
            stem = f[:-3]
            names.append(stem if rel == "." else rel.replace(os.sep, ".") + "." + stem)
    return sorted(names)


def probe_bundle(bundle_root, workdir=None):
    """Import every module in an ALREADY-STAGED bundle. Returns (modules, failures).

    Split out of run() for #2632: the deploy path has the real staged artifact in
    hand, and a gate on the artifact beats a gate on a reconstruction. The cwd is
    an empty temp dir and PYTHONPATH is the bundle root and nothing else, so the
    repo working tree cannot rescue a stale import.
    """
    out = bundle_root
    tmp = workdir or tempfile.mkdtemp(prefix="bundleboot-cwd-")
    mods = module_names(out)
    env = dict(os.environ)
    env.update(HERMETIC_ENV)
    env["PYTHONPATH"] = out  # the ONLY first-party path the probe can see
    env.pop("PYTHONHOME", None)
    # chunk so one hard crash (segfault/SystemExit) can't lose the whole report
    failures = {}
    CHUNK = 40
    for i in range(0, len(mods), CHUNK):
        batch = mods[i : i + CHUNK]
        p = subprocess.run(
            [sys.executable, "-c", PROBE, out, json.dumps(batch)],
            capture_output=True,
            text=True,
            env=env,
            cwd=tmp,
        )
        try:
            failures.update(json.loads(p.stdout.strip().splitlines()[-1]))
        except Exception:
            for m in batch:
                failures[m] = f"probe crashed (exit {p.returncode}): {p.stderr.strip()[-200:]}"
    return mods, failures


def run(mcp=False):
    """Stage a fresh bundle and probe it. Standalone/CLI path."""
    import build_bundle

    tmp = tempfile.mkdtemp(prefix="bundleboot-")
    out = os.path.join(tmp, "bundle")
    build_bundle.stage_mcp(out) if mcp else build_bundle.stage_tree(out)
    return probe_bundle(out, workdir=tmp)


def load_baseline(path):
    """Read the suppression list. Keys starting with `_` are prose, not modules."""
    if not path or not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return {k: v for k, v in data.items() if not k.startswith("_")}


def report(mods, failures, shape="tree", compare=None):
    """Print the verdict and return the process exit code (0 clean, 1 new failures).

    The single place the pass/fail decision is made, so the CLI and the deploy-path
    call site in build_bundle.py cannot drift into disagreeing about what "green"
    means (#2632).
    """
    print(f"bundle shape: {shape}   modules probed: {len(mods)}   import failures: {len(failures)}")
    known = load_baseline(compare)
    new = {m: e for m, e in failures.items() if m not in known}
    suppressed = sorted(m for m in failures if m in known)
    fixed = [m for m in known if m not in failures]
    for m in sorted(new):
        print(f"  NEW FAILURE  {m}: {new[m][:200]}")
    if suppressed:
        # Printed every run, never silent: a baseline nobody sees is a baseline
        # that grows.
        print(f"  ({len(suppressed)} baselined failure(s) suppressed: {', '.join(suppressed)})")
    if fixed:
        print(f"  ({len(fixed)} previously-failing modules now import cleanly)")
    if new:
        print(f"\n❌ {len(new)} NEW import failure(s) — the bundle would not boot.")
        return 1
    print("\n✅ no new import failures.")
    return 0


def gate_staged_bundle(bundle_root, shape="tree", compare=DEFAULT_BASELINE):
    """Probe an already-staged bundle and return an exit code. The deploy-path entry."""
    mods, failures = probe_bundle(bundle_root)
    return report(mods, failures, shape=shape, compare=compare)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mcp", action="store_true", help="stage the mcp bundle shape too")
    ap.add_argument("--bundle", help="probe this ALREADY-staged bundle dir instead of staging one")
    ap.add_argument("--baseline", help="write current failures to this JSON and exit 0")
    ap.add_argument("--compare", help="fail only on failures absent from this JSON")
    args = ap.parse_args()

    shape = "mcp" if args.mcp else "tree"
    if args.bundle:
        mods, failures = probe_bundle(args.bundle)
        shape = f"staged:{args.bundle}"
    else:
        mods, failures = run(mcp=args.mcp)

    if args.baseline:
        print(f"bundle shape: {shape}   modules probed: {len(mods)}   import failures: {len(failures)}")
        with open(args.baseline, "w", encoding="utf-8") as f:
            json.dump(failures, f, indent=1, sort_keys=True)
        print(f"baseline written -> {args.baseline} ({len(failures)} known failures)")
        for m in sorted(failures):
            print(f"  known: {m}: {failures[m][:130]}")
        return 0

    return report(mods, failures, shape=shape, compare=args.compare)


if __name__ == "__main__":
    sys.exit(main())
