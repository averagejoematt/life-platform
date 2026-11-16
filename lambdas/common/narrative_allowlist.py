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
  * never for a row whose generation read a goals-file field that is not public-safe (``goals_field_privacy``,
    owner ruling 2026-11-10 item 6) — the 14 sealed calls read the plan digest, every field of which is public-safe;
  * never for an annotated row (``narrative_annotations``): those are served only with their dated correction;
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

#: The CR2 publication switch for these words. ON since the owner's CR2 GO (ruling 2026-11-11, second message, item 1);
#: it opens nothing outside the CR2 scope, which only ``/api/coach_room_words`` enters.
CR2_PUBLIC = True
SCOPE_CR2 = "cr2"
PRODUCER = "owner_allowlist.cr2_historical_2026-11-09"
APPROVED_AT = "2026-11-09"


class Entry(NamedTuple):
    pk: str
    sk: str
    field: str  # the coach-words field the approval covers (``text`` / ``claim_natural``)
    text_sha256: str
    families: tuple  # the record's families; DERIVED_FROM_CITED for a lead read
    #: An owner-ruled call approved only WITH its dated note (owner ruling 2026-11-15): pinned here, beside the hash,
    #: so that removing or emptying the note in ``OWNER_NOTES`` withholds the words instead of serving them bare.
    note_required: bool = False


def _E(pk: str, sk: str, field: str, text_sha256: str, families: tuple = (), note_required: bool = False) -> Entry:
    return Entry(pk, sk, field, text_sha256, tuple(families), bool(note_required))


#: A lead read's families are DERIVED, never listed: ``lead_daily_read.provenance_for`` over the row's own stored
#: ``cited`` block — the prompt's only data, and the same function that stamps a lead read at write time. A cited
#: block that names a private or unclassified field makes the row fail closed.
DERIVED_FROM_CITED = ()


#: 21 lead daily reads + 14 sealed day-one calls. Withheld by the check (and so absent): the three 15 g reads, four
#: reads whose cited figure no longer matches its source record (accuracy hold — owner ruling 2026-11-10 item 4 keeps
#: them excluded; their dated corrections are in ``narrative_annotations``, unapproved), and the two sealed calls the
#: owner's ruling of 2026-11-09 (#5720) keeps private.
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

# ── owner-ruled call wording (owner ruling 2026-11-14, wording batch v1) ───────────────────────────────────────────
#: THE RULING. "This is explicit, record-specific authorization to publish the exact historical output wording for the
#: 13 selected calls, despite the limited private contextual inputs identified in their provenance. This authorization
#: does not extend to the underlying private prompts, source metadata, journal-presence information, mood data, or
#: other historical commentary." And: "Pin publication eligibility to the exact record key and original text hash ...
#: Ensure the ledger and Coaching Room obey the same publication decision ... Do not change historical grades."
#:
#: WHAT THIS IS — and what it is not. These calls are NOT lineage-clean: the read each was extracted from carried a
#: journal-presence line and/or a brief with self-report material, which is why the provenance rule alone withholds
#: them. They are published because the owner read each one and ruled on it, so ``owner_ruled_words`` is an owner
#: exception BY RECORD, not a provenance record: it claims nothing about the inputs and names no family. It is not
#: scoped to a route — the ruling is that every surface obeys one decision — so the ledger, the call pages and the
#: Coaching Room all read these words through the same gate. Only the words are released: the gate still strips any
#: provenance field, and nothing about the prompts or sources is served.
#:
#: 12 of the 13 were listed on 2026-11-14. The final accuracy check (the one the CR2 lead reads went through) held one:
#: its text cites a recovery reading under a date that differs by a day from the public series' dating of the same
#: reading. Keys and hashes only; no words.
#:
#: OWNER RULING 2026-11-15 (#6079) added two, each approved only WITH a dated note (``note_required``): the held call
#: (glucose coach, filed 2026-09-14) with a dated clarification of that date, and the explorer coach's sleep-duration
#: forecast of 2026-09-06 with a prominent explanation of how it was graded. The same ruling keeps the sleep coach's
#: deep-sleep call of 2026-09-15 WITHHELD: it is not listed and must not be.
OWNER_RULED_PUBLIC = True
OWNER_RULED_AT = "2026-11-14"
OWNER_RULED: tuple = (
    _E(
        "COACH#physical_coach",
        "PREDICTION#pred_20260912_tomorrow_s_recovery_score_will_rebound_t",
        "claim_natural",
        "201e391e1026c43f9998480bceada999be392a3ec923a1595570d2bdb16d5dbe",
    ),
    _E(
        "COACH#physical_coach",
        "PREDICTION#pred_20260913_recovery_score_expected_to_be_approximat",
        "claim_natural",
        "3be0116633bcb7b91f3017dc2797b1c71c80667f1d2c5e693338b9d60b415d6b",
    ),
    _E(
        "COACH#sleep_coach",
        "PREDICTION#pred_20260917_deep_sleep_percentage_will_rise_as_zone",
        "claim_natural",
        "20a77b6d889064ad6f023d86ff2c735f44c13a8fe6d5980c9c71f96cadc14b8a",
    ),
    _E(
        "COACH#sleep_coach",
        "PREDICTION#pred_20260917_tonight_s_sleep_duration_will_be_approxi",
        "claim_natural",
        "7168d082629beacb46a414f73e433c81d1485b2ae0e7a7e09d53276a6823509b",
    ),
    _E(
        "COACH#sleep_coach",
        "PREDICTION#pred_20260918_deep_sleep_percentage_will_rise_as_zone",
        "claim_natural",
        "56f4c63e342c95f20d2813082a353b7d43debb80ad5cf988071b1547623f9484",
    ),
    _E(
        "COACH#physical_coach",
        "PREDICTION#pred_20260921_weight_loss_trajectory_from_september_6t",
        "claim_natural",
        "d0841183036a4a2dc49dea14422a64d6fc78965e8c66fcfc8adb7cd7ada17582",
    ),
    _E(
        "COACH#sleep_coach",
        "PREDICTION#pred_20260923_recovery_score_will_be_83_7_tomorrow_8",
        "claim_natural",
        "9b63608b0ba1fff6c4c15a8830a746ac7c08a6bf094f37921c17f47d67024e2f",
    ),
    _E(
        "COACH#sleep_coach",
        "PREDICTION#pred_20260923_sleep_duration_will_be_7_4_hours_tonight",
        "claim_natural",
        "c6895a74198e90949abee0e1c3a6ad17e1f09eeffb7914d75a5024cb4fe41d18",
    ),
    _E(
        "COACH#physical_coach",
        "PREDICTION#pred_20260925_weight_will_continue_to_decline_but_bod",
        "claim_natural",
        "ac96a4e7d454021a5d81360c0e1e411e6be0845cc619c8a810d099af987a13d0",
    ),
    _E(
        "COACH#sleep_coach",
        "PREDICTION#pred_20260925_recovery_will_be_89_1_tomorrow_80_pre",
        "claim_natural",
        "849bf3d206689a582697633a8c4a6dffb63f9b4e3120499f799e06a0c54e1dcc",
    ),
    _E(
        "COACH#sleep_coach",
        "PREDICTION#pred_20260925_sleep_duration_will_be_7_8_hours_tonight",
        "claim_natural",
        "131cd84fa568c17b97f715da16824bae641f94a4bcf8526ab3922ac1813c5848",
    ),
    _E(
        "COACH#sleep_coach",
        "PREDICTION#pred_20260926_recovery_score_will_be_approximately_85",
        "claim_natural",
        "70d1f2bb4381bd1157a2d7cb0094a4e70d4c5706f7222b57390df77ea1e70eb6",
    ),
    # owner ruling 2026-11-15 (#6079): published only with the dated note in ``OWNER_NOTES``
    _E(
        "COACH#glucose_coach",
        "PREDICTION#pred_20260914_recovery_will_soften_to_roughly_59_tomo",
        "claim_natural",
        "1e66333650b40068ae15f9a6f90ea775d5514685f687d7dde183c6c8a5a553c6",
        note_required=True,
    ),
    _E(
        "COACH#explorer_coach",
        "PREDICTION#pred_20260906_sleep_model_expects_approximately_7_hour",
        "claim_natural",
        "b63f90171053f05ee1e8cda02c832eee3c04f3eb7dca8d208117c51d3e8aaffc",
        note_required=True,
    ),
)
OWNER_RULED_INDEX: dict = {(e.pk, e.sk): e for e in OWNER_RULED}
_OWNER_RULED_HASHES: frozenset = frozenset(e.text_sha256 for e in OWNER_RULED)

# ── owner-ruled notes (owner ruling 2026-11-15, #6079) ─────────────────────────────────────────────────────────────
#: THE RULING. Two held calls publish "with the original wording unchanged" beside a clearly marked, dated note — a
#: clarification of the date a cited reading belongs to; an explanation of how the call was graded ("do not present
#: it as an uncomplicated forecasting failure or alter its historical grade"). Two published deep-sleep calls keep
#: their words and grades and gain a note that separates the tested prediction (the direction of deep sleep) from the
#: coach's untested explanation ("don't imply that the evaluation established or refuted the underlying physiological
#: mechanism").
#:
#: WHAT A NOTE IS. The PLATFORM's dated note, ruled by the owner — not the coach's words and not the grader's verdict:
#: ``kind`` names what it does (``clarification`` / ``grading_explanation`` / ``scope``), ``dated`` is the day it was
#: added, ``text`` is the note, ``short`` the one line a surface with no room for the note prints (linking to the
#: call's own page). It carries only figures the served record states, never the coach's words. It changes nothing
#: about the record: status, grade, rule and counts stay exactly as stored.
#:
#: ``required`` (and the entry's own ``note_required``): the words are published ONLY together with this note —
#: ``owner_ruled_words`` refuses the record when its note is missing or empty, and the wire (``web.narrative_publication``)
#: empties the words from any served object that does not carry the note beside them.
NOTE_KINDS = ("clarification", "grading_explanation", "scope")
OWNER_NOTES_AT = "2026-11-15"


class Note(NamedTuple):
    kind: str
    dated: str  # ISO day the note was added
    required: bool
    text: str
    short: str


_SCOPE_NOTE_TEXT = (
    "This grade tests one thing: whether the deep-sleep share rose over the call's window. The reason the call gives for "
    "it \u2014 Zone 2 training volume building and adenosine accumulating \u2014 was not tested. The grade neither "
    "establishes nor refutes that mechanism."
)
_SCOPE_NOTE_SHORT = "The grade tests the direction of deep sleep, not the reason the call gives."

OWNER_NOTES: dict = {
    (
        "COACH#glucose_coach",
        "PREDICTION#pred_20260914_recovery_will_soften_to_roughly_59_tomo",
    ): Note(
        kind="clarification",
        dated="2026-11-15",
        required=True,
        text=(
            "The recovery score of 73 this call cites refers to the night of 12 September and was recorded on the morning "
            "of 13 September; the public recovery series dates that reading 13 September. The call's words are shown as "
            "filed and have not been changed."
        ),
        short="Dated clarification: the 73 it cites is the reading of the morning of 13 September.",
    ),
    (
        "COACH#explorer_coach",
        "PREDICTION#pred_20260906_sleep_model_expects_approximately_7_hour",
    ): Note(
        kind="grading_explanation",
        dated="2026-11-15",
        required=True,
        text=(
            "The grading rule frozen for this call scored its point forecast: about 7 hours, within 1.2 hours either way. "
            "The night came in at 8.4 hours, so the point forecast is graded wrong. The call also stated an 80% interval "
            "of 5.4 to 8.7 hours, and the result fell inside it. Both statements are true. The verdict here evaluates the "
            "point forecast, not whether the interval covered the result, and it has not been changed."
        ),
        short="Graded wrong on its point forecast; its own 80% interval contained the result.",
    ),
    ("COACH#sleep_coach", "PREDICTION#pred_20260917_deep_sleep_percentage_will_rise_as_zone"): Note(
        kind="scope", dated="2026-11-15", required=False, text=_SCOPE_NOTE_TEXT, short=_SCOPE_NOTE_SHORT
    ),
    ("COACH#sleep_coach", "PREDICTION#pred_20260918_deep_sleep_percentage_will_rise_as_zone"): Note(
        kind="scope", dated="2026-11-15", required=False, text=_SCOPE_NOTE_TEXT, short=_SCOPE_NOTE_SHORT
    ),
}


def _note_complete(note: Any) -> bool:
    return (
        isinstance(note, Note)
        and note.kind in NOTE_KINDS
        and isinstance(note.dated, str)
        and len(note.dated) == 10
        and isinstance(note.text, str)
        and bool(note.text.strip())
        and isinstance(note.short, str)
        and bool(note.short.strip())
    )


def _note_required(entry: Entry) -> bool:
    note = OWNER_NOTES.get((entry.pk, entry.sk))
    return bool(entry.note_required) or bool(getattr(note, "required", False))


def _required_note_hashes() -> frozenset:
    return frozenset(e.text_sha256 for e in OWNER_RULED_INDEX.values() if _note_required(e))


def required_words_served() -> bool:
    """True when the gate published, in THIS request, the words of a call ruled "publish only with its note" (the wire
    then checks every object that carries them for the note)."""
    return bool(_SERVED & _required_note_hashes())


#: How many lead daily reads were WRITTEN in the window the record-level check covered (counted read-only from the
#: table, 2026-11-11: 28 rows under COACH#eli_marsh, LEAD_DAILY#2026-10-01..2026-11-03). Served beside the approved
#: reads so the page says "n of 28", never a bare "n" that reads as the whole run (owner ruling 2026-11-11 item 8: do
#: not make a sparse historical section look more complete than the evidence supports).
LEAD_PK = "COACH#eli_marsh"
LEAD_WINDOW: dict = {"from": "2026-10-01", "to": "2026-11-03", "written": 28}

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


PRODUCER_ANNOTATED = "owner_allowlist.cr2_annotated_2026-11-11"
ANNOTATED_APPROVED_AT = "2026-11-11"


def record_for_annotated(item: Any, pk: Any = None) -> Optional[dict]:
    """The provenance record an owner-approved ANNOTATED read is published under — or None (withheld).

    Only when ``narrative_annotations.annotated_words`` would serve the pair (CR2 on and in scope, an approved
    annotation, the words byte-identical, nothing private named, the cited block public): the words then reach the
    route, which serves them only WITH their dated correction. Never for a row that is also on ``APPROVED``."""
    if not active() or not isinstance(item, dict) or NP.PROVENANCE_KEY in item:
        return None
    from common import narrative_annotations as NANN

    if (str(item.get("pk", pk) or ""), str(item.get("sk") or "")) in INDEX:
        return None
    if NANN.annotated_words(item, pk) is None:
        return None
    from coach.lead_daily_read import provenance_for

    families = list(provenance_for(item.get("cited") or [])["families"])
    return {"v": NP.SCHEMA_VERSION, "families": families, "producer": PRODUCER_ANNOTATED, "stamped_at": ANNOTATED_APPROVED_AT}


def record_for(item: Any, pk: Any = None) -> Optional[dict]:
    """The provenance record an approved, unchanged, unrecorded row is published under — or None (withheld)."""
    if not active() or not isinstance(item, dict) or NP.PROVENANCE_KEY in item:
        return None
    entry = INDEX.get((str(item.get("pk", pk) or ""), str(item.get("sk") or "")))
    if entry is None:
        return None
    from common import goals_field_privacy as GFP, narrative_annotations as NANN

    # An annotated read is published only WITH its dated correction (``narrative_annotations.annotated_words``),
    # never as bare words through the gate — even if its key were ever listed here.
    if (entry.pk, entry.sk) in NANN.KEYS:
        return None
    # Owner ruling 2026-11-10 (item 6): a text whose generation read any goals-file field that is not public-safe
    # stays withheld (the inputs it actually had, per the producing commit).
    if not GFP.inputs_public(GFP.goals_inputs_for(entry.pk, entry.sk)):
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


#: The words the gate PUBLISHED under the allowlist in this request (hashes; cleared by ``reset_served`` at every
#: request's start). The wire exemption below is keyed on this set, never on the list alone: a listed row whose
#: words hash to the pinned value but which now carries a private (or any) provenance record is withheld by the gate,
#: is never noted here, and so stays tainted at the wire.
_SERVED: set = set()


def owner_ruled_words(item: Any, pk: Any = None) -> bool:
    """True when ``item`` is one of the owner-ruled calls, exactly as ruled: the listed record key, carrying no
    provenance record of its own, its words byte-identical to the ruled text (SHA-256), and those words naming no
    private activity (a belt — the ruling was made on words that passed that screen). Any scope; fail closed."""
    if not OWNER_RULED_PUBLIC or not isinstance(item, dict) or NP.PROVENANCE_KEY in item:
        return False
    entry = OWNER_RULED_INDEX.get((str(item.get("pk", pk) or ""), str(item.get("sk") or "")))
    if entry is None:
        return False
    text = item.get(entry.field)
    if not isinstance(text, str) or _sha(text) != entry.text_sha256:
        return False
    # Owner ruling 2026-11-15: a call approved WITH a note is published only while that note exists and says something.
    if _note_required(entry) and not _note_complete(OWNER_NOTES.get((entry.pk, entry.sk))):
        return False
    from common import prediction_publication as PP

    return not PP.words_name_private_activity(text)


def owner_note(item: Any, pk: Any = None) -> Optional[dict]:
    """The public note served beside an owner-ruled call's words — ``{kind, dated, required, text, short}`` — or None.

    Only for a record whose words the gate publishes (``owner_ruled_words``) and whose note is complete: a note never
    travels without the words it is about, and (``required``) the words never travel without it."""
    if not owner_ruled_words(item, pk):
        return None
    note = OWNER_NOTES.get((str(item.get("pk", pk) or ""), str(item.get("sk") or "")))
    if note is None or not _note_complete(note):
        return None
    return {"kind": note.kind, "dated": note.dated, "required": bool(note.required), "text": note.text, "short": note.short}


def required_note_for_text(text: Any) -> Optional[str]:
    """For a string that IS the words of a call ruled "publish only with its note": that note's ``text`` (what an
    object serving the words must carry beside them); None for every other string."""
    if not isinstance(text, str) or not OWNER_RULED_PUBLIC:
        return None
    h = _sha(text)
    if h not in _OWNER_RULED_HASHES:
        return None
    for e in OWNER_RULED_INDEX.values():
        if e.text_sha256 == h and _note_required(e):
            note = OWNER_NOTES.get((e.pk, e.sk))
            return note.text if note is not None and _note_complete(note) else ""
    return None


def note_served(item: Any, pk: Any = None) -> None:
    """Record that the gate published ``item``'s approved words in this request (only an approved row, in scope —
    or an owner-ruled call, which is published in every scope)."""
    if isinstance(item, dict) and owner_ruled_words(item, pk):
        _SERVED.add(OWNER_RULED_INDEX[(str(item.get("pk", pk) or ""), str(item.get("sk") or ""))].text_sha256)
        return
    if not active() or not isinstance(item, dict):
        return
    key = (str(item.get("pk", pk) or ""), str(item.get("sk") or ""))
    entry = INDEX.get(key)
    if entry is None:
        # an approved annotated read (served by the route only with its dated correction)
        from common import narrative_annotations as NANN

        a = NANN.INDEX.get(key)
        if a is not None and a.owner_approved and NANN.annotated_words(item, pk) is not None:
            _SERVED.add(a.text_sha256)
        return
    text = item.get(entry.field)
    if isinstance(text, str) and _sha(text) == entry.text_sha256:
        _SERVED.add(entry.text_sha256)


def reset_served() -> None:
    _SERVED.clear()


def is_approved_text(text: Any) -> bool:
    """True, in an active scope, for a string that IS the words of an approved row the gate published in THIS request
    (exempt from a wire taint left by an earlier out-of-scope request in the same container)."""
    if not isinstance(text, str):
        return False
    h = _sha(text)
    return h in _SERVED and (active() or h in _OWNER_RULED_HASHES)
