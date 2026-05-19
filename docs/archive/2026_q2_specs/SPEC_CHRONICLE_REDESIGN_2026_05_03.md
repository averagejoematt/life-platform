# SPEC: Chronicle Namespace Redesign — Single Canonical Front Door

**ID:** SPEC_CHRONICLE_REDESIGN_2026_05_03
**Author:** Matthew + Claude (Opus)
**Date:** 2026-05-03
**Type:** Site architecture refactor + publisher rewrite
**Estimated effort for Claude Code:** 2–4 hours
**Predecessor:** PR-1 (`deploy/pr1_register_architecture_of_absence_2026_05_03.py`) — bandaid that registered Issue 5 in chronicle/posts.json. Run that first; this spec is the proper redesign.

---

## 1. Problem Statement

The site currently has THREE parallel namespaces serving Elena Voss's chronicle, all out of sync:

| Namespace | Index | Posts directory | Schema |
|---|---|---|---|
| `/chronicle/` | `site/chronicle/posts.json` | `site/chronicle/posts/week-XX/` | Front-door per the current design |
| `/journal/` | `site/journal/posts.json` (auto-generated to `s3://…/generated/journal/posts.json`) | `site/journal/posts/week-XX/` (S3: `generated/journal/posts/week-XX/`) | Pre-rename leftover; some entries point here from chronicle/posts.json |
| `/blog/` | `s3://…/blog/index.html` (no local source) | `s3://…/blog/week-NN.html` (no local source) | Where `wednesday_chronicle_lambda.publish_to_blog()` writes |

**Symptoms:**
- Issue 5 ("The Architecture of Absence") was published 2026-05-03 to `/blog/` and `/journal/` but invisible at `/chronicle/` because `chronicle/posts.json` was never touched. PR-1 registered it as a stopgap.
- Week-numbering uses a confusing convention: prequels count backward (week=-4, -3, -1), then a week=0 prologue, then Season 1 jumps to week=5 (skipping 1-4 because those slots were week-minus-1 / -3 / -4 / 0 / etc.). New readers can't grok it without explainer text.
- Local `site/chronicle/posts/week-01/` and `week-04/` are redirect stubs to `/chronicle/`. Local `site/journal/posts/week-04/` redirects to `/chronicle/posts/week-04/` which redirects to `/chronicle/`. Forensic mess.
- `wednesday_chronicle_lambda` writes directly to S3 without updating the local repo. Any time it publishes, local and S3 diverge.

**Root cause:** historical accretion. The journal namespace was renamed to chronicle, but the publishers (`wednesday_chronicle_lambda.publish_to_blog`, `publish_to_journal`) still write to `/blog/` and `/journal/`. The rename was a UI swap, not an architecture migration.

---

## 2. Goals

1. **One canonical namespace:** `/chronicle/`.
2. **Sequential issue numbering:** `1, 2, 3, …` — no week numbers, no prequel gaps, no special-edition tricks. Special editions and pauses don't break the sequence.
3. **One canonical URL pattern:** `/chronicle/NN-slug/` where `NN` is zero-padded issue number and `slug` is title-cased-kebab.
4. **One canonical index:** `site/chronicle/posts.json` with the new schema.
5. **Old URLs redirect to new canonical URLs.** Nothing 404s.
6. **Publisher rewrite:** future chronicles publish to the canonical namespace only, write local files first (so local always = S3), and update `chronicle/posts.json` atomically.
7. **Every published chronicle has a local file.** Local repo = source of truth; S3 = derivative.

## 3. Non-Goals

- Changing the look of individual chronicle posts. The serif-amber template stays as-is.
- Migrating the DDB partition. Keep `pk = USER#matthew#SOURCE#chronicle, sk = DATE#YYYY-MM-DD` exactly as today. Add an `issue_number` field to records during migration.
- Touching the Wednesday email sender. (It's already paused; restart is out of scope here.)
- Touching `/journal/` content that isn't Elena's chronicle. Confirm there is none — the namespace is exclusively chronicle artifacts.

---

## 4. Final State (After This Spec Lands)

### 4a. Canonical URLs

| Issue | Title | Date | Canonical URL |
|---|---|---|---|
| 1 | Before the Numbers | 2026-02-22 | `/chronicle/01-before-the-numbers/` |
| 2 | The Empty Journal | 2026-03-03 | `/chronicle/02-the-empty-journal/` |
| 3 | The DoorDash Chronicle | 2026-03-11 | `/chronicle/03-the-doordash-chronicle/` |
| 4 | The Interview | 2026-04-01 | `/chronicle/04-the-interview/` |
| 5 | The Architecture of Absence | 2026-05-03 | `/chronicle/05-the-architecture-of-absence/` |

Issue 1 = oldest published piece, regardless of phase. Phase becomes a tag, not a numbering convention.

### 4b. Redirects

ALL of these redirect (HTML meta-refresh + canonical link, matching the existing redirect-stub pattern at `site/chronicle/posts/week-01/index.html`) to the canonical URL:

| Old URL | → Redirects to |
|---|---|
| `/chronicle/posts/week-00/` | `/chronicle/01-before-the-numbers/` |
| `/chronicle/posts/week-02/` | `/chronicle/02-the-empty-journal/` |
| `/chronicle/posts/week-03/` | `/chronicle/03-the-doordash-chronicle/` |
| `/chronicle/posts/interview/` | `/chronicle/04-the-interview/` |
| `/chronicle/posts/issue-05/` | `/chronicle/05-the-architecture-of-absence/` (PR-1's URL gets retired) |
| `/chronicle/posts/week-01/` | `/chronicle/` (already a redirect; keep) |
| `/chronicle/posts/week-04/` | `/chronicle/` (already a redirect; keep) |
| `/journal/posts/week-00/` | `/chronicle/01-before-the-numbers/` |
| `/journal/posts/week-02/` | `/chronicle/02-the-empty-journal/` |
| `/journal/posts/week-03/` | `/chronicle/03-the-doordash-chronicle/` |
| `/journal/posts/week-minus-1/` | `/chronicle/04-the-interview/` |
| `/journal/posts/week-04/` | `/chronicle/` |
| `/journal/posts/week-05/` | `/chronicle/05-the-architecture-of-absence/` |
| `/journal/` | `/chronicle/` |
| `/journal/posts.json` | (delete; nothing should fetch it after publisher rewrite) |
| `/blog/week-05.html` | `/chronicle/05-the-architecture-of-absence/` |
| `/blog/index.html` | `/chronicle/` |
| `/blog/` | `/chronicle/` |

### 4c. New `site/chronicle/posts.json` schema

```json
{
  "schema_version": 2,
  "issues": [
    {
      "number": 5,
      "slug": "the-architecture-of-absence",
      "title": "The Architecture of Absence",
      "kicker": "Special Edition",
      "date": "2026-05-03",
      "url": "/chronicle/05-the-architecture-of-absence/",
      "excerpt": "...",
      "word_count": 1423,
      "phase": "season_1",
      "context_line": "Days off-grid: 19 · April experiments: 5 of 5 failed · Re-entry: May 4, 2026",
      "badges": ["Special Edition"],
      "has_board_interview": false
    }
    // ... newest first ...
  ],
  "experiment_start": "2026-04-01",
  "updated_at": "..."
}
```

Schema changes from v1:
- Top-level key `posts` → `issues`.
- Per-issue `week` → `number` (sequential, never resets).
- New `slug` field (slug of the URL path, useful for templating).
- New `kicker` field for above-title labels (e.g. "Special Edition", "Prequel", or "" for regular issues).
- `stats_line` → `context_line` (more accurate).
- Loose `phase` enum: `prequel`, `season_1`, …
- Bump `schema_version` so the index template can branch if needed.

### 4d. New publisher

`wednesday_chronicle_lambda.publish_to_blog()` and `publish_to_journal()` are deleted and replaced with a single `publish_to_chronicle()` that:

1. Computes next issue number from `chronicle/posts.json` (max(number) + 1, or 1 if empty).
2. Computes slug from title: lowercase, strip non-alphanumeric except hyphens, collapse whitespace to single hyphens, max 60 chars.
3. Renders the post HTML using a new `lambdas/templates/chronicle_post.html.jinja2` (or in-Python template — pick one and document) and writes it to:
   - **Local repo**: `site/chronicle/NN-slug/index.html` (committed via the script's caller, NOT the Lambda)
   - **S3**: `s3://matthew-life-platform/chronicle/NN-slug/index.html`
4. Updates `site/chronicle/posts.json` (local) and writes the same JSON to `s3://…/chronicle/posts.json`.
5. Invalidates `/chronicle/*` only — not `/blog/*` or `/journal/*` (those don't change at publish time anymore).

**Important:** the Lambda CANNOT modify the local repo. So for Lambda-driven Wednesday publishing, the Lambda writes to S3 only. We accept divergence between S3 and local for Lambda-published issues, with a reconciliation script (`deploy/reconcile_chronicle_local_from_s3.py`) that fetches missing issues from S3 and writes them locally. Run weekly by Matthew, or as a pre-commit hook in `.github/workflows`.

For human-driven publishing (special editions like Issue 5), use a new `deploy/publish_chronicle_special_edition.py` that writes locally THEN syncs to S3 — keeping local=S3 invariant.

### 4e. Index page (`site/chronicle/index.html`)

Update the `fetch('/chronicle/posts.json').then(...)` block to:
- Read `data.issues` (not `data.posts`).
- Use `issue.number`, `issue.kicker`, `issue.context_line` instead of `week`, `stats_line`.
- Hero post = `issues[0]` (newest, since they're sorted newest-first in JSON).
- Group archive by `phase` (same as today).
- "Issue N" displayed prominently; "Week" never appears in chronicle UI.

### 4f. Archive page (`site/chronicle/archive/index.html`)

Same schema migration as 4e.

### 4g. RSS feed (`site/rss.xml`)

Regenerated to include all 5 issues with new canonical URLs as `<link>` and `<guid>`. Keep the `<guid isPermaLink="false">` of existing items stable (so existing subscribers don't see duplicates) — set them to `chronicle:issue-1`, `chronicle:issue-2`, etc.

### 4h. Sitemap (`site/sitemap.xml`)

Regenerated. Old `week-XX` URLs removed (since they're redirects). Only canonical URLs listed.

---

## 5. Migration Plan (Single Atomic Run)

Because every old URL needs a redirect AND `posts.json` needs the new schema AND the index template needs the new field names, this MUST land as one atomic change. Half-applied state breaks the site.

### 5.1. Pre-flight (Claude Code reads, doesn't change)

1. Confirm `site/chronicle/posts/week-00/index.html`, `week-02/index.html`, `week-03/index.html`, `interview/index.html` exist and are readable. (These are the source HTML for issues 1, 2, 3, 4.)
2. Confirm `docs/elena_special_edition_chronicle_2026_05_03.md` exists. (Source for issue 5.)
3. Run PR-1 (`python3 deploy/pr1_register_architecture_of_absence_2026_05_03.py --apply`) if it hasn't been run yet, so `site/chronicle/posts/issue-05/index.html` exists.
4. Run `git status` — abort if dirty (refuse to migrate over uncommitted work).

### 5.2. Build the migration script: `deploy/migrate_chronicle_namespace_2026_05_xx.py`

Single script, two modes (`--dry-run` default, `--apply`). Idempotent. Does the following in this order:

**Step 1: Plan.**
Build the migration plan in memory: list of `(old_path, new_path, action)` tuples covering every file that needs to move/copy/delete. Print the plan in dry-run mode and abort. Only proceed if `--apply`.

**Step 2: Copy old post HTML to new canonical paths.**
For each issue 1-5:
- Read the existing post HTML from its current `site/chronicle/posts/<old-slug>/index.html`.
- Update the `<link rel="canonical">` and any internal references to point at the new URL.
- Update the kicker / series text in the HTML so `Week 0` / `Week -4` etc. is replaced with `Issue N` (and `Special Edition · Issue 5` for issue 5).
- Write to `site/chronicle/NN-slug/index.html`.

**Step 3: Replace old paths with redirect stubs.**
For each old path in the redirect table (4b above), write a redirect stub HTML using this template:

```html
<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8">
<meta http-equiv="refresh" content="0; url={CANONICAL_URL}">
<link rel="canonical" href="https://averagejoematt.com{CANONICAL_URL}">
<title>Redirecting — The Measured Life</title>
</head><body>
<p>This installment has moved to <a href="{CANONICAL_URL}">{CANONICAL_URL}</a>.</p>
</body></html>
```

This includes creating local `site/blog/week-05.html`, `site/blog/index.html`, `site/blog/` as redirects (these don't exist locally today; create them so the local repo represents the full deployed state).

**Step 4: Rewrite `site/chronicle/posts.json` to v2 schema.**
Read the existing `posts.json`, transform every entry to the new schema, sort by `number` descending, write back.

Mapping table (deterministic):

| Old `week` | Old `url` | New `number` | New `slug` |
|---|---|---|---|
| 0 | /chronicle/posts/week-00/ | 1 | before-the-numbers |
| -4 | /chronicle/posts/week-02/ | 2 | the-empty-journal |
| -3 | /chronicle/posts/week-03/ | 3 | the-doordash-chronicle |
| -1 | /chronicle/posts/interview/ | 4 | the-interview |
| 5 | /chronicle/posts/issue-05/ | 5 | the-architecture-of-absence |

`kicker` for issues 1-4 = `"Prequel"`; for issue 5 = `"Special Edition"`. `phase` for 1-4 = `"prequel"`; for 5 = `"season_1"`.

**Step 5: Update `site/chronicle/index.html` and `site/chronicle/archive/index.html`.**
Replace the JS that consumes `data.posts` with code that consumes `data.issues`, using new field names. Use `issue.number` everywhere `week` appeared. Display "Issue N" prefix, not "Week N". Update the explainer prose at the bottom of `index.html` ("Prequel chronicles count backward...") — replace with a sentence describing sequential issue numbering.

**Step 6: Regenerate RSS + sitemap.**
- `site/rss.xml`: 5 `<item>` entries, newest first, with new canonical URLs in `<link>` and stable `<guid>` strings (e.g. `chronicle:issue-1`).
- `site/sitemap.xml`: replace any `<url>` entry referencing `/chronicle/posts/`, `/journal/`, or `/blog/` with the canonical `/chronicle/NN-slug/` equivalents.

**Step 7: Delete `site/journal/posts.json`.**
After this, nothing local should reference it. (Lambda will be updated separately to stop writing it; for now it'll keep writing to S3 but no client fetches it.)

**Step 8: Print the deploy commands.**
The script does NOT execute deploys. It prints:
```
LOCAL MIGRATION COMPLETE. To deploy:

  cd ~/Documents/Claude/life-platform
  bash deploy/sync_site_to_s3.sh
  aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE \\
    --paths '/chronicle/*' '/journal/*' '/blog/*' '/rss.xml' '/sitemap.xml'

Then verify each canonical URL returns 200 and each old URL returns a redirect.
```

### 5.3. Lambda publisher rewrite — `lambdas/wednesday_chronicle_lambda.py`

Reduce surface area to the chronicle namespace:

1. **Delete** `publish_to_blog()` entirely.
2. **Delete** `publish_to_journal()` entirely.
3. **Add** `publish_to_chronicle(...)` that:
   - Computes next issue number by reading `s3://matthew-life-platform/chronicle/posts.json`. (DDB scan as fallback if the JSON is missing.)
   - Generates slug from title (use the same algorithm as the migration script — extract to a `slugify()` helper in `lambdas/lib/chronicle.py` so both share it).
   - Renders post HTML to `s3://matthew-life-platform/chronicle/NN-slug/index.html`.
   - Updates `s3://matthew-life-platform/chronicle/posts.json` (read-modify-write; accept last-write-wins because Wednesday publishing is single-threaded).
   - CloudFront invalidates `/chronicle/*` only.
4. **Update** the orchestrator (`lambda_handler`) to call `publish_to_chronicle()` instead of the two deleted functions.
5. **Update** `deploy/publish_special_edition_chronicle_2026_05_03.py` (and any future special-edition scripts) to use `publish_to_chronicle()` too — but with a `local_first=True` flag that writes to the local repo BEFORE pushing to S3.

### 5.4. Reconciliation script — `deploy/reconcile_chronicle_local_from_s3.py`

For the case where the Lambda publishes a Wednesday chronicle (writing only to S3) and Matthew wants the local repo to catch up:

```
Usage: python3 deploy/reconcile_chronicle_local_from_s3.py [--apply]

Compares s3://matthew-life-platform/chronicle/ to site/chronicle/.
For any S3 object not present locally:
  - Downloads it to the corresponding local path.
For any local file not in S3:
  - Reports it as "local only" (does NOT delete; that's a manual decision).
For any divergence:
  - Reports the diff; manual resolution.

In --apply mode: performs downloads. Never deletes anything.
```

Recommend running this after every Wednesday publish, or as a pre-commit hook on the next session start.

---

## 6. Testing & Verification

### 6.1. Local tests (run by Claude Code before declaring done)

1. Run `python3 deploy/migrate_chronicle_namespace_2026_05_xx.py --dry-run` and read the plan output for sanity. Should list ~20 file operations.
2. Run with `--apply`.
3. Verify `site/chronicle/posts.json` is valid JSON, has `schema_version: 2`, has 5 issues numbered 1-5.
4. Verify each `site/chronicle/NN-slug/index.html` exists and contains the canonical URL in its `<link rel="canonical">`.
5. Verify each redirect stub exists at every old URL listed in 4b and contains the correct `meta http-equiv="refresh"`.
6. Run `python3 -c "import json; json.load(open('site/chronicle/posts.json'))"` — must succeed.
7. HTML well-formedness check on every chronicle file — use Python's `html.parser` to verify balanced tags. (Not strict validation; just unclosed-tag detection.)
8. `grep -r "data.posts" site/chronicle/` — must return zero matches (everything migrated to `data.issues`).
9. `grep -rE "Week (-?[0-9]|0)" site/chronicle/` — must return zero matches in the canonical (non-redirect) HTML files. Old-style "Week N" strings only OK inside redirect stubs.

### 6.2. Live tests (after Matthew runs the deploy)

1. `curl -s -o /dev/null -w "%{http_code}" https://averagejoematt.com/chronicle/01-before-the-numbers/` → 200 (×5, one per issue)
2. `curl -s -L -o /dev/null -w "%{url_effective}" https://averagejoematt.com/chronicle/posts/week-00/` → final URL ends in `/01-before-the-numbers/`
3. Same redirect test for every old URL in 4b.
4. Browser: open `/chronicle/`, confirm 5 issues listed newest-first, hero is Issue 5 with "Special Edition" kicker, no "Week N" text anywhere except in archive grouping labels.
5. Browser: open `/chronicle/05-the-architecture-of-absence/` directly, confirm it renders.
6. RSS reader / `curl https://averagejoematt.com/rss.xml | head -50` — confirm 5 items, newest first.

### 6.3. Rollback

The migration script also writes a backup of every modified file into `archive/chronicle_migration_backup_YYYY-MM-DD/`. To rollback:

```
git revert <migration-commit>
bash deploy/sync_site_to_s3.sh
aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE --paths '/*'
```

Lambda rollback: revert `lambdas/wednesday_chronicle_lambda.py` and redeploy via `bash deploy/deploy_lambda.sh wednesday-chronicle`.

---

## 7. Documentation Updates

After the migration lands, update:

- `CHANGELOG.md` — entry for the redesign.
- `docs/ARCHITECTURE.md` — chronicle section, replace any reference to `/journal/` or `/blog/` with `/chronicle/NN-slug/`.
- `docs/SCHEMA.md` — add `schema_version: 2` for `chronicle/posts.json` and document the new field names. Note that DDB schema is unchanged.
- `docs/RUNBOOK_REENTRY.md` (if it covers chronicle publishing) — update commands.
- `handovers/HANDOVER_LATEST.md` — promote this redesign to the headline carry-forward item.

---

## 8. Acceptance Criteria

- [ ] Single canonical URL pattern: `/chronicle/NN-slug/`. Every issue lives at this pattern.
- [ ] Sequential numbering 1, 2, 3, 4, 5 with no gaps and no week-number references in any UI surface.
- [ ] All 12+ legacy URLs (full list in §4b) redirect to canonical with HTML meta-refresh.
- [ ] `site/chronicle/posts.json` is schema_version 2 with `issues` (not `posts`) array.
- [ ] `site/chronicle/index.html` and `archive/index.html` consume the new schema and render correctly.
- [ ] RSS and sitemap regenerated; no broken or stale URLs.
- [ ] `wednesday_chronicle_lambda.py` no longer references `/blog/` or `/journal/`. Single `publish_to_chronicle()` function.
- [ ] Reconciliation script `deploy/reconcile_chronicle_local_from_s3.py` exists and is documented.
- [ ] All §6.1 local tests pass.
- [ ] All §6.2 live tests pass after Matthew runs the deploy.
- [ ] Rollback path documented and tested (at least the git-revert step).

---

## 9. Out of Scope (Tracked for Later)

- Restarting the Wednesday publishing cadence. Currently paused; un-pausing is its own decision.
- Migrating DDB to use `issue_number` as the partition key instead of date. Not needed; date-keyed access is fine and `issue_number` can be a derived attribute.
- A `next/previous` issue link between chronicle posts (currently each post just links back to the archive). Nice-to-have, but adds template complexity.
- Updating the Wednesday email body template to use canonical URLs. Will need doing before email cadence resumes.

---

## 10. Handoff Note for Claude Code

When you pick this up:

1. Start by reading `handovers/HANDOVER_LATEST.md` for current state.
2. Confirm PR-1 has been applied (i.e., `site/chronicle/posts/issue-05/index.html` exists). If not, run it first.
3. Read this entire spec end-to-end before writing code.
4. Build `deploy/migrate_chronicle_namespace_2026_05_xx.py` (replace `xx` with the day you run it). Make it idempotent.
5. Run `--dry-run` first and show Matthew the plan output before `--apply`.
6. After `--apply`, do the §6.1 local tests yourself and report results.
7. Do NOT run `bash deploy/sync_site_to_s3.sh` — Matthew runs deploys.
8. Update the Lambda (§5.3) in a separate commit from the site migration. Easier to roll back independently.
9. Close out with a handover summarizing what changed, what's verified, and what Matthew needs to do (deploy + Lambda redeploy + verify §6.2).
