"""#1940 — the correction is STATED, not just applied.

#1892 withdrew citations that pointed at papers which did not support the claims
attached to them, and shipped a guard so it cannot recur. It deliberately left the
reader-facing statement out: silently swapping in "Open question" text fixes the
future and says nothing about the past.

Two things are load-bearing here and both are tested:

1. **The published number cannot drift from the data.** The notice does not
   contain a hardcoded count — `correctionNotice()` derives it from the payload it
   just rendered. These tests pin the SAME derivation against the config
   registries, so withdrawing another citation without updating the page is
   impossible by construction rather than by discipline.

2. **A withdrawn citation carries no url by design** (the #1892 contract), and the
   card renderer filters sources on `x.url`. That is exactly why the correction
   was invisible: the data was right and the page could not show it. If that
   filter is ever the only path again, `test_withdrawn_entries_are_rendered`
   fails.
"""

import json
import os
import re

REPO = os.path.join(os.path.dirname(__file__), "..")
JS = os.path.join(REPO, "site", "assets", "js", "evidence_body.js")


def _load(name):
    with open(os.path.join(REPO, "config", name), encoding="utf-8") as fh:
        return json.load(fh)


def _supplement_withdrawn():
    """Withdrawn source entries on the supplement registry — the number the page shows."""
    sup = _load("supplement_registry.json")
    out = []
    for gname, g in sup["groups"].items():
        for item in g["items"]:
            for s in item.get("sources") or []:
                if not s.get("url") and re.search(r"withdrawn", str(s.get("title") or ""), re.I):
                    out.append(f"{gname}:{item['key']}")
    return out


def _experiment_withdrawn():
    exp = _load("experiment_library.json")
    out = []
    for e in exp["experiments"]:
        for fld in ("evidence_for", "evidence_against"):
            for s in e.get(fld) or []:
                if isinstance(s, dict) and not s.get("url") and re.search(r"withdrawn", str(s.get("title") or ""), re.I):
                    out.append(e.get("id") or e.get("key"))
    return out


# ── the number cannot drift ──────────────────────────────────────────────────
def test_notice_derives_its_count_and_never_hardcodes_it():
    """The count in the notice must come from the payload, not from a literal.

    A hardcoded number is the whole failure mode: the data changes, the sentence
    doesn't, and the page states something false about its own honesty.
    """
    js = open(JS, encoding="utf-8").read()
    body = js[js.index("function correctionNotice") : js.index("export function renderSupplements")]
    assert "withdrawnCount(d)" in body, "the notice must derive its count from the payload"
    # No bare 2-digit count literal in the sentence-building code.
    assert not re.search(r"\b(2[0-9]|1[0-9])\b(?![0-9])\s*(?:citations|withdrawn)", body), "the notice must not hardcode a count"


def test_supplement_registry_still_carries_the_withdrawn_set():
    """If this drops to zero the notice disappears — which is correct only if the
    withdrawals were genuinely reverted, never because a marker was reworded."""
    assert len(_supplement_withdrawn()) > 0


# A withdrawal that was later re-resolved to a real supporting paper and restored.
# It still counts toward the documented total — the withdrawal HAPPENED — but it is no
# longer a live "Open question" in the registry, so the reconciliation has to carry it
# explicitly rather than let the published number quietly shrink.
_RESTORED_SINCE = {
    # #1983, 2026-08-04 — Talbott et al., J Int Soc Sports Nutr 2013 resolves and does
    # support the claim; #1892 withdrew the URL, not the underlying study.
    "tongkat-ali-recovery",
}


def test_documented_total_reconciles_across_both_registries():
    """#1940 states 23. That number spans TWO registries — 21 on supplements and 2
    on experiments (tongkat-ali-recovery, berberine-glucose). Counting only the
    supplements payload understates it, which is precisely the drift this box
    exists to prevent. A restored withdrawal stays in the total and moves into
    _RESTORED_SINCE, so the published number can only change deliberately."""
    sup, exp = _supplement_withdrawn(), _experiment_withdrawn()
    total = len(sup) + len(exp) + len(_RESTORED_SINCE)
    assert total == 23, f"documented total is 23; registries now hold {len(sup)}+{len(exp)} live + {len(_RESTORED_SINCE)} restored"
    assert len(exp) + len(_RESTORED_SINCE) == 2, "the experiments half of the correction must not silently vanish"


def test_a_restored_withdrawal_is_disclosed_to_the_reader():
    """Un-withdrawing is itself a correction. If a claim moves back from 'Open
    question' to cited, the notice has to say so — otherwise the page silently
    walks back a published statement, which is the #1940 failure in reverse."""
    js = open(JS, encoding="utf-8").read()
    if not _RESTORED_SINCE:
        return
    assert "restored" in js, "a restored withdrawal must be disclosed in the correction notice"
    assert "4 August 2026" in js, "the restoration must carry its own date, not hide under the original one"


def test_the_notice_names_the_experiments_half():
    """The page can only count its own payload, so the sentence must say the rest
    out loud or the reader gets a number smaller than the correction."""
    js = open(JS, encoding="utf-8").read()
    assert "experiments registry" in js, "the notice must disclose the withdrawals it cannot count"


# ── the correction must be visible, not merely present ───────────────────────
def test_withdrawn_entries_are_rendered_despite_carrying_no_url():
    """The exact reason the correction was invisible: withdrawn sources have no
    url, and the card filters sources on x.url."""
    js = open(JS, encoding="utf-8").read()
    assert "const isWithdrawn" in js
    assert "withdrawnList" in js, "withdrawn entries must render, not be filtered away"
    assert "supp-srcs--withdrawn" in js


def test_evidence_note_reaches_the_card():
    """NAC and myo-inositol explain why they cite nothing — that explanation has to
    reach the page, not sit in the payload (#1940 acceptance)."""
    js = open(JS, encoding="utf-8").read()
    assert "evidence_note" in js and "supp-evnote" in js


def test_items_with_no_surviving_citation_explain_themselves():
    """Mirrors the #1892 guard from the reader's side: any item whose citations were
    all withdrawn must carry an evidence_note, or the card shows an unexplained gap."""
    sup = _load("supplement_registry.json")
    missing = []
    for gname, g in sup["groups"].items():
        for item in g["items"]:
            live = [s for s in item.get("sources") or [] if s.get("url")]
            withdrawn = [
                s for s in item.get("sources") or [] if not s.get("url") and re.search(r"withdrawn", str(s.get("title") or ""), re.I)
            ]
            if withdrawn and not live and not item.get("evidence_note"):
                missing.append(f"{gname}:{item['key']}")
    assert not missing, f"item(s) with every citation withdrawn and no explanation: {missing}"


def test_notice_states_the_machine_check_that_makes_it_a_fixed_class():
    """#1940 acceptance: the note must read as a fixed class, not a one-off tidy-up."""
    js = open(JS, encoding="utf-8").read()
    body = js[js.index("function correctionNotice") : js.index("export function renderSupplements")]
    assert "resolved title" in body, "must state that surviving citations store the resolved paper title"
    assert "PubMed" in body, "must state that citations are re-resolved (machine-checked)"
