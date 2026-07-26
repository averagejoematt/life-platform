# Syndication Runbooks — token rotation + post recall

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-07-25

Last updated: 2026-07-25 (#1630 — written BEFORE the first automated post, per the ADR-140
requirement and the R22 precedent (#893): "how do I delete a bad post and rotate a leaked
token" must be a document, not a 2am improvisation.)

**Scope:** the social syndication surface governed by **ADR-140** (`docs/DECISIONS.md`) —
the Phase 0 manual script (`scripts/post_social.py`, #1622), the gated Bluesky poster
(#1629, unbuilt), and the Phase 2 X channel (explicitly not built — see ADR-140 rule 4).
Covers **Bluesky** (the staged `life-platform/bluesky` credential) and, prospectively, **X**.

## What exists today vs. what ships with #1629

Honesty note (`reference_docs_current_truth_only`) — this runbook is deliberately written
*before* the poster, so it names what is live now vs. pre-staged:

| Thing | State (2026-07-25) |
|---|---|
| `life-platform/bluesky` secret (handle + **scoped app password**, AT Protocol `createSession`) | **LIVE** — created 2026-07-25, createSession-validated. App password only, never the account password (#1629 non-negotiable 10) |
| `scripts/post_social.py` Phase 0 manual poster | Gated on owner trial (#1622) |
| The syndication lambda (`lambdas/syndication/`) | **Unbuilt** — #1629, gated on Phase 0 hitting ≥15/30 days |
| SSM `/life-platform/syndication-mode` (`off \| shadow \| live`) | **Does not exist yet** — ships with #1629; until then there is no automated poster to switch off |
| `life-platform/bluesky` in the freshness checker's `MANUAL_ROTATION_SECRETS` (`lambdas/emails/freshness_checker_lambda.py`) | **Not yet listed** — add the entry in the #1629 PR so staleness alerting starts when the consumer does |
| `life-platform/x` secret / X developer-portal app | **Does not exist** — Phase 2 is do-not-build until the ADR-063 per-post-spend amendment is signed |

---

## Runbook 1 — Rotate a syndication token (routine or leaked)

### Bluesky — routine rotation

The credential is a **scoped app password** (Bluesky → Settings → Privacy and Security →
App Passwords). Rotation is create-new → update secret → revoke-old, in that order, so
there is no gap for the (future) poster's scheduled runs:

1. Create a new app password: bsky.app (or the app) → **Settings → Privacy and Security →
   App Passwords → Add App Password**. Name it with the date (e.g. `life-platform-2026-07`).
2. Update Secrets Manager (keep the existing JSON shape — handle + app password fields;
   read the current shape first, change only the password value):
   ```bash
   aws secretsmanager get-secret-value --secret-id life-platform/bluesky \
     --region us-west-2 --query SecretString --output text   # note the field names
   aws secretsmanager put-secret-value --secret-id life-platform/bluesky \
     --region us-west-2 --secret-string '<same JSON, new app password>'
   ```
3. Verify the new credential authenticates (safe, read-only session create):
   ```bash
   curl -s https://bsky.social/xrpc/com.atproto.server.createSession \
     -H 'Content-Type: application/json' \
     -d '{"identifier":"<handle>","password":"<new app password>"}' | head -c 200
   ```
4. **Revoke the old app password** in the same Settings screen (delete it — revocation is
   immediate at the source).
5. Consumers pick up the new value within ~15 min via the `secret_cache.py` TTL; no
   redeploy needed (force one only if you can't wait).

Cadence: 180 days, or immediately on any suspicion. Inventory row: `docs/SECRETS_ROTATION.md`.

### Bluesky — LEAKED token (the 2am path; order matters)

1. **Revoke at the source FIRST — phone-operable, no AWS needed:** Bluesky app →
   Settings → Privacy and Security → App Passwords → delete the leaked app password.
   Every session created with it dies immediately. Do this before anything else; a
   leaked app password can post *as you*.
2. **Kill the poster** (once #1629 exists): set SSM `/life-platform/syndication-mode`
   → `off` (phone-operable by ADR-140 rule 3 — AWS Console mobile app, or the laptop
   command below). Today, with no poster built, step 1 alone stops all writing.
   ```bash
   aws ssm put-parameter --name /life-platform/syndication-mode --value off \
     --type String --overwrite --region us-west-2
   ```
3. **Audit for abuse:**
   - The Bluesky profile timeline — any post you did not make → Runbook 2 for each.
   - CloudTrail for secret reads:
     ```bash
     aws cloudtrail lookup-events --region us-west-2 --lookup-attributes \
       AttributeKey=ResourceName,AttributeValue=life-platform/bluesky \
       --start-time $(date -u -v-30d +%Y-%m-%dT%H:%M:%S)
     ```
4. **Re-issue:** follow the routine-rotation steps above (new app password → put-secret-value → verify).
5. **Record it:** one row in `docs/INCIDENT_LOG.md` (what leaked, exposure window, posts
   made, response times) — the R22/#893 handling was good *because* it was written down.

### X (Phase 2 — prospective; do not build the channel yet)

No `life-platform/x` secret exists and none may be created until the ADR-063 amendment
for third-party per-post spend is signed (ADR-140 rule 4). When Phase 2 is sanctioned,
the same shape applies: revoke/regenerate the app's tokens in the X developer portal
(regenerating access token + secret invalidates the old pair immediately), update the
new `life-platform/x` secret, verify with a read-only `GET /2/users/me`, and add the
secret to `MANUAL_ROTATION_SECRETS`. Until then, any X credential found in the account
is itself an incident — nothing should hold one.

---

## Runbook 2 — Recall a bad post ("delete a bad post")

A post is *bad* if it is wrong, private, milestone/body-composition-class (structurally
excluded by ADR-140 rule 5 — reaching public means the exclusion failed), or was not
made by an authorized path.

1. **Stop the next post before cleaning up this one.** SSM
   `/life-platform/syndication-mode` → `off` (command in Runbook 1 step 2; phone-operable).
   In Phase 0 (manual script only), there is nothing scheduled — skip to step 2.
2. **Delete the post at the channel:**
   - **Phone (fastest):** Bluesky app → the post → **⋯ → Delete post**.
   - **API** (when you have the handle + app password and the post's `rkey` from its URL
     `…/profile/<handle>/post/<rkey>`): create a session (Runbook 1 verify step), then:
     ```bash
     curl -s https://bsky.social/xrpc/com.atproto.repo.deleteRecord \
       -H "Authorization: Bearer <accessJwt>" -H 'Content-Type: application/json' \
       -d '{"repo":"<handle>","collection":"app.bsky.feed.post","rkey":"<rkey>"}'
     ```
3. **Know what deletion does NOT do.** AT Protocol deletion propagates to the relay and
   AppViews, but reposts/quotes render tombstoned only where the network cooperates, and
   screenshots/mirrors persist. Deletion *limits* exposure; it does not erase it. This
   irreversibility is exactly why milestone and body-composition posting is permanently
   excluded (ADR-140 rule 5) — for those classes there is no acceptable recall story.
4. **Classify the cause — it decides the rest:**
   - **(a) The poster selected the wrong artifact** (selection/claims bug): file a BUG
     issue; syndication-mode stays `off` until the fix lands *with a test*; reconcile the
     poster's claim record so the artifact cannot be re-claimed and re-posted on the next
     run (#1629's three-state CLAIMED/POSTED/FAILED design — mark the claim per its docs).
   - **(b) The artifact itself was wrong:** fix/unpublish upstream on averagejoematt.com
     first (the post only projected it — ADR-140 rule 1), then repost manually if warranted.
   - **(c) You didn't make it and the platform didn't either:** token compromise —
     execute Runbook 1's leaked-token path immediately, then return here for remaining posts.
5. **Record it:** `docs/INCIDENT_LOG.md` row (which post, minutes-to-delete, cause class,
   follow-up issue). A recall with no ledger row is not finished.

---

**See also:** ADR-140 (`docs/DECISIONS.md`) · `docs/SECRETS_ROTATION.md` ·
`docs/SECRETS_MAP.md` · epic #1619 / story #1629 · `docs/INCIDENT_LOG.md`.
