Push the current v5 design system — tokens, foundations, components, reference pages,
and the design-session contract — into the "AverageJoeMatt Design System v5" design
project, so any Claude Design session (or outside designer) opens on repo truth. This is
the **push** path, the mirror image of `/design-implement`'s **pull** path (#1465):
`/design-sync` never touches `site/`, never opens a PR, and never reads a proposal back —
it only writes freshly-built bundle content into the design project.

## Arguments: $ARGUMENTS

None. Running `/design-sync` always performs a full sync of the current repo state —
there is no partial or scoped invocation. (Contrast `/design-implement <slug>`, which
targets one proposal; this command has no analogous unit to target.)

---

## Phase 0 — Orient

1. Read the contract this command exists to distribute: `docs/design/DESIGN_PARTNER_BRIEF.md`
   (the file this sync ships into the design project as root `BRIEF.md` — see Phase 2)
   and this command file itself.
2. `list_projects` (DesignSync tool) and resolve the target project by **exact literal
   title match** on `"AverageJoeMatt Design System v5"` — not a substring or fuzzy match.
   The June 2026 project is titled `"AverageJoeMatt Design System"` (no `v5` suffix); a
   fuzzy or prefix match ("starts with AverageJoeMatt Design System") would hit both and
   risks writing to the archive by accident, which is the one mistake this command exists
   to prevent (see Notes). If exactly one project title-matches `"AverageJoeMatt Design
   System v5"`, target it. If none exists yet, create it (first-run scenario) with that
   exact title. If the match is ambiguous for any reason (e.g. two projects somehow share
   the v5 title), stop and report — do not guess.
3. Do **not** enumerate, read, write, or delete anything in the June 2026 archive project
   under any circumstance in this command.

## Phase 1 — Build the fresh bundle + refresh the live reference captures

1. Run:

```bash
python3 scripts/design_sync_bundle.py
```

(default output `scratch/design_sync_bundle/`; pass `--out DIR` only if you have a
specific reason to write elsewhere — the diff in Phase 2 assumes the default unless
overridden). This script is already merged and self-contained (#1462) — do not modify it
mid-run. It fully rebuilds (`rmtree` + recreate) on every run from checked-in repo truth
(`tokens.css`, `icons.svg`, `charts.js`, `sigils.js`, `v4_kit.py`, the built reference
pages) and self-verifies on exit (raises on an absolute `/…` asset reference, a literal
`https://averagejoematt` URL, or a missing `@dsCard` marker). If it raises, stop — do not
sync a bundle that failed its own verification.

2. Then refresh `reference/` from the CURRENT live site (#1467 — this step is what keeps
   the design project's reference layer from rotting into a stale snapshot):

```bash
python3 scripts/design_sync_capture.py
```

(same `--out` default — it writes INTO the bundle just built, and refuses to run if the
bundle isn't there). It screenshots the doors (the `tests/qa_manifest.py` tier-1 set) +
the data-dense surface (`/data/sleep/`) at 1440×900 dark over the network — read-only
GETs, honoring the `QA_SITE_URL` override — reusing the visual-QA harness's
navigation/scroll discipline. It writes `reference/captures/<slug>.png`, one
`@dsCard group="reference"` card per capture, and `reference/captures_base64.json` (the
binary-upload mirror of `fonts_base64.json`), then re-runs the bundle-wide verification
sweep. Requires `playwright install chromium` and network reach to the live site. If it
raises — including any page failing to load — stop: a bundle whose reference layer is
stale or partial must not sync (that failure mode is the exact problem #1467 exists to
prevent).

The bundle's four directories (`assets/`, `foundations/`, `components/`, `reference/`)
plus its `MANIFEST.md` are the source of truth for Phase 2's diff.

## Phase 2 — Structural diff (never wholesale replace)

1. `list_files` on the target v5 project, recursively (or the closest the tool surface
   offers — if it only lists one level at a time, walk it depth-first). This is the
   current remote state.
2. Compute a three-way file-level diff between the remote list and the fresh bundle's
   file list (`assets/**`, `foundations/**`, `components/**`, `reference/**`, plus the one
   extra root file from step 4 below):
   - **Added** — in the bundle, not present remotely.
   - **Removed** — present remotely, not in the bundle (nor the `BRIEF.md` pairing from
     step 4).
   - **Possibly changed** — present in both, same relative path. A path match alone does
     not prove the content is identical: `get_file` the remote copy and byte/text-compare
     it against the bundle's local content. This is the only way to detect a changed file
     without a remote content-hash API — call it out to whoever runs this that at bundle
     scale (dozens of files across `foundations/`+`components/`+`reference/`) this means
     one `get_file` round-trip per existing path, which has real latency/cost, but it is
     still strictly preferable to a blind wholesale replace (which would also re-upload
     every unchanged font/asset needlessly and defeats the whole point of diffing).
3. `BRIEF.md` — **not** part of `scripts/design_sync_bundle.py`'s output directory. Read
   `docs/design/DESIGN_PARTNER_BRIEF.md` directly from the repo at sync time and include
   it in the same diff pass as one extra project-root file, target path `BRIEF.md` (root
   of the v5 project, not nested under `assets/`/`foundations/`/anything else — per the
   brief's own line: "pushes it into the … v5 … design project as project-root `BRIEF.md`").
4. Font binaries: for every file listed in the bundle's `assets/fonts_base64.json`
   manifest (a `{filename: base64}` map of all 5 vendored woff2 files), use that
   manifest's base64 value **directly** as the write payload on whatever binary/base64
   upload path the tool surface exposes. Do not re-derive base64 from the raw `.woff2`
   copies also present in `assets/` — the manifest exists specifically so this command
   never has to.
5. Capture binaries (#1467): identical rule for `reference/captures/*.png` — use the
   base64 values in `reference/captures_base64.json` directly as the write payload. For
   the byte-compare in step 2, comparing the manifest's base64 entry against the remote
   copy IS the comparison for a PNG. Expect the capture PNGs (and therefore the manifest)
   to differ on almost every run — they are screenshots of live-data pages; re-uploading
   the changed ones is the incremental refresh working as designed, not churn to
   optimize away. The capture *cards* (`reference/<slug>-capture.html`) change at most
   once per UTC day (they carry the capture date), and the built page shells stay
   byte-stable — those still diff to no-ops on an unchanged repo.

## Phase 3 — `finalize_plan`

Before any write, call `finalize_plan` with the full computed diff from Phase 2: the
added-file list, the changed-file list (with a one-line reason each — "content differs"
is enough), and the removed-file list. This is the point where a human or a gating layer
can see the plan before anything is mutated. If the plan comes back empty (no added,
changed, or removed files), skip Phase 4 entirely and go straight to Phase 5 — that is
the no-op case working as designed, not an error.

## Phase 4 — Incremental write

1. `write_files` for the added and changed files **only** — never re-upload a file whose
   Phase 2 byte-compare showed no difference.
2. `delete_files` for the removed files **only** — files present remotely but absent from
   the fresh bundle + `BRIEF.md` pairing.
3. At no point does this command call an operation equivalent to "delete everything, then
   write everything." If the tool surface's only available primitive were a wholesale
   replace, this command could not satisfy its own no-op guarantee (Phase 5) and would
   need to stop and report that limitation rather than fall back to it.

## Phase 5 — Report

Report, in order:

1. What was created / updated / deleted this run (the Phase 3 plan, annotated with the
   actual Phase 4 result), and the project URL/id if the tool surface returns one.
2. The **no-op property** (amended by #1467): running `/design-sync` again immediately,
   with no repo changes in between, should produce a Phase 3 plan that is empty
   **except for the live-capture layer** — `reference/captures/*.png` +
   `captures_base64.json` legitimately differ run-to-run (they screenshot live-data
   pages), and the capture cards roll once per UTC day. Everything else (`assets/`,
   `foundations/`, `components/`, the reference shells, `BRIEF.md`) must still diff to
   zero writes. A non-capture file appearing in a back-to-back rerun's plan is a real
   determinism bug to report, not noise.

---

## Notes

- **Archive vs. v5 — this is the one mistake this command exists to prevent.** The June
  2026 `"AverageJoeMatt Design System"` project (no `v5` suffix, old palette) stays
  untouched forever as a read-only archive: never listed for write, never written to,
  never deleted from, by this command. Mixing fresh v5 cards into a project that still
  carries the old-palette cards would mislead any future design session that opens it,
  which defeats the entire purpose of syncing repo truth into a design project. The match
  rule (Phase 0 step 2) is exact-literal-title, specifically because a fuzzy or
  prefix match is the concrete way this could go wrong.
- **This command DOES write to the design project** — that is the asymmetry with
  `/design-implement` (#1465), which explicitly never calls `write_files`/`delete_files`/
  `finalize_plan` (that surface belongs to this command's push path only, per its own
  Notes section). `/design-sync` is the only command in this pair that mutates the design
  project; `/design-implement` only ever reads from it (`list_files`/`get_file`) and
  writes to `site/` instead.
- If the DesignSync tool surface (`list_projects`/`list_files`/`get_file`/`finalize_plan`/
  `write_files`/`delete_files`) isn't connected in the current session, stop and say so —
  there is no offline fallback for a push sync (there is nothing meaningful to simulate
  writing to a design project that isn't reachable).
- This command never touches `site/`, never opens a PR, and never mutates AWS — it is
  scoped entirely to `scripts/design_sync_bundle.py` + `scripts/design_sync_capture.py`
  output plus the DesignSync tool calls above. The capture step's only network activity
  is read-only GETs against the live site (or `QA_SITE_URL`).
- Precedent: `scripts/design_sync_bundle.py` (#1462) is the bundle builder this command
  depends on; `scripts/design_sync_capture.py` (#1467) is the live reference-capture
  refresh that runs right after it; `docs/design/DESIGN_PARTNER_BRIEF.md` (#1464) is the
  contract file this command ships as root `BRIEF.md`;
  `.claude/commands/design-implement.md` (#1465) is the pull-path mirror of this command.
- **Documented assumption, unverified in this session:** the exact parameter names/shapes
  of `list_projects`/`list_files`/`get_file`/`finalize_plan`/`write_files`/`delete_files`
  (e.g. whether `list_files` is natively recursive, whether `write_files` takes a batch or
  one call per file, whether binary payloads are a distinct `write_files` variant or the
  same call with a base64 flag) are inferred from `.claude/commands/design-implement.md`'s
  description of the same tool surface, not from an actual invocation — this command was
  authored without the DesignSync tool connected. Whoever runs `/design-sync` for real
  should reconcile Phases 2–4 against the tool's actual schema and correct this file if
  the shapes differ.
