"""tests/obligation_residue_3597.py — the #3597 obligation-carrier residue ledger.

THE dated, shrink-only record of every obligation block (`revisit …`, `fast-follow`,
`owner decides`, a deferral to later/step N) on a governed surface
(`scripts/obligation_carriers.OBLIGATION_SURFACES`) that carried NO home — no carrier
`#N`, no `not-work —` tag, no calendar-probed date — when the rule landed.

Each key is ``path::<sha256-12 of the cue sentence, digits masked>`` — content-keyed on
purpose (the conformance-residue precedent, #2844): EDITING a pinned obligation's words
re-keys it, surfaces as a NEW unhomed obligation, and the only green path is giving it a
home. Digits are masked so a doc-literal sync rewriting a count does not re-key a row.
Entries only ever come OUT — a key whose block gained a home (or was deleted) must be
removed, and `tests/test_obligation_carriers_3597.py` reds a stale key so the ledger
cannot silently over-state its debt.

Seeded 2026-09-23 by `python3 scripts/obligation_carriers.py --keys` — the sweep's own
output, no hand-typed key. 44 rows: 39 in docs/DECISIONS.md, 5 in docs/PROPORTIONALITY.md,
0 in docs/alarm_citations.json. The trailing comment on each row is the cue sentence at
seeding, for a reviewer — it is not read by anything.

Registered in `scripts/obligation_carriers.RESIDUE_LEDGERS` (carrier, condition, expiry).
"""

OBLIGATION_RESIDUE: dict[str, str] = {
    "docs/DECISIONS.md::66a2714d58f9": "2026-09-23",  # | ADR-029 | MCP Monolith: Retain Single Lambda, Revisit at 100+ Calls/Day | Active | 2026-03-15 |
    "docs/DECISIONS.md::5673a1f5d53c": "2026-09-23",  # Revisit if table grows beyond 10GB or new access patterns emerge.
    "docs/DECISIONS.md::a188255f557c": "2026-09-23",  # Revisit if usage pattern shifts to high-frequency interactive sessions.
    "docs/DECISIONS.md::55dbe6ea2e49": "2026-09-23",  # Revisit if platform ever becomes multi-tenant or processes clinical-grade regulated health data.
    "docs/DECISIONS.md::43247602c759": "2026-09-23",  # Revisit when either:
    "docs/DECISIONS.md::7c76c9675dcb": "2026-09-23",  # **Revisit conditions:**
    "docs/DECISIONS.md::265b9af0f955": "2026-09-23",  # **Revisit trigger defined.** If tool selection accuracy degrades measurably (Claude consistently pic
    "docs/DECISIONS.md::a631509ed3a8": "2026-09-23",  # Revisit only if a model's floor drops or a prompt grows on its own merits; the register's test fires
    "docs/DECISIONS.md::30a48131774c": "2026-09-23",  # Revisit per trigger conditions above.
    "docs/DECISIONS.md::e00332936068": "2026-09-23",  # Revisit only if a second major importer emerges.
    "docs/DECISIONS.md::1e440764aeff": "2026-09-23",  # Revisit only if a 6th+ data type is added.
    "docs/DECISIONS.md::8b5b206203ff": "2026-09-23",  # Revisit only if a new endpoint surfaces an actually-unbounded query.
    "docs/DECISIONS.md::5b2486e235bd": "2026-09-23",  # Revisit only when a second real user is on the horizon.
    "docs/DECISIONS.md::87eb32b6b994": "2026-09-23",  # the deferral posture itself (revisit only when a second real user is on the horizon)
    "docs/DECISIONS.md::5d01fc7c1bc3": "2026-09-23",  # **Revisit trigger:** the operator's `shadow` → `auto` flip.
    "docs/DECISIONS.md::f57c2c65511f": "2026-09-23",  # **Revisit trigger.** Two consecutive quarterly proportionality re-reads with zero `ALLOW-ADDITIVE` l
    "docs/DECISIONS.md::2ad27d8b5d56": "2026-09-23",  # **Revisit trigger.** A stack deploy blocked by a Deny in this document that is judged legitimate → w
    "docs/DECISIONS.md::2e05d0f10b71": "2026-09-23",  # Phase 1 prefers the simpler interpretation; Phase 2 can revisit if the drift turns out to matter.
    "docs/DECISIONS.md::b06ce287ef49": "2026-09-23",  # (Reversible: enabling both is a few CLI/CDK calls; revisit on the triggers below.)
    "docs/DECISIONS.md::7af3c20b944f": "2026-09-23",  # **Revisit triggers:** a second/paying user, an SLA commitment, or the platform becoming something wh
    "docs/DECISIONS.md::0d292c231ecb": "2026-09-23",  # Retained verbatim; see the amendment below.]** **Monitor trigger (revisit this ADR when):** Google s
    "docs/DECISIONS.md::0b8eb0c9f65c": "2026-09-23",  # **The ceiling stays $75 for now, chosen on purpose rather than inherited.** The number is re-affirme
    "docs/DECISIONS.md::1dca3dd01d95": "2026-09-23",  # At 100 board questions/day — far beyond current traffic — the month costs ~$50, which is the point o
    "docs/DECISIONS.md::ea62f60844ce": "2026-09-23",  # **Revisit trigger.** The trigger firing (either arm) re-opens monetization as a deliberate session w
    "docs/DECISIONS.md::438bd3e7485d": "2026-09-23",  # The choice was never recorded, and internal notes justified revisiting it with a premise the 2026-07
    "docs/DECISIONS.md::d24f566c61a2": "2026-09-23",  # **Revisit trigger (concrete, not "someday"):** introduce a READ-SIDE analytical layer (DuckDB/Athena
    "docs/DECISIONS.md::ac77930dcbab": "2026-09-23",  # field_notes keeps its own dict-shaped regen flow (already on the shared guard); the STANCE# writer g
    "docs/DECISIONS.md::c9804a7478e5": "2026-09-23",  # **Revisit only if** Garmin ingestion is restored to a healthy, non-rate-limited cadence — at which p
    "docs/DECISIONS.md::591f9f959d6c": "2026-09-23",  # Future "add an LLM council" proposals are answered by this ADR unless a proposer clears the revisit
    "docs/DECISIONS.md::31dc0266ed03": "2026-09-23",  # Revisit the threshold as the baseline traffic grows — it is one env var, not a code change.
    "docs/DECISIONS.md::9ae37b788b4d": "2026-09-23",  # **The revisit clause's carrier.** `tests/test_cost_governor.py::test_derived_threshold_exceeds_every
    "docs/DECISIONS.md::359e10311f1f": "2026-09-23",  # **Revisit trigger.** Reopen only when BOTH hold: the dose-response engine has armed (≥15 nonzero eve
    "docs/DECISIONS.md::42c130c63b33": "2026-09-23",  # **Revisit trigger (mirrors ADR-057).** Reopen when any of: real multi-user traffic (a second N=1 wit
    "docs/DECISIONS.md::6d49dc1549bd": "2026-09-23",  # **Revisit trigger.** Flip the lane to required (owner toggle + posture-file flip, same PR) when eith
    "docs/DECISIONS.md::03de035d6f9b": "2026-09-23",  # Revisit trigger: if conversation-sourced moves ever dominate a coach's confidence state (conversatio
    "docs/DECISIONS.md::cdfcf00ab73c": "2026-09-23",  # **Revisit when** any of these change: a second contributor (required reviews stop being absurd and s
    "docs/DECISIONS.md::651298774e7e": "2026-09-23",  # Keep brute-force cosine over a single `Query`.** Recorded with a concrete revisit trigger rather tha
    "docs/DECISIONS.md::bf4197e03458": "2026-09-23",  # **Revisit trigger (both conditions, not either).** Revisit when (a) the recall corpus exceeds **~5,0
    "docs/DECISIONS.md::5fecce78918f": "2026-09-23",  # The cost honestly carried: between DEXA scans the floor has no automated tripwire, and full-scan com
    "docs/PROPORTIONALITY.md::e6cd9c13ca46": "2026-09-23",  # | fresh-eyes weekly survey workflow | Portfolio | $ (small) | **This row's own revisit trigger FIRED
    "docs/PROPORTIONALITY.md::1f3a16390c3f": "2026-09-23",  # **Revisit:** measurable reader-audience growth · any accessibility complaint · commercialization |
    "docs/PROPORTIONALITY.md::51b488bd00b9": "2026-09-23",  # **Revisit triggers: a second subject · any external claim of generalization · a published methods ar
    "docs/PROPORTIONALITY.md::bedbff955964": "2026-09-23",  # **Revisit triggers:** a second user of any kind · any claim on the public surface that crosses from
    "docs/PROPORTIONALITY.md::fc23c29c6324": "2026-09-23",  # **The honest residual is recovery TIME, not recoverability.** **Revisit triggers:** a second operato
}
