"""#1392 — The Mirror's two promises are enforced, not asserted.

Promise 1 — "the same instruments": the browser scoring (site/assets/js/mirror-core.js)
is pinned to the deployed Python engine by tests/vectors/mirror_vectors.json, generated
FROM the deployed modules by scripts/gen_mirror_vectors.py. This module keeps the
committed vectors honest (a stale fixture after an engine change fails here); the JS
side of the numeric contract is tests/js/mirror_core.test.mjs under `node --test`
(exact equality — ADR-105, never a tolerance).

Promise 2 — "your file never leaves this page": there is no upload endpoint, and the
page's own module graph is pinned to exactly ONE network request — a GET of the static
published-distributions artifact. Anything that could carry reader data off the page
(a second fetch, XHR, sendBeacon, WebSocket, EventSource, a request body) fails here.
This is the guard-the-SET shape (the 08-02 genome lesson): the pins walk the page's
whole shipped module graph, not a hand list of functions.

The distributions artifact itself is scope-pinned: exactly the six already-public
metrics, full sorted samples, n and window stamped — a seventh metric (or an unsorted
sample that would make the percentile claim wrong) fails the build.
"""

import importlib.util
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))

VECTORS_PATH = os.path.join(ROOT, "tests", "vectors", "mirror_vectors.json")
DIST_PATH = os.path.join(ROOT, "site", "data", "mirror_distributions.json")
PAGE_PATH = os.path.join(ROOT, "site", "method", "mirror", "index.html")
JS_DIR = os.path.join(ROOT, "site", "assets", "js")

# The page's whole shipped module graph — additions must be listed here AND survive
# the privacy pins below.
MIRROR_MODULES = ("mirror.js", "mirror-core.js", "mirror_demo.js")

PUBLIC_METRICS = {"recovery_score", "hrv", "resting_heart_rate", "sleep_duration_hours", "sleep_performance", "strain"}


def _load_by_path(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, *rel.split("/")))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _stripped(js_name):
    """Module source with // comment lines removed, so prose about fetch() never counts."""
    with open(os.path.join(JS_DIR, js_name), "r", encoding="utf-8") as fh:
        return "\n".join(ln for ln in fh.read().splitlines() if not ln.lstrip().startswith("//"))


# ── Promise 1: parity ────────────────────────────────────────────────────────


def test_committed_vectors_match_a_fresh_recompute_from_the_deployed_engine():
    gen = _load_by_path("gen_mirror_vectors_under_test", "scripts/gen_mirror_vectors.py")
    with open(VECTORS_PATH, "r", encoding="utf-8") as fh:
        committed = json.load(fh)
    assert committed == json.loads(json.dumps(gen.build())), (
        "tests/vectors/mirror_vectors.json is stale against the deployed scoring modules — "
        "run `python3 scripts/gen_mirror_vectors.py` and commit the diff (and expect the JS "
        "port to need the same change: the Mirror page's numbers are pinned to these)."
    )


def test_js_port_imports_the_shared_pyround_rather_than_reinventing_rounding():
    code = _stripped("mirror-core.js")
    assert 'from "/assets/js/calibration-core.js"' in code and "pyRound" in code, (
        "mirror-core.js must import pyRound from the vendored calibration scorer — a second "
        "rounding implementation is exactly the drift the parity suite exists to prevent"
    )


# ── Promise 2: nothing leaves the page ───────────────────────────────────────


def test_the_module_graph_makes_exactly_one_network_request_and_it_is_the_static_artifact():
    controller = _stripped("mirror.js")
    assert "fetch(DIST_URL" in controller and controller.count("fetch(") == 1, (
        "mirror.js must make exactly one network call — fetch(DIST_URL) for the published "
        "distributions. A second request is how a reader's export could leave the page."
    )
    assert '"/data/mirror_distributions.json"' in controller
    for js in ("mirror-core.js", "mirror_demo.js"):
        assert "fetch(" not in _stripped(js), f"{js} must make no network calls at all"
    for js in MIRROR_MODULES:
        code = _stripped(js)
        for leak in ("XMLHttpRequest", "navigator.sendBeacon", "new WebSocket", "new EventSource", "method:", "body:"):
            assert leak not in code, f"{js} must not contain {leak!r} — the reader's export never leaves the page"


def test_no_api_route_serves_or_accepts_mirror_uploads():
    """The privacy wedge is architectural: no /api/ route exists for this page at all.

    Walks the site-api ROUTES surface (the set, not a hand list): no route path may
    mention the mirror, and the page itself declares no api_deps in the QA manifest.
    """
    import web.site_api_lambda as site_api  # noqa: F401 — route table import

    route_blob = json.dumps(sorted(getattr(site_api, "ROUTES", {}).keys())) if hasattr(site_api, "ROUTES") else ""
    if not route_blob:
        # fall back to scanning the module source for route strings
        with open(os.path.join(ROOT, "lambdas", "web", "site_api_lambda.py"), "r", encoding="utf-8") as fh:
            route_blob = fh.read()
    assert "mirror" not in route_blob.lower(), "no site-api route may exist for the Mirror — the absence IS the control"

    sys.path.insert(0, os.path.join(ROOT, "tests"))
    import qa_manifest

    entry = next(p for p in qa_manifest.MANIFEST if p["path"] == "/method/mirror/")
    assert entry["api_deps"] == [], "the Mirror page must declare zero api_deps — it reads only static artifacts"


# ── The distributions artifact: honest and scope-pinned ──────────────────────


def test_distributions_artifact_is_sorted_scoped_and_stamped():
    with open(DIST_PATH, "r", encoding="utf-8") as fh:
        dist = json.load(fh)
    assert set(dist["metrics"].keys()) == PUBLIC_METRICS, (
        "mirror_distributions.json may carry EXACTLY the six already-public metrics — "
        "adding one is a data-publication decision (PRE-13 class), not a code change"
    )
    w = dist["window"]
    assert re.match(r"^\d{4}-\d{2}-\d{2}$", w["start"]) and re.match(r"^\d{4}-\d{2}-\d{2}$", w["end"])
    for metric, d in dist["metrics"].items():
        sample = d["sample"]
        assert d["n"] == len(sample) and d["n"] >= 30, f"{metric}: n must be honest and >= 30 for percentile claims"
        assert all(isinstance(v, (int, float)) for v in sample), metric
        assert sample == sorted(sample), f"{metric}: sample must be sorted — midrank percentile depends on it"


# ── The page ships what its controller binds ─────────────────────────────────


def test_the_page_ships_the_hooks_its_controller_binds_and_is_not_stale():
    with open(PAGE_PATH, "r", encoding="utf-8") as fh:
        page = fh.read()
    for hook in (
        "mirror-file",
        "mirror-drop",
        "mirror-demo",
        "mirror-clear",
        "mirror-prov",
        "mirror-readout",
        "mirror-bands",
        "mirror-quick",
    ):
        assert f'id="{hook}"' in page, f"/method/mirror/ is missing the #{hook} hook its controller binds"
    assert "/assets/js/mirror.js" in page, "the page must load its controller module"
    assert (
        "calibrated on me" in page.lower() or "One person" in page
    ), "the permanent one-person's-model banner is an acceptance requirement (#1392)"
    # No raw builder==page assert: scripts/v4_apply_chrome.py is the AUTHORITATIVE
    # post-build pass (head chrome #1639, loop-forward #1468) and rewrites the built
    # file; tests/test_site_chrome.py owns chrome canonicality for every page. The
    # regen recipe is: v4_build_mirror.py, then v4_apply_chrome.py, then commit.
    assert 'class="mr-banner"' in page, "the banner element must survive regeneration"
