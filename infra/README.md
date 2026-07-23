# infra/

IAM policy/trust JSON snapshots for the GitHub-Actions OIDC roles (`infra/iam/`). **Kept,
load-bearing:** these are the committed audit record of the deploy / diagnosis / remediation
/ golden-eval roles and the OIDC provider — the reference the CI role wiring is checked
against. Live AWS IAM is still CDK-owned (`cdk/stacks/`); this dir is the reviewable
snapshot, not a second source of truth. See `infra/iam/README.md`.
