"""tests/test_personal_context_cases_6291.py — the gate on the coach-context switch (#6291, #6226).

The switch (`coach.coach_context_pilot.LIVE`) is turned on by a one-line change, and only once:
  * every applicable known-answer case passes on BOTH interfaces' real builders with the assembly on (test 1);
  * the assembly's personal context rides the dynamic tail of the Telegram system prompt, never the cached prefix,
    and the prefix is byte-identical with the switch off and on (test 3);
  * a failed read never breaks a turn (test 4);
  * the Claude session packet and the Telegram chat are handed the same sections (test 5).
Test 2 pins what the builders hand a coach TODAY with the switch off (and the brief, which does not consume the
assembly): those FAILs are the reason for the switch. A production builder fixed later flips a pin — update the pin
and the matrix in the PR body together.

All fixtures are synthetic (`tests/personal_context_cases_6291.py`); no AWS, no model, the clock pinned.
"""

from __future__ import annotations

import os

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

import personal_context_cases_6291 as h  # noqa: E402

# What the builders hand a coach today, with the switch OFF (and the brief): case -> {column: verdict}.
PINNED_OFF = {
    1: {"telegram/off": "fail", "packet/off": "fail", "brief": "fail"},  # brief: the scan's fields are read off the wrong level (null)
    2: {"telegram/off": "fail", "packet/off": "fail", "brief": "fail"},
    3: {"telegram/off": "fail", "packet/off": "fail", "brief": "n/a"},
    4: {"telegram/off": "fail", "packet/off": "fail", "brief": "n/a"},
    5: {"telegram/off": "fail", "packet/off": "fail", "brief": "fail"},
    6: {"telegram/off": "pass", "packet/off": "pass", "brief": "pass"},  # #6149 already wired corrections everywhere
    7: {"telegram/off": "fail", "packet/off": "fail", "brief": "pass"},
    8: {"telegram/off": "fail", "packet/off": "n/a", "brief": "n/a"},
    9: {"telegram/off": "fail", "packet/off": "fail", "brief": "n/a"},  # #6294: the assembly alone reads his profile disputes
}

NEEDLES = (h.SCAN_LEAN, h.WORDS["decision"], h.WORDS["correction"], h.WORDS["record"], h.WORDS["note"], "IMPLIED BY HIS WEIGHT CHANGE")


def test_every_applicable_case_passes_with_the_assembly_on():
    """Mutation: drop a section from `build_turn_context` (scan / intake / latest message), restore 'These are HIS
    priorities' to the decisions header, or stop `packet_context` rendering the assembly — each reds its case."""
    failures, applicable = [], 0
    for case in h.CASES:
        for col in ("telegram/on", "packet/on"):
            r = h.run_case(case, col)
            assert not r.get("writes"), (case.n, col, r["writes"])
            assert not r.get("unsupported"), (case.n, col, r["unsupported"])
            if r["verdict"] == "n/a":
                continue
            applicable += 1
            if r["verdict"] != "pass":
                failures.append((case.n, case.name, col, r["why"]))
    assert applicable == 17, applicable  # #6294: case 9 on both interfaces
    assert not failures, failures


def test_the_switch_off_matrix_is_pinned():
    """The current builders, as observed. Mutation: wire the scan into the brief's physical data correctly, or give
    the off-switch Telegram memory a platform-memory block — the pin flips and must be updated with the matrix."""
    observed = {c.n: {col: h.run_case(c, col)["verdict"] for col in PINNED_OFF[c.n]} for c in h.CASES}
    assert observed == PINNED_OFF


def test_the_switch_is_committed_off():
    """The switch is turned on only after the cases pass and the owner has seen the dry render (#6291 acceptance)."""
    from coach import coach_context_pilot

    assert coach_context_pilot.LIVE is False


def test_personal_context_rides_the_dynamic_tail_never_the_cached_prefix():
    """Mutation: move `memory_block` into `coach_chat._system_parts`' prefix — the needles land in the cached block,
    and the prefix stops being byte-identical across the switch (every turn would bust the cache)."""
    on = h.render_telegram(h.StoreTable(h.synthetic_store()), h.LEAD, pilot=True)
    off = h.render_telegram(h.StoreTable(h.synthetic_store()), h.LEAD, pilot=False)
    nut = h.render_telegram(h.StoreTable(h.synthetic_store()), "nutrition_coach", pilot=True)
    leaked = [n for n in NEEDLES if n in on.cached_prefix or n in nut.cached_prefix]
    assert not leaked, leaked
    assert on.cached_prefix == off.cached_prefix
    for n in (h.WORDS["decision"], "3c. LOGGED INTAKE"):
        assert n in nut.text, n


class _Broken(h.StoreTable):
    def query(self, **kw):
        raise ConnectionError("synthetic read failure")

    def get_item(self, **kw):
        raise ConnectionError("synthetic read failure")


def test_a_failed_read_never_breaks_a_turn():
    """Mutation: remove `_safe` around a section, or the try in `scan_section` / `intake_section` — the render raises."""
    from coach import coach_context_pilot as pilot

    tg = h.render_telegram(_Broken([]), h.LEAD, pilot=True)
    assert "6. WHAT YOU CAN AND CANNOT REMEMBER" in tg.text
    with h.hermetic(_Broken([]), pilot=True):
        ctx = pilot.build_turn_context(_Broken([]), "nutrition_coach", h.TODAY, memory="", thread=[])
        pkt = pilot.packet_context(_Broken([]), h.TODAY, live=True)
    assert ctx["sections"]["capability"] and not ctx["sections"]["body_composition"] and not ctx["sections"]["intake"]
    assert pkt["state"] in ("measured", "read_failed")


def test_one_assembly_both_interfaces():
    """The packet's `text` and the Telegram memory are the SAME sections for the lead seat; only the three lines worded
    per interface differ. Mutation: give `packet_context` its own reads instead of `build_turn_context`."""
    from coach import coach_context_pilot as pilot, personal_context as pc

    table = h.StoreTable(h.synthetic_store())
    with h.hermetic(table, pilot=True):
        memory = pc.memory_core(table, h.LEAD)
        thread = pilot.thread_turns(pc.chat_rows(table, h.LEAD), live=True)
        tg = pilot.build_turn_context(table, h.LEAD, h.TODAY, memory=memory, thread=thread)
        se = pilot.build_turn_context(table, h.LEAD, h.TODAY, memory=memory, thread=thread, channel="session")
        packet = pilot.packet_context(table, h.TODAY, live=True)
    worded = {"thread_dates", "capability", "latest_message"}
    assert set(tg["sections"]) == set(se["sections"])
    differ = {k for k in tg["sections"] if tg["sections"][k] != se["sections"][k]}
    assert differ <= worded, differ
    assert packet["text"] == se["memory"]
    for k in ("priorities", "body_composition", "intake", "notes", "corrections"):
        assert tg["sections"][k], k  # every shared section is populated by the synthetic store
    assert not table.writes


def test_seats_read_only_their_facts():
    """A seat outside the scan / intake sets gets neither section and spends no read on it."""
    from coach import personal_context as pc

    table = h.StoreTable(h.synthetic_store())
    with h.hermetic(table, pilot=True):
        assert pc.scan_section(table, "sleep_coach", h.TODAY) == "" and pc.intake_section(table, "sleep_coach", h.TODAY) == ""
        assert table.queries == 0
        assert pc.intake_section(table, "physical_coach", h.TODAY) == ""
        assert "3b." in pc.scan_section(table, "physical_coach", h.TODAY)
        empty = h.StoreTable([])
        assert "No body-composition scan is stored" in pc.scan_section(empty, h.LEAD, h.TODAY)
        assert "Not computable today" in pc.intake_section(empty, h.LEAD, h.TODAY)
