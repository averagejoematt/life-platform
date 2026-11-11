"""Can a reader check the sealed pre-registration against the file the site serves? (owner ruling 2026-11-11, item 3)

A seal is a published SHA-256 of a frozen file. The claim "anyone can re-hash the file and compare" is only true while
the file served at the sealed address hashes to that digest. ``assess`` decides it from the served bytes, never from a
flag: the verify command and the link to the file are offered only when the bytes match.

``WITHDRAWN`` records, per genesis, the sealed file that can no longer be served and why — the reader-facing
explanation of an unverifiable seal. It never carries the withdrawn material, only counts and a date. The original file
is unchanged and kept privately; its digest stays published. No replacement seal is made: a redacted copy re-hashed and
presented as the seal would be a different file under the old claim.

Shared by the Site API (``site_api_common.prereg_seal_meta``) and the snapshot producer
(``scripts/publish_snapshot_calibration.py::guard_seal``), so the page and the API say the same thing.
"""

from __future__ import annotations

import hashlib
from typing import Any

# genesis -> the withdrawn sealed file. ``sha256`` must equal the published stamp's digest (pinned by
# tests/test_prereg_seal_withdrawn.py against the committed stamp and fixture).
WITHDRAWN: dict[str, dict[str, Any]] = {
    "2026-09-06": {
        "sha256": "bd225d24f67381c253a34671107ba1bc1a8a3c9cc35dadbca1a5edd061b9782d",
        "withdrawn_on": "2026-11-10",
        "calls_total": 16,
        "calls_withdrawn": 2,
        "text": (
            "The pre-registration for this start was hashed and stamped on 6 September 2026, before the first day was"
            " graded, and its SHA-256 is published here. The sealed file itself is no longer served. On 10 November 2026"
            " two of its sixteen calls were withdrawn from the site for privacy, and the file now at its address is a"
            " placeholder. The original is kept privately and has not been changed, but because it contains the"
            " withdrawn calls it cannot be published for checking, so this hash cannot be checked against a file from"
            " this site."
        ),
    },
}

GENERIC_TEXT = (
    "The file served at the sealed address does not match this hash, so the seal cannot be checked against a file from" " this site."
)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def unverifiable_text(genesis: str | None, sha256: str | None) -> str:
    """The reader-facing explanation for a seal that cannot be checked: the withdrawal's, else the generic one."""
    w = WITHDRAWN.get(str(genesis or ""))
    if w and w["sha256"] == sha256:
        return str(w["text"])
    return GENERIC_TEXT


def assess(genesis: str | None, sha256: str | None, served: bytes | None) -> tuple[bool, str | None]:
    """``(verifiable, text)``: verifiable only when the served bytes hash to the sealed digest; otherwise the text that
    explains why not. ``served`` is None when the file could not be read — unverifiable, never assumed."""
    if not sha256:
        return False, GENERIC_TEXT
    if served is not None and sha256_hex(served) == sha256:
        return True, None
    return False, unverifiable_text(genesis, sha256)
