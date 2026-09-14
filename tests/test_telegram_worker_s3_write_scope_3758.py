"""tests/test_telegram_worker_s3_write_scope_3758.py — the coach worker's FIRST S3 canary.

WHY THIS FILE EXISTS AT ALL

Before #3758 the telegram worker had no `s3:PutObject` of any kind. Its only S3 grant was
`S3ConfigRead` on `config/*`, so there was no write prefix to widen and nothing to guard.
The progress-photo capture gives it one, and the rule from #3559 and again from the recap
cards is that you guard the SET, not the instance — a prefix that exists for one writer
today is a prefix any future writer will reach for.

THE GAP THIS CLOSES, NAMED

Two canaries look like they already cover this and neither does:

  * `tests/test_role_family_write_scope.py` auto-enrols the worker and reds by name on any
    DynamoDB write outside `COACH#*`. That half IS covered by construction, which is why
    this file does not re-test it — the new `USER#matthew#SOURCE#progress_photos` grant
    is the exception it already knows how to see.
  * `tests/test_raw_archive_role_parity.py` is the S3 prefix canary, and it is scoped to
    `lambdas/ingestion/`. The coach worker lives in `lambdas/coach/`, so a raw-prefix
    widen there was invisible to it — and would have stayed invisible, because a source
    writing into `raw/` from outside the ingestion package had never existed before.

So this is the S3 half, written the way `tests/test_site_api_write_scope.py` writes the
DynamoDB half: the grant must cover what the code writes, AND a new write call site in the
worker package must red until its prefix is declared. Both directions, because a canary
that only checks one is a canary that passes while the thing it watches walks out the door.
"""

import os
import re
from glob import glob

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ROLE_FAMILY = sorted(glob(os.path.join(_REPO, "cdk", "stacks", "role_policies*.py")))
_COACH = os.path.join(_REPO, "lambdas", "coach")

#: Every prefix the worker's role is allowed to write. One entry, and adding a second is
#: meant to be an argument rather than a diff — a coach chat worker with broad write
#: access to the raw zone is a different piece of software than this one.
EXPECTED_WRITE_PREFIXES = {"raw/matthew/progress_photos/*"}

#: Modules in `lambdas/coach/` that may call `put_object` at all. The canary below reds on
#: any other one, which is the "guard the SET" half: the next capture channel gets its own
#: prefix declaration here before it gets a grant.
S3_WRITERS = {"progress_capture.py"}


def _read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


def _role_src(marker):
    for path in _ROLE_FAMILY:
        text = _read(path)
        if marker in text:
            return text
    raise AssertionError(f"{marker!r} not found in any of {[os.path.basename(p) for p in _ROLE_FAMILY]}")


def _worker_policy_src():
    """The body of `telegram_worker()`, up to the next top-level def."""
    src = _role_src("def telegram_worker(")
    body = src.split("def telegram_worker(", 1)[1]
    return body.split("\ndef ", 1)[0]


def _granted_write_prefixes():
    """Every `BUCKET_ARN`-scoped resource on a statement that grants an S3 write."""
    body = _worker_policy_src()
    prefixes = set()
    for stmt in body.split("iam.PolicyStatement("):
        if "s3:PutObject" not in stmt and "s3:DeleteObject" not in stmt and "s3:*" not in stmt:
            continue
        prefixes.update(re.findall(r'BUCKET_ARN\}/([^"\']+)', stmt))
    return prefixes


# ── 1. The grant is exactly what we declared, no wider ────────────────────────
def test_the_worker_writes_exactly_the_declared_prefixes():
    granted = _granted_write_prefixes()
    assert granted == EXPECTED_WRITE_PREFIXES, (
        f"telegram_worker()'s S3 write prefixes are {sorted(granted)}, expected {sorted(EXPECTED_WRITE_PREFIXES)}. "
        "A new prefix needs a line in EXPECTED_WRITE_PREFIXES and a reason in the PR — this worker talks to a "
        "public-facing bot, so its reach into the raw zone is a security posture, not a convenience."
    )


def test_the_worker_has_no_s3_delete_and_no_wildcard():
    body = _worker_policy_src()
    assert "s3:DeleteObject" not in body, "a capture path that can delete can lose what it captured"
    assert 's3:*"' not in body and "'s3:*'" not in body, "wildcard S3 on the coach worker"
    for prefix in _granted_write_prefixes():
        assert prefix not in ("*", "raw/*", "raw/matthew/*"), f"{prefix!r} is the whole raw zone, not one source"


# ── 2. The code's write matches the grant ─────────────────────────────────────
def test_the_declared_prefix_is_the_one_the_code_actually_writes():
    """The grant and the key builder must agree, or the feature ships AccessDenied.

    This is the #3768 shape in advance: a missing or mismatched IAM grant whose only
    symptom is a caught exception and a fail-soft path. Asserted against the module's own
    constant rather than a repeated literal.
    """
    import sys

    sys.path.insert(0, os.path.join(_REPO, "lambdas"))
    from coach import progress_capture

    granted = {p.rstrip("*").rstrip("/") for p in _granted_write_prefixes()}
    assert (
        progress_capture.RAW_PREFIX in granted
    ), f"progress_capture writes under {progress_capture.RAW_PREFIX!r} but the role grants {sorted(granted)}"
    key = progress_capture.s3_key("2026-09-14", "front")
    assert key.startswith(progress_capture.RAW_PREFIX + "/"), key


def test_the_key_shape_matches_the_source_registry_facet():
    """`raw_layout` is the registry's claim about where this source writes.

    `scripts/check_raw_zone_drift.py` asserts the PREFIX is named by a facet; nothing
    asserted the leaf, which is how the facet came to say `<pose>.jpg` — a name that
    silently overwrites the first week of every month with the last.
    """
    import sys

    sys.path.insert(0, os.path.join(_REPO, "lambdas"))
    from coach import progress_capture
    from ingestion.source_registry import SOURCE_REGISTRY

    layout = SOURCE_REGISTRY["progress_photos"]["raw_layout"]
    assert layout["prefix"] == progress_capture.RAW_PREFIX
    assert layout["scheme"] == "date-tree"
    assert layout["filename"] == "YYYY-MM-DD-<pose>.jpg", (
        "the facet and the writer disagree about the leaf — one of them is wrong, and the "
        "registry is what every other reader of this source will believe"
    )

    key = progress_capture.s3_key("2026-09-14", "front")
    assert key == f"{layout['prefix']}/2026/09/2026-09-14-front.jpg"
    # Two different days in one month must be two different objects.
    assert progress_capture.s3_key("2026-09-01", "front") != progress_capture.s3_key("2026-09-28", "front")


# ── 3. The SET canary: a new writer in this package must declare itself ───────
def test_no_undeclared_s3_writer_in_the_coach_package():
    """The half `test_raw_archive_role_parity.py` cannot see, because it stops at ingestion.

    If this reds on a module you just wrote: add it to `S3_WRITERS` AND add its prefix to
    `EXPECTED_WRITE_PREFIXES` AND grant that prefix in `telegram_worker()`. All three, in
    the same PR. Two of the three is how a writer ends up with a grant nobody reviewed, or
    a review of a grant the code does not use.
    """
    offenders = []
    for path in sorted(glob(os.path.join(_COACH, "*.py"))):
        name = os.path.basename(path)
        if name in S3_WRITERS:
            continue
        src = _read(path)
        if re.search(r"\bput_object\s*\(", src):
            offenders.append(name)
    assert not offenders, f"undeclared S3 writers in lambdas/coach/: {offenders}"
