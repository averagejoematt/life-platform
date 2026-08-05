"""Legibility gloss for n-gated correlation labels (#1996, ADR-105).

Split out of weekly_correlation_compute_lambda.py when the #1996 helper pushed
that module over the 1200-line ceiling (#1665) — pure functions, no AWS calls.
interpret_r() in the weekly module owns the n-gating itself; this module only
explains a downgrade to the reader, never re-derives or overrides it.
"""

# Rank order for comparing an n-gated label against the label |r| alone would earn
# (interpret_r's raw-magnitude bands, before any n-gate downgrade is applied).
_INTERP_RANK = {"insufficient_data": -1, "negligible": 0, "weak": 1, "moderate": 2, "strong": 3}


def n_gate_gloss(r, n, interpretation):
    """Legibility gloss for an n-gated interpretation downgrade (#1996, ADR-105).

    interpret_r() deliberately DOWNGRADES a label when n is below the sample-size
    floor |r| alone would earn (moderate needs n>=30, strong needs n>=50) — that
    gating is real and correct, never re-derived here (see interpret_r's docstring).
    But served bare next to a strong r ("r=0.88 ... weak") the downgrade reads as a
    stats error to a skeptical reader, not as the rigor it actually is.

    Returns a short explanatory string when the served `interpretation` sits BELOW
    the band |r| alone would earn, else None — a label that already matches its r
    (or a downgrade we can't evaluate, e.g. missing r/n) gets no invented gloss.
    """
    if r is None or n is None or not interpretation:
        return None
    abs_r = abs(r)
    if abs_r >= 0.6:
        raw = "strong"
    elif abs_r >= 0.4:
        raw = "moderate"
    elif abs_r >= 0.2:
        raw = "weak"
    else:
        raw = "negligible"
    if _INTERP_RANK.get(interpretation, -1) < _INTERP_RANK.get(raw, -1):
        return "evidence still thin"
    return None
