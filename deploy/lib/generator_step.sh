#!/usr/bin/env bash
# deploy/lib/generator_step.sh — #3681: a site generator step that names WHY it failed.
#
# THE DEFECT THIS REPLACES
# -----------------------
# Every content-generation step in `deploy/sync_site_to_s3.sh` was spelled
#
#     python3 .../scripts/v4_build_<thing>.py || echo "  ⚠️  <thing> build skipped (offline?) — keeping existing <artifact>"
#
# `|| echo` turns EVERY non-zero exit into exit 0 and one sentence, and that sentence
# names a cause nobody measured. On 2026-09-07 the theme-river step printed
# `(offline?)` over this, in the `Deploy public site` job of run 34144388209:
#
#     botocore.exceptions.ClientError: An error occurred (AccessDeniedException) when
#     calling the Query operation: User: arn:aws:sts::205930651321:assumed-role/
#     github-actions-deploy-role/GitHubActions is not authorized to perform:
#     dynamodb:Query on resource: arn:aws:dynamodb:us-west-2:205930651321:table/
#     life-platform because no identity-based policy allows the dynamodb:Query action
#
# The runner had a network. It had credentials. It had an IAM misconfiguration that
# recurs on every single invocation and NEVER self-heals — the #3563 / G-3 class, on
# the deploy path instead of inside a Lambda. The step exited 0, the deploy went
# green, and `https://averagejoematt.com/data/theme_river.json` shipped
# `{"state": "empty"}` for the entire life of the feature. "(offline?)" was the one
# diagnosis that was definitely wrong and it was the only one printed.
#
# THE RULE
# --------
# A non-zero exit is a failure until a RECOGNISED benign cause is read out of the
# generator's own output. The degradable set is an allowlist of two causes that a
# deploy genuinely cannot do anything about — no network path, and no credentials at
# all — and it is honoured ONLY outside CI. In CI nothing degrades: a deploy is not
# green when it shipped a stale artifact it was asked to regenerate.
#
#   denied              IAM refused. FAILS. Never prints "offline".
#   credentials-invalid expired/bad token. FAILS — a deploy with dead creds is not a deploy.
#   unclassified        anything else (a TypeError, a bad schema, a missing file). FAILS.
#   offline             no network path to the live source. Degrades locally, FAILS in CI.
#   no-credentials      no AWS identity at all (`--live` run from a laptop). Same.
#
# `classify_generator_failure` is a pure text function on purpose: it is the thing worth
# testing, and tests/test_sync_site_generator_steps_3681.py drives it with the VERBATIM
# denial above (fixture: tests/fixtures/generator_step/real_failure_output_3681.json)
# rather than a paraphrase, so "the classifier still recognises what the platform
# actually prints" is asserted against the wire.
#
# Usage (sourced by deploy/sync_site_to_s3.sh):
#
#     run_site_generator "<label>" "<artifact kept on degrade>" <command> [args...]
#
# Under the caller's `set -e`, a failing step aborts the sync at that line. That is
# the point.

# Exported so the sync script and the tests read the same names.
SITE_GENERATOR_DEGRADABLE_CAUSES="offline no-credentials"

# Classify a generator's combined stdout+stderr. Echoes exactly one cause token.
#
# Order is load-bearing: a denial is checked FIRST. An AWS denial message can contain
# almost any other word (resource arns, retry chatter from botocore), and misreading a
# denial as something benign is the entire defect this file exists for.
classify_generator_failure() {
  local text="$1"

  case "$text" in
    *"not authorized to perform"* | *"AccessDenied"* | *"UnauthorizedOperation"* | \
      *"explicit deny"* | *"AuthorizationError"* | *"is not authorized to"* | \
      *"User is not authorized"* | *"no identity-based policy allows"*)
      echo "denied"
      return 0
      ;;
  esac

  case "$text" in
    *"ExpiredToken"* | *"InvalidClientTokenId"* | *"SignatureDoesNotMatch"* | \
      *"security token included in the request is expired"* | *"InvalidAccessKeyId"*)
      echo "credentials-invalid"
      return 0
      ;;
  esac

  case "$text" in
    *"NoCredentialsError"* | *"Unable to locate credentials"* | \
      *"PartialCredentialsError"* | *"NoRegionError"*)
      echo "no-credentials"
      return 0
      ;;
  esac

  case "$text" in
    *"EndpointConnectionError"* | *"ConnectTimeoutError"* | *"ReadTimeoutError"* | \
      *"ConnectionError"* | *"Temporary failure in name resolution"* | \
      *"Name or service not known"* | *"nodename nor servname"* | \
      *"Network is unreachable"* | *"Connection refused"* | *"Connection reset by peer"* | \
      *"Max retries exceeded"* | *"urlopen error"* | *"getaddrinfo"* | \
      *"Could not connect to the endpoint URL"*)
      echo "offline"
      return 0
      ;;
  esac

  echo "unclassified"
}

# True when this run may NOT degrade — CI, or an explicit local strict request.
# A deploy in CI is the deploy; nothing it was asked to regenerate may be skipped.
site_generators_are_strict() {
  [ -n "${GITHUB_ACTIONS:-}" ] || [ "${SITE_GENERATORS_STRICT:-0}" = "1" ]
}

run_site_generator() {
  local label="$1"
  local artifact="$2"
  shift 2

  local out rc
  # `if` context suspends errexit, so a non-zero exit reaches `rc` instead of
  # aborting here with the output still trapped inside the substitution.
  if out="$("$@" 2>&1)"; then
    rc=0
  else
    rc=$?
  fi

  # The generator's own output is ALWAYS relayed — success or failure. The old idiom
  # discarded nothing, but it buried the traceback under a one-line verdict that
  # contradicted it.
  [ -n "$out" ] && printf '%s\n' "$out"

  if [ "$rc" -eq 0 ]; then
    return 0
  fi

  local cause
  cause="$(classify_generator_failure "$out")"

  local degradable=0
  case " $SITE_GENERATOR_DEGRADABLE_CAUSES " in
    *" $cause "*) degradable=1 ;;
  esac

  if [ "$degradable" = "1" ] && ! site_generators_are_strict; then
    echo "  ⚠️  ${label} build skipped — CAUSE: ${cause} (exit ${rc}); keeping existing ${artifact}."
    echo "      This degrade is allowed OUTSIDE CI only. In CI it is a failure."
    return 0
  fi

  {
    echo "⛔ ${label} build FAILED — CAUSE: ${cause} (exit ${rc}). ${artifact} was NOT regenerated."
    case "$cause" in
      denied)
        echo "   An IAM permission was DENIED. This is a misconfiguration, not a blip: it"
        echo "   recurs on every run and never self-heals. Widen the identity that runs this"
        echo "   deploy (infra/iam/github-actions-deploy-role.permissions.json for CI —"
        echo "   Bucket B, #2611), then re-run. See #3681."
        ;;
      credentials-invalid)
        echo "   The AWS credentials were rejected (expired or wrong). Re-authenticate; a"
        echo "   deploy running without a usable identity is not a deploy."
        ;;
      offline | no-credentials)
        echo "   This cause degrades outside CI, but this run is STRICT (GITHUB_ACTIONS or"
        echo "   SITE_GENERATORS_STRICT=1). A deploy is not green when it shipped a stale"
        echo "   artifact it was asked to regenerate."
        ;;
      *)
        echo "   The failure did not match any known benign cause, so it is treated as real."
        echo "   The generator's full output is above. If this IS a benign class, add it to"
        echo "   classify_generator_failure in deploy/lib/generator_step.sh with the reason."
        ;;
    esac
    echo "   Step: ${label}  ·  Command: $*"
  } >&2

  return 1
}
