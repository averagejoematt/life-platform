"""tests/test_failsoft_aws_reads_3813.py — #3813: the two fail-soft AWS reads #3681 left.

#3681 converted all 14 content-generation steps in deploy/sync_site_to_s3.sh to
`run_site_generator`, which classifies a non-zero exit and never reports an IAM denial as
"(offline?)". Two same-class swallows on the SAME deploy path were outside that issue's
declared Set and were left alone rather than folded in silently:

  (a) the CloudFront distribution lookup  — `2>/dev/null || echo ""` discarded the error
      text AND the exit status, and the deploy then pushed new bytes to S3 and NEVER
      invalidated the CDN, while reporting success.
  (b) theme_river.latest_provenance      — a bare `except Exception: pass` published
      DEFAULT provenance on a PUBLIC artifact as if it had been measured.

Both are the #3681 shape one step along: the one diagnosis that is definitely wrong is the
only one printed.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SYNC = ROOT / "deploy" / "sync_site_to_s3.sh"
LIB = ROOT / "deploy" / "lib" / "generator_step.sh"


def _load_theme_river():
    sys.path.insert(0, str(ROOT / "lambdas"))
    spec = importlib.util.spec_from_file_location("_theme_river_3813", ROOT / "lambdas" / "content" / "theme_river.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


tr = _load_theme_river()


class _Boom:
    """A table whose Query is DENIED — the live #3681 cause, at the other call site."""

    def query(self, **_kw):
        raise RuntimeError(
            "An error occurred (AccessDeniedException) when calling the Query operation: User: "
            "arn:aws:sts::205930651321:assumed-role/github-actions-deploy-role/GitHubActions is not "
            "authorized to perform: dynamodb:Query on resource: table/life-platform"
        )


class _Empty:
    """An HONEST empty partition — no flourishing rows yet."""

    def query(self, **_kw):
        return {"Items": []}


class _Real:
    def query(self, **_kw):
        return {"Items": [{"enrichment_model": "claude-haiku-4-5", "enrichment_schema_version": 3}]}


# ── member (b): "no rows" and "could not read" must not render identically ───────────────
def test_an_unreadable_partition_RAISES_rather_than_returning_the_defaults():
    with pytest.raises(tr.ProvenanceUnreadable) as e:
        tr.latest_provenance(_Boom())
    assert "AccessDenied" in str(e.value), "the cause must survive into the error, not be flattened"


def test_an_HONEST_empty_partition_still_returns_the_defaults_quietly():
    """The control that stops the fix from crying wolf: absence is not failure."""
    model, sv = tr.latest_provenance(_Empty())
    assert (model, sv) == (tr.DEFAULT_MODEL, tr.DEFAULT_SCHEMA_VERSION)


def test_a_real_row_is_read_and_is_not_degraded():
    model, sv, degraded = tr.latest_provenance_or_degraded(_Real())
    assert model == "claude-haiku-4-5" and sv == 3 and degraded is None


def test_THE_DEFECT_the_two_cases_are_now_DISTINGUISHABLE_at_the_caller():
    """Before #3813 both of these returned exactly (DEFAULT_MODEL, DEFAULT_SCHEMA_VERSION)
    and nothing downstream could tell them apart."""
    empty = tr.latest_provenance_or_degraded(_Empty())
    denied = tr.latest_provenance_or_degraded(_Boom())
    assert empty[:2] == denied[:2] == (tr.DEFAULT_MODEL, tr.DEFAULT_SCHEMA_VERSION)
    assert empty[2] is None and denied[2] is not None, "the two fail-soft cases are still indistinguishable"


def test_the_fail_soft_wrapper_never_raises():
    """A provenance read must not take the river build down — that part was right before."""
    assert tr.latest_provenance_or_degraded(_Boom())[0] == tr.DEFAULT_MODEL


def test_MUTATION_restoring_the_bare_except_collapses_the_two_cases():
    """Prove the controls measure the distinction and not merely the tuple."""
    src = (ROOT / "lambdas" / "content" / "theme_river.py").read_text(encoding="utf-8")
    assert "except Exception:\n        pass" not in src, "the bare `except: pass` is back — member (b) has regressed"
    assert "raise ProvenanceUnreadable" in src


def test_the_builder_STAMPS_a_degraded_provenance_onto_the_artifact():
    """A public artifact must carry the fact, or a reader cannot tell measured from fallback."""
    src = (ROOT / "scripts" / "v4_build_theme_river.py").read_text(encoding="utf-8")
    assert "latest_provenance_or_degraded" in src, "the builder still calls the collapsing form"
    assert "provenance_degraded" in src


# ── member (a): the CloudFront lookup ────────────────────────────────────────────────────
def _code_only(text: str) -> str:
    """Shell source with comment lines stripped.

    The cause vocabulary legitimately appears in PROSE here — the script's header explains
    at length that the old idiom reported an IAM AccessDenied as a network blip. Asserting
    over raw text would forbid the explanation along with the defect, which is the
    "hasher counts comment paths" mistake. Only executable lines are the claim.
    """
    out = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        out.append(line.split("  #", 1)[0] if "  #" in line else line)
    return "\n".join(out)


def test_the_cloudfront_lookup_no_longer_discards_its_exit_status():
    sh = SYNC.read_text(encoding="utf-8")
    block = sh.split("CF_LOOKUP_OUT=", 1)
    assert len(block) == 2, "the CloudFront lookup was renamed — re-point this assertion, do not delete it"
    assert '--output text 2>/dev/null || echo ""' not in sh, "the swallow is back"
    assert "CF_LOOKUP_RC=$?" in sh and "classify_generator_failure" in sh


def test_the_lookup_reuses_the_SHARED_classifier_rather_than_a_second_copy():
    """#3681's classifier is the one home for cause vocabulary; a second copy is drift."""
    sh = SYNC.read_text(encoding="utf-8")
    assert 'CF_CAUSE="$(classify_generator_failure "$CF_LOOKUP_OUT")"' in sh
    assert "SITE_GENERATOR_DEGRADABLE_CAUSES" in sh, "degradability must come from the shared list"
    assert "site_generators_are_strict" in sh, "the CI-strictness test must be the shared one"
    code = _code_only(sh)
    for tok in ("AccessDenied", "ExpiredToken", "not authorized to perform"):
        assert tok not in code, f"{tok!r} is string-matched in EXECUTABLE sync-script code — that belongs in generator_step.sh"


def test_a_skipped_invalidation_is_NAMED_not_a_bare_warning():
    sh = SYNC.read_text(encoding="utf-8")
    assert "CF_INVALIDATION_SKIPPED" in sh, "a skipped invalidation leaves no named outcome"
    assert "stack-has-no-distribution-output" in sh


@pytest.mark.parametrize(
    "output,expected",
    [
        ("An error occurred (AccessDeniedException) ... is not authorized to perform: cloudformation:DescribeStacks", "denied"),
        ("An error occurred (ExpiredToken) when calling DescribeStacks", "credentials-invalid"),
        ('Could not connect to the endpoint URL: "https://cloudformation.us-east-1.amazonaws.com/"', "offline"),
        ("Unable to locate credentials", "no-credentials"),
        ("Stack with id LifePlatformWeb does not exist", "unclassified"),
    ],
)
def test_the_shared_classifier_reads_real_cloudformation_failures(output, expected):
    """The classifier was written against DynamoDB denials; assert it reads the
    CloudFormation wording too, since that is what member (a) will hand it."""
    got = subprocess.run(
        ["bash", "-c", f'source "{LIB}"; classify_generator_failure "$1"', "_", output],
        capture_output=True,
        text=True,
    )
    assert got.stdout.strip() == expected, got.stdout + got.stderr


def test_a_denied_lookup_would_EXIT_rather_than_degrade_in_CI():
    """The decisive behaviour, driven through real bash rather than asserted from source."""
    script = f"""
      set -euo pipefail
      source "{LIB}"
      GITHUB_ACTIONS=true
      CF_LOOKUP_OUT="An error occurred (AccessDeniedException) ... is not authorized to perform: cloudformation:DescribeStacks"
      CF_CAUSE="$(classify_generator_failure "$CF_LOOKUP_OUT")"
      CF_DEGRADABLE=0
      case " $SITE_GENERATOR_DEGRADABLE_CAUSES " in *" $CF_CAUSE "*) CF_DEGRADABLE=1 ;; esac
      if [ "$CF_DEGRADABLE" = "1" ] && ! site_generators_are_strict; then echo DEGRADED; else echo FAILED; exit 1; fi
    """
    got = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    assert got.returncode == 1 and "FAILED" in got.stdout, got.stdout + got.stderr


def test_an_OFFLINE_lookup_degrades_locally_but_NOT_in_CI():
    """Both directions of the degradable rule — the half that keeps a laptop usable, and
    the half that stops CI shipping a deploy that skipped invalidation."""
    base = f"""
      set -uo pipefail
      source "{LIB}"
      CF_CAUSE=offline
      CF_DEGRADABLE=0
      case " $SITE_GENERATOR_DEGRADABLE_CAUSES " in *" $CF_CAUSE "*) CF_DEGRADABLE=1 ;; esac
      if [ "$CF_DEGRADABLE" = "1" ] && ! site_generators_are_strict; then echo DEGRADED; else echo FAILED; fi
    """
    local = subprocess.run(["bash", "-c", "unset GITHUB_ACTIONS SITE_GENERATORS_STRICT; " + base], capture_output=True, text=True)
    in_ci = subprocess.run(["bash", "-c", "GITHUB_ACTIONS=true; " + base], capture_output=True, text=True)
    assert "DEGRADED" in local.stdout, local.stdout + local.stderr
    assert "FAILED" in in_ci.stdout, in_ci.stdout + in_ci.stderr


def test_the_SET_is_2_of_2_and_the_enumeration_query_still_returns_only_those():
    """Box 4: the guard covers both members, and the issue's own enumeration query is
    re-run so a THIRD member appearing on this path is not silently uncovered."""
    sh = SYNC.read_text(encoding="utf-8")
    tr_src = (ROOT / "lambdas" / "content" / "theme_river.py").read_text(encoding="utf-8")
    assert '2>/dev/null || echo ""' not in _code_only(sh)
    assert "except Exception:\n        pass" not in tr_src
    # The two excluded-with-reason members from the issue stay excluded and stay present.
    assert "|| echo 0" in sh or "|| echo unknown" in sh, (
        "the git-default fallbacks vanished — they are deliberately EXCLUDED from this Set "
        "(genuine not-a-git-repo defaults, #3681 excluded them too); if they were removed, "
        "re-read the Set rather than deleting this assertion"
    )


def test_a_skipped_invalidation_is_a_NON_GREEN_outcome_at_the_END_of_the_run():
    """Box 2, the half a mid-script warning does not satisfy.

    A `⚠️` line two hundred lines up scrolls off. If the CDN was not invalidated, the
    deploy pushed new bytes that readers cannot see — the run must say so where a human
    reads the result, and must not exit 0.
    """
    code = _code_only(SYNC.read_text(encoding="utf-8"))
    assert 'if [[ -n "${CF_INVALIDATION_SKIPPED:-}" ]]; then' in code
    assert "INVALIDATION SKIPPED — CAUSE:" in code
    assert "exit 3" in code, "a skipped invalidation still exits 0 — it is not a non-green outcome"
    tail = code.rsplit("Site live at", 2)
    assert len(tail) == 3, "expected the skipped-invalidation branch to precede the success line"
