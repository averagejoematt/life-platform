"""#3717 — an attestation may never be read as a measurement.

The owner asked whether we could "imply" the missing post-lift cardio, or
backfill it onto the old Hevy workouts. We are not doing that: a synthetic row
in SOURCE#hevy is indistinguishable from a measured one the moment it lands,
would feed the band reference, the proven curve and the public site, and
`raw/*` is delete-protected so it is close to irreversible.

The attestation layer is the safe version — declared, separable, labelled. That
only holds if the separation is enforced, which is what these tests do.
"""

from lambdas.training import attested_training as at


def _confirmed(**over):
    base = {
        "id": "post_lift_low_cardio",
        "active": True,
        "start_date": "2024-09-05",
        "end_date": "2025-04-30",
        "applies_when": "hevy_lift_logged",
        "kind": "cycle",
        "minutes_low": 30,
        "minutes_high": 60,
        "minutes_typical": 45,
        "attested_by": "matthew",
    }
    base.update(over)
    return [base]


def test_an_unconfirmed_attestation_is_not_evidence(monkeypatch):
    """A draft must not reach a prescription just because it exists in the file.

    Guarded against a SYNTHETIC record, not against whatever the shipped list
    happens to contain — pinning "the file's entry is inactive" would test the
    instance and would have to be rewritten every time the owner confirms one.
    """
    monkeypatch.setattr(at, "ATTESTATIONS", [dict(_confirmed()[0], active=False)])
    assert at.active_attestations() == [], "an unconfirmed attestation went live"
    assert at.attested_minutes_for_day("2024-10-01", had_lift=True) is None
    assert at.attested_overlay({"2024-10-01"}, {"2024-10-01"}) is None


def test_every_shipped_attestation_is_fully_specified():
    """Whatever IS active must carry the fields that make it auditable — who
    said it, when, and on what basis. An attestation without provenance is
    indistinguishable from a guess someone typed in."""
    for a in at.active_attestations():
        for field in ("id", "start_date", "end_date", "attested_by", "attested_at", "basis"):
            assert a.get(field), f"active attestation {a.get('id')!r} is missing {field}"
        assert a["start_date"] <= a["end_date"]
        assert (
            a.get("minutes_low", 0) <= a.get("minutes_typical", 0) <= a.get("minutes_high", 0)
        ), "an attested range must bracket its typical value"


def test_an_attestation_missing_its_dates_never_activates(monkeypatch):
    monkeypatch.setattr(at, "ATTESTATIONS", [{"id": "x", "active": True, "start_date": None, "end_date": None}])
    assert at.active_attestations() == []


def test_a_confirmed_attestation_applies_only_on_lift_days(monkeypatch):
    monkeypatch.setattr(at, "ATTESTATIONS", _confirmed())
    assert at.attested_minutes_for_day("2024-10-01", had_lift=True) is not None
    assert at.attested_minutes_for_day("2024-10-01", had_lift=False) is None, "applied on a rest day"


def test_it_applies_only_inside_its_declared_window(monkeypatch):
    monkeypatch.setattr(at, "ATTESTATIONS", _confirmed())
    assert at.attested_minutes_for_day("2026-09-08", had_lift=True) is None, "leaked past its end date"
    assert at.attested_minutes_for_day("2020-01-01", had_lift=True) is None, "leaked before its start date"


def test_the_overlay_carries_its_range_and_its_basis_label(monkeypatch):
    monkeypatch.setattr(at, "ATTESTATIONS", _confirmed())
    days = {f"2024-10-{d:02d}" for d in range(1, 15)}
    o = at.attested_overlay(days, days)
    assert o is not None
    assert (
        o["cardio_hr_wk_attested_low"] < o["cardio_hr_wk_attested"] < o["cardio_hr_wk_attested_high"]
    ), "a single invented number with no uncertainty"
    assert o["basis"] == "OWNER-ATTESTED, NOT MEASURED"


def test_the_overlay_never_returns_a_merged_total(monkeypatch):
    """The only safe place to combine attested and measured is at display, with
    a label. A merged total here would be laundered into every consumer."""
    monkeypatch.setattr(at, "ATTESTATIONS", _confirmed())
    days = {f"2024-10-{d:02d}" for d in range(1, 15)}
    o = at.attested_overlay(days, days)
    for k in o:
        assert "attested" in k or k in ("attestation_id", "kind", "n_days_covered", "basis"), f"{k} reads as a plain measured field"


def test_measured_covariates_are_never_mutated_by_an_attestation(monkeypatch):
    """The load-bearing invariant: walk_hr_wk / cardio_hr_wk stay measured."""
    from lambdas.compute import episode_detect_lambda as ed

    monkeypatch.setattr(at, "ATTESTATIONS", _confirmed())
    idx = [f"2024-10-{d:02d}" for d in range(1, 15)]
    vals = [255.0] * len(idx)
    acts = [{"date": d, "kind": "walk", "hours": 1.0, "miles": 3.0, "hr": 100} for d in idx]
    hevy = {d: {"sets": 10.0, "tonnage_lb": 5000.0, "top_kg": {}} for d in idx}
    ref = ed.build_reference(idx, vals, [], acts, {}, hevy, {})
    band = ref["bands"]["250-259"]
    # 14 walks of 1h over ~14 days ≈ 7 h/wk measured, regardless of any attestation.
    assert 5.0 < band["walk_hr_wk"] < 9.0, band["walk_hr_wk"]
    assert band["cardio_hr_wk"] == band["walk_hr_wk"] + band["cycle_hr_wk"], "attested leaked into cardio_hr_wk"
    if "attested" in band:
        assert band["attested"]["basis"] == "OWNER-ATTESTED, NOT MEASURED"


def test_no_synthetic_rows_are_written_to_a_measured_partition():
    """A backfill would have put these in SOURCE#hevy. Assert nothing does.

    Parsed with AST, not grepped: this module's own docstring explains WHY it
    does not write to SOURCE#hevy, so a text search matches its own prose and
    passes for the wrong reason. That is exactly the failure mode of the
    #2376 wallclock guard, which is satisfied by the word "frozen" appearing
    anywhere in a file. A guard must read code, not commentary.
    """
    import ast

    tree = ast.parse(open(at.__file__).read())
    called = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            called.add(f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", ""))
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mods = [a.name for a in node.names] + ([node.module] if isinstance(node, ast.ImportFrom) else [])
            for m in mods:
                assert "boto3" not in str(m), "the attestation layer imports a storage client"
    for w in ("put_item", "batch_writer", "update_item", "transact_write_items"):
        assert w not in called, f"the attestation layer writes to the store ({w})"

    # And the string constants it does hold must not name a measured partition.
    consts = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    body_consts = {c for c in consts if "\n" not in c}  # exclude docstrings
    for c in body_consts:
        assert "SOURCE#" not in c, f"names a measured partition in code: {c!r}"
