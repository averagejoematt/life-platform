"""Guard: restart_leadin_repair.backup_record must not crash formatting its notes.

LOCAL_BACKUP_DIR is intentionally `/tmp/leadin_backups` (outside the repo — the
pre-repair originals are unvetted and must never be committed). The note-formatting
lines used `local.relative_to(REPO_ROOT)`, which raises ValueError for ANY path not
under the repo — i.e. every real run — aborting the live-DDB content repair mid-way
(after the local backup was written, before the S3 backup + the DDB write). This is a
pre-existing bug from #943, surfaced closing #1219 (whose editor's-note fix ships via
this same repair path). Non-vacuous: the pre-fix `.relative_to(REPO_ROOT)` call raises
on the /tmp LOCAL_BACKUP_DIR asserted below.
"""

import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "deploy"))

import restart_leadin_repair as rlr  # noqa: E402


class _StubS3:
    """Minimal S3 stub: the backup object already exists (head_object succeeds), so
    backup_record takes the 'kept' branches and never mutates anything."""

    def head_object(self, Bucket, Key):  # noqa: N803 — boto3 kwarg names
        return {"ContentLength": 1}


def test_local_backup_dir_is_outside_the_repo():
    # The precondition that made the old `.relative_to(REPO_ROOT)` raise on every run.
    assert not str(rlr.LOCAL_BACKUP_DIR).startswith(str(rlr.REPO_ROOT)), (
        "LOCAL_BACKUP_DIR must stay outside the repo (unvetted originals); "
        "if it moves in-repo, the relative_to display would be valid again."
    )


def test_backup_record_notes_do_not_raise_for_tmp_backup_dir():
    # apply=False (dry-run) exercises the note formatting that previously raised
    # ValueError via local.relative_to(REPO_ROOT) for the /tmp LOCAL_BACKUP_DIR.
    notes = rlr.backup_record("DATE#2026-02-28", {"pk": {"S": "x"}}, _StubS3(), apply=False)
    assert notes and any("backup" in n for n in notes)
    # The absolute /tmp path is surfaced honestly (not a repo-relative path).
    assert any(str(rlr.LOCAL_BACKUP_DIR) in n for n in notes)
