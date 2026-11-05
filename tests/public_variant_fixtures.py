"""Test helper: give a synthetic stored ``character_sheet`` record a public variant (owner ruling 2026-11-05).

Every public reader now serves a record's ``public`` attribute (``character_privacy.public_sheet``) and nothing when it
is absent. A test written before that ruling builds method-1-shaped records; ``with_public`` copies the record's own
score fields into a public variant so such a test keeps exercising what it was written for (a route's rendering of a
sheet) — the variant's ARITHMETIC is ``tests/test_character_public_variant.py``'s.
"""

import copy
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from health import character_privacy  # noqa: E402

_ENVELOPE = ("pk", "sk", "date", "phase", "input_manifest", "input_status")


def with_public(record, origin="recomputed"):
    """``record`` with a public variant carrying its own score fields (returns the same dict, mutated, for chaining)."""
    if not isinstance(record, dict) or record.get("character_level") is None:
        return record
    block = {k: copy.deepcopy(v) for k, v in record.items() if k not in _ENVELOPE and k != character_privacy.PUBLIC_KEY}
    block.update({"public_method_version": character_privacy.PUBLIC_METHOD_VERSION, "origin": origin})
    record[character_privacy.PUBLIC_KEY] = block
    return record


def all_with_public(records):
    return [with_public(r) for r in records]
