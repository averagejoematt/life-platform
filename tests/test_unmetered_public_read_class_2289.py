"""tests/test_unmetered_public_read_class_2289.py — the unmetered public-read
class posture, enforced structurally (#2289).

#2239 fixed the one handler in ``lambdas/web/site_api_social.py`` that was an
information oracle (``_handle_verify_subscriber``). What remained was a CLASS
question, not a defect: eleven-plus public reads carry no rate limiter at all.
The recorded decision (module docstring, #2289): they get NO per-IP DynamoDB
metering — a counter is a DDB write per read, costlier than the read spend it
would count — and instead every one of them must be **edge-cacheable**, i.e.
every success response declares ``cache_seconds >= 300`` (the ``_ok`` default),
so the CloudFront ``/api/*`` behaviour (min 0 / default 300 / max 3600, honors
origin Cache-Control) absorbs an abusive crawler at the edge.

This file is that decision as a guard, in the #2239 style: the handler set is
AST-DERIVED from the module source, never hand-listed, and the derivation is
parameterized over the source text so the guard itself is mutation-proved below
(a synthetic unmetered read is planted in a scratch copy of the source and the
guard must name it).

Every top-level ``handle_*``/``_handle_*`` function must be one of:

  * **metered** — calls ``_rate_check`` or ``_rate_limited`` (the #2237/#2239
    chokepoints; those sets have their own mutation sweeps in
    ``test_site_api_social_behavior.py`` §9);
  * **edge-cached** — every ``_ok(...)`` declares ``cache_seconds >= 300``
    (omitting the kwarg inherits the default 300 and passes), and the handler
    emits no uncached 2xx ``_envelope`` (``_envelope`` is ``no-store``);
  * **dedup-metered write** — no rate call, but its write is a one-shot
    ``ConditionExpression`` ``attribute_not_exists`` put (one action per source,
    EVER — stricter than any windowed limiter). Today: ``_handle_replicate_certify``
    (#1825). The pattern is detected by AST, not name-listed, so the exemption
    cannot silently cover a handler that lost its dedup.

Anything else fails BY NAME. A new unmetered, under-cached public read in this
module cannot merge without either joining the metered set or declaring its
edge-cacheability.
"""

from __future__ import annotations

import ast
import inspect
import pathlib

from web import site_api_social as social

# The class floor. Matches the CloudFront /api/* behaviour default and the _ok
# default in web.site_api_common (asserted below, not assumed).
CACHE_FLOOR = 300

# The metering chokepoints (#2237 collapsed the module to these two).
_RATE_CALLS = {"_rate_check", "_rate_limited"}


def _module_source() -> str:
    return pathlib.Path(inspect.getfile(social)).read_text()


def _calls_by_name(fn: ast.FunctionDef, names: set) -> bool:
    return any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in names for node in ast.walk(fn))


def _has_one_shot_dedup_write(fn: ast.FunctionDef) -> bool:
    """A ``*.put_item(..., ConditionExpression=<contains attribute_not_exists>)``
    anywhere in the handler — the write-door pattern whose dedup IS the meter."""
    for node in ast.walk(fn):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "put_item"):
            continue
        for kw in node.keywords:
            if kw.arg == "ConditionExpression" and "attribute_not_exists" in ast.unparse(kw.value):
                return True
    return False


def _under_cached_responses(fn: ast.FunctionDef) -> list:
    """Success-response call sites of ``fn`` that are NOT edge-cacheable at the
    floor: any ``_ok`` whose ``cache_seconds`` is a constant < CACHE_FLOOR or a
    non-constant expression (unverifiable ⇒ counted against), and any
    ``_envelope`` whose status is a constant < 400 (``_envelope`` defaults to
    ``no-store``) or a non-constant status."""
    bad = []
    for node in ast.walk(fn):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
            continue
        if node.func.id == "_ok":
            cache = CACHE_FLOOR  # the _ok default, asserted in the parity test below
            for kw in node.keywords:
                if kw.arg == "cache_seconds":
                    cache = kw.value.value if isinstance(kw.value, ast.Constant) else -1
            if not (isinstance(cache, int) and cache >= CACHE_FLOOR):
                bad.append(f"_ok at line {node.lineno} (cache_seconds={ast.unparse(node) if cache == -1 else cache})")
        elif node.func.id == "_envelope":
            status = node.args[0] if node.args else None
            if not (isinstance(status, ast.Constant) and isinstance(status.value, int) and status.value >= 400):
                bad.append(f"_envelope at line {node.lineno} (uncached non-error response)")
    return bad


def classify_handlers(source: str) -> dict:
    """name -> ("metered" | "edge_cached" | "dedup_metered_write" | "UNMETERED", detail).

    THE derivation the #2289 decision is recorded against — same shape as #2239's
    ``_handlers_using_the_rate_chokepoint``: top-level ``handle_*``/``_handle_*``
    FunctionDefs of the module source, never a hand-typed list.
    """
    out = {}
    for fn in ast.parse(source).body:
        if not isinstance(fn, ast.FunctionDef) or not fn.name.lstrip("_").startswith("handle_"):
            continue
        if _calls_by_name(fn, _RATE_CALLS):
            out[fn.name] = ("metered", [])
        elif _has_one_shot_dedup_write(fn):
            out[fn.name] = ("dedup_metered_write", [])
        else:
            bad = _under_cached_responses(fn)
            out[fn.name] = ("UNMETERED", bad) if bad else ("edge_cached", [])
    return out


# ──────────────────────────────────────────────────────────────────────────────
# 1. The derivation is real: it sees the whole module, and the class is the one
#    the #2289 decision was recorded against.
# ──────────────────────────────────────────────────────────────────────────────


def test_the_derivation_enumerates_the_handler_surface():
    postures = classify_handlers(_module_source())
    # 26 handlers at decision time; the assertion is a floor so the module can
    # grow — every newcomer is classified, and the posture test below judges it.
    assert len(postures) >= 26, sorted(postures)


def test_the_unmetered_public_read_class_is_the_enumerated_one():
    """The #2289 class, BY DERIVATION: the issue's 11 doors (+ handle_membrane,
    which joined the module after the issue's snapshot and is judged by the same
    rule). Subset — not equality — so a new COMPLIANT read may join the class
    without editing this list; joining it non-compliantly fails the posture test."""
    postures = classify_handlers(_module_source())
    the_class = {n for n, (p, _) in postures.items() if p == "edge_cached"}
    assert {
        "handle_current_challenge",
        "handle_subscriber_count",
        "handle_experiment_library",
        "_handle_experiment_detail",
        "handle_challenge_catalog",
        "handle_challenges",
        "handle_predict_week_tally",
        "handle_broadcast",
        "_handle_social_context",
        "handle_ladder_counts",
        "handle_cohort_strip",
        "handle_membrane",
    } <= the_class, sorted(the_class)


def test_the_ok_default_matches_the_class_floor():
    """The derivation treats a bare ``_ok(data)`` as declaring the floor because
    the default IS the floor. If the default in site_api_common ever drops below
    300, that silently un-caches the whole class — so it is pinned here."""
    from web import site_api_common

    assert inspect.signature(site_api_common._ok).parameters["cache_seconds"].default == CACHE_FLOOR


# ──────────────────────────────────────────────────────────────────────────────
# 2. THE GUARD — the recorded posture, enforced on the live source.
# ──────────────────────────────────────────────────────────────────────────────


def test_every_public_handler_is_metered_or_edge_cached():
    """#2289: no handler in site_api_social may be reachable, unmetered, and
    un-cacheable. Fails with the handler's name and the offending call sites."""
    offenders = {n: bad for n, (p, bad) in classify_handlers(_module_source()).items() if p == "UNMETERED"}
    assert not offenders, (
        "Unmetered, under-cached public read(s) — add a _rate_check/_rate_limited "
        f"call or declare cache_seconds >= {CACHE_FLOOR} on every success response "
        f"(#2289 class rule, module docstring): {offenders}"
    )


def test_the_dedup_metered_exemption_covers_only_the_replicate_cert_door():
    """The one sanctioned no-limiter, no-cache handler is the self-cert write
    whose permanent per-IP ConditionExpression dedup (#1825) is the meter. If a
    second handler ever matches the dedup pattern, that is a NEW class decision —
    this test forces it to be made consciously rather than inherited."""
    postures = classify_handlers(_module_source())
    assert {n for n, (p, _) in postures.items() if p == "dedup_metered_write"} == {"_handle_replicate_certify"}


# ──────────────────────────────────────────────────────────────────────────────
# 3. Mutation proofs — the guard is shown to fire, not trusted to.
# ──────────────────────────────────────────────────────────────────────────────


def test_the_guard_names_a_synthetic_unmetered_read_planted_in_a_scratch_copy():
    """Acceptance #4: plant a new public read with a sub-floor TTL in a scratch
    copy of the real source; the derivation must classify it UNMETERED by name."""
    scratch = _module_source() + (
        "\n\ndef handle_scratch_probe_2289(event: dict) -> dict:\n" '    return _ok({"probe": True}, cache_seconds=60)\n'
    )
    postures = classify_handlers(scratch)
    posture, bad = postures["handle_scratch_probe_2289"]
    assert posture == "UNMETERED" and bad, postures["handle_scratch_probe_2289"]


def test_the_guard_names_a_synthetic_uncached_envelope_read_too():
    """The other way to build the same hole: a 200 via ``_envelope`` (no-store).
    The guard must refuse it just like a sub-floor ``cache_seconds``."""
    scratch = _module_source() + (
        "\n\ndef handle_scratch_envelope_2289(event: dict) -> dict:\n" '    return _envelope(200, {"probe": True})\n'
    )
    posture, bad = classify_handlers(scratch)["handle_scratch_envelope_2289"]
    assert posture == "UNMETERED" and bad


def test_the_guard_fires_when_an_existing_reads_cache_declaration_is_degraded():
    """Sabotage a COMPLIANT member of the class (the 900s broadcast feed) down to
    0 and the guard must name exactly that door — proving the per-call-site check
    reads the value, not merely the presence, of ``cache_seconds``."""
    source = _module_source()
    assert "cache_seconds=900," in source  # the sabotage below must actually mutate
    postures = classify_handlers(source.replace("cache_seconds=900,", "cache_seconds=0,"))
    assert postures["handle_broadcast"][0] == "UNMETERED", postures["handle_broadcast"]


def test_the_dedup_exemption_dies_with_its_dedup():
    """Strip the ConditionExpression off the self-cert write in a scratch copy:
    the handler must drop out of the exemption and fail as UNMETERED — the
    exemption is the PATTERN, not the name."""
    source = _module_source()
    assert 'ConditionExpression="attribute_not_exists(pk)",' in source
    mutated = source.replace('ConditionExpression="attribute_not_exists(pk)",', "")
    posture, bad = classify_handlers(mutated)["_handle_replicate_certify"]
    assert posture == "UNMETERED" and bad
