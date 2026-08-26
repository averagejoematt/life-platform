"""#3207 — the declared-but-not-yet-applied posture marker, proved in BOTH directions.

THE INCIDENT. `deploy/github_posture.json` could only express DESIRED state. D0.6's
`main-required-fast-lane` ruleset is declared but deliberately unapplied (blocked on the
`RECONCILE_PUSH_TOKEN` PAT), so the 2026-08-26 remediation sweep reported it as a
**critical safety gap** and recommended `python3 scripts/apply_branch_protection.py
--apply` — an action that would have rejected ci-cd.yml's post-merge reconcile push on
every merge, because that job falls back to `GITHUB_TOKEN` (github-actions[bot]), which
the ruleset's `User` bypass actor does not cover. The false alarm regenerated every
Mon/Wed/Fri sweep.

THE CRUX OF THIS FILE. A fix that silences both directions is a false green, so every
suppression here is proved against its opposite:

  * `test_applied_entry_still_drifts_*`   — a GENUINELY drifted APPLIED entry still
    reports drift, with the --apply recommendation intact.
  * `test_unapplied_entry_reports_pending_*` — a not-yet-applied entry reports the
    distinct `pending` status, names its blocker, and carries NO --apply advice.
  * `test_stale_marker_*` — an entry that IS applied live while still marked
    `applied: false` reports DRIFT on the stale marker. Without this, the pending state
    would be a one-way silencer: apply the ruleset, forget the marker, and the sentinel
    stops judging the surface forever while reporting a comfortable non-drift.

STRUCTURAL, NEVER PHRASE-MATCHED. `test_classification_is_structural_not_name_matched`
pins that the verdict keys off the machine-readable `applied` field and not the ruleset's
name — every phrase-matched member of the #2959/#3003/#3199 suppressor family has failed
in the field, one of them gating main.
"""

from __future__ import annotations

import copy
import json
import os
import re
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "deploy"))
sys.path.insert(0, os.path.join(_ROOT, "scripts"))
sys.path.insert(0, _ROOT)

import apply_branch_protection as abp  # noqa: E402
import drift_sentinel as ds  # noqa: E402
import sentinel_github as sg  # noqa: E402

from remediation import drift_report  # noqa: E402

LEDGER = os.path.join(_ROOT, "docs", "MANAGED_WHERE_LEDGER.md")

# ── live-shape fixtures (the real /rulesets and /repos payload shapes) ────────

_OWNER_USER = {"id": 174924761, "login": "averagejoematt"}
_GITHUB_ACTIONS_APP = {"id": 15368, "slug": "github-actions"}
_ENV_WITH_REVIEWERS = {"protection_rules": [{"type": "required_reviewers"}]}
_MAIN_RULESET = {
    "id": 19162901,
    "name": "main-block-force-push-and-deletion",
    "enforcement": "active",
    "rules": [{"type": "deletion"}, {"type": "non_fast_forward"}],
    "conditions": {"ref_name": {"include": ["refs/heads/main"]}},
}


def _rc_ruleset_live(spec):
    """A live /rulesets/{id} record that MATCHES the checked-in spec exactly."""
    return {
        "id": 4242424,
        "name": spec["name"],
        "enforcement": spec["enforcement"],
        "conditions": {"ref_name": {"include": list(spec["include_refs"])}},
        "bypass_actors": [{"actor_id": _OWNER_USER["id"], "actor_type": "User", "bypass_mode": "always"}],
        "rules": [
            {
                "type": "required_status_checks",
                "parameters": {
                    "strict_required_status_checks_policy": False,
                    "required_status_checks": [{"context": c["context"], "integration_id": 15368} for c in spec["required_status_checks"]],
                },
            }
        ],
    }


def _posture(applied_ruleset, applied_settings=None):
    """The REAL checked-in posture with only the `applied` marker(s) mutated.

    Mutating the real file rather than hand-building a spec is deliberate: the fixture
    must be the wire. A hand-written spec would let the shipped file drift out from
    under every assertion here.
    """
    # Read the file DIRECTLY, never through sg._load_github_posture — tests below
    # monkeypatch that name, and a builder that went through it would silently inherit
    # the previous test's mutated spec.
    with open(sg.GITHUB_POSTURE_FILE) as f:
        posture = json.load(f)
    posture["main_required_checks_ruleset"]["applied"] = applied_ruleset
    posture["repo_settings"]["applied"] = applied_ruleset if applied_settings is None else applied_settings
    return posture


def _run_config(monkeypatch, posture, *, rc_present, auto_merge):
    """check_github_config() against a fully faked GitHub, GET-only, no network."""
    spec = posture["main_required_checks_ruleset"]
    live_rc = _rc_ruleset_live(spec)
    routes = {
        "environments/production": (_ENV_WITH_REVIEWERS, None),
        "rulesets/19162901": (_MAIN_RULESET, None),
        f"rulesets/{live_rc['id']}": (live_rc, None),
        "rulesets": ([_MAIN_RULESET] + ([live_rc] if rc_present else []), None),
        "vulnerability-alerts": ({}, None),
        "/apps/github-actions": (_GITHUB_ACTIONS_APP, None),
        "/users/averagejoematt": (_OWNER_USER, None),
        "repos/": ({"allow_auto_merge": auto_merge}, None),
    }

    def fake(path, timeout=60):
        for frag, resp in routes.items():
            if frag in path:
                return resp
        raise AssertionError(f"unrouted gh api path in test: {path}")

    monkeypatch.setattr(sg, "_gh_api_result", fake)
    monkeypatch.setattr(ds, "_gh_api_result", fake)
    monkeypatch.setattr(sg, "_load_github_posture", lambda: posture)
    return sg.check_github_config()


# ── MUTATION PROOF (a): a genuinely-drifted APPLIED entry still drifts ────────


def test_applied_entry_still_drifts_when_the_ruleset_is_absent(monkeypatch):
    # The real regression this sweep exists to catch: the gate WAS applied, and the
    # ruleset has since been deleted in the GitHub UI. `applied: true` must leave the
    # #1662 behaviour byte-for-byte intact, --apply recommendation and all.
    res = _run_config(monkeypatch, _posture(True), rc_present=False, auto_merge=False)
    assert res["status"] == "drift"
    rc = res["surfaces"]["main_required_checks_ruleset"]
    assert rc["status"] == "drift", rc
    assert "NO required status checks" in rc["detail"]
    assert "apply_branch_protection.py --apply" in rc["detail"]
    assert "pending" not in res


def test_applied_entry_still_drifts_when_a_repo_setting_is_off(monkeypatch):
    # Same proof for the value-comparison surface: auto-merge silently flipped off.
    res = _run_config(monkeypatch, _posture(True), rc_present=True, auto_merge=False)
    settings = res["surfaces"]["repo_settings"]
    assert settings["status"] == "drift"
    assert "allow_auto_merge" in settings["detail"]
    assert "apply_branch_protection.py --apply" in settings["detail"]


def test_applied_entry_is_clean_when_live_matches(monkeypatch):
    # The post-apply steady state stays a plain clean — the marker adds no new noise.
    res = _run_config(monkeypatch, _posture(True), rc_present=True, auto_merge=True)
    assert res["status"] == "clean"
    assert res["surfaces"]["main_required_checks_ruleset"]["status"] == "clean"
    assert res["surfaces"]["repo_settings"]["status"] == "clean"


# ── MUTATION PROOF (b): a not-yet-applied entry does NOT drift ────────────────


def test_unapplied_entry_reports_pending_not_drift(monkeypatch):
    # TODAY'S REAL STATE, replayed: no fast-lane ruleset, auto-merge off, posture says
    # `applied: false`. Before #3207 this was `status: drift` on both surfaces with
    # "critical safety gap … run --apply to restore".
    res = _run_config(monkeypatch, _posture(False), rc_present=False, auto_merge=False)
    assert res["status"] == "pending", res
    for name in ("main_required_checks_ruleset", "repo_settings"):
        surface = res["surfaces"][name]
        assert surface["status"] == "pending", surface
        assert surface["applied"] is False
        assert "RECONCILE_PUSH_TOKEN" in surface["blocked_on"]
        # THE LOAD-BEARING NEGATIVE: the advice that would have wedged the reconcile
        # push must not appear anywhere in what a human or the agent reads.
        assert "fix: python3 scripts/apply_branch_protection.py --apply" not in surface["detail"]
        assert "Do NOT run scripts/apply_branch_protection.py --apply" in surface["detail"]
        assert "critical" not in surface["detail"].lower()
    assert set(res["pending"]) == {"main_required_checks_ruleset", "repo_settings"}
    # …and the surfaces that are NOT marked pending are still judged normally.
    assert res["surfaces"]["main_ruleset"]["status"] == "clean"
    assert res["surfaces"]["environment_production"]["status"] == "clean"


def test_pending_never_masks_a_real_drift_on_another_surface(monkeypatch):
    # Guard-the-SET: pending on two surfaces must not downgrade the whole check when a
    # DIFFERENT surface genuinely regressed (vulnerability alerts turned off here).
    posture = _posture(False)
    posture["vulnerability_alerts"]["enabled"] = True

    res = _run_config(monkeypatch, posture, rc_present=False, auto_merge=False)
    assert res["status"] == "pending"
    # now break an unmarked surface and confirm drift wins the aggregation
    posture["environment_production"]["required_reviewers"] = False
    res = _run_config(monkeypatch, posture, rc_present=False, auto_merge=False)
    assert res["status"] == "drift"
    assert res["surfaces"]["environment_production"]["status"] == "drift"
    assert res["surfaces"]["main_required_checks_ruleset"]["status"] == "pending"


# ── the marker cannot rot: applied-live while still marked false is DRIFT ─────


def test_stale_marker_is_drift_when_the_surface_is_applied_live(monkeypatch):
    # Without this, `pending` is a one-way silencer: apply the ruleset, forget to flip
    # the marker, and the sentinel stops judging the surface forever while reporting a
    # comfortable non-drift. (fail_closed_paths_need_a_live_proof, applied to a marker.)
    res = _run_config(monkeypatch, _posture(False), rc_present=True, auto_merge=True)
    assert res["status"] == "drift"
    for name in ("main_required_checks_ruleset", "repo_settings"):
        surface = res["surfaces"][name]
        assert surface["status"] == "drift", surface
        assert surface["stale_applied_marker"] is True
        assert "STALE" in surface["detail"]
        assert "Flip `applied` to true" in surface["detail"]


def test_stale_marker_preserves_the_underlying_diagnosis(monkeypatch):
    # An out-of-band ruleset that exists AND is wrong must still say what is wrong —
    # the stale-marker line is prepended, never a replacement for the real judgement.
    posture = _posture(False)
    spec = posture["main_required_checks_ruleset"]
    live_rc = _rc_ruleset_live(spec)
    live_rc["rules"].append({"type": "pull_request", "parameters": {"required_approving_review_count": 1}})

    def fake(path, timeout=60):
        if "environments/production" in path:
            return _ENV_WITH_REVIEWERS, None
        if "rulesets/19162901" in path:
            return _MAIN_RULESET, None
        if f"rulesets/{live_rc['id']}" in path:
            return live_rc, None
        if "rulesets" in path:
            return [_MAIN_RULESET, live_rc], None
        if "vulnerability-alerts" in path:
            return {}, None
        if "/users/" in path:
            return _OWNER_USER, None
        if "/apps/" in path:
            return _GITHUB_ACTIONS_APP, None
        return {"allow_auto_merge": True}, None

    monkeypatch.setattr(sg, "_gh_api_result", fake)
    monkeypatch.setattr(sg, "_load_github_posture", lambda: posture)
    rc = sg.check_github_config()["surfaces"]["main_required_checks_ruleset"]
    assert rc["status"] == "drift"
    assert "STALE" in rc["detail"] and "approval-shaped" in rc["detail"]


# ── the classification is STRUCTURAL, never a name/phrase match ───────────────


def test_classification_is_structural_not_name_matched(monkeypatch):
    # Rename the ruleset to something that shares no substring with
    # "main-required-fast-lane": the `applied: false` marker alone must still produce
    # pending. And the shipped NAME with `applied: true` must still drift. If either
    # flipped, the suppressor would be keyed on a string, which is the #2959/#3003/#3199
    # failure mode (suppressor_rules_must_be_STRUCTURAL).
    renamed = _posture(False)
    renamed["main_required_checks_ruleset"]["name"] = "zzz-some-other-gate"
    res = _run_config(monkeypatch, renamed, rc_present=False, auto_merge=False)
    assert res["surfaces"]["main_required_checks_ruleset"]["status"] == "pending"

    named = _posture(True)
    assert named["main_required_checks_ruleset"]["name"] == "main-required-fast-lane"
    res = _run_config(monkeypatch, named, rc_present=False, auto_merge=False)
    assert res["surfaces"]["main_required_checks_ruleset"]["status"] == "drift"


def test_classifier_unit_covers_all_three_arms():
    drifted = {"status": "drift", "detail": "the ruleset is absent"}
    clean = {"status": "clean"}
    # no marker → untouched (both arms)
    assert sg._classify_declared_but_unapplied({}, False, drifted) is drifted
    assert sg._classify_declared_but_unapplied({"applied": True}, True, clean) is clean
    # marker + not live → pending
    pending = sg._classify_declared_but_unapplied({"applied": False, "blocked_on": "SOME_PAT"}, False, drifted)
    assert pending["status"] == "pending" and pending["blocked_on"] == "SOME_PAT"
    # marker + live → drift on the stale marker
    stale = sg._classify_declared_but_unapplied({"applied": False, "blocked_on": "SOME_PAT"}, True, clean)
    assert stale["status"] == "drift" and stale["stale_applied_marker"] is True
    # a marker with no blocker still reports pending, and SAYS the blocker is missing
    vague = sg._classify_declared_but_unapplied({"applied": False}, False, drifted)
    assert vague["status"] == "pending" and "add `blocked_on`" in vague["blocked_on"]


# ── the triage that consumes the sweep ────────────────────────────────────────


def _pending_record():
    return {
        "status": "clean",
        "date": "2026-08-26",
        "summary": "All clear. 1 declared-but-not-yet-applied posture surface(s) PENDING, not drift: repo_settings",
        "checks": {
            "github_config": {
                "status": "pending",
                "pending": {"main_required_checks_ruleset": "RECONCILE_PUSH_TOKEN (D0.6, #3042)"},
                "surfaces": {},
            }
        },
    }


def test_pending_never_becomes_a_needs_human_signal():
    # The concrete harm: a needs-human slot consumed three times a week by a false alarm
    # whose recommended action would break the deploy plane.
    assert drift_report.as_signal(_pending_record()) is None
    # and a record whose top-level status says drift while NO check does is also not a
    # signal — there is nothing for a human to act on.
    bogus = _pending_record()
    bogus["status"] = "drift"
    assert drift_report.as_signal(bogus) is None


def test_pending_is_rendered_on_the_report_not_silently_dropped():
    # Pending is not an alarm, but a state that neither alarms nor prints is exactly how
    # a stale marker rots unseen.
    html = drift_report.status_html(_pending_record())
    assert "main_required_checks_ruleset" in html
    assert "RECONCILE_PUSH_TOKEN" in html
    assert "not drift" in html


def test_sweep_summary_names_the_pending_surfaces():
    checks = _pending_record()["checks"]
    assert "main_required_checks_ruleset" in ds._pending_note(checks)
    assert "RECONCILE_PUSH_TOKEN" in ds._pending_note(checks)
    # rendered on a CLEAN sweep too, not only when something else is wrong
    assert "PENDING" in ds._summary("clean", checks)
    assert ds._pending_note({"github_config": {"status": "clean"}}) == ""


# ── the WRITER: the wedge is prevented where the write happens ────────────────


def _fake_gh_json(spec_name, *, rc_present, auto_merge):
    def fake(path, method="GET", payload=None):
        assert method == "GET", f"the test must never reach a mutating {method} {path}"
        if path.startswith("/users/"):
            return _OWNER_USER, None
        if path.startswith("/apps/"):
            return _GITHUB_ACTIONS_APP, None
        if path.endswith("/rulesets"):
            return ([{"id": 4242424, "name": spec_name}] if rc_present else []), None
        if "/rulesets/" in path:
            return {"id": 4242424, "name": spec_name}, None
        if path.endswith("/actions/secrets"):
            return {"secrets": []}, None
        return {"allow_auto_merge": auto_merge}, None

    return fake


def test_writer_refuses_apply_while_the_entry_is_marked_unapplied(monkeypatch, capsys):
    # THE WEDGE, STOPPED AT THE WRITER. The sweep's recommended command, run verbatim.
    monkeypatch.setattr(abp, "gh_json", _fake_gh_json("main-required-fast-lane", rc_present=False, auto_merge=False))
    rc = abp.main(["--apply"])
    err = capsys.readouterr().err
    assert rc == 2, "an `applied: false` entry must never be written"
    assert "applied: false" in err and "RECONCILE_PUSH_TOKEN" in err
    assert "Refusing to write" in err


def test_writer_check_reports_pending_not_drift(monkeypatch, capsys):
    # `--check` is the on-demand form of the sentinel leg; it gave the same bad advice.
    monkeypatch.setattr(abp, "gh_json", _fake_gh_json("main-required-fast-lane", rc_present=False, auto_merge=False))
    rc = abp.main(["--check"])
    out = capsys.readouterr()
    assert rc == 0, out
    assert "pending: declared but deliberately not yet applied" in out.out
    assert "DRIFT" not in out.err


def test_writer_check_flags_a_stale_marker_as_drift(monkeypatch, capsys):
    # The other direction at the writer: live already matches while the posture still
    # says `applied: false` → exit 1, naming the marker.
    monkeypatch.setattr(abp, "gh_json", _fake_gh_json("main-required-fast-lane", rc_present=True, auto_merge=True))
    rc = abp.main(["--check"])
    err = capsys.readouterr().err
    assert rc == 1
    assert "flip the marker" in err


def test_writer_still_applies_when_the_marker_says_applied(monkeypatch, capsys):
    # Mutation-proof the refusal is not a blanket "never write": with `applied: true`
    # and the bypass secret provisioned, --apply reaches the POST. Guarded by a fake
    # that records the mutation instead of performing it.
    posture = _posture(True)
    writes = []

    def fake(path, method="GET", payload=None):
        if method != "GET":
            writes.append((method, path))
            return {}, None
        if path.startswith("/users/"):
            return _OWNER_USER, None
        if path.startswith("/apps/"):
            return _GITHUB_ACTIONS_APP, None
        if path.endswith("/rulesets"):
            return [], None
        if path.endswith("/actions/secrets"):
            return {"secrets": [{"name": "RECONCILE_PUSH_TOKEN"}]}, None
        return {"allow_auto_merge": False}, None

    monkeypatch.setattr(abp, "load_spec", lambda path=abp.POSTURE_FILE: posture)
    monkeypatch.setattr(abp, "gh_json", fake)
    assert abp.main(["--apply"]) == 0, capsys.readouterr()
    assert ("POST", "/repos/averagejoematt/life-platform/rulesets") in writes
    assert ("PATCH", "/repos/averagejoematt/life-platform") in writes
    # the metadata keys must never be PATCHed to the repo settings endpoint
    body = json.dumps(writes)
    assert "blocked_on" not in body and "ledger_row" not in body


def test_writer_refuses_when_the_bypass_secret_cannot_be_verified(monkeypatch, capsys):
    # #3207 fail-closed: "could not read /actions/secrets" is NOT "verified present".
    # This branch used to WARN and proceed on trust — for exactly the token most
    # operators run this with.
    posture = _posture(True)

    writes = []

    def fake(path, method="GET", payload=None):
        if method != "GET":
            writes.append((method, path))
            return {}, None
        if path.startswith("/users/"):
            return _OWNER_USER, None
        if path.startswith("/apps/"):
            return _GITHUB_ACTIONS_APP, None
        if path.endswith("/rulesets"):
            return [], None
        if path.endswith("/actions/secrets"):
            return None, "gh: Resource not accessible by integration (HTTP 403)"
        return {"allow_auto_merge": False}, None

    monkeypatch.setattr(abp, "load_spec", lambda path=abp.POSTURE_FILE: posture)
    monkeypatch.setattr(abp, "gh_json", fake)
    assert abp.main(["--apply"]) == 2
    assert writes == [], "the refusal must land BEFORE any mutation"
    err = capsys.readouterr().err
    assert "could not verify" in err and "RECONCILE_PUSH_TOKEN" in err
    # …and the explicit typed override still lets a confirmed operator through — the
    # guard is fail-closed, not a dead end (a guard nobody can pass gets deleted).
    assert abp.main(["--apply", "--allow-unverified-bypass-secret"]) == 0
    assert ("POST", "/repos/averagejoematt/life-platform/rulesets") in writes


def test_bypass_actor_satisfiability_reads_the_real_workflow_wiring():
    # The wire, as shipped: ci-cd.yml's reconcile checkout must reference the secret.
    spec = sg._load_github_posture()["main_required_checks_ruleset"]
    assert abp.bypass_actor_satisfiability_problems(spec) == []


def test_bypass_actor_satisfiability_fires_when_the_token_wiring_is_gone(tmp_path, monkeypatch):
    # MUTATION: a `User` bypass whose PAT is never used by the pushing workflow can be
    # satisfied by nothing — applying it rejects the reconcile push on every merge.
    spec = copy.deepcopy(sg._load_github_posture()["main_required_checks_ruleset"])
    unwired = {"jobs": {"reconcile": {"steps": [{"uses": "actions/checkout@v7", "with": {"fetch-depth": 0}}]}}}
    monkeypatch.setattr(abp, "_load_workflow", lambda filename: unwired)
    problems = abp.bypass_actor_satisfiability_problems(spec)
    assert len(problems) == 1 and "does NOT cover" in problems[0]

    # …and a spec that declares a User bypass with no secret at all is refused too.
    spec.pop("reconcile_push_secret")
    problems = abp.bypass_actor_satisfiability_problems(spec)
    assert len(problems) == 1 and "names no `reconcile_push_secret`" in problems[0]

    # …while an Integration-only spec is out of scope, not falsely flagged.
    spec["bypass_actors"] = [{"actor_type": "Integration", "app": "github-actions"}]
    assert abp.bypass_actor_satisfiability_problems(spec) == []


# ── posture ↔ ledger agreement, and the two META-KEY lists ────────────────────


def _ledger_rows():
    with open(LEDGER) as f:
        return [line for line in f if line.startswith("| **")]


@pytest.mark.parametrize("key", ["main_required_checks_ruleset", "repo_settings"])
def test_posture_marker_and_ledger_prose_agree(key):
    """The #3207 acceptance box: the ledger's prose caveat and the posture file must
    not be able to disagree by hand.

    The posture entry names its own ledger row (`ledger_row`); the CLASSIFICATION is
    read structurally off `applied`, and only the ledger's human-facing wording is
    matched — because prose is the only thing a markdown table has."""
    entry = sg._load_github_posture()[key]
    anchor = entry.get("ledger_row")
    assert anchor, f"{key} must name its docs/MANAGED_WHERE_LEDGER.md row via `ledger_row`"
    rows = [r for r in _ledger_rows() if anchor in r]
    assert len(rows) == 1, f"`ledger_row` {anchor!r} matched {len(rows)} ledger rows — it must identify exactly one"
    says_unapplied = "NOT YET APPLIED" in rows[0]
    if entry.get("applied", True):
        assert not says_unapplied, (
            f"{key} is marked `applied: true` but its ledger row still says NOT YET APPLIED — " "flip both in the same PR (#3207)"
        )
    else:
        assert says_unapplied, (
            f"{key} is marked `applied: false` but its ledger row does not say NOT YET APPLIED — "
            "the machine-readable marker and the prose caveat have diverged (#3207)"
        )
        assert entry.get("blocked_on"), f"{key} is `applied: false` and must name its blocker in `blocked_on`"


def test_ledger_rows_claiming_unapplied_are_all_backed_by_a_marker():
    """The other direction: no GitHub ledger row may say NOT YET APPLIED in prose only.

    Scoped to the rows the posture file owns (those naming `deploy/github_posture.json`)
    — the AWS rows are covered by their own sentinels, not by this marker."""
    posture = sg._load_github_posture()
    anchored = {v.get("ledger_row") for v in posture.values() if isinstance(v, dict) and v.get("ledger_row")}
    for row in _ledger_rows():
        if "github_posture.json" not in row or "NOT YET APPLIED" not in row:
            continue
        assert any(a in row for a in anchored), (
            "a posture-owned ledger row claims NOT YET APPLIED but no posture entry's `ledger_row` "
            f"points at it — the prose would be unenforced (#3207): {row[:120]}"
        )


def test_posture_meta_keys_are_identical_in_both_tools():
    # The sentinel and the applier each hold their own copy (separate import roots).
    # A metadata key added to one only would be compared against live state — or worse,
    # PATCHed to /repos — by the other.
    assert tuple(sg._POSTURE_META_KEYS) == tuple(abp.POSTURE_META_KEYS)
    assert "applied" in abp.POSTURE_META_KEYS and "source" in abp.POSTURE_META_KEYS


def test_posture_file_documents_the_marker_rule():
    # Rule (4) of the posture file's own `_comment` block: the file is where the next
    # operator learns that `applied: false` exists at all.
    with open(sg.GITHUB_POSTURE_FILE) as f:
        comment = " ".join(json.load(f)["_comment"])
    assert "applied" in comment and "#3207" in comment
    assert re.search(r"pending", comment), "the _comment must name the `pending` state the marker produces"
