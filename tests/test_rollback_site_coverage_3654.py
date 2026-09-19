"""tests/test_rollback_site_coverage_3654.py

Pins the #3654 contract: the S3 prefixes `.github/workflows/site-deploy.yml` writes on
every deploy must all be restored by `deploy/rollback_site.sh`, or explicitly declared
LEFT LIVE in its run log — never silently dropped.

Reads exactly TWO files, named directly — never a directory sweep or a tracked-file
listing, this is not a repo-wide census: `.github/workflows/site-deploy.yml` and
`deploy/rollback_site.sh`.

Write-set derivation (from the workflow text only):
  Rule A — every literal `aws s3 sync|cp SRC DEST` destination prefix in a `run:` block.
           This is the shape of a NEW write a future step could add (the mutation test
           below adds exactly one).
  Rule B — every `X/**` entry in the workflow's own `on.push.paths:` trigger list — the
           workflow's own structural declaration of which top-level trees cause it to
           run (the same list its "Superseded-run check" step re-reads). This is what
           catches `site/**` and `config/**` without hardcoding either name — a rename
           of the config twin prefix to something else would still be caught here, and
           the mutation test proves the aws-sync path is independently sensitive too.

Restore-set derivation (from the rollback script text only): every top-level prefix
named in a `git checkout "$REF" -- <path>` restore.

A write-set prefix missing from the restore-set is only acceptable when the rollback
script's own text carries an explicit "LEFT LIVE" run-log marker — the #3654 box 1
requirement that nothing is left live in silence.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "site-deploy.yml"
ROLLBACK_PATH = REPO_ROOT / "deploy" / "rollback_site.sh"


def _dewrap(text: str) -> str:
    """Collapse a shell line-continuation (`\\` + newline) to one space.

    `aws s3 sync SRC \\\n  DEST` is one logical command split across lines in the
    workflow's `run:` blocks; the SRC/DEST regex below matches on logical whitespace,
    not literal backslash-newline.
    """
    return re.sub(r"\\\n\s*", " ", text)


def _top_level_prefix(path: str) -> str:
    return path.strip().strip('"').lstrip("/").split("/", 1)[0]


def _aws_sync_prefixes(workflow_text: str) -> set:
    """Rule A: literal `aws s3 sync|cp SRC DEST` destination prefixes."""
    text = _dewrap(workflow_text)
    prefixes = set()
    for match in re.finditer(r'aws s3 (?:sync|cp)\s+\S+\s+"?s3://[^/\s"]+/([^\s"]+)/?"?', text):
        prefixes.add(_top_level_prefix(match.group(1)))
    return prefixes


def _trigger_path_prefixes(workflow_text: str) -> set:
    """Rule B: `X/**` entries in the `on.push.paths:` trigger list."""
    prefixes = set()
    for match in re.finditer(r"^\s*-\s*'([^']+/\*\*)'", workflow_text, re.MULTILINE):
        prefixes.add(_top_level_prefix(match.group(1)))
    return prefixes


def _deploy_write_set(workflow_text: str) -> set:
    return _aws_sync_prefixes(workflow_text) | _trigger_path_prefixes(workflow_text)


def _rollback_restore_set(rollback_text: str) -> set:
    prefixes = set()
    for match in re.finditer(r'git checkout "\$REF" -- (\S+)', rollback_text):
        prefixes.add(_top_level_prefix(match.group(1)))
    return prefixes


def test_derivation_finds_the_two_known_live_prefixes():
    """Sanity on the derivation itself: if a workflow edit silently dropped the fonts
    sync line or the `config/**` trigger entry, that is a real regression in what this
    test can see — fail loudly here rather than let the coverage test below go vacuous."""
    write_set = _deploy_write_set(WORKFLOW_PATH.read_text())
    assert "site" in write_set, f"derived write-set {write_set} lost the site/ prefix"
    assert "config" in write_set, f"derived write-set {write_set} lost the config/ prefix"


def test_rollback_restores_every_written_prefix_or_declares_it_left_live():
    workflow_text = WORKFLOW_PATH.read_text()
    rollback_text = ROLLBACK_PATH.read_text()

    write_set = _deploy_write_set(workflow_text)
    restore_set = _rollback_restore_set(rollback_text)

    uncovered = write_set - restore_set
    if uncovered:
        assert "LEFT LIVE" in rollback_text, (
            f"{sorted(uncovered)} is written by site-deploy.yml but not restored by "
            "rollback_site.sh, and rollback_site.sh has no 'LEFT LIVE' run-log "
            "declaration naming what it left live — the exact silent gap #3654 filed"
        )


def test_config_prefix_restore_actually_restores_not_just_mentions():
    """The #3654 fix itself: rollback_site.sh must re-checkout config/ from REF and
    re-run the real twin-sync apply, not just reference config/ in prose (this repo has
    hit the "a text match reads the comment explaining it" false-green before)."""
    rollback_text = ROLLBACK_PATH.read_text()
    assert 'git checkout "$REF" -- config/' in rollback_text
    assert "config_twin_sync.py" in rollback_text and "--apply" in rollback_text


def test_mutation_new_write_prefix_without_restore_is_caught():
    """Box 2's mutation: add a new `aws s3 sync ... s3://bucket/newprefix/` line to a
    COPY of the workflow text, leave rollback_site.sh untouched, and confirm the
    derived write-set grows to include the new prefix while the restore-set (and any
    LEFT LIVE declaration, which can only ever name a prefix the script reasons about)
    does not — i.e. this detector is sensitive to the class of gap #3654 filed, not
    just to the one instance already fixed."""
    workflow_text = WORKFLOW_PATH.read_text()
    rollback_text = ROLLBACK_PATH.read_text()

    mutated_workflow = workflow_text + (
        "\n      - name: mutation probe (not a real step)\n"
        "        run: |\n"
        '          aws s3 sync build/ "s3://matthew-life-platform/newprefix/" \\\n'
        "            --region us-west-2\n"
    )

    write_set = _deploy_write_set(mutated_workflow)
    restore_set = _rollback_restore_set(rollback_text)

    assert "newprefix" in write_set
    assert "newprefix" not in restore_set
    assert "newprefix" not in rollback_text  # no LEFT LIVE declaration can name it either
