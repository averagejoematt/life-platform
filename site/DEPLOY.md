# site/DEPLOY.md — pointer only

> **Status:** pointer shell · **Verified:** 2026-07-10
> The pre-v4 guide that lived here (platform/, character/, journal/posts/TEMPLATE.html —
> none of which exist anymore) is gone; git history has it if you're curious.

- The site is **v4 "The Measured Life"** (ADR-071) — static S3 + CloudFront, no framework.
- **Authoring guide (add/change a page, generated-vs-hand-authored, the hashing trap):**
  `docs/SITE_AUTHORING.md`
- **Deploy is automatic on merge to main** touching `site/**` —
  `.github/workflows/site-deploy.yml` (sync + fonts + smoke/visual-QA gates + auto-rollback).
- Attended fallback + safety rules: `docs/CONVENTIONS.md` + `deploy/sync_site_to_s3.sh`.
