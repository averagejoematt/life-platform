# The Permanence Contract

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-08-10
> **Contract version:** 1.0.0 · **Effective:** 2026-08-10 · **Issue:** #1400 (epic #1367)

The question this document exists to answer is the one friends and family actually
ask, and the one no wearable company has ever answered in writing: **what happens to
all of this if he stops?**

The answer is not a reassurance. It is a downloadable file and a written commitment,
each of which can be checked against the other.

---

## 1. Why this is versioned like an ADR

A promise about permanence that can be quietly edited is not a promise. So the terms
below carry a version number, a dated amendment history, and one structural rule:
**clauses are added or superseded, never rewritten away.** If clause P7 says something
different next year, the amendment history will say when it changed and why.

The terms also exist twice on purpose — as the prose in §2, and as data in
`lambdas/operational/permanence_terms.py`. `tests/test_permanence_contract_1400.py`
asserts the two agree clause for clause, version for version, and that every clause
claiming a mechanism names a function that actually exists and is importable. Delete
the code behind a promise and the build goes red. That is the only way a written
commitment stays honest in a repository that changes every day.

---

## 2. The terms

<!-- BEGIN READER TERMS -->
<!-- Everything between these markers is reader-facing and infrastructure-free.
     A future public page (#1400's second PR) should lift this section verbatim;
     the gate test asserts no internal detail leaks into it. -->

**Version 1.0.0 — effective 2026-08-10**

### P1 · Nothing here is for sale

No reader's email address, question, or submitted finding is ever sold, rented, or
handed to an advertiser, a data broker, or a sponsor. Neither is any of Matthew's own
health data. There is no advertising business here to be tempted by.

### P2 · The public record is rebuilt as a single download every night

Every night the platform packages everything it already publishes — the data, the
methods, the chronicle, the sealed pre-registrations — into one compressed archive at
a fixed address, and overwrites yesterday's. It is not generated on request and it is
not gated: it is simply there.

### P3 · What may enter the archive is decided by a gate, not by hand

Nothing enters because someone remembered to add it. An artefact enters only if the
public site already serves it at a public address, and only if a registry classifies
that address as part of the published record. Anything the registry does not classify
is refused. The API portion is fetched with no credentials at all, over the same
public address a reader would use, so it can contain nothing a reader could not
already fetch themselves.

### P4 · Every archive publishes its own inventory and checksum

Alongside the archive sits a manifest listing every file in it with a size and a
SHA-256, the checksum of the archive as a whole, the moment it was built, and — in the
same document — a list of what was deliberately left out and why. You do not have to
trust the description; you can check it.

### P5 · You may keep a copy

Mirroring the archive, in full and unmodified, is expressly permitted and actively
encouraged — no permission needed, no attribution required beyond leaving the manifest
intact. The most durable version of this record is the one that exists in more than
one place, and that copy is not something this platform can make for you.

### P6 · Silence is measured out loud

The platform watches for its own silence: the number of days since the last signal
from any source that only produces data when a living person is doing something. That
number, and the state it puts the contract in, are published in the same place as the
archive, every night, whether the news is good or not.

### P7 · Ninety days of silence freezes the record and raises the alarm

At 30 days of silence the contract enters a notice state, at 60 a warning state, and
at 90 the switch trips: the archive stops being overwritten and is sealed as a final,
dated edition, the published state says so plainly, and the people configured as
continuity contacts are told where the record is and how to check it. Any new signal
from any watched source resets the clock — the switch is a measurement, and it is
reversible.

### P8 · What this contract does not promise

It does not promise the archive outlives the bill: everything here sits in one cloud
account, and if that account lapses the archive lapses with it. That is precisely why
P5 exists. It does not promise a third-party mirror — no automatic copy is made to any
host outside this account, and any claim that one exists would be false. It does not
promise the archive is complete: audio, artwork, and the site's presentation layer are
excluded, and the manifest names every exclusion. It does not promise the switch
detects a person: it detects the absence of data, which a long holiday, a hardware
failure, or a vendor lockout can also produce — that is why the first two thresholds
notify rather than act. And it does not promise to publish anything currently private:
the archive is a repackaging of the public surface, never a widening of it.

### P9 · The terms are versioned, and amendments are append-only

This contract carries a version and a dated amendment history. Clauses are added or
superseded, never quietly rewritten, and the published version number tells you which
edition you are reading.

<!-- END READER TERMS -->

---

## 3. Amendment history

| Version | Date | Issue | Change |
|---|---|---|---|
| 1.0.0 | 2026-08-10 | #1400 | First edition: the nightly public archive, its admission gate, and the continuity clock. |

---

## 4. How each clause is kept

| Clause | Kind | Mechanism |
|---|---|---|
| P1 | policy | No mechanism — a statement of intent, backed by the absence of any advertising or data-sale integration in the platform at all. |
| P2 | mechanism | `lambdas/operational/public_archive.py::build_archive`, run nightly by `lambdas/operational/permanence_lambda.py`. |
| P3 | mechanism | `lambdas/operational/public_archive_registry.py` — the admission registry, gated by `tests/test_public_archive_privacy_gate_1400.py`. |
| P4 | mechanism | `lambdas/operational/public_archive.py::build_manifest`. |
| P5 | policy | No mechanism — a permission grant, not a capability. |
| P6 | mechanism | `lambdas/operational/continuity_watch.py::evaluate`. |
| P7 | mechanism | `lambdas/operational/continuity_watch.py::apply_transition`, plus the freeze/seal branch in the handler. |
| P8 | limit | No mechanism by definition — this clause exists to name what the mechanisms cannot do. |
| P9 | mechanism | `lambdas/operational/permanence_terms.py::public_terms` + this document's amendment table. |

### The admission rule, in full

An artefact may enter the archive through exactly three arms, each fail-closed:

1. **Published `generated/` objects.** The bucket prefix is world-readable, but only
   part of it is *published* — several sub-prefixes (the QA capture, raw
   reader-submitted questions and findings, coach engine state) have no CloudFront
   behaviour at all. The registry classifies every generated-origin behaviour in
   `cdk/stacks/web_stack.py` as include or exclude with a reason, and the gate test
   AST-derives that behaviour set from the CDK source: **a new public route cannot
   join the archive without a verdict, and a retired one cannot linger.**
2. **Published site documents.** `.html`, `.json`, `.xml`, `.txt`, `.webmanifest`
   outside `site/legacy/`. Every admitted suffix is one `deploy/pii_surface_guard.py`
   actually scans, and the gate test pins that subset relation — the archive can never
   admit a class of file the site's own privacy scanner does not read.
3. **Anonymous API snapshots.** The route set is derived: every route
   `deploy/endpoint_registry.py` discovers, minus the write paths already exempted by
   the endpoint privacy gate, minus a handful of parameterised routes declared with a
   reason. Each archived route must already have a committed shape snapshot under
   `tests/api_schemas/`, i.e. must already be scanned by the endpoint PII arm. The
   fetch carries no `Authorization`, no cookie, and no subscriber token, which is what
   makes Tier 1/2/3 data in `docs/DATA_GOVERNANCE.md` unreachable **by construction**
   rather than by policy.

### The continuity clock, in full

The clock measures days since the last row from a source that only writes when a
person acts. That set is **derived from the `behavioral` facet in
`lambdas/ingestion/source_registry.py`** — the facet that already means "staleness
here is a logging lapse, not an outage" — so a new behavioural source joins the clock
the day it lands. Paused sources are excluded: a source with no live schedule is
silent for reasons that have nothing to do with a person.

Two corrections sit on top of the derived set:

* **Apple Health is read on a value, not on the partition.** Its rows keep arriving
  from automations that need no person, so the clock reads the most recent day with
  non-zero steps instead.
* **A source that cannot be read is not a silent source.** Read failures are counted
  separately, and if nothing at all could be read the verdict is `unknown` — never
  `triggered`. A DynamoDB timeout must never be able to announce that somebody
  stopped living.

Thresholds: 30 days → notice, 60 → warning, 90 → the switch trips. Escalation
notifies; only the third threshold acts. Contacts are read from Secrets Manager and
appear nowhere in this repository — the people on that list did not sign up to be
named in a public git history.

---

## 5. How to check it yourself

Nothing below requires access to anything private.

```bash
# The archive, its inventory, and the continuity clock (all public URLs):
curl -sO https://averagejoematt.com/archive/latest.tar.gz
curl -s  https://averagejoematt.com/archive/manifest.json | head -40
curl -s  https://averagejoematt.com/archive/continuity.json

# Does the published checksum match the bytes you received?
shasum -a 256 latest.tar.gz

# Does every file in the archive match its listed checksum, and is every
# entry reachable at its own public URL?
python3 scripts/verify_public_archive.py --archive latest.tar.gz --check-urls
```

`scripts/verify_public_archive.py` is deliberately dependency-free (stdlib only) and
read-only, so it can be run by anyone, from a mirror, long after this repository has
stopped changing.

---

## 6. Relationship to the rest of the platform

* `docs/DATA_GOVERNANCE.md` is the authority on what is Tier 0 (public) and what is
  not. This contract adds no new classification and widens no tier — it repackages
  Tier 0 and nothing else.
* `lambdas/operational/data_export_lambda.py` is a *different* artefact: the owner's
  monthly full export of every partition to a private prefix. It is not public, it is
  not in the archive, and this contract makes no promise about it.
* The experiment-restart pipeline's "archive" (ADR-077) means tombstoned, cycle-stamped
  DynamoDB history. Also a different thing, also not this.
