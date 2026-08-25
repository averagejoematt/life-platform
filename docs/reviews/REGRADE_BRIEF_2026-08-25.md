# Re-grade brief — for the external assessor

> **Status:** active · **Owner:** Matthew · **Verified:** 2026-08-25

**You are being asked to re-score a platform you (or a peer) scored 4.47/10 —
"conditional no-go" — on 2026-08-23, across 52 findings (DIL-001 … DIL-052).**

This brief exists so you can do that **without taking our word for anything**. It tells
you what changed, how to verify it yourself in about ten minutes, and — the part that
matters most — where we think you should attack.

---

## 1. The one-paragraph summary

Five P0s were confirmed and fixed. A meaningful number of findings were **wrong or stale
as filed**, and the reason they were filed is itself the most important finding of the
review: *the platform's own documentation lied about the platform.* Three of your false
positives (DIL-004, DIL-006, half of DIL-005) were manufactured by a self-stamped
"Verified 2026-07-09" ledger that had been wrong for seven weeks. We do not count those
as wins. Documentation truth is now a guarded surface, not a good intention.

The remaining open items are **priced acceptances**, not backlog. Each has a dated row
and a named revisit trigger. We would rather be scored honestly on a deliberate gap than
generously on a hidden one.

---

## 2. Verify it yourself — the ten-minute path

Everything below runs against **live** state. Nothing asks you to trust a repo grep.

```bash
python3 scripts/diligence_verify.py --strict
```

That is your §15 playbooks, scripted: **12 playbooks across your four families**
(`control`, `privacy`, `prediction`, `edge`). It hits the GitHub API, the public site,
the public JSON endpoints, and CloudWatch. Current result: **12 PASS · 0 FAIL ·
0 UNVERIFIED**.

Three things to check about the instrument before you trust its output:

1. **It has three verdicts, not two.** `UNVERIFIED` — auth failure, transport error,
   changed API shape, unexpected exception — is never folded into `PASS`, and `--strict`
   exits non-zero on it. We built it this way because our *own* CodeQL sentinel had
   declared itself armed for weeks while never once successfully reading the
   code-scanning API (three independent sufficient defects, each producing a
   clean-looking result). Assume we would have made that mistake again if we had not
   named it.
2. **It is mutation-proved.** `tests/test_diligence_verify_d5.py` plants a defect at each
   playbook's seam and asserts the verdict flips — a demoted approval gate, a leaked
   owner-only field, a returned `'unsafe-inline'`, a calibration surface claiming skill
   it has not earned. We also checked the *tests* for vacuity: neutering three playbooks
   turns four tests red.
3. **It covers 14 of your 52 findings, and says so at runtime** — that fraction is
   derived from the playbook registry, not typed into a doc. The other 38 are priced
   acceptances, commercial gaps, and product findings that no script can verify. If we
   had claimed broader coverage, that claim would itself be the finding.

Then read `docs/reviews/DILIGENCE_2026-08-23_RESPONSE.md` — the per-finding register,
with `CONFIRMED` / `STALE` / `WRONG` / `PRICED` and live evidence per row.

---

## 3. Where we think you should attack

We are not going to pretend these are solved. In rough order of how much they should
cost us:

**a. Key-person concentration (DIL-047/048).** One person holds every credential, every
decision, and all the context. We cannot fix this at this headcount — only mitigate and
disclose. The mitigation is real (operating knowledge is written down continuously rather
than resident; secrets are in Secrets Manager, not in a head or a laptop; the re-entry
path is scripted with deliberately loud gaps). **The honest residual is recovery *time*,
not recoverability.** Note that our own cross-region backup does **not** touch this — it
protects data, not decision continuity. If you think we have under-priced this, we would
want to hear it.

**b. The production approval gate is self-approvable (DIL-004).** Your report said the
gate did not exist; that was wrong, and it is live and blocking today. But a one-reviewer
environment where the author is the approver is a **pause with an audit record**, not an
independent check. We have written it down as the former. If you score it as the latter's
absence, we will not argue.

**c. Founder-calibrated scoring (DIL-049).** Every threshold on this platform is derived
from one person's variance. Single-subject validity is a real limit on every score the
system emits, and no amount of internal rigor fixes it.

**d. The historical privacy exposure (DIL-001) is not undone.** Five owner-private
coaching docs were world-readable for months. They now 404 and the tree is structurally
guarded — but a git-history rewrite was evaluated and **ruled ineffective** (GitHub
retains ~1,454 pull refs that keep force-pushed content reachable by direct sha), so the
historical copies remain reachable. We accepted that rather than perform a rewrite that
would break every reference and erase nothing.

**e. Replication is not retroactive.** The `raw/` cross-region backup is live and
asserted weekly, but the pre-existing ~37,665 objects stay unprotected until an S3 Batch
Replication backfill runs. Our own sentinel reports drift **by design** until it does. At
the time of writing, it has not run.

---

## 4. What we would consider a fair scoring frame

- **Score the priced acceptances as gaps.** They are gaps. We ask only that the score
  reflect that they are *known, dated, and triggered* rather than discovered by you.
- **Do not credit us for controls you cannot observe.** If `diligence_verify.py` reports
  `UNVERIFIED` for something in your environment, treat it as unproven. That is what the
  verdict means.
- **Weight the documentation-truth finding heavily.** It caused your false positives, and
  it is the failure mode most likely to recur. If you can find a live claim on this
  platform that contradicts its own behaviour, that is a more damaging finding than
  anything in the P1 register — and we would rather you find it than not.

---

## 5. Known limits of this brief

It is written by the party being assessed. Treat its framing as advocacy and its
**commands** as the evidence. Everything in §2 runs on your machine, against live
systems, and can contradict us.

---

*Companion documents: `docs/reviews/DILIGENCE_2026-08-23_RESPONSE.md` (the register) ·
`docs/reviews/evidence/` (dated machine-readable bundles) ·
`docs/PROPORTIONALITY.md` (the priced rows) · `docs/DECISIONS.md` (ADRs, incl. ADR-155
publication consent, ADR-104 honest numbers, ADR-105 the rigor bar).*
