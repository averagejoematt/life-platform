"""Owner-approved historical coach words for the Coaching Room's CR2 layer (owner ruling 2026-11-09, D).

THE RULING. "Prepare the 16 sealed calls + 25 clean lead reads for CR2, subject to a final record-level
provenance and privacy check. Confirm actual source lineage, not merely current classification ... NOT
authorization to release all of CR2; remaining historical coach material stays withheld."

WHAT THIS IS. Every narrative row written before 2026-11-03 carries no provenance record, so the narrative gate
(``web.narrative_publication``) withholds it. ``APPROVED`` names, BY RECORD KEY, the rows the record-level check
passed: their generation lineage was traced to public inputs only (the sealed pre-registration packet; the lead
read's stored ``cited`` block in a single model call). Each entry pins the SHA-256 of the approved field's text,
so a row whose words changed after the check is not the row that was approved. No text is stored here — the repo
is public; the check's evidence is in the owner's private record (provenance_v2_cr2), not in this file.

HOW THE GATE HONOURS IT — fail closed at every step (``record_for``):
  * only while ``CR2_PUBLIC`` is on AND the request runs inside ``serving(SCOPE_CR2)``. Today the switch is OFF and
    no route enters the scope: CR2 is dark, and every live surface reads these rows exactly as before;
  * only for a row with NO provenance record — a row that carries one (a private family, an unrecorded input, a
    malformed record) is decided by that record, allowlisted or not;
  * only when (pk, sk) is listed AND the field's text hashes to the pinned value;
  * never when the words name private activity (``prediction_publication.words_name_private_activity``) — a belt;
  * the record it returns (a sealed call's listed families; a lead read's families derived from its own stored
    ``cited`` block) must still pass ``narrative_provenance.eligibility`` like any stamped row.

Adding a row is an owner decision with its own record-level check; flipping ``CR2_PUBLIC`` is the CR2 release.
"""

from __future__ import annotations

import contextlib
import contextvars
import hashlib
from typing import Any, Iterator, NamedTuple, Optional

from common import narrative_provenance as NP

#: The CR2 publication switch for these words. OFF until the owner's CR2 GO (tests pin it off on main).
CR2_PUBLIC = False
SCOPE_CR2 = "cr2"
PRODUCER = "owner_allowlist.cr2_historical_2026-11-09"
APPROVED_AT = "2026-11-09"


class Entry(NamedTuple):
    pk: str
    sk: str
    field: str  # the coach-words field the approval covers (``text`` / ``claim_natural``)
    text_sha256: str
    families: tuple  # the record's families; DERIVED_FROM_CITED for a lead read


def _E(pk: str, sk: str, field: str, text_sha256: str, families: tuple = ()) -> Entry:
    return Entry(pk, sk, field, text_sha256, tuple(families))


#: A lead read's families are DERIVED, never listed: ``lead_daily_read.provenance_for`` over the row's own stored
#: ``cited`` block — the prompt's only data, and the same function that stamps a lead read at write time. A cited
#: block that names a private or unclassified field makes the row fail closed.
DERIVED_FROM_CITED = ()


#: 21 lead daily reads + 14 sealed day-one calls. Withheld by the check (and so absent): the three 15 g reads, four
#: reads whose cited figure no longer matches its source record (accuracy hold), and the two sealed calls the owner's
#: ruling of 2026-11-09 (#5720) keeps private.
APPROVED: tuple = (
    _E(
        "COACH#eli_marsh",
        "LEAD_DAILY#2026-10-01",
        "text",
        "8f1a3649071984a7ff0953b24a29eeada3769f8e3bd6581d91edb8f1fb654296",
    ),
    _E(
        "COACH#eli_marsh",
        "LEAD_DAILY#2026-10-03",
        "text",
        "6248c3152183decad7c5bf6d18bcc16d044c587471664538ac9e71837fd3f88b",
    ),
    _E(
        "COACH#eli_marsh",
        "LEAD_DAILY#2026-10-04",
        "text",
        "625ba7c197f9190e29bbc6497228210484d1a58512ec13fa89ccc21624b60e93",
    ),
    _E(
        "COACH#eli_marsh",
        "LEAD_DAILY#2026-10-05",
        "text",
        "abef491750c5097d84810544390579f79b50d271cd9032ec0ae72c307f1948a2",
    ),
    _E(
        "COACH#eli_marsh",
        "LEAD_DAILY#2026-10-06",
        "text",
        "acdc8a5247158de1878e2b81237a7354cb7c7ac493ea6238479746bdcc30c1b4",
    ),
    _E(
        "COACH#eli_marsh",
        "LEAD_DAILY#2026-10-08",
        "text",
        "25c2fa6975fb8c407405c4e0cc109b1d04de39026228b698f7db6afc54d541cf",
    ),
    _E(
        "COACH#eli_marsh",
        "LEAD_DAILY#2026-10-09",
        "text",
        "eadf7efe4ee243418d8731e61afc3fa7153632aa6d0331675c2d06fb1e28d33d",
    ),
    _E(
        "COACH#eli_marsh",
        "LEAD_DAILY#2026-10-10",
        "text",
        "42f73fbf63353d5e8150b0da3e92bfd0e771cb59621124e6f775557d0e9ad377",
    ),
    _E(
        "COACH#eli_marsh",
        "LEAD_DAILY#2026-10-12",
        "text",
        "deecf924345b7c275465866fd9e77cf7ee3100bc2f1020b000f53605700e9165",
    ),
    _E(
        "COACH#eli_marsh",
        "LEAD_DAILY#2026-10-13",
        "text",
        "5308236f5b07ec66b8b1b495538e670f3cad12613dc59424f11adbf114b03680",
    ),
    _E(
        "COACH#eli_marsh",
        "LEAD_DAILY#2026-10-14",
        "text",
        "86eed73ffd9b8510415632ebdeded488f5a6927388d84b017b4bd2a06345fdfe",
    ),
    _E(
        "COACH#eli_marsh",
        "LEAD_DAILY#2026-10-15",
        "text",
        "4da7bbd3938576e9afc0aa11bc5f7160c5cf4efabc2fa0651e2fd503f42d0c68",
    ),
    _E(
        "COACH#eli_marsh",
        "LEAD_DAILY#2026-10-16",
        "text",
        "67275952caa5f0b77220199be748e97a8e9d627b7d6832decee996dc93b4a6f4",
    ),
    _E(
        "COACH#eli_marsh",
        "LEAD_DAILY#2026-10-18",
        "text",
        "cbd1c435e1cb550035e1bef4a663bd78aff381648dc35651bbd5329e49624612",
    ),
    _E(
        "COACH#eli_marsh",
        "LEAD_DAILY#2026-10-19",
        "text",
        "de5282c57996444262cb92bbda5bf1cb36758e846af4b3c1235c412bef3061e7",
    ),
    _E(
        "COACH#eli_marsh",
        "LEAD_DAILY#2026-10-24",
        "text",
        "d9dcf2c41dcee6e6b37781b4d7e843e7dc4e1677a06f8d9763fe79843385ffc6",
    ),
    _E(
        "COACH#eli_marsh",
        "LEAD_DAILY#2026-10-25",
        "text",
        "e88797dfd73a7985636a6828062edc625a1247eede33f97fdabfac9028444a56",
    ),
    _E(
        "COACH#eli_marsh",
        "LEAD_DAILY#2026-10-27",
        "text",
        "4ca01f6bd5fa8ff24c99fcfbce2067e50416b6fafd255e41296ea7250441b482",
    ),
    _E(
        "COACH#eli_marsh",
        "LEAD_DAILY#2026-11-01",
        "text",
        "30a322c0bcc68035da8366cbdbea051cac453d05d52ee54fbcbce92c26bd19d6",
    ),
    _E(
        "COACH#eli_marsh",
        "LEAD_DAILY#2026-11-02",
        "text",
        "a99c2f42ee5ac88694c9df4005d2819f9f9bf8d7412a0534176691738d88453b",
    ),
    _E(
        "COACH#eli_marsh",
        "LEAD_DAILY#2026-11-03",
        "text",
        "022c2fdc05f4a395192de11eb27e72b200ca43b80f18f0bd405655e97513d9c8",
    ),
    _E(
        "COACH#explorer_coach",
        "PREDICTION#pred_20260906_as_an_n_1_statistician_establishing_a_cl",
        "claim_natural",
        "fb136e63e1f28fdc1aab5ca9d0be4b72309d135d6abb72ad9f5c510f2827e2d5",
        ("experiments", "persona"),
    ),
    _E(
        "COACH#explorer_coach",
        "PREDICTION#pred_20260906_with_the_ramp_discipline_rule_mandating",
        "claim_natural",
        "11b588047bb62de61a007b59e72cc8b2b0af9a446182d77800dfa20e2788f1f9",
        ("experiments", "persona"),
    ),
    _E(
        "COACH#glucose_coach",
        "PREDICTION#pred_20260906_the_combination_of_the_8_hour_eating_win",
        "claim_natural",
        "c5104c38d61749896c91ed981c4b2c6cdc2018eedc91b6c3ae138503e179a2ef",
        ("experiments", "persona"),
    ),
    _E(
        "COACH#glucose_coach",
        "PREDICTION#pred_20260906_with_a_strict_11_30am_7_30pm_eating_wind",
        "claim_natural",
        "92688f75179f3b7e5829d4f854b8225ba39fd83695188812956e393ac9cb6155",
        ("experiments", "persona"),
    ),
    _E(
        "COACH#labs_coach",
        "PREDICTION#pred_20260906_with_7_5_hours_of_nightly_sleep_bed_9_0",
        "claim_natural",
        "eb3a1d492a537c95edb8f347db9d7593abcf1ebc3172be60c99c357ff9dd8bac",
        ("experiments", "persona"),
    ),
    _E(
        "COACH#labs_coach",
        "PREDICTION#pred_20260906_with_a_structured_8_hour_eating_window",
        "claim_natural",
        "9bc9c55b9599649d4d8b24138f1f168c6bc1c1f16ccce40c63c4c8bf037a04c9",
        ("experiments", "persona"),
    ),
    _E(
        "COACH#mind_coach",
        "PREDICTION#pred_20260906_hrv_7_day_average_will_trend_upward_over",
        "claim_natural",
        "3a5ae8c899028810b051c583c037a6483d413bd6641d2a229cd3a40320f5d3db",
        ("experiments", "persona"),
    ),
    _E(
        "COACH#nutrition_coach",
        "PREDICTION#pred_20260906_adherence_to_the_1500_kcal_day_target_wi",
        "claim_natural",
        "c2de37c8733e26ee11b51d3a253d6f7fcd42b6e9a7e20500b3fa7c7e57c85f9f",
        ("experiments", "persona"),
    ),
    _E(
        "COACH#nutrition_coach",
        "PREDICTION#pred_20260906_with_a_strict_1500_kcal_day_intake_and_a",
        "claim_natural",
        "032439aa82a5aa6ae2558188881ebd2f4651e9639525c5d0c9fbe57eea4b2743",
        ("experiments", "persona"),
    ),
    _E(
        "COACH#physical_coach",
        "PREDICTION#pred_20260906_daily_step_counts_will_consistently_meet",
        "claim_natural",
        "42201e650552d7f061081c4eea67ed0e8aa15cb977b3537249412a72e00f2cbc",
        ("experiments", "persona"),
    ),
    _E(
        "COACH#physical_coach",
        "PREDICTION#pred_20260906_starting_from_326_2_lbs_on_day_1_body_w",
        "claim_natural",
        "0d313f0cee76a6f1ba426e4ca6ddfdddd2523ebdc5efadebfbd53f55a257a25a",
        ("experiments", "persona"),
    ),
    _E(
        "COACH#sleep_coach",
        "PREDICTION#pred_20260906_the_ramp_discipline_in_week_1_reduced",
        "claim_natural",
        "da78c4ac59570ae8196d5079d5dd9f63666dc5d0ecc685d8340f5bc6f4a9df57",
        ("experiments", "persona"),
    ),
    _E(
        "COACH#sleep_coach",
        "PREDICTION#pred_20260906_with_a_fixed_bed_time_of_9_00_pm_and_wak",
        "claim_natural",
        "c6e16f3d3d2289f67c29cf1aab8f9d26df87b5b3e68c93622c1d463d29b0eadf",
        ("experiments", "persona"),
    ),
    _E(
        "COACH#training_coach",
        "PREDICTION#pred_20260906_with_the_ramp_discipline_rule_requiring",
        "claim_natural",
        "e5858d36f33caa3416dbc631b289e8c56b8892f2d1a93fa687aa22a101e62e14",
        ("experiments", "persona"),
    ),
)

INDEX: dict = {(e.pk, e.sk): e for e in APPROVED}

_SCOPE: contextvars.ContextVar = contextvars.ContextVar("narrative_allowlist_scope", default=None)


@contextlib.contextmanager
def serving(scope: str) -> Iterator[None]:
    """Run a request's reads inside ``scope`` (only ``SCOPE_CR2`` is honoured, and only with the switch on)."""
    token = _SCOPE.set(scope)
    try:
        yield
    finally:
        _SCOPE.reset(token)


def active() -> bool:
    return bool(CR2_PUBLIC) and _SCOPE.get() == SCOPE_CR2


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def record_for(item: Any, pk: Any = None) -> Optional[dict]:
    """The provenance record an approved, unchanged, unrecorded row is published under — or None (withheld)."""
    if not active() or not isinstance(item, dict) or NP.PROVENANCE_KEY in item:
        return None
    entry = INDEX.get((str(item.get("pk", pk) or ""), str(item.get("sk") or "")))
    if entry is None:
        return None
    text = item.get(entry.field)
    if not isinstance(text, str) or _sha(text) != entry.text_sha256:
        return None
    from common import prediction_publication as PP

    if PP.words_name_private_activity(text):
        return None
    families = list(entry.families)
    if not families:
        from coach.lead_daily_read import provenance_for

        families = list(provenance_for(item.get("cited") or [])["families"])
    return {"v": NP.SCHEMA_VERSION, "families": families, "producer": PRODUCER, "stamped_at": APPROVED_AT}


_APPROVED_HASHES = frozenset(e.text_sha256 for e in APPROVED)


def is_approved_text(text: Any) -> bool:
    """True, in an active scope, for a string that IS an approved row's words (exempt from a wire taint left by an
    earlier out-of-scope request in the same container)."""
    return active() and isinstance(text, str) and _sha(text) in _APPROVED_HASHES
