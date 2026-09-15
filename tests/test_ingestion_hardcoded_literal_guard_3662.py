"""tests/test_ingestion_hardcoded_literal_guard_3662.py — the #3662 generalized guard.

`measurements_ingestion_lambda.py` wrote `"measured_by": "partner"` as a literal the
CSV parser could never override — false on the only session it actually ingested.
`scripts/check_ingestion_hardcoded_literals.py` is the AST sweep over the WHOLE
`lambdas/ingestion/` tree that finds every field written as a hard-coded string
literal while the same file demonstrably reads a same-named column elsewhere (the
"the source could have overridden this, and doesn't" shape). This test wires that
sweep into CI so the class the issue names — not just the one instance — cannot land
silently again.
"""

import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "scripts"))

import check_ingestion_hardcoded_literals as guard  # noqa: E402


def test_no_unexempted_hardcoded_literal_fields_in_ingestion_tree():
    """Every (file, field) hit is either fixed or carries a written EXEMPTIONS reason."""
    results = guard.scan_all()
    assert not results, (
        "hard-coded literal field(s) found where the same file also reads a "
        f"same-named column — register a reason in EXEMPTIONS or fix the write: {results}"
    )


def test_every_exemption_carries_a_written_reason():
    for fname, fields in guard.EXEMPTIONS.items():
        for field, reason in fields.items():
            assert (
                isinstance(reason, str) and len(reason.strip()) >= 15
            ), f"{fname}: exemption for {field!r} needs a real written reason, not a placeholder"


def test_guard_would_catch_the_original_measured_by_bug():
    """A planted hard-coded literal reds the test (the issue's own must-fail case)."""
    path = os.path.join(_REPO, "lambdas", "ingestion", "measurements_ingestion_lambda.py")
    src = open(path, encoding="utf-8").read()
    assert '"measured_by": measured_by,' in src, "measured_by must be written from the parsed/derived variable, not a literal"

    # Simulate the pre-#3662 regression: hard-code the write back to "partner" while
    # keeping the (now-real) CSV read in place, and confirm the guard fires on it.
    planted = src.replace('"measured_by": measured_by,', '"measured_by": "partner",')
    assert planted != src, "the replacement above must actually match something in the file"

    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix="_measurements_ingestion_lambda.py", delete=False) as f:
        f.write(planted)
        tmp_path = f.name
    try:
        violations = guard.scan_file(tmp_path)
    finally:
        os.unlink(tmp_path)

    assert ("measured_by", "partner") in violations, "planting the old hard-coded literal must red this guard"
