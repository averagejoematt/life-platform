"""#2541 — the starter template's public claims, enforced rather than asserted.

`oss/starter-slice/` exists to be copied out of this repository and handed to a
stranger. Three of its claims are the kind that quietly stop being true:

  1. **Zero personal data, secrets, or account-specific identifiers.** The whole
     template is derived from a codebase full of them, so this is the claim most
     likely to be violated by an innocent copy-paste. Scanned as a forbidden-literal
     sweep over every byte of the directory.
  2. **It runs standalone.** No import may reach back into the platform. Checked by
     parsing every module's top-level imports, and by running the template's own
     test suite in a subprocess (CI's `pytest tests/` does not collect `oss/`).
  3. **Its cost note is derived, not retyped.** `scripts/build_starter_slice_cost.py`
     bakes `site/data/stack.json`'s `cost_of_ownership` into the template. This
     re-runs the generator in memory and fails on any drift, so a manifest change
     cannot leave a stale dollar figure in an artifact we are about to publish.

Publication itself is an owner act and is deliberately not automated anywhere.
"""

import ast
import importlib.util
import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SLICE_DIR = os.path.join(ROOT, "oss", "starter-slice")
PKG_DIR = os.path.join(SLICE_DIR, "starter_slice")
README = os.path.join(SLICE_DIR, "README.md")
NOTE = os.path.join(SLICE_DIR, "cost_note.json")

# Every literal that would make this template a leak rather than a lesson. Lower-cased
# before comparison. `averagejoematt.com` is deliberately ABSENT: the public site name
# is the template's provenance, and is already published on every page of it.
FORBIDDEN_LITERALS = [
    "matthew",  # the owner's name, in any casing, anywhere
    "205930651321",  # the AWS account id
    "matthew-life-platform",  # the real S3 bucket
    "life-platform/",  # the Secrets Manager prefix
    "user#matthew",  # the real DynamoDB partition
    "e3s424oxqz8nbe",  # the CloudFront distribution
    "47.6062",  # the real weather lambda's latitude
    "-122.3321",  # ...and longitude
    "whoop",  # credentialed vendors: naming them implies keys the template has not got
    "withings",
    "garmin",
    "hevy",
    "todoist",
]

_STDLIB = set(getattr(sys, "stdlib_module_names", ())) | {"starter_slice"}


def _slice_files():
    for dirpath, dirnames, filenames in os.walk(SLICE_DIR):
        dirnames[:] = [d for d in dirnames if d not in {"__pycache__", ".slice-data", "out"}]
        for name in filenames:
            if not name.endswith(".pyc"):
                yield os.path.join(dirpath, name)


def _py_files():
    return [p for p in _slice_files() if p.endswith(".py")]


# --- claim 1: zero personal data -------------------------------------------


def test_no_personal_data_secrets_or_account_identifiers():
    hits = []
    for path in _slice_files():
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            lowered = fh.read().lower()
        for literal in FORBIDDEN_LITERALS:
            if literal in lowered:
                hits.append(f"{os.path.relpath(path, ROOT)}: {literal!r}")
    assert not hits, "starter-slice must contain no personal or account-specific literal:\n  " + "\n  ".join(hits)


def test_the_forbidden_sweep_can_actually_fail(tmp_path):
    """Mutation proof: the sweep is only worth having if a planted literal reds it."""
    planted = tmp_path / "leak.txt"
    planted.write_text("bucket = matthew-life-platform\n", encoding="utf-8")
    lowered = planted.read_text(encoding="utf-8").lower()
    assert any(literal in lowered for literal in FORBIDDEN_LITERALS)


def test_the_default_coordinates_are_not_the_platform_s():
    spec = importlib.util.spec_from_file_location("_slice_config_under_test", os.path.join(PKG_DIR, "config.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert (module.DEFAULT_LAT, module.DEFAULT_LON) == (51.4779, -0.0015)
    assert module.load(bucket=None, table=None).user_id == "demo"


# --- claim 2: it runs standalone -------------------------------------------


def test_no_module_imports_the_platform_at_module_level():
    offenders = []
    for path in _py_files():
        with open(path, "r", encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), filename=path)
        # Module level ONLY — `tree.body`, never ast.walk: an import inside a function
        # (boto3 in the AWS backend) is exactly the lazy pattern that keeps the local
        # path dependency-free, and must not be flagged.
        for node in tree.body:
            roots = []
            if isinstance(node, ast.Import):
                roots = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                roots = [node.module.split(".")[0]]
            for root in roots:
                if root not in _STDLIB and root not in {"pytest"}:
                    offenders.append(f"{os.path.relpath(path, ROOT)}: {root}")
    assert not offenders, "starter-slice must import nothing outside the standard library at module level:\n  " + "\n  ".join(offenders)


def test_the_templates_own_test_suite_passes_standalone():
    """CI's `pytest tests/` never collects oss/ — run the template's suite here."""
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-q"],
        cwd=SLICE_DIR,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc.returncode == 0, f"starter-slice's own suite failed:\n{proc.stdout}\n{proc.stderr}"


def test_it_ships_what_a_stranger_needs():
    for name in ("README.md", "LICENSE", "run.py", "infrastructure.yaml", "cost_note.json", "pyproject.toml"):
        assert os.path.exists(os.path.join(SLICE_DIR, name)), f"missing {name}"


def test_the_readme_states_what_the_slice_is_not():
    text = open(README, encoding="utf-8").read()
    assert "## What this is NOT" in text
    for omission in ("Scheduling", "Credentialed sources", "Gap-aware backfill", "Any AI"):
        assert omission in text, f"the README stops naming a real omission: {omission}"
    assert "costs money" in text, "the AWS path must warn about cost before the commands, not after"


# --- claim 3: the cost note is derived --------------------------------------


def _generator():
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import build_starter_slice_cost  # noqa: E402

    return build_starter_slice_cost


def test_cost_note_and_readme_block_match_the_stack_manifest():
    gen = _generator()
    note, readme = gen.render()
    on_disk_note = open(NOTE, encoding="utf-8").read()
    assert (
        on_disk_note == json.dumps(note, indent=2, ensure_ascii=False) + "\n"
    ), "cost_note.json has drifted from site/data/stack.json — run `python3 scripts/build_starter_slice_cost.py`"
    assert (
        open(README, encoding="utf-8").read() == readme
    ), "the README cost block has drifted from site/data/stack.json — run `python3 scripts/build_starter_slice_cost.py`"


def test_every_dollar_figure_in_the_template_comes_from_the_manifest():
    """Mutation proof: move a manifest figure, and the rendered block must move with it."""
    gen = _generator()
    with open(os.path.join(ROOT, "site", "data", "stack.json"), encoding="utf-8") as fh:
        manifest = json.load(fh)
    real = gen.build_readme_block(gen.build_note(manifest))
    assert f"${manifest['cost_of_ownership']['aws']['ceiling_usd']:g}" in real

    manifest["cost_of_ownership"]["aws"]["ceiling_usd"] = 999.0
    moved = gen.build_readme_block(gen.build_note(manifest))
    assert "$999" in moved and moved != real


def test_the_note_asserts_no_unmeasured_figure_for_the_slice_itself():
    note = json.load(open(NOTE, encoding="utf-8"))
    assert note["this_slice"]["monthly_usd"] is None, "ADR-104: no guessed figure for a cost nothing here measures"
    assert note["this_slice"]["basis"]
    assert note["derived_from"].endswith("/data/stack.json")


@pytest.mark.parametrize("marker", ["<!-- BEGIN GENERATED: cost", "<!-- END GENERATED: cost -->"])
def test_the_generated_block_is_marked_as_generated(marker):
    assert marker in open(README, encoding="utf-8").read()
