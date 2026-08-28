---
name: prove-it
description: "Prove an instrument actually works before trusting it — a gate, check, watcher, measurement, negative control, Verified stamp, closure comment, deploy, or an agent's own status report. Use before calling any of those done, when a check passes and you cannot say what would make it fail, or when a green result seems too easy."
user-invocable: true
argument-hint: "[what you are about to trust]"
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, TodoWrite
---

One failure shape accounts for roughly half this platform's incident corpus:

> **A thing that reports success without having done its job.**

Not a wrong answer — a *confident* one, from something that never looked. It is the
platform's signature defect and it has been found in every layer: a gate, a watcher, a
measurement, a negative control, a `Verified` stamp, a closure comment, a deploy, a
reconcile job, and an agent's own status report. Session F found five independent
instances in one night. About 80% of recent closed issues were defects in the platform's
own instruments rather than in the product.

Run this before trusting any instrument.

## The five questions

**1. Make the must-fail case actually fail.**
Break the thing the instrument claims to catch and watch it go red. If it stays green the
instrument is decoration.

*Paid for:* `#3200` shipped verdict-closed with 60 green tests and was non-functional — a
broken fail-closed path looks exactly like a working one. A negative control used
`find_module`, removed in Python 3.12, so the import it "blocked" was never blocked. A
CloudWatch query ran against a log group that did not exist, returned 0 events, and
inverted a live finding from "firing" to "latent". **A vacuous negative control is
indistinguishable from a passing one.**

**2. Pair it with a positive control.**
Show the instrument stays quiet on the healthy case too. Something that always fires is
not a detector; something that never fires is not a gate.

**3. Print the denominator next to the verdict.**
How many rows, bytes, files did it actually examine? A 401 with no body read as a clean
PRIVACY verdict. An argv overflow made `grep -c` return a confident, plausible `0`. Ten
libraries entered a ratcheted gate inventory on a filename substring — the census's own
denominator was wrong by ten the whole time.

**4. Check the fixture is the wire.**
A green non-vacuous gate whose fixture encodes a false assumption about the real payload
guards nothing (#1221). Mutation-provable is not the same as true.

**5. Ask where it is blind, and write that down.**
Every instrument has a blind spot. One that has never named its own is not a measured
instrument, it is a hopeful one. Say it in the code, next to the check.

## Then ask what could make it dark

Green is not the only failure mode. An instrument can also stop running:

- **A missing dependency.** `setup-ci` installs no packages; `gate_census` raised
  `ModuleNotFoundError`, was swallowed to `None`, and the job reported `success` while
  leaving main drifted — twice.
- **A `⚠` and `exit 0`.** A piped step exits with `tail`'s status. Both AI gates printed
  a warning and the job passed.
- **A schedule that never fires.** A cron that never fires is never armed, so nothing it
  guards is ever checked and nothing notices.
- **A window it never runs in.** A time-dependent gate shipped green because CI ran at
  13:00 PT; the test fails 7 of every 24 hours and broke main a day later on someone
  else's commit.
- **Local-only state.** A check that reads a path present on one machine and no clean
  checkout will pass locally and fail in CI — or worse, the reverse.

## Record it

A gate the repo relies on is registered in `docs/CONVENTIONS.md` §9 with its defect class
and where the proof lives. Per §9a: *a gate that can fail is not yet a gate that guards.*
The mutation evidence is the artifact, not the green run.
