<!--
Lightweight PR template (#1663). Keep the body freeform What/Why — this scaffold
is a checklist, not a form. Delete any line that doesn't apply.
Supersedes the 2026-05 template retired in #1324 (whose Backfill/Lambda-parity
checkbox went unused in 0/20 merged PRs); this one keeps only what every PR needs.
-->

## What & why

<!-- 1–3 sentences: what changed and the reason. -->

Fixes #<!-- issue number -->

## Checklist

- [ ] `black` + `flake8` clean on any changed Python (line-length 140; never run `black` on `.json`)
- [ ] Targeted `pytest` for what I touched passes locally
- [ ] Conventional-commit title (`feat|fix|chore|docs|refactor|test|ci|build|perf|style(scope): …`)
- [ ] **Docs:** updated the affected page(s) **OR** none needed (one-clause reason: …)
- [ ] Shared code stays **one bundle, no layer** (#781) — I did not reintroduce a Lambda layer for shared modules

## Deploy / ops notes

<!--
What has to happen AFTER merge, if anything. Merge alone is not prod.
 - Lambda code:   bash deploy/deploy_lambda.sh <fn> <src>   (full-tree bundle, #781)
 - Site (site/**): auto-deploys on merge via .github/workflows/site-deploy.yml
 - Infra (cdk/):   needs `cdk deploy <Stack>` from main (owner-run)
 - None:           additive/docs-only, nothing to deploy
-->
