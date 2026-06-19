# Hevy routine specs — folder convention

Per-routine build specs, organized into **type folders** so a session only loads the folder
it needs (e.g. building a push day reads `push/` only). Keeps coaching context lean.

```
program/routines/
  push/      pull/      legs/
  upper/     lower/     engine/      conditioning/
  README.md  ← this file (convention + index)
```

**One file per routine version.** Filename mirrors the Hevy title convention
`Phase - Type - N - Y` → `foundation_legs_w1.md`. Bump the file when the routine materially changes.

**Each spec file holds:**
- Metadata: phase, type, Hevy `routine_id`, target date, status, tier.
- Exercise list with **per-exercise notes** (the annotation standard — every exercise carries
  intent), sets × reps, load (or "feeler"), rest.
- Progression levers currently in play (load / reps / rest / tempo / cardio intent).
- Short changelog.

**Annotation standard (enforced):** no bare sets. Cardio states an explicit intent and rotates
(recovery / steady / intervals / long-hard). Accessories get a focus/tempo/hold cue. Rest is a
programmed variable, tightened over weeks. Warm-up cues before key lifts.

---

## Index (active)

| Type | File | Hevy routine_id | Status |
|------|------|-----------------|--------|
| legs | `legs/foundation_legs_w1.md` | a98f6295-0e6e-42b5-86da-93df6eb854a8 | committed (2026-06-18) |

*(append as routines are built)*
