"""tests/call_publication_fixtures.py — synthetic calls as REVIEWED-PUBLIC calls (owner ruling 2026-11-05).

Every public read omits a call the reviewed registry (``common.prediction_publication_registry``) does not list and
whose own structure does not make it eligible (``common.prediction_publication``). A test that builds SYNTHETIC calls to
exercise some other public behaviour (the narrative gate, the record's arithmetic, a page's shape) means them as
ordinary, publishable calls; ``register_reviewed_public`` records that reading, the way the reviewer's registry does
for real rows. It rebinds the registry's digest set for the life of the process — every caller runs in its own
interpreter (the route walks) or restores it (``registered`` below).
"""

from __future__ import annotations

import contextlib
from typing import Iterable, Mapping


def _identity(row: Mapping):
    from common import prediction_publication as PP

    pk, sk = row.get("pk"), row.get("sk")
    kind = PP.kind_of(pk, sk)
    if kind == PP.CALL:
        return pk, PP.call_key(sk, row)
    if kind in (PP.ASK, PP.DOCKET):
        return pk, sk
    if kind == PP.REFERENCE:
        ref = PP.referenced_call(pk, row)
        return ref if ref is not None else (pk, sk)
    return None


def digests_for(rows: Iterable[Mapping]) -> set:
    from common import prediction_publication as PP

    out = set()
    for row in rows or ():
        ident = _identity(row) if isinstance(row, Mapping) else None
        if ident is not None:
            out.add(PP.digest(*ident))
    return out


def register_reviewed_public(rows: Iterable[Mapping]) -> frozenset:
    """Add the synthetic governed rows in ``rows`` to the reviewed-public registry; returns the previous set."""
    from common import prediction_publication_registry as REG

    before = REG.PUBLIC_DIGESTS
    REG.PUBLIC_DIGESTS = frozenset(before | digests_for(rows))
    return before


@contextlib.contextmanager
def registered(rows: Iterable[Mapping]):
    from common import prediction_publication_registry as REG

    before = register_reviewed_public(rows)
    try:
        yield
    finally:
        REG.PUBLIC_DIGESTS = before
