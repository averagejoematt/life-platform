# Syndication Runbooks — token rotation + post recall

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-10-17

Last updated: 2026-10-17 (re-verified against the code: the automated poster #1629 was retired
won't-do 2026-09-19, so rows and steps that assumed an unbuilt-but-coming poster now describe the
manual script only). Earlier: 2026-08-05 (#1402 — the artifact-class table); originally 2026-07-25
(#1630 — written BEFORE the first automated post, per the ADR-140 requirement and the R22
precedent (#893): "how do I delete a bad post and rotate a leaked token" must be a document,
not a 2am improvisation.)

**Scope:** the social syndication surface governed by **ADR-140** (`docs/DECISIONS.md`) —
the manual script (`scripts/post_social.py`, #1622), which is the **only** poster. The
automated Bluesky poster (#1629) was **retired as won't-do on 2026-09-19** (owner ruling:
its own promotion trigger passed 2026-09-01 at 0/30 days of use) and the X channel
(#1631) is closed unbuilt — both stay governed by ADR-140 should either ever be revived.
Covers **Bluesky** (the `life-platform/bluesky` credential) and, prospectively, **X**.

**Not to be confused with the inbound social feeds.** `bluesky-social-ingestion`,
`mastodon-social-ingestion` and `youtube-social-ingestion` (`lambdas/ingestion/bluesky_lambda.py`,
`mastodon_lambda.py`, `youtube_lambda.py`; schedules are each function's `schedule=` in
`cdk/stacks/ingestion_stack.py`) READ public feeds; they post nothing. All three run on
**placeholder account ids** (`__OWNER_MUST_SUPPLY__` sentinels, deliberate and documented in
#1669), so they find zero rows until the owner supplies real accounts; whether to disable the
schedules meanwhile is an open ruling on #4641. `life-platform/bluesky` is shared: the
`handle` field feeds the inbound lambda, the app password is the poster's credential.

## What exists today vs. what ships with #1629

Honesty note (`reference_docs_current_truth_only`) — this runbook was written *before* the
first post; the table is the state read from the code and AWS on 2026-10-17:

| Thing | State (2026-10-17) |
|---|---|
| `life-platform/bluesky` secret (handle + **scoped app password**, AT Protocol `createSession`) | **EXISTS** — created 2026-07-25, last changed the same day (read-only `describe-secret`), createSession-validated then. App password only, never the account password (#1629 non-negotiable 10). Rotation cadence below is measured from the last-changed date |
| `scripts/post_social.py` manual poster | **LIVE, ungated.** The 30-day usage-trial gate was removed 2026-08-02; Bluesky posts live, `--platform x` prints a pointer to #1631 and exits with no network call. **Its Bluesky credential is read from the macOS keychain (service `life-platform-bluesky`), not from AWS** — a rotation must update the keychain entry as well as the secret |
| The syndication lambda (`lambdas/syndication/`) | **Does not exist, and will not** — #1629 retired won't-do 2026-09-19 (see Scope) |
| SSM `/life-platform/syndication-mode` (`off \| shadow \| live`) | **Does not exist** (no code or CDK references it) — there is no automated poster to switch off. ADR-140 rule 3 requires it before any automated poster ships |
| `life-platform/bluesky` in the freshness checker's `MANUAL_ROTATION_SECRETS` (`lambdas/emails/freshness_checker_lambda.py`) | **Not listed** (the list is `ai-keys`, `site-api-ai-key`, `eightsleep-client`, `notion`, `todoist`, `ingestion-keys`) — so no staleness alert fires; calendar the 180-day rotation by hand. Add the entry only if an automated consumer is ever built |
| `life-platform/x` secret / X developer-portal app | **Does not exist** (`describe-secret` → ResourceNotFound, 2026-10-17) — #1631 closed unbuilt; do-not-build until the ADR-063 per-post-spend amendment is signed |
| The daily-fingerprint broadcast artifact (`/moments/fingerprint/{date}/`, #1402) | **LIVE** — dated card + permalink + provenance caption, written by `og_moments._sweep_fingerprint`. Nothing posts it; see the class table below |

## What may be posted by what — the artifact-class table (#1402)

ADR-140 rule 5 excludes milestones, achievements, weigh-ins and anything
body-composition-related from **automated** posting, permanently. #1629's owner-recorded
non-negotiable is broader: no automated surface may post a claim about Matthew's body.
The Daily Fingerprint is a pure function of his recovery, sleep, HRV and streak — so it is
a vitals-derived artifact, and the row below is the consequence, not a preference.

| Artifact class | Human post (`scripts/post_social.py`) | Automated post (no such poster exists — #1629 retired; the rule binds any successor) |
|---|---|---|
| Chronicle / podcast / essay / build beat | **Yes** — `--kind chronicle` | **Not built** — would need a new poster clearing ADR-140's shadow bar |
| Daily fingerprint card (#1402) | **Yes** — `--kind fingerprint`, caption printed in full for approval before the choice | **NO — structurally denied.** `fingerprint_broadcast.AUTOMATED_SYNDICATION_ALLOWED = False`; the payload says so in-band and `tests/test_fingerprint_broadcast.py` pins it. Reversing needs a new three-board convening, not a code change |
| Milestones / achievements / weigh-ins / body composition | Matthew's own account, by hand, outside this tooling | **NO — permanently denied** (ADR-140 rule 5) |

**A warming-up day is published but never offered.** If fewer than `web.fingerprint.THIN_N`
signals reported, the dated card and permalink are still written (the sparse mark is the
honest render and the archive should have no holes) but the payload comes back
`syndicatable: false`, and the poster shows no candidate. This is #1629's non-negotiable
11, written from cycle 8's three present-None firings.

**Recall for a fingerprint post** is Runbook 2 below, unchanged — the post is a normal
Bluesky record. The dated artifact it links to is deliberately *not* deleted on recall:
the permalink is an archive entry, and removing it would make the reader's back-link rot.

---

## Runbook 1 — Rotate a syndication token (routine or leaked)

### Bluesky — routine rotation

The credential is a **scoped app password** (Bluesky → Settings → Privacy and Security →
App Passwords). Rotation is create-new → update secret → revoke-old, in that order, so
there is no gap for the poster (the manual script, which reads the keychain):

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
5. Update the keychain entry the manual poster reads:
   `security add-generic-password -U -s life-platform-bluesky -a <handle> -w '<new app password>'`.
   The inbound `bluesky-social-ingestion` lambda reads only the `handle` field (keyless
   public AppView), so it is unaffected; its `secret_cache.py` TTL is ~15 min.

Cadence: 180 days, or immediately on any suspicion. Inventory row: `docs/SECRETS_ROTATION.md`.

### Bluesky — LEAKED token (the 2am path; order matters)

1. **Revoke at the source FIRST — phone-operable, no AWS needed:** Bluesky app →
   Settings → Privacy and Security → App Passwords → delete the leaked app password.
   Every session created with it dies immediately. Do this before anything else; a
   leaked app password can post *as you*.
2. **Kill the poster.** There is no automated poster and no `syndication-mode` parameter,
   so step 1 alone stops all writing. Also delete the keychain entry the manual script
   reads (`security delete-generic-password -s life-platform-bluesky`) and stop running
   `scripts/post_social.py`. (If an automated poster is ever built, ADR-140 rule 3's
   SSM `/life-platform/syndication-mode` → `off` becomes step 2.)
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

1. **Stop the next post before cleaning up this one.** Today the manual script is the only
   poster and nothing is scheduled — skip to step 2. (With a future automated poster:
   SSM `/life-platform/syndication-mode` → `off`, ADR-140 rule 3.)
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
   - **(a) The poster selected the wrong artifact** (selection/claims bug in
     `scripts/post_social.py` or the candidate builders): file a BUG issue; do not run the
     script again until the fix lands *with a test*. (A future automated poster would also
     need syndication-mode `off` and its claim record reconciled.)
   - **(b) The artifact itself was wrong:** fix/unpublish upstream on averagejoematt.com
     first (the post only projected it — ADR-140 rule 1), then repost manually if warranted.
   - **(c) You didn't make it and the platform didn't either:** token compromise —
     execute Runbook 1's leaked-token path immediately, then return here for remaining posts.
5. **Record it:** `docs/INCIDENT_LOG.md` row (which post, minutes-to-delete, cause class,
   follow-up issue). A recall with no ledger row is not finished.

---

**See also:** ADR-140 (`docs/DECISIONS.md`) · `docs/SECRETS_ROTATION.md` ·
`docs/SECRETS_MAP.md` · epic #1619 / story #1629 (retired) / #1631 (X, closed unbuilt) · #4641 (the placeholder-id feeds) · `docs/INCIDENT_LOG.md`.
