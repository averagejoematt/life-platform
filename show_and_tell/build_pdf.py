#!/usr/bin/env python3
"""
show_and_tell/build_pdf.py

Data-driven PDF builder for the Life Platform Show & Tell.
Reads manifest.json for all version-specific stats, then calls build_v4.py
using the processed screenshots from show_and_tell/processed/.

Usage:
  python3 build_pdf.py                    # builds to show_and_tell/output/
  python3 build_pdf.py --open             # builds and opens in Preview

Full pipeline:
  1. python3 capture_screenshots.py       # automated + manual screenshot checklist
  2. python3 redact_screenshots.py        # apply redaction rules
  3. python3 build_pdf.py --open          # generate PDF

Or all at once:
  ./run.sh
"""

import json
import sys
import os
import subprocess
import shutil
from pathlib import Path
from datetime import datetime

HERE = Path(__file__).parent
ROOT = HERE.parent
MANIFEST_PATH = HERE / "manifest.json"
PROCESSED_DIR = HERE / "processed"
BUILD_SCRIPT  = HERE / "build_pdf_core.py"  # generated copy of build_v4.py
OUTPUT_DIR    = HERE / "output"
OUTPUT_DIR.mkdir(exist_ok=True)


def load_manifest():
    with open(MANIFEST_PATH) as f:
        return json.load(f)


def patch_build_script(manifest):
    """
    Copy build_v4.py from root, then patch all hardcoded stats
    with values from manifest.json.
    """
    src = ROOT / "build_v4.py"
    if not src.exists():
        # Check show_and_tell dir itself
        src = HERE / "build_v4.py"
    if not src.exists():
        print(f"ERROR: Cannot find build_v4.py at {ROOT}")
        sys.exit(1)

    code = src.read_text()

    # ── Patch all /home/claude/ hardcoded paths ──
    path_patches = {
        '"/home/claude/demo_processed"': f'"{PROCESSED_DIR}"',
        '"/home/claude/tier_progression.png"': f'"{HERE / "tier_progression.png"}"',
        '"/home/claude/arch_diagram.png"': f'"{HERE / "arch_diagram.png"}"',
    }
    for old, new in path_patches.items():
        code = code.replace(old, new)

    # ── Patch hardcoded output path ──
    code = code.replace(
        'build("/mnt/user-data/outputs/LifePlatform_ShowAndTell_v4.pdf")',
        'import os as _os; build(_os.environ.get("SAT_OUTPUT_PATH", "output/LifePlatform_ShowAndTell_LATEST.pdf"))'
    )

    # ── Patch version numbers ──
    m = manifest["meta"]
    p = manifest["platform_stats"]

    replacements = [
        ('"v2.80"',              f'"{m["version"]}"'),
        ('"555 objects"',        f'"{m["git_objects"]} objects"'),
        ('"~80 sessions"',       f'"{m["sessions"]} sessions"'),
        ('124 tools',            f'{p["tools"]} tools'),
        ('124-tool',             f'{p["tools"]}-tool'),
        ('"124"',                f'"{p["tools"]}"'),
        ('30 Lambdas',           f'{p["lambdas"]} Lambdas'),
        ('30th Lambda',          f'{p["lambdas"]}th Lambda'),
        ('"30"',                 f'"{p["lambdas"]}"'),
        ('19 sources',           f'{p["sources"]} sources'),
        ('"19"',                 f'"{p["sources"]}"'),
        ('20 of 30 Lambdas',     f'{p["dlq_lambdas"]} of {p["lambdas"]} Lambdas'),
        ('35 alarms',            f'{p["alarms"]} alarms'),
        ('20+", "incidents',     f'{p["incidents_logged"]}", "incidents'),
        ('80+", "handover',      f'{p["handover_files"]}", "handover'),
        ('80+", "CHANGELOG',     f'{p["changelog_entries"]}", "CHANGELOG'),
        ('v2.80.1 — 555',        f'{m["version"]}.1 — {m["git_objects"]}'),
    ]

    for old, new in replacements:
        code = code.replace(old, new)

    BUILD_SCRIPT.write_text(code)
    return BUILD_SCRIPT


def build(manifest, open_after=False):
    version = manifest["meta"]["version"]
    date_str = datetime.now().strftime("%Y-%m-%d")
    out_filename = f"LifePlatform_ShowAndTell_{version}_{date_str}.pdf"
    out_path = OUTPUT_DIR / out_filename

    print(f"\nLife Platform Show & Tell PDF Builder")
    print(f"Version:  {version}")
    print(f"Output:   {out_path}")
    print(f"─"*60)

    # Check screenshots are present
    shots = list(PROCESSED_DIR.glob("*.png"))
    print(f"Screenshots: {len(shots)} found in processed/")
    if len(shots) < 10:
        print("⚠  Warning: fewer than 10 screenshots — some sections may be empty")

    # Patch build script
    print("Patching build script with manifest values... ", end="", flush=True)
    patched = patch_build_script(manifest)
    print("✓")

    # Run build — pass output path as env var so the patched script picks it up
    print(f"Building PDF... ", end="", flush=True)
    env = os.environ.copy()
    env["SAT_OUTPUT_PATH"] = str(out_path)
    result = subprocess.run(
        [sys.executable, str(patched)],
        env=env, capture_output=True, text=True
    )

    if result.returncode != 0:
        print("✗ FAILED")
        print(result.stderr)
        sys.exit(1)

    print(f"✓")
    print(f"\n✅ PDF ready: {out_path}")

    # Also copy to a stable "latest" path
    latest = OUTPUT_DIR / "LifePlatform_ShowAndTell_LATEST.pdf"
    shutil.copy(out_path, latest)
    print(f"   Also at:   {latest}")

    if open_after:
        subprocess.run(["open", str(out_path)])


def main():
    open_after = "--open" in sys.argv

    if not MANIFEST_PATH.exists():
        print(f"ERROR: manifest.json not found at {MANIFEST_PATH}")
        sys.exit(1)

    if not any(PROCESSED_DIR.glob("*.png")):
        print("ERROR: No processed screenshots found.")
        print("Run: python3 capture_screenshots.py && python3 redact_screenshots.py")
        sys.exit(1)

    manifest = load_manifest()
    build(manifest, open_after=open_after)


if __name__ == "__main__":
    main()
