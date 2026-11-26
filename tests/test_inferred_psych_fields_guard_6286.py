"""tests/test_inferred_psych_fields_guard_6286.py — the model-inferred psychological labels stay out of prompts (#6286).

The SET, not the instance: every Python source under ``lambdas/`` and ``mcp/`` is parsed, and any string
constant that names a field in ``common.inferred_fields.INFERRED_PSYCH_LABEL_FIELDS`` (or the bare key a
consumer used to re-key it under, ``INFERRED_PSYCH_LABEL_KEYS``) fails the test unless the file is the
sanctioned module or one of the two producers. Before #6286 seven consumers read these fields; the daily
brief's journal coach was told "DEFENSE PATTERNS DETECTED: … Challenge one gently."

A consumer that needs the labels for their OWNER goes through ``inferred_fields.unreviewed_model_reading``
(or ``relabel_row``), which carries the "unreviewed model reading, may be wrong" caveat.
"""

from __future__ import annotations

import ast
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "lambdas"))

from common import inferred_fields as IF  # noqa: E402

SANCTIONED = ("lambdas/common/inferred_fields.py",) + IF.PRODUCER_MODULES
NAMES = IF.INFERRED_PSYCH_LABEL_FIELDS | IF.INFERRED_PSYCH_LABEL_KEYS


def offending_constants(source: str, filename: str = "<planted>") -> list[tuple[int, str]]:
    """Every (line, name) where a str constant in ``source`` is exactly a guarded name."""
    tree = ast.parse(source, filename=filename)
    return sorted((node.lineno, node.value) for node in ast.walk(tree) if isinstance(node, ast.Constant) and node.value in NAMES)


def _python_sources() -> list[str]:
    out = []
    for root in ("lambdas", "mcp"):
        for dirpath, dirnames, filenames in os.walk(os.path.join(REPO, root)):
            dirnames[:] = [d for d in dirnames if d not in ("__pycache__", "node_modules", ".venv")]
            for fn in filenames:
                if fn.endswith(".py"):
                    out.append(os.path.relpath(os.path.join(dirpath, fn), REPO))
    return sorted(out)


# premerge-gate: #6286: no module outside common.inferred_fields + the two producers reads a model-inferred psychological label
def test_no_consumer_reads_a_model_inferred_psych_label():
    files = _python_sources()
    # Population floor: a walk that found nothing would pass vacuously.
    assert len(files) >= 300, f"the sweep found only {len(files)} sources under lambdas/ and mcp/ — has it gone blind?"
    offenders = []
    seen_in_producers = set()
    for rel in files:
        with open(os.path.join(REPO, rel), encoding="utf-8") as fh:
            src = fh.read()
        hits = offending_constants(src, rel)
        if rel in SANCTIONED:
            seen_in_producers.update(name for _line, name in hits)
            continue
        offenders.extend(f"{rel}:{line}: {name!r}" for line, name in hits)
    # The producers must still name the fields — otherwise the field names drifted and this guard is blind.
    for producer in IF.PRODUCER_MODULES:
        assert os.path.isfile(os.path.join(REPO, producer)), f"producer {producer} moved; update PRODUCER_MODULES"
    assert (
        "enriched_avoidance_flags" in seen_in_producers and "enriched_defense_patterns" in seen_in_producers
    ), "the producers no longer name the label fields — INFERRED_PSYCH_LABEL_FIELDS has drifted from what is written"
    assert not offenders, (
        "model-inferred psychological labels read outside common.inferred_fields (#6286). A coach, brief, digest or "
        "challenge prompt may not receive defense / avoidance / cognitive-distortion labels as fact; an owner-facing "
        "read goes through inferred_fields.unreviewed_model_reading or relabel_row, which carry the caveat:\n  " + "\n  ".join(offenders)
    )


def test_the_guard_reds_on_a_planted_read():
    """The proof the sweep can fail: the exact pre-#6286 shapes, each caught."""
    planted = (
        "def build(entry, j_signals):\n"
        "    a = entry.get('enriched_defense_patterns')\n"
        "    b = entry['enriched_avoidance_flags']\n"
        "    c = [f for f in ('enriched_cognitive_patterns', 'enriched_primary_defense')]\n"
        "    d = j_signals.get('defense_patterns')\n"
        "    return a, b, c, d\n"
    )
    names = {n for _l, n in offending_constants(planted)}
    assert names == {
        "enriched_defense_patterns",
        "enriched_avoidance_flags",
        "enriched_cognitive_patterns",
        "enriched_primary_defense",
        "defense_patterns",
    }
    # Themes, emotions, behaviours and his own causal statements stay readable.
    assert offending_constants("x = e.get('enriched_themes') or e.get('enriched_causal_hints') or e.get('enriched_emotions')") == []
