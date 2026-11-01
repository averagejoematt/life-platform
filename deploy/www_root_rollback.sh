#!/usr/bin/env bash
# deploy/www_root_rollback.sh — the v9 root deploy's auto-rollback decision + action (#5534).
#
# Runs in web-preview-deploy.yml's `rollback-v9-on-failure` job after a ROOT deploy whose smoke or
# visual sweep went red. Mirrors site-deploy.yml's #3352/#3395 scope check: only an EXPLICIT
# `false` from a sweep's reachability verdict declines (an `api`, `deploy-script` or
# `ai-unevaluated` red is not something a v9 revert can change — restoring the previous build
# would hide the new one while the real defect stayed live); an absent verdict rolls back.
#
# The rollback itself is `deploy/www_preview_sync.sh --target root --restore-previous`: the last
# green root build from s3://matthew-life-platform/site/_v9_previous/ copied back over the root,
# S3 → S3, no delete, v9-owned keys only — it structurally cannot re-publish the v8 front page or
# touch a kept site/ page. On the first root deploy there is no previous build; the restore says so
# and nothing is written (www/README.md names the owner's deliberate un-launch).
#
# Env (from the workflow): SITE_REACHABLE QA_SURFACES QA_SUMMARY (visual-qa) · SMOKE_REACHABLE
# SMOKE_SURFACES SMOKE_SUMMARY (smoke) · SNS_TOPIC_ARN AWS_REGION RUN_URL GITHUB_SHA · GATE.
# Writes declined=true|false (+ surfaces/verdict) to $GITHUB_OUTPUT when set. Always exits 0 once it
# has decided — a second failure mode here would only give the rollback a new way not to happen.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
SHORT="${GITHUB_SHA:0:7}"
RUN_URL="${RUN_URL:-}"

out() { [ -n "${GITHUB_OUTPUT:-}" ] && printf '%s\n' "$@" >> "$GITHUB_OUTPUT"; return 0; }
notify() {
  local subject="$1" message="$2"
  if [ -n "${SNS_TOPIC_ARN:-}" ]; then
    aws sns publish --topic-arn "$SNS_TOPIC_ARN" --subject "$subject" --message "$message" --region "${AWS_REGION:-us-west-2}" \
      || echo "::warning::SNS publish failed — the rollback decision above still stands"
  fi
}

echo "v9 root rollback scope check (#3352 visual / #3395 smoke, applied to the v9 paths):"
echo "  visual-qa: site_reachable='${SITE_REACHABLE:-<unset>}' surfaces='${QA_SURFACES:-<none>}'  ${QA_SUMMARY:-<no verdict recorded>}"
echo "  smoke:     site_reachable='${SMOKE_REACHABLE:-<unset>}' surfaces='${SMOKE_SURFACES:-<none>}'  ${SMOKE_SUMMARY:-<no verdict recorded>}"

if [ "${SITE_REACHABLE:-}" = "false" ] || [ "${SMOKE_REACHABLE:-}" = "false" ]; then
  SURFACES=""
  VERDICT=""
  [ "${SITE_REACHABLE:-}" = "false" ] && { SURFACES="visual-qa[${QA_SURFACES:-?}]"; VERDICT="visual-qa: ${QA_SUMMARY:-<no summary>}"; }
  [ "${SMOKE_REACHABLE:-}" = "false" ] && { SURFACES="${SURFACES}${SURFACES:+ }smoke[${SMOKE_SURFACES:-?}]"; VERDICT="${VERDICT}${VERDICT:+ · }smoke: ${SMOKE_SUMMARY:-<no summary>}"; }
  echo "⛔ v9 ROLLBACK DECLINED — the failing surface is not one a v9 revert can reach: ${SURFACES}"
  echo "::warning title=v9 root rollback DECLINED (#5534)::${VERDICT}"
  out "declined=true" "surfaces=${SURFACES}" "verdict=${VERDICT}"
  notify "Life Platform v9 ROOT ROLLBACK DECLINED [$SHORT]" "v9 root deploy $SHORT: a post-deploy sweep failed (${GATE:-?}) on a surface a v9 revert cannot reach — NOTHING WAS REVERTED.
Surfaces: ${SURFACES}
Verdict:  ${VERDICT}
The v9 build is still live at /. Diagnose the named surface; do not re-deploy blindly.
Run: ${RUN_URL}"
  exit 0
fi

echo "⚠️  a post-deploy sweep failed on a v9-reachable surface — restoring the previous v9 build (never site/)"
if bash "$HERE/www_preview_sync.sh" --target root --restore-previous; then
  RESULT="restored the previous v9 build from s3://matthew-life-platform/site/_v9_previous/ (or reported that none exists yet)"
else
  RESULT="RESTORE FAILED (exit $?) — the root may be a mixed build; run: bash deploy/www_preview_sync.sh --target root --restore-previous"
fi
out "declined=false"
notify "Life Platform v9 ROOT AUTO-ROLLBACK [$SHORT]" "v9 root deploy $SHORT: a post-deploy sweep failed (${GATE:-?}) — ${RESULT}.
The site/ tree was NOT touched (one owner per path, #5534). Verify https://averagejoematt.com/
Run: ${RUN_URL}"
echo "✅ v9 rollback step finished: ${RESULT}"
