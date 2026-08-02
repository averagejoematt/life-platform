"""tests/test_grounding_wiring_1967.py — #1967: grounding-gate coverage is STRUCTURE.

The gate params on ``grounding_findings()`` are all optional (backward compat, #1691/#1699),
so nothing used to fail when a reader-facing AI surface shipped without one. These tests
bind the DERIVED surface list (``tests/grounding_wiring.scan_tree``, an AST scan of every
grounding chokepoint call in ``lambdas/``) to the per-surface policy registry, in both
directions, and prove the guard actually fires on a synthetic ungated surface.

Offline by construction: pure AST over source text. No Bedrock, no AWS, no imports of the
lambda handlers themselves.
"""

import os

import pytest
from grounding_wiring import (
    GATE_CLASSES,
    PARAM_PROVIDER_MODULE,
    PARAM_PROVIDERS,
    REPO,
    SURFACES,
    scan_source,
    scan_tree,
)


@pytest.fixture(scope="module")
def discovered():
    return scan_tree()


# ── Direction 1: nothing may ship un-registered ──────────────────────────────
def test_every_discovered_grounding_surface_is_registered(discovered):
    """A NEW reader-facing AI surface cannot ship half-gated — it fails here first."""
    missing = sorted(set(discovered) - set(SURFACES))
    assert not missing, (
        "grounding-gate surface(s) with no policy entry in tests/grounding_wiring.SURFACES:\n"
        + "\n".join(f"  {k}  (arms: {sorted(discovered[k]) or 'nothing'})" for k in missing)
        + "\n\nAdd an entry naming the gate classes this surface must arm, and a written "
        "reason for each class it does not (see the module docstring)."
    )


# ── Direction 2: the registry cannot rot into a stale hand-list ──────────────
def test_registry_has_no_stale_entries(discovered):
    stale = sorted(set(SURFACES) - set(discovered))
    assert not stale, (
        "tests/grounding_wiring.SURFACES names surface(s) the AST scan no longer finds "
        "(renamed, moved, or the gate call was removed):\n" + "\n".join(f"  {k}" for k in stale)
    )


# ── Every entry must DECIDE every gate class ─────────────────────────────────
def test_every_entry_decides_every_gate_class():
    """required | exempt == GATE_CLASSES, and every exemption carries a real reason.

    This is what makes a NEW gate class structural too: adding one to GATE_CLASSES
    fails every surface until each has either wired it or written down why not.
    """
    problems = []
    for key, entry in sorted(SURFACES.items()):
        required, exempt = entry["required"], entry["exempt"]
        overlap = required & set(exempt)
        undecided = set(GATE_CLASSES) - required - set(exempt)
        unknown = (required | set(exempt)) - set(GATE_CLASSES)
        if overlap:
            problems.append(f"{key}: class(es) both required and exempt: {sorted(overlap)}")
        if undecided:
            problems.append(f"{key}: undecided gate class(es) {sorted(undecided)} — wire them or exempt with a reason")
        if unknown:
            problems.append(f"{key}: unknown gate class(es) {sorted(unknown)}")
        for cls, reason in exempt.items():
            if not isinstance(reason, str) or len(reason.strip()) < 40:
                problems.append(f"{key}: exemption for {cls!r} needs a substantive written reason")
    assert not problems, "\n".join(problems)


# ── The wiring itself ────────────────────────────────────────────────────────
def test_every_required_gate_class_is_actually_wired(discovered):
    """The load-bearing assertion: policy vs. what the source really passes."""
    problems = []
    for key, entry in sorted(SURFACES.items()):
        if key not in discovered:
            continue  # covered by test_registry_has_no_stale_entries
        armed = discovered[key]
        gap = sorted(entry["required"] - armed)
        if gap:
            problems.append(f"{key}: required gate class(es) NOT armed at the call site: {gap} (arms: {sorted(armed)})")
    assert not problems, (
        "grounding surface(s) declare a gate class they do not pass:\n"
        + "\n".join(f"  {p}" for p in problems)
        + "\n\nEither pass the params (cycle anchors: `**cycle_gate_params()`) or move the "
        "class to `exempt` with a written reason."
    )


def test_freshness_is_never_exempt():
    """Policy floor for #1691/#1897: the cycle anchors are framing-scoped and free.

    ``stale_phase``/``experiment_span`` only look at text that FRAMES a "Day N" or
    "N days of the experiment" claim, and ``stale_baseline`` only at a weight token
    next to baseline framing — so arming them on a surface that never uses that framing
    is a no-op, never new noise. There is therefore no honest reason for a grounding
    surface to opt out, and this keeps "we'll wire it later" from becoming an exemption.
    """
    opted_out = sorted(k for k, e in SURFACES.items() if "freshness" in e["exempt"])
    assert not opted_out, "freshness (#1691/#1897) has no valid exemption — wire `**cycle_gate_params()`:\n" + "\n".join(opted_out)


def test_behavioral_gate_is_armed_somewhere(discovered):
    """#1699 must not become a class that exists but no surface ever runs."""
    armed = sorted(k for k, c in discovered.items() if "behavioral" in c)
    assert armed, "no surface arms the ungrounded-behavioral gate (#1699) — the class would be dead code"


def test_param_provider_exists_and_supplies_its_declared_classes():
    """`**cycle_gate_params()` is how freshness is armed — the provider must be real.

    Renaming/removing it would otherwise disarm every spreading caller while the AST
    scan happily reported the class as armed.
    """
    path = os.path.join(REPO, PARAM_PROVIDER_MODULE)
    assert os.path.exists(path), f"{PARAM_PROVIDER_MODULE} is missing — PARAM_PROVIDERS points at nothing"
    src = open(path, encoding="utf-8").read()
    for provider, classes in PARAM_PROVIDERS.items():
        assert f"def {provider}(" in src, f"PARAM_PROVIDERS names {provider!r}, not defined in {PARAM_PROVIDER_MODULE}"
        for cls in classes:
            for kwarg in GATE_CLASSES[cls]["kwargs"]:
                assert f'"{kwarg}"' in src, f"{provider}() claims to arm {cls!r} but never returns {kwarg!r}"


# ── Prove the guard fires (synthetic surfaces, never touching the real tree) ──
_UNGATED = """
def brand_new_reader_surface(text, prompt):
    from ai import grounded_generation as gg
    allowed = gg.allowed_numbers(prompt)
    return gg.grounding_findings(text, allowed=allowed)
"""

_WIRED = """
def brand_new_reader_surface(text, prompt):
    from ai import grounded_generation as gg
    from ai.grounding_gate_params import cycle_gate_params
    allowed = gg.allowed_numbers(prompt)
    return gg.grounding_findings(text, allowed=allowed, allowed_dates=gg.allowed_dates(prompt), **cycle_gate_params())
"""


def test_guard_catches_a_synthetic_ungated_surface():
    found = scan_source("lambdas/web/synthetic_new_surface.py", _UNGATED)
    key = "lambdas/web/synthetic_new_surface.py::brand_new_reader_surface"
    assert key in found, "the AST scan must discover a brand-new grounding caller"
    assert found[key] == {"numbers"}, f"expected only the number gate armed, got {sorted(found[key])}"
    # …and it is not in the registry, which is exactly what direction-1 fails on.
    assert key not in SURFACES
    unregistered = sorted(set(found) - set(SURFACES))
    assert unregistered == [key]


def test_guard_passes_a_synthetic_wired_surface():
    found = scan_source("lambdas/web/synthetic_new_surface.py", _WIRED)
    key = "lambdas/web/synthetic_new_surface.py::brand_new_reader_surface"
    assert found[key] == {"numbers", "dates", "freshness"}, sorted(found[key])


def test_guard_attributes_a_nested_closure_to_its_outer_surface():
    """The regen-once shape nests the findings fn — attribution must not fragment."""
    src = """
def outer_surface(text, prompt):
    from ai import grounded_generation as gg
    def _findings_fn(t):
        return gg.grounding_findings(t, allowed=gg.allowed_numbers(prompt))
    return _findings_fn(text)
"""
    found = scan_source("lambdas/web/synthetic_nested.py", src)
    assert list(found) == ["lambdas/web/synthetic_nested.py::outer_surface"], list(found)


def test_direct_gate_helpers_also_count_as_armed():
    """ai_calls runs the two advisory gates as separate steps — that must count."""
    src = """
def advisory_surface(text):
    from ai import grounded_generation as gg
    a = gg.baseline_freshness_findings(text, generation_date_iso="2026-08-02", start_date_iso="2026-07-27")
    b = gg.ungrounded_behavioral_findings(text, available_logs={"steps"})
    return a + b
"""
    found = scan_source("lambdas/web/synthetic_direct.py", src)
    key = "lambdas/web/synthetic_direct.py::advisory_surface"
    assert found[key] == {"freshness", "behavioral"}, sorted(found[key])
