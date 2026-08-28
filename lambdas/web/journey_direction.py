"""#3285 — the ONE ruling on the SIGN of the weight-journey delta.

``journey.lost_lbs`` is a SIGNED number (start − current): positive is a loss,
negative is a gain, zero is even. Every consumer used to treat it as a magnitude
and supply its own direction word *statically* — the home OG share card drew it
under a literal ``"LOST"`` caption in ``card_engine.GREEN``, and the home
``og:description`` appended a literal ``" lb down"``. Handed a negative value both
surfaces published a double negative ("lost -5 lbs") and painted a miss in the
success colour, on the single most-distributed artifact the platform ships.

That is an ADR-104 defect of a specific shape: **a truthful value rendered under
an untruthful frame**. This module exists to make it structurally impossible for a
caller to name a direction the data did not.

Presentation deliberately stays with each surface — a caption plus a brand token on
the card, a clause in a sentence for the meta description — because those are
different media. Only the RULING lives here, so the two can never disagree about
which way the number points.

Stdlib only: no Pillow, no boto3. ``scripts/v4_proof.py`` (a build-time site
generator, which already puts ``lambdas/`` on ``sys.path`` for
``common.pacific_time``) imports this alongside ``lambdas/web/og_image_lambda.py``
(a Lambda that runs with the Pillow layer). A shared ruling has to be importable
from both planes or it is not shared.
"""

from __future__ import annotations

import math

DOWN = "down"  # a loss — start > current
UP = "up"  # a gain — current > start
EVEN = "even"  # no movement AT DISPLAY PRECISION
UNKNOWN = "unknown"  # nothing to read — absent, non-numeric, or non-finite


def classify_delta(lost_lbs: object, decimals: int = 0) -> tuple[str, float | None]:
    """Rule on a signed ``lost_lbs``. Returns ``(direction, magnitude)``.

    ``magnitude`` is ALWAYS non-negative and is already rounded to the precision the
    caller is about to render at — which is exactly why the rounding happens here and
    not at the call site. A −0.4 lb delta displayed to whole pounds renders as "0"; if
    the direction were ruled on the raw value, that tile would read "GAINED 0 lbs" and
    the description "0 lb up". Rounding *before* the sign test keeps the caption and
    the number in agreement under every input, which is the property #3285 was written
    to guarantee.

    A missing, non-numeric or non-finite value is ``UNKNOWN`` with no magnitude —
    never coerced into a direction. Absence is a legitimate answer here (ADR-104);
    guessing "down" because nothing came back is the whole bug class.

    ``bool`` is rejected on purpose: it is an ``int`` subclass, and ``True`` arriving
    from a JSON payload must not silently rule "1 lb down".
    """
    if isinstance(lost_lbs, bool) or not isinstance(lost_lbs, (int, float)):
        return UNKNOWN, None
    raw = float(lost_lbs)
    if not math.isfinite(raw):
        return UNKNOWN, None
    value = round(raw, decimals)
    if value > 0:
        return DOWN, value
    if value < 0:
        return UP, -value
    return EVEN, 0.0
