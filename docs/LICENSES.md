# Third-Party License Inventory

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-08-12

> **Purpose.** One-lookup answer to the license-DD question: what third-party code
> runs in this platform, under what license, and does any of it create a distribution
> obligation. Written for the asset-sale / due-diligence reviewer so the one copyleft
> edge (statically-linked LAME) is a **written non-issue**, not a discovery. Filed for
> #1352 (SDLC review 2026-07-18, commercial lens).
>
> **Scope reality that makes this short:** the Lambda *runtime* is **stdlib-only** — all
> outbound HTTP is Python's `urllib.request` (see `CLAUDE.md` → "No external HTTP
> libraries"; Bedrock is the one exception, reached via the runtime-provided `boto3`).
> Third-party code enters in exactly three places: three **binary/native Lambda layers**,
> the **CDK** (build/deploy-time only, never shipped in a Lambda), and **dev/CI tooling**
> (never shipped at all). Each is inventoried below.

Last reconciled: 2026-08-12. **Pins are authoritative in their source files**
(`deploy/build_lambda_layer.py` + `lambdas/requirements/*.txt` for layer package pins,
`cdk/stacks/constants.py` for layer *versions*, `cdk/requirements.txt`,
`requirements-dev.txt`); this table is the license annotation over them, and it
**names packages, not versions** — see §6.1 for why that is a decision rather than an
omission.

---

## 1. Runtime dependency layers (the only third-party code that ships)

Three native/binary wheels can't be stdlib, so they ride as Lambda **layers** attached
to specific functions (`cdk/stacks/constants.py` holds the pinned ARNs;
`ingestion_stack.py` / `web_stack.py` / `email_stack.py` attach them). Everything else in
`lambdas/` is stdlib + the runtime-provided `boto3`.

Package pins live in `deploy/build_lambda_layer.py`'s `LAYERS` registry (from which
`lambdas/requirements/*.txt` is generated); the published layer *versions* are
`cdk/stacks/constants.py`'s `*_LAYER_VERSION` constants.

| Layer | Package | Used by | License | Distribution obligation |
|---|---|---|---|---|
| `pillow-layer` | Pillow (PIL) | OG share-card image generator (HP-13), visual-QA render | **HPND** (MIT/BSD-style permissive) | None. Permissive; server-side use only. |
| `garth-layer` | `garth`, `garminconnect` | `garmin-data-ingestion` (OAuth + intervals) | **MIT** | None. |
| `lameenc-layer` | `lameenc` (LAME MP3 encoder wheel, #1018) | `coach-panel-podcast` → `lambdas/ai/audio_encode.py` (WAV→MP3 compression) | Wrapper permissive; **statically links LGPL-2.1 LAME** | **None today** — see §1.1. |

### 1.1 The one copyleft edge — lameenc / LAME (stated as a non-issue)

`lameenc` bundles a statically-linked build of **LAME**, which is **LGPL-2.1**. LGPL's
relinking/source-availability obligations attach on **distribution** of the linked work.
This platform **does not distribute** the layer, the wheel, or the encoder: `lameenc`
runs **server-side inside a Lambda** to compress one podcast WAV to MP3, and only the
*output* MP3 (an ordinary media file, not a derivative of LAME's source) is ever
published. **Server-side use is not distribution**, so no LGPL relinking or
source-offer obligation is triggered under the current architecture.

**If that ever changes** (e.g. the encoder is shipped in a downloadable "Fork My
Life-Stack" starter kit, #1401, or any client-side/redistributed artifact), the LGPL
obligation activates and must be honored — provide the LAME source + a relink path, or
switch to a permissively-licensed encoder. That is the single license tripwire in the
tree; it is recorded here so a future redistribution decision meets it as a known
condition, not a surprise.

---

## 2. Build/deploy-time dependencies (CDK — never shipped in a Lambda)

`cdk/requirements.txt`, run only in CI's "Plan/Deploy" jobs and on an operator's
machine. Pinned exactly (#814).

| Package | Purpose | License |
|---|---|---|
| `aws-cdk-lib` | Infrastructure-as-code synth | **Apache-2.0** |
| `constructs` | CDK construct programming model | **Apache-2.0** |

Permissive; both are AWS-published. No obligation beyond notice retention.

---

## 3. Dev / CI tooling (test + lint + provenance — never shipped)

`requirements-dev.txt`. Installed only in CI lint/test jobs and locally; no path into a
Lambda bundle or the published site.

| Package | Purpose | License |
|---|---|---|
| `pytest`, `pytest-cov` | Test runner + coverage | **MIT** |
| `hypothesis` | Property-based tests (#1664) | **MPL-2.0** (file-level copyleft; used unmodified as a library — no obligation) |
| `playwright` | Visual-QA browser automation | **Apache-2.0** |
| `pyyaml` | Workflow parsing in `scripts/apply_branch_protection.py`'s preflight (#2200) | **MIT** |
| `boto3`, `botocore` | AWS SDK for tests that call boto3 directly | **Apache-2.0** |
| `flake8` | Lint | **MIT** |
| `ruff` | Lint + import-sort | **MIT** |
| `black` | Formatter | **MIT** |
| `mypy` | Type checker | **MIT** |
| `pip-audit` (CI-installed) | CVE gate (`ci-lint.yml`) | **Apache-2.0** |
| `pip-licenses` (CI-installed) | Advisory license report (`ci-lint.yml`, §6) | **MIT** |
| `syft` (CI-installed, #1661) | SBOM provenance | **Apache-2.0** |

All permissive or library-use-exempt; nothing here reaches a distributable artifact.

---

## 4. The repository's own LICENSE posture

`LICENSE` (repo root): **proprietary, all-rights-reserved** — "Copyright © 2026
Matthew. All rights reserved. PROPRIETARY AND CONFIDENTIAL." No license, express or
implied, is granted; copying, modification, redistribution, commercial/non-commercial
use, and reverse-engineering are all withheld absent written permission. This is a
deliberate posture (a personal-data platform published for reading, not for reuse), not
an oversight — the public website is a *view*, not a grant.

---

## 5. AI-generated-content ownership stance ⚠️ **[owner-signed posture]**

**The tension.** `LICENSE` claims copyright over "content," and large narrative surfaces
of this platform are **AI-generated** (the daily brief, coach voices, the chronicle, the
State-of-Matthew retrospectives, Horizons "why I sent it" notes). `ADR-106` settles
ownership for **coach portraits only** (AI may sketch, only code ships, only Matthew
approves) — it does not, on its face, cover the far larger surface of AI-written prose.

**Recorded stance (owner, 2026-07):**
1. **Inputs are the operator's.** Every AI narrative is generated from Matthew's own
   measured data and prompts, on infrastructure he controls, via a paid tool (AWS
   Bedrock) whose terms assign output rights to the customer. The generated text is a
   **work made for the operator's account**, not a third party's property.
2. **The copyrightable thing is the curated, edited whole** — selection, arrangement,
   grounding gates (ADR-104/105), editorial review, and the human-authored scaffolding
   around the generated spans. Bare machine output may enjoy thin or no copyright in
   some jurisdictions; the platform's claim rests on the human-authored compilation and
   editing, which is protectable, plus the proprietary data it is derived from.
3. **No third-party rights are implicated** — the model is not a co-author with a claim;
   Bedrock's terms disclaim ownership of outputs. There is no open-source model weight
   or dataset license flowing an obligation into the generated text.
4. **Portraits remain the one place with a stricter, code-only bar** (ADR-106); nothing
   here weakens that.

**Owner sign-off:** this §5 posture is Matthew's to ratify as the platform's stated
position; it is recorded here as the working stance for DD purposes and updated if the
legal posture is formalized further. It is a **stated posture, not legal advice.**

---

## 6. How this stays honest (regression guard)

- **CVEs:** `pip-audit` (blocking, `ci-lint.yml`) over `requirements-dev.txt` +
  `cdk/requirements.txt` (#1661).
- **Licenses:** an **advisory** `pip-licenses` step runs beside `pip-audit` — it prints
  the resolved license of every dev/CDK dependency each build, so a new or bumped
  dependency that changes license surfaces in the log instead of drifting silently. It
  is non-gating by design (this is an inventory-honesty aid, not a pass/fail gate; a new
  copyleft dependency is a human decision, not a build break).
- **SBOM:** `syft` emits SPDX + CycloneDX provenance per build (#1661).
- **Layer versions:** pinned in `cdk/stacks/constants.py`; bumping a layer is a
  deliberate PR that should re-check §1 here.

### 6.1 Decision: this table names packages, not versions (#2588, 2026-08-12)

**Decision.** §1–§3 record **package + license**, never a patch-exact `name==version`.
The version of record is whatever the authoritative pin file says at the commit you are
reading; this document does not carry a second copy of it.

**Why — measured, not assumed.** #2570 widened the CQ-01 pin guard
(`tests/test_ci_pin_consistency.py`) to derive its declaration surface from `git
ls-files`, which pulled this table into scope and immediately found `hypothesis` and
`playwright` stale. Auditing the rest of the table on 2026-08-12 showed the two the
guard caught were not the problem:

- The table carried **13** version-bearing rows. **6 were stale** — `hypothesis`
  (6.161.2 vs 6.165.0), `playwright` (1.61.0 vs 1.62.0), `aws-cdk-lib` (2.261.0 vs
  2.263.0), `constructs` (10.7.1 vs 10.8.1), `garth` (0.4.47 vs 0.6.3),
  `garminconnect` (0.2.23 vs 0.3.8). A **46% rot rate** on a table 18 days old.
- The guard could only ever see **7 of the 13** rows (`_GATED_TOOLS` covers the CI
  tooling, not `flake8`/`pip-audit`/the CDK pair/the layer packages), so it caught
  **2 of the 6** stale rows. The four it missed include §1's layer packages — the only
  third-party code that ships, i.e. the section where exactness would matter most, two
  minor versions behind with nothing red.
- Follow-through is not a discipline problem that a reminder fixes: since this file was
  created (2026-07-25), `requirements-dev.txt` moved 5 times and `cdk/requirements.txt`
  3 times; this file followed **once**. Dependabot moves those pins and has no reason to
  know this table exists.

**Why not the alternatives.**

- *Keep exact versions and let dependabot PRs also touch this file* — pays new friction
  on every routine bump to protect a fact that is not load-bearing: a package's licence
  does not change between patch releases, and the one row that genuinely carries a
  copyleft obligation (`lameenc`, §1.1) never had a version to begin with.
- *Have `deploy/sync_doc_metadata.py` own the rows* — technically expressible (one RULE
  + one derived fact per row), but it buys ~13 rules and a discovery function to keep a
  number nobody reads, adds this file to the doc-sync literal surface the driver has to
  reconcile across concurrent PRs, and still does not make a dependabot PR green on its
  own — someone has to run the sync. Machinery out of proportion to the fact (ADR-103/144).

**What actually keeps this honest instead.** The advisory `pip-licenses` step in
`ci-lint.yml` resolves **the live manifests every build** and prints the licence of every
dev/CDK dependency at its real installed version — continuous verification against the
actual pins, which is strictly stronger than a hand-typed version that rotted 6 ways in
18 days. `pip-audit` (blocking) and `syft` scan the same manifests. A licence *change* is
what this document must catch, and that is what those steps surface.

**Enforced, not aspirational.** `test_licenses_doc_declares_no_patch_exact_pins` in
`tests/test_ci_pin_consistency.py` reds if a `name==version` reappears in §1–§3, so this
decision cannot silently erode back into the drift it replaced. If a future row's version
*is* load-bearing (a licence that genuinely changed at a known version boundary), state
the boundary in prose — "MIT through 4.x, BUSL from 5.0" — rather than pinning a patch.

> Retired: the `lambdas/requirements/layer.txt` "shared-utils layer" manifest was
> **deleted** (2026-07-25, #1352) — it described the shared-utils Lambda layer retired
> by #781 and was consumed by no build. Its removal also closes a tombstone-gate blind
> spot (the retired-concept scanner covers `.py`/`.md`, not `.txt`).
