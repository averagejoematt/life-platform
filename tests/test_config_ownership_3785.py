"""tests/test_config_ownership_3785.py — #3785: every `config/` object has ONE ruling,
and a generated one carries no committed twin.

THE INCIDENT THIS PINS
──────────────────────
`config/hevy_template_index.json` is rebuilt daily at 13:40Z by
`lambdas/training/hevy_template_index.py` and published to S3. The repo ALSO carried a
June-1 copy of it — 789 templates against the live 820 — and `site-deploy.yml`'s config
twin sync uploaded that copy over the live catalogue on three separate deploys
(2026-09-14 16:43Z, 2026-09-14 18:13Z, 2026-09-15 17:47Z, each ~1m35s after its run
started; the 09-15 job log reads `🔴 DRIFT config/hevy_template_index.json` /
`uploaded: 2` at 17:47:57.9Z against an S3 version written at 17:47:58Z). `draft_custom`
then resolved exercise titles against 789 of 820 templates until the next 13:40Z rebuild
silently repaired it.

WHY THE EXISTING CHECKS COULD NOT SEE IT, IN ONE LINE EACH
──────────────────────────────────────────────────────────
* the twin-drift check COMPARED the two copies — and while the clobber was live they
  AGREED (789 == 789), nine green runs;
* the CloudWatch dead-man watched the PRODUCER's emit — which was firing perfectly;
* the shrink guard in `rebuild()` compares against S3 — 789 -> 820 is growth, so the
  repair was allowed and the whole window closed itself;
* `config_twin_registry`'s AST writer scan looks for a `config/` key passed to a boto3
  write call — the producer injects its put function (`put_json_fn(INDEX_KEY, payload)`),
  so the scan never saw a writer and called the generated index an ordinary twin.

Four checks that miss for four different reasons is the argument for a RULING rather than
a fifth derivation: `deploy/config_ownership_audit.py` writes down who owns each subject,
and everything derivable is cross-checked against it here so the two cannot drift apart.

THE MUTATION CONTROL
────────────────────
`test_MUTATION_restoring_the_committed_twin_reds_the_audit` re-creates the incident's
precondition in the REAL tree — the generated key gets a repo file again — and watches
three things go red: the audit's `stale-twin` finding, the key's exclusion from the twin
set, and the sync's refusal at the `put_object` call. It asserts its own plant took
effect (md5 before != md5 after) BEFORE reading any verdict, because a mutation that
silently did nothing produces a green that looks exactly like a working guard. It runs
`serial` and is registered in `tests/test_suite_parallel_safety_3025.py::IN_TREE_WRITERS`:
the plant lands in the real `config/` tree, which every rglob sweep in the suite reads.
"""

from __future__ import annotations

import hashlib
import pathlib
import sys

import pytest

_REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "deploy"))

import config_ownership_audit as own  # noqa: E402
import config_provenance_audit as prov  # noqa: E402
import config_twin_registry as twins  # noqa: E402
import config_twin_sync as sync  # noqa: E402

pytestmark = pytest.mark.serial  # plants into the real config/ tree — see the docstring

INDEX_KEY = "config/hevy_template_index.json"


def _md5_or_absent(path: pathlib.Path) -> str:
    """The file's md5, or a sentinel naming its absence. Absence is a state, not an error."""
    if not path.exists():
        return "ABSENT"
    # usedforsecurity=False: this is a CHANGE DETECTOR for the mutation control, not a
    # credential hash — ruff's S324 is right about md5 and irrelevant to this use.
    return hashlib.md5(path.read_bytes(), usedforsecurity=False).hexdigest()


def _codes(findings, code):
    return [f for f in findings if f["code"] == code]


# ─────────────────────────────────────────────────────────────────────────────
# Box 1 — one registry, and it covers the whole tree
# ─────────────────────────────────────────────────────────────────────────────


def test_every_config_json_on_disk_is_ruled():
    """No file in `config/` may be uncovered — a subject with no ruling is a subject
    whose deploy behaviour is decided by convention, which is the defect."""
    found = own.findings(str(_REPO))
    unruled = _codes(found, "unruled-file")
    assert not unruled, "config/ files with no ownership ruling: " + ", ".join(f["subject"] for f in unruled)


def test_the_walk_is_not_vacuous():
    """A registry that rules an empty set passes every other test in this file."""
    on_disk = own.config_json_files(str(_REPO))
    assert len(on_disk) >= 24, f"the config/ walk found only {len(on_disk)} json files — it is broken, not the tree empty"


def test_the_real_tree_audit_is_clean():
    """The audit's own verdict over the real repo, so a finding of ANY code reds here."""
    fails = [f for f in own.findings(str(_REPO)) if f["severity"] == "fail"]
    assert not fails, "\n".join(f"{f['code']}: {f['subject']} — {f['detail']}" for f in fails)


def test_an_unruled_subject_is_not_uploadable():
    """Fail closed. A `config/` name nobody has ruled must not be pushable — the window
    between adding a generated artifact and classifying it is exactly when it is loaded."""
    assert own.owner_of("config/a_file_nobody_ruled_3785.json") == own.UNKNOWN
    assert own.uploadable("config/a_file_nobody_ruled_3785.json") is False


def test_a_directory_ruling_covers_its_members_by_longest_prefix():
    ruling = own.ruling_for("config/coaches/sleep_coach.json")
    assert ruling is not None and ruling.subject == "config/coaches/"
    assert ruling.owner == own.HAND_OWNED
    assert own.uploadable("config/coaches/sleep_coach.json") is True


def test_an_empty_tree_is_a_finding_not_a_pass(tmp_path):
    """The vacuity guard: `findings()` over a tree with no config/ must say so loudly."""
    found = own.findings(str(tmp_path))
    assert _codes(found, "vacuous-walk"), f"an empty config/ walk reported {found} instead of a broken-derivation finding"


# ─────────────────────────────────────────────────────────────────────────────
# Box 2 — the generated artifacts carry no committed twin
# ─────────────────────────────────────────────────────────────────────────────


def test_the_generated_index_is_ruled_generated_and_absent_from_the_repo():
    ruling = own.ruling_for(INDEX_KEY)
    assert ruling is not None and ruling.owner == own.RUNTIME_GENERATED
    assert ruling.producer == "lambdas/training/hevy_template_index.py:INDEX_KEY"
    assert own.uploadable(INDEX_KEY) is False
    assert not (_REPO / INDEX_KEY).exists(), (
        "the generated Hevy template index is back in the repo. It is a stale print of live state and the config "
        "twin sync will push it over the live catalogue on the next site deploy (#3785)."
    )


def test_no_runtime_generated_subject_has_a_committed_twin():
    """The SET, not the specimen: the same invariant for every generated ruling."""
    present = [r.subject for r in own.RULINGS if r.owner == own.RUNTIME_GENERATED and (_REPO / r.subject).exists()]
    assert not present, f"generated artifacts with a committed twin (delete them; repair live by re-running the producer): {present}"


def test_the_twin_set_holds_out_every_not_uploadable_key():
    registry = twins.derive(str(_REPO))
    leaked = [t.key for t in registry.twins if not own.uploadable(t.key)]
    assert not leaked, f"not-uploadable keys are in the deploy path: {leaked}"


def test_a_checkout_that_HAS_the_generated_twin_still_never_deploys_it(tmp_path):
    """The POSITIVE proof of the exclusion leg, and it has to be a fixture.

    Once the twin is deleted from the repo, the real-tree assertion above is true over an
    EMPTY population — it would stay green with the exclusion ripped out. So the leg is
    proved against a checkout that does carry the file: the same ruled key, a consumer
    reading it, and the answer must still be "not a twin, and say why". That is the state
    the repo was in for three months and the one a careless `git revert` would restore.
    """
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "hevy_template_index.json").write_text('{"count": 789, "templates": {}}')
    (tmp_path / "config" / "training_week.json").write_text('{"_version": 1}')
    (tmp_path / "mcp").mkdir()
    (tmp_path / "mcp" / "fake_reader.py").write_text(
        "import boto3\n"
        's3 = boto3.client("s3")\n'
        "def go():\n"
        '    s3.get_object(Bucket="b", Key="config/hevy_template_index.json")\n'
        '    return s3.get_object(Bucket="b", Key="config/training_week.json")\n'
    )

    registry = twins.derive(str(tmp_path))

    assert INDEX_KEY not in registry.by_key(), "the generated index joined the deploy path of a checkout that carries it"
    assert registry.not_uploadable.get(INDEX_KEY) == own.RUNTIME_GENERATED, (
        "the exclusion must be RECORDED, not silent — a file dropped without a reason is how the twin set got "
        f"this wrong in the first place. not_uploadable={registry.not_uploadable}"
    )
    # …and the hand-owned sibling in the same fixture still deploys, so this is an
    # ownership decision and not a blanket refusal.
    assert "config/training_week.json" in registry.by_key()


def test_runtime_written_keys_are_ruled_generated_too():
    """Cross-check against the OTHER derivation. `config_twin_registry` finds keys written
    through a boto3 call; anything it finds must be ruled generated here, or the two
    answers to 'who owns this' disagree and the registry is the one that would be believed."""
    registry = twins.derive(str(_REPO))
    assert registry.runtime_written, "the writer scan found no runtime-written config key at all — it is broken"
    disagreement = {key: own.owner_of(key) for key in registry.runtime_written if own.owner_of(key) != own.RUNTIME_GENERATED}
    assert not disagreement, f"written at runtime but not ruled runtime_generated: {disagreement}"


def test_the_producer_scan_enrols_the_next_generated_artifact():
    """#3785's SET guard, shared with the provenance audit: a module that declares a
    `config/` key AND stamps `_built_at` is generated by construction, so a new one reds
    this audit until somebody rules it rather than waiting to be noticed."""
    derived = prov.declared_generated(str(_REPO))
    assert derived, "the producer scan returned nothing — a broken derivation, not an empty generated set"
    assert INDEX_KEY in derived
    unruled = {key: own.owner_of(key) for key in derived if own.owner_of(key) != own.RUNTIME_GENERATED}
    assert not unruled, f"producers declare these generated keys, but the registry rules them otherwise: {unruled}"


# ─────────────────────────────────────────────────────────────────────────────
# The deploy path refuses, at the mutation itself
# ─────────────────────────────────────────────────────────────────────────────


class _RecordingS3:
    """Records put_object calls. Never touches AWS — a real upload here would be the bug."""

    def __init__(self):
        self.puts = []

    def put_object(self, **kwargs):
        self.puts.append(kwargs["Key"])
        return {}


def test_apply_sync_refuses_a_generated_key_even_when_handed_one(tmp_path):
    """Defence in depth. `derive()` already drops the key, so this proves the SECOND stop:
    a caller that assembles its own twin list (a script, a future workflow step, a test)
    still cannot upload a generated artifact."""
    repo_copy = tmp_path / "hevy_template_index.json"
    repo_copy.write_text('{"count": 789}')
    twin = twins.Twin(key=INDEX_KEY, repo_path=str(repo_copy), consumers=("mcp/hevy_resolution.py",))
    s3 = _RecordingS3()

    actions = sync.apply_sync({"drifted": [INDEX_KEY]}, [twin], s3)

    assert s3.puts == [], f"the sync uploaded a generated artifact: {s3.puts}"
    assert actions["refused"] == [{"key": INDEX_KEY, "owner": own.RUNTIME_GENERATED}]
    assert actions["uploaded"] == []


def test_apply_sync_still_uploads_a_hand_owned_key(tmp_path):
    """The other arm — a refusal that refuses everything is not a guard, it is an outage."""
    repo_copy = tmp_path / "training_week.json"
    repo_copy.write_text('{"_version": 1}')
    twin = twins.Twin(key="config/training_week.json", repo_path=str(repo_copy), consumers=("lambdas/training/routine_generator.py",))
    s3 = _RecordingS3()

    actions = sync.apply_sync({"drifted": ["config/training_week.json"]}, [twin], s3)

    assert s3.puts == ["config/training_week.json"]
    assert actions["refused"] == []


# ─────────────────────────────────────────────────────────────────────────────
# THE MUTATION CONTROL — the incident's precondition, planted in the real tree
# ─────────────────────────────────────────────────────────────────────────────


def test_MUTATION_restoring_the_committed_twin_reds_the_audit():
    """Plant the defect that caused the incident: the generated key gets a repo file again.

    Watched in three places, with the plant's own effect asserted first. BASELINE green ->
    MUTATED red -> REVERTED green, because a red with no green on either side proves
    nothing about which state the guard is reading.
    """
    target = _REPO / INDEX_KEY
    before = _md5_or_absent(target)
    assert before == "ABSENT", "baseline is already dirty — the generated twin is in the tree before this test planted it"
    assert not _codes(own.findings(str(_REPO)), "stale-twin"), "BASELINE is already red; a mutation verdict would mean nothing"

    try:
        target.write_text('{"_comment": "#3785 mutation control — a stale committed twin", "count": 789, "templates": {}}\n')
        after = _md5_or_absent(target)
        assert after != before, f"the plant changed nothing (md5 {before} -> {after}) — the verdict below would be meaningless"

        # 1. the audit names it
        stale = _codes(own.findings(str(_REPO)), "stale-twin")
        assert [f["subject"] for f in stale] == [INDEX_KEY], f"audit did not red on the restored twin: {own.findings(str(_REPO))}"

        # 2. the twin set still holds it out, and SAYS so rather than dropping it quietly
        registry = twins.derive(str(_REPO))
        assert INDEX_KEY not in registry.by_key()
        # (it is only in `not_uploadable` once git tracks it; the audit above is the
        # check that fires on an untracked plant, which is itself the point — a file
        # does not have to be committed to be uploadable by hand.)

        # 3. the sync refuses the upload
        s3 = _RecordingS3()
        twin = twins.Twin(key=INDEX_KEY, repo_path=str(target), consumers=())
        actions = sync.apply_sync({"drifted": [INDEX_KEY]}, [twin], s3)
        assert s3.puts == []
        assert actions["refused"] == [{"key": INDEX_KEY, "owner": own.RUNTIME_GENERATED}]
    finally:
        target.unlink(missing_ok=True)

    assert _md5_or_absent(target) == before, "the plant leaked — the tree is not back to its baseline state"
    assert not _codes(own.findings(str(_REPO)), "stale-twin"), "REVERTED is still red — the guard is not reading the tree"
