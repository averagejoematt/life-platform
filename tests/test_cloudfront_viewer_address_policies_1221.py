"""#1221 — CloudFront-Viewer-Address belongs in the ORIGIN REQUEST policy and in NO cache policy.

WHY THIS GUARD EXISTS
=====================
`lambdas/common/client_ip.py` keys every IP-gated rate limit off
``CloudFront-Viewer-Address`` — a header CloudFront sets from the TCP peer address,
which a client cannot forge. It only reaches the origin because
`cdk/stacks/web_cloudfront_policies.py` forwards it in an origin-request policy.

**Deleting it from there silently re-opens the vulnerability**: the helper falls back
to ``X-Forwarded-For``, which this distribution forwards unchanged from the client, so
every per-IP bucket becomes evadable again — and nothing else fails. That is the exact
"reads green while telling you nothing" shape, so it gets a test.

**Adding it to a CACHE policy is the opposite failure and just as bad.** The value is
unique per viewer. In a cache key it turns `/api/*`'s 300 s cached object into
one-per-client, so the busiest read path on the site goes to the origin every time —
a latency and cost regression shipped in the name of a security fix.

AST over the module, never an import: CI's Deploy-critical/Unit Tests lane does NOT
install `aws_cdk`, and importing it fails at COLLECTION and aborts the whole job.
This reads ONE known file — it is deliberately not a source-tree sweep, so it needs no
`_PREMERGE_EXTRA_FILES` registration (#2372).
"""

import ast
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE = os.path.join(REPO, "cdk", "stacks", "web_cloudfront_policies.py")

VIEWER_ADDRESS = "CloudFront-Viewer-Address"


def _tree():
    with open(MODULE, encoding="utf-8") as f:
        return ast.parse(f.read())


def _calls(tree, ctor_name):
    """Every ast.Call whose callee attribute is `ctor_name` (e.g. CachePolicy)."""
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            name = getattr(fn, "attr", None) or getattr(fn, "id", None)
            if name == ctor_name:
                out.append(node)
    return out


def _kwarg(call, name):
    for kw in call.keywords:
        if kw.arg == name:
            return kw.value
    return None


def _literal_strings(node):
    """Every string constant reachable from a node — resolving module-level tuple
    constants by name, since the header lists are named rather than inline."""
    out = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            out.append(sub.value)
        elif isinstance(sub, ast.Name):
            out.append(f"<name:{sub.id}>")
    return out


def _resolve_module_constants(tree):
    """Module-level string / string-sequence constants, resolved IN ORDER so a tuple
    may reference an earlier name — `_API_ORIGIN_HEADERS` contains `VIEWER_ADDRESS_HEADER`,
    which `ast.literal_eval` cannot evaluate on its own."""
    consts = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if not targets:
            continue
        v = node.value
        if isinstance(v, ast.Constant) and isinstance(v.value, str):
            resolved = v.value
        elif isinstance(v, (ast.Tuple, ast.List)):
            items = []
            for el in v.elts:
                if isinstance(el, ast.Constant) and isinstance(el.value, str):
                    items.append(el.value)
                elif isinstance(el, ast.Name) and isinstance(consts.get(el.id), str):
                    items.append(consts[el.id])
                else:
                    items.append(None)  # unresolvable — keep the slot, never silently drop it
            resolved = tuple(i for i in items if i is not None)
        else:
            continue
        for t in targets:
            consts[t] = resolved
    return consts


def _expand(strings, consts):
    out = []
    for s in strings:
        if s.startswith("<name:"):
            v = consts.get(s[6:-1])
            if isinstance(v, (tuple, list)):
                out.extend(str(x) for x in v)
            elif isinstance(v, str):
                out.append(v)
        else:
            out.append(s)
    return out


# ── the two halves of the rule ────────────────────────────────────────────────


def test_every_origin_request_policy_forwards_viewer_address():
    tree = _tree()
    consts = _resolve_module_constants(tree)
    orps = _calls(tree, "OriginRequestPolicy")
    assert orps, "no OriginRequestPolicy found — the header cannot reach the origin"
    for call in orps:
        hb = _kwarg(call, "header_behavior")
        assert hb is not None, "an OriginRequestPolicy with no header_behavior"
        headers = _expand(_literal_strings(hb), consts)
        assert VIEWER_ADDRESS in headers, (
            f"an OriginRequestPolicy does not forward {VIEWER_ADDRESS} — #1221's rate-limit "
            f"identity silently falls back to the forgeable X-Forwarded-For. Got: {headers}"
        )


def test_no_cache_policy_carries_viewer_address():
    """The regression that would shatter /api/*'s 300s cache key, one entry per viewer."""
    tree = _tree()
    consts = _resolve_module_constants(tree)
    for call in _calls(tree, "CachePolicy"):
        for kw in call.keywords:
            if kw.arg in ("header_behavior", "query_string_behavior", "cookie_behavior"):
                found = _expand(_literal_strings(kw.value), consts)
                assert VIEWER_ADDRESS not in found, (
                    f"{VIEWER_ADDRESS} appears in a CachePolicy's {kw.arg}. It is unique per viewer — "
                    "in a cache key it turns /api/*'s cached object into one-per-client. It belongs "
                    "ONLY in the origin-request policy."
                )


def test_the_cached_api_behaviour_keeps_its_ttls():
    """`/api/*` is the only cached /api behaviour: 0/300/3600 pre-migration. A silent
    TTL change here is a availability/cost regression, so pin the numbers."""
    tree = _tree()
    hits = []
    for call in _calls(tree, "CachePolicy"):
        name = _kwarg(call, "cache_policy_name")
        if not (isinstance(name, ast.Constant) and "default-cache" in str(name.value)):
            continue
        ttls = {}
        for field in ("min_ttl", "default_ttl", "max_ttl"):
            v = _kwarg(call, field)
            secs = [c.value for c in ast.walk(v) if isinstance(c, ast.Constant) and isinstance(c.value, int)]
            ttls[field] = secs[0] if secs else None
        hits.append(ttls)
    assert hits, "the /api/* default-cache policy is gone — did a refactor collapse the policies?"
    assert hits[0] == {"min_ttl": 0, "default_ttl": 300, "max_ttl": 3600}, (
        f"/api/*'s TTLs changed: {hits[0]} — pre-migration they were 0/300/3600. "
        "Changing them is a separate decision, not a side effect of #1221."
    )


def test_guard_would_catch_the_regression_it_names():
    """Mutation proof — a gate that cannot fail is a green light wired to nothing."""
    src = open(MODULE, encoding="utf-8").read()
    mutated = src.replace(
        '_API_CACHE_KEY_HEADERS = ("Origin", "Content-Type")',
        '_API_CACHE_KEY_HEADERS = ("Origin", "Content-Type", "CloudFront-Viewer-Address")',
    )
    assert mutated != src, "mutation anchor missing — the guard is no longer exercising the real shape"
    tree = ast.parse(mutated)
    consts = _resolve_module_constants(tree)
    leaked = False
    for call in _calls(tree, "CachePolicy"):
        for kw in call.keywords:
            if kw.arg == "header_behavior" and VIEWER_ADDRESS in _expand(_literal_strings(kw.value), consts):
                leaked = True
    assert leaked, "planting the header in the cache key did NOT trip the detection — this guard is vacuous"
