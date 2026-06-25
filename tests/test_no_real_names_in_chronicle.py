"""Privacy guard — the chronicle generator must never name real public figures.

The platform casts a *fictional* Board of Directors (Dr. Victor Reyes, Dr. Kai
Nakamura, Dr. Marcus Webb, Dr. Lisa Park, …). The live Elena prompt builds those
names from the S3 board config, but the in-code `_FALLBACK_ELENA_PROMPT` (which
fires only if that S3 load fails) once hardcoded the real public figures the
personas are modelled on — a leak that would have published real people as
Matthew's advisors (a privacy + likeness problem). This pins the fallback to the
fictional roster so the leak can't silently return.
"""

import pathlib

_SRC = pathlib.Path(__file__).resolve().parent.parent / "lambdas" / "emails" / "wednesday_chronicle_lambda.py"

# Real public figures the fictional Board members are modelled on. None of these
# has any legitimate use in this generator. (Deliberately NOT bare "Walker" — that
# is the user's own surname — nor "Park"/"Reyes"/etc., which are the fictional names.)
_BANNED_REAL_NAMES = ["Attia", "Huberman", "Norton"]


def test_chronicle_source_names_no_real_public_figures():
    text = _SRC.read_text()
    hits = [n for n in _BANNED_REAL_NAMES if n in text]
    assert not hits, f"chronicle generator names real public figure(s) {hits} — use the fictional Board personas (Reyes/Nakamura/Webb/Park)"


def test_fallback_prompt_references_the_fictional_board():
    # Guard the positive: the fallback's Board paragraph must name fictional personas,
    # so a future edit that strips the names doesn't quietly regress to generic-or-real.
    text = _SRC.read_text()
    assert any(
        n in text for n in ("Dr. Reyes", "Dr. Nakamura", "Dr. Webb", "Dr. Park")
    ), "fallback Board paragraph lost its fictional persona names"
