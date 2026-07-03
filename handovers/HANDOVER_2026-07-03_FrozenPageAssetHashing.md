# HANDOVER — the "frozen page" fix: content-hash the full JS module graph — 2026-07-03

**One focused bug, shipped + deployed live + doc'd.** Matthew reported many v5 pages loading "frozen" — the static shell rendered (header/title/footer) but the JS-populated content was blank; a hard reload fixed it, and it reproduced after a browser restart. Root-caused to a deploy-tooling gap, fixed structurally, deployed, and live-verified. **PR #332 open** (branch `worktree-asset-hash-fix-deploy`; docs added on `asset-hash-docs` → fold into #332). The fix was **already deployed to production** (Matthew authorized "deploy this conversation"); the PR is for durability.

---

## The bug

The v5 site is vanilla ES modules that `import` each other by absolute URL (`import ... from "/assets/js/charts.js"`). `sync_site_to_s3.sh` content-hashes CSS/JS and serves the hashed copies `max-age=31536000, immutable` (ADR-039) — but the old inline bash hashing rewrote references **only in `*.html`**. The intra-module import statements *inside* the modules were never rewritten, so they kept pointing at the **unhashed, mutable, `max-age=86400`** URL (the original file, also uploaded as ADR-039's "dynamic-load fallback").

So the entry module (`evidence.js`) was hashed/immutable, but its dependencies (`charts.js`, `sigils.js`, `icons.js`, `ask.js`) resolved to mutable 24h URLs. When a deploy changed an entry module **and** a dependency together (exactly what #260's graphic-identity change did), a returning browser paired a **fresh hashed entry module with a stale cached dependency**. An ES module graph fails atomically — one mismatched import throws at load, the whole module never executes — so the page rendered only its static shell (the frozen screenshot). Hard reload bypassed the HTTP cache; the stale copy survived a browser restart (≤24h TTL), so it reproduced reliably.

Server-side freshness/QA never saw it — it's an interactive, cache-state bug.

## The fix (ADR-098)

New **`deploy/hash_site_assets.py`** replaces the inline bash hashing:
- Builds the module dependency graph from source, hashes **leaves-first** (topological sort; raises on a cycle) so a dependency's hash is final before any dependent is hashed.
- Rewrites **every** reference: HTML `<link>`/`<script>`, intra-module `import`s, and CSS.
- Writes `name.<hash>.ext` (immutable) and rewrites the original in place too (kept as the short-cache fallback), both internally consistent. Skips `legacy/`.

Every asset URL is now content-hashed and immutable → an entry module pins the exact hashed bytes of every transitive dependency → **version skew is structurally impossible**. Chose the graph approach over a hardcoded dep list precisely because it auto-discovers new imports (current `evidence.js` imports an `ask.js` the bug diagnosis didn't know about — hashed automatically).

`sync_site_to_s3.sh` now just calls the helper. The SW (`site/sw.js`) needs no change — cache-first-on-immutable is now genuinely correct for these URLs.

## Deploy + verification

Deployed from an **isolated worktree off fresh origin/main** — the shared checkout was 70 commits / 32 site-commits behind, and deploying from it would have clobbered live content (the clobber guard would also have blocked it). Live-verified:
- `/data/` serves `evidence.<hash>.js` immutable + all 4 imports hashed/immutable/200.
- Deepest chain `coaching → coach_popover → sigils` resolves; the `sigils` hash is **byte-identical across pages** (one consistent graph, no dup).
- 0 dangling refs, 0 unhashed HTML refs; `version.json` build == `sw.js` VERSION.
- Headless render (Playwright) executes the module and populates the content slots (opposite of the frozen shell).

Stuck visitors self-heal within ~5 min (their cached HTML expires and points at the all-new hashed graph).

## State of main + PR

- **PR #332** (`worktree-asset-hash-fix-deploy`) — the 2-file tooling fix (`deploy/hash_site_assets.py` + `deploy/sync_site_to_s3.sh`). Already deployed to prod; PR lands it on main so future deploys keep full-graph hashing (else the next clean-checkout deploy reverts to HTML-only hashing and reintroduces the bug).
- **Docs** (this handover + ADR-098 + INCIDENT_LOG P3 + CHANGELOG + SITE_UPLEVEL_PLAYBOOK gotcha) are on branch `asset-hash-docs` off #332 — **fold into #332 before merge** (or merge both).
- Merge order doesn't matter; both are additive. After merge, delete both branches.

## Notes / gotchas

- The unhashed-original upload (`sync_site_to_s3.sh` "Original CSS/JS", `max-age=86400`) is now dead weight for statically-referenced modules but still correct for true runtime `document.createElement('script')` loads (ADR-039's `countdown.js`). Left in place; a candidate for later cleanup.
- **CLAUDE.md verified-line NOT updated** — the shared checkout had CLAUDE.md dirty from a concurrent session; touching it here would collide. Left for Matthew / that session.
- Memory: `reference_asset_hashing_full_graph` (the durable "for any frozen/stale-page report, check import()/module paths, not just HTML").

See ADR-098, INCIDENT_LOG 2026-07-03 (P3).
