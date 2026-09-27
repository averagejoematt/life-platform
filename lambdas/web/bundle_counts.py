"""
lambdas/web/bundle_counts.py — the counters STAMPED INTO THE BUNDLE at build time (#4250).

`test_count` used to be a committed literal in the generated `web/platform_counts.py`.
Nearly every PR adds a test, so the reconcile bot committed a one-integer bump to main
after nearly every merge (7 d to 2026-09-27: 120 of 125 `chore(reconcile)` commits
touched it, 70 changed nothing else), and each of those pushes started a second full
CI/CD run and a gated fleet deploy.

The count is not a fact about main's history, it is a fact about the code that is
DEPLOYED — so it is stamped where the deploy is built. `deploy/build_bundle.py::
stage_bundle_counts` writes `bundle_counts.json` at the bundle root (the same fail-soft,
deterministic, no-timestamp shape as `qa_coverage_stats.json`), from the same
`def test_` count `sync_doc_metadata.py --print test_count` prints. Nothing is committed.

Resolution, in order:
  1. `bundle_counts.json` at the bundle root — a deployed Lambda.
  2. a `tests/` directory beside the bundle root — a repo checkout (unit tests, local
     tools). That is a LIVE derivation of the very tree being read, never a cached number.
  3. neither — `test_count` is omitted from the served dict. An absent key is honest; a
     remembered number is the stale-literal class this module exists to remove.

What this gives up: the served number is as fresh as the last deploy of the bundle, not
as fresh as main. A PR that adds tests but deploys nothing moves no served number until
the next site-api/fleet deploy.
"""

import json
import os
import re

BUNDLE_COUNTS_NAME = "bundle_counts.json"
_BUNDLE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TEST_DEF = re.compile(r"^\s*def test_", re.MULTILINE)


def count_test_functions(tests_dir: str) -> int | None:
    """`def test_` functions across tests/*.py (non-recursive) — the one public test count.

    Must equal deploy/sync_doc_metadata.py::_count_test_functions (pinned by
    tests/test_platform_stats_truth.py), because the bundle stamp is built from that
    script's `--print test_count` and this is the checkout-side reader of the same fact.
    """
    if not os.path.isdir(tests_dir):
        return None
    total = 0
    try:
        for name in os.listdir(tests_dir):
            if name.endswith(".py") and not name.startswith("."):  # glob("*.py") semantics
                with open(os.path.join(tests_dir, name), encoding="utf-8") as f:
                    total += len(_TEST_DEF.findall(f.read()))
    except Exception:
        return None
    return total or None


def load_bundle_counts(bundle_root: str = _BUNDLE_ROOT) -> dict:
    """{"test_count": int} from the bundle stamp, else a live checkout count, else {}."""
    stamp = os.path.join(bundle_root, BUNDLE_COUNTS_NAME)
    try:
        with open(stamp, encoding="utf-8") as f:
            data = json.load(f)
        n = data.get("test_count") if isinstance(data, dict) else None
        if isinstance(n, int) and not isinstance(n, bool) and n > 0:
            return {"test_count": n}
        return {}
    except FileNotFoundError:
        pass
    except Exception:
        return {}
    n = count_test_functions(os.path.join(os.path.dirname(bundle_root), "tests"))
    return {"test_count": n} if n else {}
