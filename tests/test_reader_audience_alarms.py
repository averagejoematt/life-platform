"""tests/test_reader_audience_alarms.py — the #3423 reader-audience facet.

Defect class owned: `ai-canary-overall` went ALARM 2026-08-31 09:22 PT (the #3413
`/api/board_ask` 504 P1) and sat lit ~31h across launch day with zero escalation,
because it was under the citation gate's 72h bar and nothing routed it to a human
sooner. The fix attaches a curated `audience: "reader"` facet to
`model/platform_model.json`'s alarms plane (`scripts/platform_model_alarms.py::
READER_AUDIENCE_ALARMS`), which `scripts/check_alarm_citations.py` and
`remediation/agent.py` both read to lower an otherwise-72h bar to 0h (first red) for
exactly those alarms.

This file pins:
  * the registry itself — non-empty, every name a real CDK-declared alarm (a typo or
    rename fails LOUDLY, both here and via the `assert` inside `extract_alarms()`
    itself), `ai-canary-overall` present (the regression pin for the motivating
    incident);
  * every tagged alarm carries a non-empty blast-radius ruling — "asserted by an
    operator", per docs/alarm_citations.json's own convention, not a bare tag;
  * the registry round-trips into the GENERATED, committed `model/platform_model.json`
    (a direct pin alongside the general `test_platform_model_drift.py` byte-diff, so a
    forgotten `python3 scripts/generate_platform_model.py` after editing the registry
    fails here with a specific, readable message);
  * a name NOT in the registry carries no `audience` facet at all (absent, never
    "internal") — the same unlisted-means-default convention the privacy plane uses.
"""

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import platform_model_alarms as pma  # noqa: E402


def test_registry_is_non_empty_and_pins_the_motivating_alarm():
    assert pma.READER_AUDIENCE_ALARMS, "READER_AUDIENCE_ALARMS is empty — #3423 tagged nothing"
    assert "ai-canary-overall" in pma.READER_AUDIENCE_ALARMS, (
        "ai-canary-overall is the alarm that sat lit ~31h through the #3413 launch-day incident — "
        "it must be tagged reader-audience or this facet doesn't fix what it was filed for"
    )


def test_every_registry_entry_names_a_real_cdk_declared_alarm():
    """A typo/rename must fail loudly, not silently drop coverage — the same
    discipline docs/alarm_citations.json's own test enforces for `#N` references."""
    alarms = pma.extract_alarms()
    unknown = sorted(n for n in pma.READER_AUDIENCE_ALARMS if n not in alarms)
    assert not unknown, f"READER_AUDIENCE_ALARMS names alarms not in the CDK-declared inventory: {unknown}"


def test_every_registry_entry_carries_a_non_empty_ruling():
    for name, ruling in pma.READER_AUDIENCE_ALARMS.items():
        assert isinstance(ruling, str) and ruling.strip(), f"{name}: audience ruling must be non-empty prose, not a bare tag"


def test_extract_alarms_attaches_the_facet_and_ruling():
    alarms = pma.extract_alarms()
    for name, ruling in pma.READER_AUDIENCE_ALARMS.items():
        assert alarms[name]["audience"] == "reader"
        assert alarms[name]["audience_ruling"] == ruling


def test_an_untagged_alarm_carries_no_audience_facet_at_all():
    """Unlisted = default by omission (absent, never the string 'internal') — the
    same convention the privacy plane already uses (see generate_platform_model.py's
    module docstring)."""
    alarms = pma.extract_alarms()
    untagged = [n for n in alarms if n not in pma.READER_AUDIENCE_ALARMS]
    assert untagged, "sanity: there must be alarms NOT in the reader-audience registry"
    sample = untagged[0]
    assert "audience" not in alarms[sample]


# ── the committed model — direct pin, not only the general drift byte-diff ─────


def _committed_model():
    return json.loads((ROOT / "model" / "platform_model.json").read_text(encoding="utf-8"))


def test_the_committed_model_carries_the_reader_audience_facet():
    model_alarms = _committed_model()["alarms"]
    for name, ruling in pma.READER_AUDIENCE_ALARMS.items():
        assert name in model_alarms, f"{name}: in the registry but missing from the committed model — regenerate the model"
        assert model_alarms[name].get("audience") == "reader", (
            f"{name}: registry tags it reader-audience but the committed model/platform_model.json disagrees — "
            "run `python3 scripts/generate_platform_model.py` and commit both artifacts"
        )
        assert model_alarms[name].get("audience_ruling") == ruling


def test_the_committed_model_has_no_extra_reader_tags():
    """The model's reader set must equal the registry's — never wider (a stray tag
    the registry doesn't know about would mean the two drifted in the OTHER
    direction: the model claims more than the curated registry asserts)."""
    model_alarms = _committed_model()["alarms"]
    model_reader = {n for n, r in model_alarms.items() if r.get("audience") == "reader"}
    assert model_reader == set(pma.READER_AUDIENCE_ALARMS)
