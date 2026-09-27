"""tests/test_public_claims_registry_3042.py — the public-claims derivation guard (D2, #3042).

`tests/public_claims_registry.py` declares, per public behavioural claim: the SUBJECT ·
the surfaces permitted to STATE it · the sources it is DERIVED FROM · the COMPARATOR that
reads both. This file is the guard over that registry, in both directions:

  (a) every registered claim's comparator passes — the published sentence still matches
      the machine it describes;
  (b) discovery finds no public surface asserting a registered claim SUBJECT outside that
      claim's declared `stated` globs — a new page, generator, or copy-pasted paragraph
      joins the registry or reds the build.

WHY BOTH. Direction (a) alone is a hand-list: it checks the instances someone remembered.
The claim it was filed on lives in ONE generator editorial and is emitted into 31 published
pages — a registry naming one page would have described one instance of a claim that
exists in dozens. That is the "guard the SET, not the instance" rule, and (b) is the set.

Direction (b) also catches the quieter failure: a claim whose phrase STOPS matching. If
someone rewrites the essay so "lands as a pull request a human merges" becomes something
else, the comparator loses its anchor. `test_the_sweep_is_not_vacuous` treats a claim with zero discovered
surfaces as a failure, so a reworded claim forces re-registration instead of silently
disarming its own comparator.

MUTATION PROOFS RUN EVERY TIME. Three of the tests below deliberately falsify a claim —
a flipped runtime mode, a rogue generator in a synthetic tree, a merge step slipped back
into the agent's workflow — and assert the machinery reds. A guard that has never been shown to fail is indistinguishable in CI
from a guard that cannot.
"""

from __future__ import annotations

import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import public_claims_registry as reg  # noqa: E402

DISCOVERED = reg.discover_claim_statements()


# ── Direction (a): every comparator passes ───────────────────────────────────


@pytest.mark.parametrize("claim_id", sorted(reg.CLAIMS))
def test_the_claims_comparator_passes(claim_id):
    """The published claim still matches the machine. A failure here is not a test bug —
    it means a reader is currently being told something untrue, and the fix is either the
    prose or the machine, never this assertion."""
    findings = reg.comparator_for(claim_id)()
    assert not findings, "public claim '{}' no longer matches its source of truth:\n  - {}".format(claim_id, "\n  - ".join(findings))


# ── Direction (b): the SET ───────────────────────────────────────────────────


def test_no_unregistered_surface_states_a_registered_claim():
    """A NEW public surface asserting a registered claim must join that claim's `stated`
    globs before it can merge. Otherwise the registry drifts back into the hand-list it
    replaced: the comparator keeps passing against the pages someone remembered while a
    fresh copy of the same sentence rots somewhere else in the tree."""
    loose = reg.unregistered_statements()
    assert not loose, (
        "public surface(s) assert a registered claim but are not in that claim's `stated` globs: "
        + "; ".join(f"{path} -> {sorted(ids)}" for path, ids in sorted(loose.items()))
        + ". Add the surface to the claim's `stated` tuple in tests/public_claims_registry.py "
        "(and make sure its comparator still derives the claim there), or stop stating the claim on it."
    )


def test_the_sweep_is_not_vacuous():
    """A discovery that finds nothing would make the assertion above trivially true and
    read exactly like 'no drift'. Every registered claim must be found on at least one
    real surface — which is also what catches a claim reworded out from under its own
    comparator's regex."""
    assert len(DISCOVERED) > 10, f"discovery found only {len(DISCOVERED)} claim-bearing surfaces — the scan is broken, not the repo"
    for claim_id in reg.CLAIMS:
        surfaces = [path for path, ids in DISCOVERED.items() if claim_id in ids]
        assert surfaces, (
            f"claim {claim_id!r} is registered but discovery finds NO surface stating it. Either the prose was "
            "reworded (update `phrases`, and check the comparator still has its anchor) or the claim was retired "
            "(remove the entry) — a registered claim nobody states is a comparator guarding nothing."
        )


# ── Shape ────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("claim_id", sorted(reg.CLAIMS))
def test_entry_shape(claim_id):
    entry = reg.CLAIMS[claim_id]
    for facet in ("subject", "stated", "phrases", "derived_from", "comparator", "reason"):
        assert entry.get(facet), f"{claim_id}: missing {facet}"
    assert callable(reg.comparator_for(claim_id)), f"{claim_id}: comparator {entry['comparator']!r} does not resolve"
    assert isinstance(entry["runtime"], bool), f"{claim_id}: `runtime` must say explicitly whether the claim's truth is live state"
    # A reason that could be pasted onto any other entry records that nobody looked
    # (the #2056 lesson, carried over from the derived-artifact registry).
    assert len(entry["reason"]) >= 120, f"{claim_id}: reason is too thin to be specific — {entry['reason']!r}"


@pytest.mark.parametrize("claim_id", sorted(reg.CLAIMS))
def test_declared_surfaces_and_sources_exist(claim_id):
    """A registry entry pointing at a deleted page or module is worse than no entry: it
    reads as coverage. Globs are checked by discovery instead — a glob matching nothing
    is caught by `test_the_sweep_is_not_vacuous`."""
    entry = reg.CLAIMS[claim_id]
    for stated in entry["stated"]:
        if "*" in stated:
            continue
        assert (reg.REPO / stated).exists(), f"{claim_id}: declared stated-where {stated} does not exist"
    for source in entry["derived_from"]:
        path = source.split(" (")[0]
        if "/" not in path or not path.endswith((".py", ".json", ".yml", ".md", ".html")):
            continue  # a runtime source (SSM), described in prose
        assert (reg.REPO / path).exists(), f"{claim_id}: declared derived-from {path} does not exist"


def test_every_excluded_tree_is_real_and_reasoned():
    """`EXCLUDED_TREES` is the one place this sweep can be quietly narrowed into
    uselessness. Each entry must name a directory that actually exists and carry a
    reason specific to it."""
    for tree, reason in reg.EXCLUDED_TREES.items():
        assert (reg.REPO / tree).is_dir(), f"EXCLUDED_TREES names {tree}, which is not a directory — stale exclusion"
        assert len(reason) >= 40, f"EXCLUDED_TREES[{tree}]: reason is too thin — {reason!r}"


# ── Mutation proofs: both directions, run every time ─────────────────────────


def test_a_flipped_runtime_mode_reds_the_comparator():
    """Direction (a), proven. The published claim is 'every fix lands as a pull request a
    human merges'. Flip the runtime mode to `auto` — an operator SSM action with NO repo
    diff — and the comparator must red. If it did not, the recorded-value pattern would
    be decoration: it would pass identically whatever the parameter said."""
    assert reg.compare_remediation_mode("shadow") == [], "the comparator should be clean at the recorded mode"
    assert reg.compare_remediation_mode("off") == [], "`off` also means no self-merge — the claim still holds"
    findings = reg.compare_remediation_mode("auto")
    assert findings, "flipping the runtime mode to `auto` did not red the comparator — it cannot detect the drift it exists for"
    assert any("self-merge" in f for f in findings), f"the finding should name the contradiction, got: {findings}"


def test_discovery_reds_on_an_unregistered_claim_generator(tmp_path):
    """Direction (b), proven, against a synthetic tree — the #2372 derivation's own
    lesson. A brand-new generator repeating a registered claim outside the claim's
    `stated` globs must be reported as unregistered."""
    rogue = tmp_path / "scripts" / "v4_build_rogue_page.py"
    rogue.parent.mkdir(parents=True)
    rogue.write_text('EDITORIAL = "the merge gate runs in shadow mode, so a human merges every fix"\n', encoding="utf-8")

    found = reg.discover_claim_statements(root=tmp_path)
    assert found.get("scripts/v4_build_rogue_page.py") == {"remediation_agent_mode"}, f"discovery missed the rogue generator: {found}"

    loose = reg.unregistered_statements(root=tmp_path)
    assert loose == {
        "scripts/v4_build_rogue_page.py": {"remediation_agent_mode"}
    }, f"the rogue generator was not reported as unregistered: {loose}"


def test_a_registered_surface_is_not_reported_as_unregistered(tmp_path):
    """The other half of the (b) proof: a sweep that reported EVERYTHING would also pass
    the test above while being useless. A surface inside the declared globs must come
    back clean."""
    page = tmp_path / "site" / "method" / "build" / "index.html"
    page.parent.mkdir(parents=True)
    page.write_text("<p>that gate currently runs in shadow mode</p>", encoding="utf-8")
    assert reg.discover_claim_statements(root=tmp_path)["site/method/build/index.html"] == {"remediation_agent_mode"}
    assert reg.unregistered_statements(root=tmp_path) == {}


def test_an_excluded_tree_is_actually_skipped(tmp_path):
    """The frozen v3 archive states the old posture on purpose. Prove the exclusion works
    — and, by pairing it with the test above, that it is an exclusion rather than a sweep
    that silently reads nothing."""
    legacy = tmp_path / "site" / "legacy" / "platform" / "index.html"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("<p>the gate runs in shadow mode</p>", encoding="utf-8")
    assert reg.discover_claim_statements(root=tmp_path) == {}


def test_a_merge_step_back_in_the_workflow_reds_the_comparator(monkeypatch):
    """Fixture must be the wire, proven. Since #2833 the 'a human merges' claim is derived
    from the workflow having no merge step. Plant one and the comparator must red — which
    shows it reads `.github/workflows/remediation-agent.yml` rather than a recorded
    assertion about it."""
    real = reg._read

    def with_merge_step(path):
        text = real(path)
        if str(path).endswith("remediation-agent.yml"):
            text += "\n      - name: Merge safe PRs\n        run: gh pr merge --squash 1\n"
        return text

    monkeypatch.setattr(reg, "_read", with_merge_step)
    findings = reg.compare_remediation_mode("shadow")
    assert any("merge step" in f for f in findings), f"a planted merge step did not red the comparator: {findings}"


def test_the_agent_merge_prohibition_is_load_bearing(monkeypatch):
    """Same proof for the in-band guard: strip `gh pr merge` from the agent's disallowed
    tools and the comparator must red."""
    real = reg._read

    def without_disallow(path):
        text = real(path)
        if str(path).endswith("remediation/agent.py"):
            text = text.replace('"Bash(gh pr merge *)"', '"Bash(gh pr view *)"')
        return text

    monkeypatch.setattr(reg, "_read", without_disallow)
    findings = reg.compare_remediation_mode("shadow")
    assert any("gh pr merge" in f for f in findings), f"removing the in-band merge prohibition did not red: {findings}"


def test_the_deletion_comparator_reads_the_signed_policy(monkeypatch):
    """Same proof for the reader-facing promise: change the signed retention policy and
    the privacy page's 'on the spot' wording must red."""
    real = reg._module_constants

    def relaxed(rel_path):
        consts = dict(real(rel_path))
        if rel_path.endswith("subscriber_retention.py"):
            consts["RETENTION_WINDOW_DAYS"] = 548
            consts["RETENTION_MODE"] = "purge"
        return consts

    monkeypatch.setattr(reg, "_module_constants", relaxed)
    findings = reg.compare_deletion_promise()
    assert any("on the spot" in f for f in findings), f"a 548-day window did not contradict the on-the-spot promise: {findings}"
    assert any("RETENTION_MODE" in f for f in findings), f"a changed retention mode did not red the page's described mechanism: {findings}"


# ── Live reconciliation: opt-in, loud skip (the permanence-terms pattern) ────


def test_recorded_runtime_mode_matches_live_ssm():
    """The recorded value has a shelf life. When live state is reachable AND explicitly
    requested (`CLAIMS_LIVE_RECONCILE=1`), reconcile it; otherwise SKIP with the reason
    said out loud. CI must never depend on AWS for this — but a silent pass would be a
    check that never ran, which is the failure this whole phase is about."""
    if not reg.live_reconcile_enabled():
        pytest.skip(
            "LIVE RECONCILIATION NOT RUN: the remediation-mode claim is checked against the RECORDED value "
            f"{reg.recorded_runtime('remediation_mode')!r} (recorded {reg.RECORDED_RUNTIME['remediation_mode']['recorded']}), "
            "not live SSM. Set CLAIMS_LIVE_RECONCILE=1 with AWS credentials to reconcile."
        )
    import boto3

    param = reg.RECORDED_RUNTIME["remediation_mode"]["param"]
    live = boto3.client("ssm", region_name=os.environ.get("AWS_REGION", "us-west-2")).get_parameter(Name=param)["Parameter"]["Value"]
    recorded = reg.recorded_runtime("remediation_mode")
    assert live == recorded, (
        f"{param} is live {live!r} but the registry records {recorded!r}. Update RECORDED_RUNTIME (with the date "
        "and the decision that flipped it) and re-check every surface stating the remediation-mode claim."
    )
    assert not reg.compare_remediation_mode(live), f"live mode {live!r} contradicts the published claim"
