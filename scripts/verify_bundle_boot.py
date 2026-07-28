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

Usage:
  python3 scripts/verify_bundle_boot.py                    # tree bundle
  python3 scripts/verify_bundle_boot.py --mcp              # tree + mcp/ bundle
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


def run(mcp=False):
    import build_bundle

    tmp = tempfile.mkdtemp(prefix="bundleboot-")
    out = os.path.join(tmp, "bundle")
    build_bundle.stage_mcp(out) if mcp else build_bundle.stage_tree(out)
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mcp", action="store_true", help="stage the mcp bundle shape too")
    ap.add_argument("--baseline", help="write current failures to this JSON and exit 0")
    ap.add_argument("--compare", help="fail only on failures absent from this JSON")
    args = ap.parse_args()

    mods, failures = run(mcp=args.mcp)
    shape = "mcp" if args.mcp else "tree"
    print(f"bundle shape: {shape}   modules probed: {len(mods)}   import failures: {len(failures)}")

    if args.baseline:
        with open(args.baseline, "w", encoding="utf-8") as f:
            json.dump(failures, f, indent=1, sort_keys=True)
        print(f"baseline written -> {args.baseline} ({len(failures)} known failures)")
        for m in sorted(failures):
            print(f"  known: {m}: {failures[m][:130]}")
        return 0

    known = {}
    if args.compare and os.path.exists(args.compare):
        with open(args.compare, encoding="utf-8") as f:
            known = json.load(f)

    new = {m: e for m, e in failures.items() if m not in known}
    fixed = [m for m in known if m not in failures]
    for m in sorted(new):
        print(f"  NEW FAILURE  {m}: {new[m][:200]}")
    if fixed:
        print(f"  ({len(fixed)} previously-failing modules now import cleanly)")
    if new:
        print(f"\n❌ {len(new)} NEW import failure(s) — the bundle would not boot.")
        return 1
    print("\n✅ no new import failures.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
