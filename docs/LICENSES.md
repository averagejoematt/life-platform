# Third-Party License Inventory

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-07-25

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

Last reconciled: 2026-07-25. Pins are authoritative in their source files
(`cdk/stacks/constants.py` for layer versions, `lambdas/requirements/*.txt`,
`cdk/requirements.txt`, `requirements-dev.txt`); this table is the license annotation
over them.

---

## 1. Runtime dependency layers (the only third-party code that ships)

Three native/binary wheels can't be stdlib, so they ride as Lambda **layers** attached
to specific functions (`cdk/stacks/constants.py` holds the pinned ARNs;
`ingestion_stack.py` / `web_stack.py` / `email_stack.py` attach them). Everything else in
`lambdas/` is stdlib + the runtime-provided `boto3`.

| Layer | Package (pin) | Used by | License | Distribution obligation |
|---|---|---|---|---|
| `pillow-layer` | Pillow (PIL) | OG share-card image generator (HP-13), visual-QA render | **HPND** (MIT/BSD-style permissive) | None. Permissive; server-side use only. |
| `garth-layer` | `garth==0.4.47`, `garminconnect==0.2.23` | `garmin-data-ingestion` (OAuth + intervals) | **MIT** | None. |
| `lameenc-layer` | `lameenc` (LAME MP3 encoder wheel, #1018) | `coach-panel-podcast` → `lambdas/audio_encode.py` (WAV→MP3 compression) | Wrapper permissive; **statically links LGPL-2.1 LAME** | **None today** — see §1.1. |

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

| Package (pin) | Purpose | License |
|---|---|---|
| `aws-cdk-lib==2.261.0` | Infrastructure-as-code synth | **Apache-2.0** |
| `constructs==10.7.1` | CDK construct programming model | **Apache-2.0** |

Permissive; both are AWS-published. No obligation beyond notice retention.

---

## 3. Dev / CI tooling (test + lint + provenance — never shipped)

`requirements-dev.txt`. Installed only in CI lint/test jobs and locally; no path into a
Lambda bundle or the published site.

| Package (pin) | Purpose | License |
|---|---|---|
| `pytest==9.1.1`, `pytest-cov==7.1.0` | Test runner + coverage | **MIT** |
| `hypothesis==6.161.2` | Property-based tests (#1664) | **MPL-2.0** (file-level copyleft; used unmodified as a library — no obligation) |
| `playwright==1.61.0` | Visual-QA browser automation | **Apache-2.0** |
| `flake8==7.3.0` | Lint | **MIT** |
| `ruff==0.14.14` | Lint + import-sort | **MIT** |
| `black==25.9.0` | Formatter | **MIT** |
| `mypy==2.3.0` | Type checker | **MIT** |
| `pip-audit==2.10.1` (CI-installed) | CVE gate (`ci-lint.yml`) | **Apache-2.0** |
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

> Retired: the `lambdas/requirements/layer.txt` "shared-utils layer" manifest was
> **deleted** (2026-07-25, #1352) — it described the shared-utils Lambda layer retired
> by #781 and was consumed by no build. Its removal also closes a tombstone-gate blind
> spot (the retired-concept scanner covers `.py`/`.md`, not `.txt`).
