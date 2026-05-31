# V2 site consolidation — rollback runbook

**Source brief:** `~/Desktop/BRIEF_claude_code_v2_consolidation.md` (2026-05-31)
**Pre-consolidation rollback floor:** tag `site-v1` (pushed to origin 2026-05-31).
**Working branch:** `redesign/v2-consolidation`.
**Active path chosen:** **Plan B** (branch-only, no live preview prefix).

---

## Why Plan B, not the live `/v2/` preview

Priya's hard condition in the brief: if the CloudFront-Function preview prefix (rewrite `/v2/*` → S3 `site-v2/*` + basic-auth gate + `noindex` headers) exceeds ~half a day, **stop and use Plan B instead**.

Realistic estimate for the preview path on this codebase:

- CDK addition: new S3 origin for `site-v2/` prefix, new cache behavior for `/v2/*`, CloudFront Function for basic auth (~30-60 min + the deploy).
- Robots/noindex layer for the preview prefix.
- Initial sync + smoke test.
- Documentation for promotion + rollback.

Probably 2-4 hours. Doable, but on a one-user platform with a "build for Matthew first, polish later" cadence, **local preview** during the work + a clean branch + a fast rollback story is enough. Upgrading to the live `/v2/` preview is a 2-hour follow-up if Matthew later wants to share a URL with reviewers before promotion.

---

## How to preview v2 changes during the work

```bash
# Serve site/ locally with python's built-in server
cd ~/Documents/Claude/life-platform/site
python3 -m http.server 8000
# → http://localhost:8000/observatory/, etc.
```

The static pages render correctly locally because they're plain HTML. Anything that hits `/api/*` will not work locally (CORS + no Lambda), but layout, nav, and content can be verified locally without infrastructure.

---

## Promotion runbook — v2 → production

When Matthew has reviewed the consolidation locally and signed off:

```bash
# 1. Verify v2 branch is up to date with main (no main-only commits left behind)
git checkout redesign/v2-consolidation
git fetch origin
git diff origin/main..HEAD --stat   # review the full v2 delta

# 2. Run the full test suite + a syntax check
python3 -m pytest tests/ --ignore=tests/test_integration_aws.py -q
flake8 lambdas/ mcp/ --select=E9,F63,F7,F82

# 3. Merge to main (squash or merge; either is fine)
git checkout main
git merge --no-ff redesign/v2-consolidation -m "v2 site consolidation: ~44 → ~13 destinations"

# 4. Push, then deploy static + invalidate CloudFront
git push origin main
bash deploy/sync_site_to_s3.sh

# 5. Smoke test the live site:
curl -sI https://averagejoematt.com/observatory/ | head -1   # expect 200
curl -sI https://averagejoematt.com/sleep/        | head -1   # expect 200 (sub-page still live per "keep sub-pages for rollback")
curl -sI https://averagejoematt.com/the-ai/       | head -1   # expect 301 (folded into How It Works)
```

---

## Rollback runbook — undo the promotion

If anything looks wrong after promotion, the rollback is fast and total because `site-v1` is the immutable floor:

```bash
# 1. Check out the pre-consolidation tag
git checkout site-v1

# 2. Push v1 site back to S3 (no --delete; only re-uploads v1 files)
bash deploy/sync_site_to_s3.sh

# 3. ORPHAN CLEANUP — v2-only routes that no longer exist in v1 will still
#    have stale objects under s3://matthew-life-platform/site/<new-route>/
#    Plan B trade-off: we have to identify these manually.
#
#    The list of v2-introduced routes is in this file's "v2-only routes"
#    section, kept current by each consolidation stage commit.
#    To clean an orphan route (tombstone-overwrite, never hard delete):
#      aws s3 cp /dev/null s3://matthew-life-platform/site/<route>/index.html
#    (creates a 0-byte tombstone matching ADR-032 IAM pattern).

# 4. CloudFront invalidation (handled by sync_site_to_s3.sh, verify):
aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE --paths '/*'
```

After step 2 + 4, the live site is identical to the pre-consolidation state.

---

## v2-only routes (orphan-cleanup index)

Each consolidation stage adds entries here. On rollback, the routes listed
below MUST be tombstoned (Step 3 above) — they don't exist in v1 and would
otherwise 404 on the live site.

**Stage 1 (Observatory hub, 2026-05-31):**
  - `/observatory/index.html` — new hub. On rollback, tombstone:
    `aws s3 cp /dev/null s3://matthew-life-platform/site/observatory/index.html`

*(Stage 1 only adds the hub route. All 8 dispatch sub-pages remain live at their original URLs per the brief's "keep sub-pages for rollback" call.)*

**Stage 2 (How It Works absorbs explainers, 2026-05-31):**
Three explainer pages folded into /platform/ as anchored sections. Originals
archived to site/archive/v1/, and the original routes now serve a meta-refresh
redirect to the anchor. On rollback, NO orphan cleanup needed — these routes
already existed in v1; the redirect HTML just replaces the original index.
  - `/intelligence/index.html` (redirect) — v1 original archived at
    `site/archive/v1/intelligence/`. `git checkout site-v1` restores the
    original full content.
  - `/board/index.html`         (redirect) — original at `site/archive/v1/board/`.
  - `/coaches/index.html`       (redirect) — original at `site/archive/v1/coaches/`.
  - `/character/index.html`     — the long methodology essay block was replaced
    with a pointer to /methodology/. Character-specific scoring mechanics
    ("THE MATH" details block) stay. Rollback via `git checkout site-v1`.
  - `/platform/index.html`      — three new sections (`#the-ai`, `#ai-board`,
    `#coaching-team`) added. Rollback via `git checkout site-v1`.

---

## Stage status

- [x] **Stage 0** — tag `site-v1` + branch `redesign/v2-consolidation` + this runbook (2026-05-31)
- [x] **Stage 1** — Observatory hub at `/observatory/`; nav collapsed 8 dispatches → 1 entry (2026-05-31)
- [x] **Stage 2** — How It Works absorbs The AI + AI Board + Coaching Team; Character methodology dup pointed at standalone /methodology/ (2026-05-31)
- [ ] Stage 3 — Supplement + weekly dedupe + footer cleanup
- [ ] Stage 4 — ~13-spine nav rebuild + final verification

Each stage commits to `redesign/v2-consolidation`. Nothing lands on `main`
until Matthew reviews the full consolidation locally and signs off.
