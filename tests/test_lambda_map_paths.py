"""tests/test_lambda_map_paths.py — #1653: every source path in ci/lambda_map.json must exist.

Why this is a separate guard from the ones that already existed:

  * CI's "Validate lambda_map.json" step (ci-cd.yml) walks `jq -r '.lambdas | keys[]'`.
  * CI's "Check lambda_map coverage" step (ci-lint.yml) greps the file for each source
    file — it checks the OTHER direction (repo -> map).
  * tests/test_lambda_map_imports.py AST-checks annotations on `.lambdas` entries.

All three only ever look at the `.lambdas` section. Nothing validated the sibling
sections, so when the 2026-05-25 reorg moved handlers into subpackages, eight dead
`lambdas/<name>.py` paths survived undetected in four orphan top-level sections and in
`skip_deploy.files` — carrying FLAT handler strings ("acwr_compute_lambda.lambda_handler")
that live had long since stopped matching ("compute.acwr_compute_lambda.lambda_handler").
Dead JSON is harmless until someone believes it. This asserts the whole file.

Deliberately a subset-style ratchet: it asserts every declared path RESOLVES, not that
every file on disk is declared (ci-lint.yml owns that direction). So pruning the map
never reds this, and the #1653 packaging slices only have to keep declared paths honest.
"""

import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_MAP = os.path.join(_REPO, "ci", "lambda_map.json")


def _all_py_paths(obj, trail=""):
    """Yield (json_trail, path) for every .py-looking string anywhere in the map.

    Source paths appear both as dict KEYS (the .lambdas section, keyed by source file)
    and as list VALUES (skip_deploy.files), so both positions are walked.
    """
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str) and k.endswith(".py"):
                yield f"{trail}.{k}" if trail else k, k
            yield from _all_py_paths(v, f"{trail}.{k}" if trail else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _all_py_paths(v, f"{trail}[{i}]")
    elif isinstance(obj, str) and obj.endswith(".py"):
        yield trail, obj


def test_every_declared_source_path_exists():
    with open(_MAP, encoding="utf-8") as f:
        data = json.load(f)

    missing = []
    for trail, path in _all_py_paths(data):
        # Lambda@Edge ships .mjs; only first-party python paths are checked here.
        if not path.startswith("lambdas/"):
            continue
        if not os.path.exists(os.path.join(_REPO, path)):
            missing.append(f"{path}   (at ci/lambda_map.json -> {trail})")

    assert not missing, "ci/lambda_map.json references source files that do not exist:\n  " + "\n  ".join(sorted(set(missing)))


def test_no_orphan_top_level_function_sections():
    """Function entries belong in `.lambdas`, not as ad-hoc top-level sections.

    The four orphan sections removed in #1653 were invisible to every deploy path and
    every gate. This keeps the file's shape legible: top-level keys are either metadata
    (`_`-prefixed), or one of the known sections.
    """
    with open(_MAP, encoding="utf-8") as f:
        data = json.load(f)

    known_sections = {"lambdas", "lambda_edge", "mcp", "skip_deploy"}
    stray = [k for k, v in data.items() if not k.startswith("_") and k not in known_sections and (isinstance(v, dict) or k.endswith(".py"))]
    assert not stray, (
        "Unexpected top-level section(s) in ci/lambda_map.json: "
        f"{sorted(stray)}. Lambda entries belong under `.lambdas` — CI validates only that "
        "section (jq '.lambdas | keys[]'), so anything else is invisible to the deploy path."
    )
