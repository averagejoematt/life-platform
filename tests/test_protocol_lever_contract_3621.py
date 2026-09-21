"""tests/test_protocol_lever_contract_3621.py — #3621 box 5: the PROTOCOL# write contract.

THE CLAUSE
──────────
"Every protocol lever states the data it targets and the hypothesis that spawned it."
Measured 2026-09-06 it passed VACUOUSLY — `/api/protocols` returned `count=0` and the
schema had no linkage field at all, so every grading moment a reviewer could occupy
showed a pass over an empty set.

Re-measured 2026-09-20 (read-only DDB query): nine `PROTOCOL#` rows DO exist, all nine
`tombstone=true, cycle=5, phase=pilot` from the 2026-07-13 reset — so `count=0` was the
phase filter over an archive, not an empty table — and not one carries a `spawned_by`.
Those nine stay as they are: re-putting an archived row destroys the record of the cycle
it belonged to (#1202/ADR-077, and box 1's own ruling on the 329 reason strings).

So the contract binds the NEXT write, in BOTH doors the acceptance names:
  * the DDB writer — `experiment.protocol_levers.build_protocol_item`, reached by the one
    seeder (`deploy/seed_protocols.py`, which `seed_protocols_to_dynamodb.sh` delegates to);
  * `site/config/protocols.json` — the catalogue the site itself serves and the S3
    fallback returns, graded by the SAME predicate.

The clause is therefore graded AT THE WRITE, not against an empty payload — which is the
acceptance box's own last sentence.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (str(REPO_ROOT), str(REPO_ROOT / "lambdas")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from experiment import phase_taxonomy as taxonomy  # noqa: E402
from experiment.protocol_levers import (  # noqa: E402
    PRE_PLATFORM,
    PROTOCOL_SK_PREFIX,
    ProtocolLeverRefused,
    audit_catalog,
    build_protocol_item,
    spawned_by_problem,
)

CATALOG = REPO_ROOT / "site" / "config" / "protocols.json"
PK = "USER#matthew#SOURCE#protocols"

_seed_spec = importlib.util.spec_from_file_location("seed_protocols", REPO_ROOT / "deploy" / "seed_protocols.py")
seed = importlib.util.module_from_spec(_seed_spec)
sys.modules["seed_protocols"] = seed
_seed_spec.loader.exec_module(seed)


def _catalog() -> list[dict]:
    return json.loads(CATALOG.read_text(encoding="utf-8"))["protocols"]


# ─────────────────────────────────────────────────────────────────────────────
# door 1 — the DDB writer
# ─────────────────────────────────────────────────────────────────────────────


def test_a_lever_with_no_spawned_by_is_refused_at_the_write():
    with pytest.raises(ProtocolLeverRefused) as e:
        build_protocol_item({"id": "cold_plunge", "name": "Cold Plunge"}, pk=PK)
    assert "spawned_by" in str(e.value) and "cold_plunge" in str(e.value)


@pytest.mark.parametrize("bad", [None, "", "   ", 7, True, ["HYPOTHESIS#x"], "Published literature (Walker, 2017)", "hypothesis-4"])
def test_every_unlinked_shape_is_refused(bad):
    with pytest.raises(ProtocolLeverRefused):
        build_protocol_item({"id": "x", "spawned_by": bad}, pk=PK)


def test_a_hypothesis_id_is_accepted_and_keys_the_row():
    item = build_protocol_item({"id": "zone2_v2", "spawned_by": "HYPOTHESIS#2026-09-14T19:00:00+00:00"}, pk=PK)
    assert item["pk"] == PK
    assert item["sk"] == f"{PROTOCOL_SK_PREFIX}zone2_v2"
    assert item["spawned_by"] == "HYPOTHESIS#2026-09-14T19:00:00+00:00"


def test_the_literature_label_is_accepted_at_its_exact_spelling_only():
    assert spawned_by_problem(PRE_PLATFORM) is None
    for near_miss in ("Pre-Platform / Literature", "pre-platform/literature", "pre-platform", "pre-platform / lit"):
        assert spawned_by_problem(near_miss) is not None, f"{near_miss!r} must not pass — spelling is the contract"
        assert "EXACT" in (spawned_by_problem(near_miss) or "") or "not a HYPOTHESIS#" in (spawned_by_problem(near_miss) or "")


def test_a_lever_with_no_id_is_refused_before_anything_is_keyed():
    with pytest.raises(ProtocolLeverRefused, match="no `id`"):
        build_protocol_item({"spawned_by": PRE_PLATFORM}, pk=PK)


def test_the_writer_never_mutates_the_payload_it_was_handed():
    payload = {"id": "sleep", "spawned_by": PRE_PLATFORM}
    build_protocol_item(payload, pk=PK)
    assert payload == {"id": "sleep", "spawned_by": PRE_PLATFORM}


def test_the_seeder_refuses_the_whole_batch_rather_than_half_seeding():
    """A partial seed grades as 'some levers have provenance', which is the least
    readable of the three states — and it is the one an operator would ship by accident."""
    rows = [{"id": "ok", "spawned_by": PRE_PLATFORM}, {"id": "bad", "name": "Bad"}]
    with pytest.raises(SystemExit) as e:
        seed.build_items(rows, pk=PK)
    assert "nothing written" in str(e.value) and "bad" in str(e.value)


def test_the_seeder_is_dry_run_by_default_and_never_imports_boto3_to_print():
    """The heredoc this replaced had no dry-run. `--apply` is the only write path."""
    src = (REPO_ROOT / "deploy" / "seed_protocols.py").read_text(encoding="utf-8")
    assert '"--apply"' in src
    apply_block = src.split("if not args.apply:", 1)[1]
    assert "import boto3" in apply_block, "boto3 must be reached only after the dry-run return"
    assert seed.main(["--config", str(CATALOG)]) == 0  # dry-run over the real catalogue: prints, writes nothing


def test_the_shell_entrypoint_delegates_rather_than_carrying_its_own_writer():
    """Two writers is two contracts. The .sh must not keep a `put_item` of its own."""
    sh = (REPO_ROOT / "deploy" / "seed_protocols_to_dynamodb.sh").read_text(encoding="utf-8")
    assert "python3 deploy/seed_protocols.py" in sh
    assert "put_item" not in sh


def test_the_repo_has_exactly_one_protocol_write_path():
    """Guard the SET, not the instance: a second `PROTOCOL#` writer appearing anywhere in
    lambdas/ or deploy/ would be a door this contract does not cover."""
    sanctioned = {"lambdas/experiment/protocol_levers.py", "deploy/seed_protocols.py"}
    hits = set()
    for root in ("lambdas", "deploy", "mcp"):
        for path in (REPO_ROOT / root).rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            if "PROTOCOL#" in text and "put_item" in text:
                hits.add(path.relative_to(REPO_ROOT).as_posix())
    assert hits == sanctioned, (
        f"the PROTOCOL# write set drifted: unexpected {sorted(hits - sanctioned)}, missing {sorted(sanctioned - hits)}. "
        "A new writer must go through experiment.protocol_levers.build_protocol_item (#3621)."
    )


# ─────────────────────────────────────────────────────────────────────────────
# door 2 — site/config/protocols.json
# ─────────────────────────────────────────────────────────────────────────────


def test_the_catalogue_is_not_empty_so_this_clause_is_not_vacuous():
    rows = _catalog()
    assert len(rows) >= 6, f"only {len(rows)} levers — the grading moment this box exists for needs a real set"


def test_every_catalogue_lever_carries_a_valid_spawned_by():
    assert audit_catalog(_catalog()) == []


def test_an_empty_catalogue_is_a_FINDING_not_a_pass():
    """The exact failure the issue names: a clause graded over zero levers passes
    forever. `audit_catalog` reports it rather than returning []."""
    assert audit_catalog([]) and "EMPTY" in audit_catalog([])[0]


def test_the_catalogue_and_the_writer_are_graded_by_the_same_predicate():
    """Two predicates over two doors is how the two doors come to disagree."""
    for entry in _catalog():
        assert build_protocol_item(entry, pk=PK)["spawned_by"] == entry["spawned_by"]


def test_every_catalogue_lever_also_states_the_data_it_targets():
    """The anchor clause has two halves; `key_metrics` is the other one. Asserted here so
    adding `spawned_by` cannot be mistaken for satisfying the whole sentence."""
    for entry in _catalog():
        assert entry.get("key_metrics"), f"{entry['id']} names no key_metrics"


def test_the_catalogue_keeps_origin_as_its_own_field():
    """`spawned_by` is a linkage; `origin` is prose about why the lever exists. Collapsing
    them would make the field ungradeable."""
    for entry in _catalog():
        assert entry.get("origin"), f"{entry['id']} lost its origin prose"
        assert entry["origin"] != entry["spawned_by"]


def test_the_levers_stay_experiment_scoped_per_the_owner_ruling():
    """Owner ruling 2026-09-05 (#3606 item 8): levers are wiped with the cycle. This
    module does not re-open that, and the assertion says so on the record."""
    assert taxonomy.classify(PK, "PROTOCOL#sleep") == taxonomy.EXPERIMENT_SCOPED


# ─────────────────────────────────────────────────────────────────────────────
# mutation controls — remove the refusal, these must RED
# ─────────────────────────────────────────────────────────────────────────────


def test_mutation_control_a_truthiness_check_admits_a_prose_citation():
    """The plausible weakening: `if not p.get("spawned_by"): refuse`. It accepts any
    non-empty string, so `origin`'s own prose would pass as a linkage. Watched here so
    the shape test in `spawned_by_problem` is load-bearing."""
    softened = bool("Published literature (Walker, 2017; Huberman, 2021)")
    assert softened is True, "the softened predicate must be shown to accept it"
    assert spawned_by_problem("Published literature (Walker, 2017; Huberman, 2021)") is not None


def test_mutation_control_defaulting_instead_of_refusing_makes_every_lever_claim_provenance():
    """The other plausible weakening: fill in the label when the field is absent. Every
    lever would then assert 'no hypothesis spawned me' — a claim nobody made."""
    payload = {"id": "cold_plunge"}
    with pytest.raises(ProtocolLeverRefused):
        build_protocol_item(payload, pk=PK)
    assert "spawned_by" not in payload, "a refusal must not leave a default behind on the caller's dict"


def test_mutation_control_dropping_the_catalogue_leg_leaves_the_s3_fallback_ungraded():
    """`/api/protocols` falls back to site/config/protocols.json when the DDB query
    fails. A writer-only contract leaves that door open, so the catalogue audit must be
    able to fail: shown here on a doctored copy of the real catalogue."""
    doctored = [dict(e) for e in _catalog()]
    doctored[0].pop("spawned_by")
    problems = audit_catalog(doctored)
    assert len(problems) == 1 and doctored[0]["id"] in problems[0]
