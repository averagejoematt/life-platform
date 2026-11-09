"""web/verification_fields.py — the additive verification fields of the public call routes (owner 2026-11-09).

WHAT IS SERVED (additive; no existing field or label changes):

  * per item on ``/api/ledger_export`` and ``/api/predictions`` — ``item_fields``:
      ``evaluator_version``  the row's stored ``evaluator_version`` stamp (null when the row has none);
      ``algo_version``       the version that WROTE the grade text (``outcome_notes.algo_version``, null when absent);
      ``verification``       ``{outcome, verified_at, ruleset_version, classification_validated}`` read off the row's
                             ``latest_verification`` pointer (``coach.verification_record``) — NULL when the call has
                             no verification record. Never inferred from a version number.
  * top level on both routes — ``verification_summary``: ``{reproduced, corrected, could_not_verify, none}`` counted
    over the SAME rows the route's own total counts (the ledger's served items; ``/api/predictions``' season rows).
  * ``/api/calibration`` — ``verification_summary`` (``headline``, CR1, owner ruling 2026-11-09): the verified
    headline — only calls whose latest VERIFY# record reproduced their grade (or its recorded correction) AND whose
    approved classification keeps them as a checkable forecast, counted once — with the "nothing changes" baseline
    and an exact sign test on EXACTLY those calls, the exclusions by category from the eligible total down to N, the
    archived first grading and the counted call ids. The same ``verified`` object is ``platform.strata.coaches.verified``;
    each coach's own subset is ``coaches[].verified``. Null until a verification record exists in the eligible set.

PRIVACY. Every number here is taken over rows the route already counts — and those reach a handler only through
``web.narrative_publication.PublicationTable``, which omits a private (journal / State of Mind / diary-derived) call
and every row naming one — its VERIFY# record included — before any handler runs (``common.prediction_publication``,
method v2). A VERIFY# record is only ever read through the pointer of a public call it names, so it cannot add a
call: ``tests/test_call_publication_privacy.py`` walks every route with and without private verified calls.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Iterable

from coach import classification_review, coach_baseline, coach_record, grade_corrections, verification_record
from common import stats_core
from experiment import calibration_core
from experiment.phase_filter import singleton_visible

SUMMARY_KEYS = verification_record.OUTCOMES + ("none",)


def item_fields(row: dict) -> dict:
    ver = (row or {}).get("evaluator_version")
    return {
        "evaluator_version": None if ver is None else str(ver),
        "algo_version": grade_corrections.grade_text_version(row or {}),
        "verification": verification_record.served(row or {}),
    }


def summary(verifications: Iterable[Any]) -> dict:
    """Counts by outcome over served ``verification`` objects (``None`` = no record)."""
    out = {k: 0 for k in SUMMARY_KEYS}
    for v in verifications:
        out[v["outcome"] if isinstance(v, dict) and v.get("outcome") in verification_record.OUTCOMES else "none"] += 1
    return out


def attach_stratum_extras(platform: dict, strata_pairs: dict, verified: dict | None = None) -> None:
    """Owner 2026-11-09, additive — changes no existing field. Each season stratum gains:

    * ``accuracy_pct`` / ``accuracy_ci95`` (95% Wilson) — ``calibration_core.score_pairs`` over the stratum's OWN
      pairs, the same function ``score_strata`` scores each stratum with (``n`` is already served beside them);
    * ``verified`` — the coaches' verified-only numbers: the ``verified`` object of ``headline`` (CR1), passed in by
      the route that read the VERIFY# records. Null when not passed — the edition's narrow sweep reads no VERIFY#
      record and serves none (no reader of the edition reads it) — and null for the hypothesis and forecast strata,
      which have no verification record.

    Computed here, not in ``experiment.calibration_core``, so the scorer, its OSS parity vectors and its methods
    fingerprint are untouched."""
    for name, stratum in (platform.get("strata") or {}).items():
        scored = calibration_core.score_pairs(strata_pairs.get(name) or [])
        stratum["accuracy_pct"] = scored["accuracy_pct"]
        stratum["accuracy_ci95"] = scored["accuracy_ci95"]
        stratum["verified"] = verified if name == "coaches" else None


# ── the verified headline, the exclusions and the archive (owner ruling 2026-11-09, CR1) ─────────────────────────
#
# THE RULING (in part, verbatim). "The primary message should be: 'Of 75 forecasts that could be checked under the
# current rules, the coaches got 38 right (51%). A simple prediction that nothing would change got 40 right (53%). The
# coaches have not demonstrated an advantage over that baseline.' Use the final verified figures if the approved
# corrections change the denominator." Every figure below is COMPUTED from the rows; no count is a literal.
#
# WHICH CALLS COUNT. A public, this-cycle call (``coach_record`` scope, not under classification review) graded right
# or wrong now OR at its first grade is in the ELIGIBLE set. It is COUNTED when:
#   1. its owner classification — the ``classification`` map of the VERIFY# record its ``latest_verification`` pointer
#      names (``coach.verification_record``) — is APPROVED and keeps it as a checkable forecast;
#   2. its grade is right or wrong NOW (a call corrected to "could not be graded" has left the record);
#   3. that latest VERIFY# record says ``reproduced`` or ``corrected``;
#   4. it is not a repeat of an earlier counted forecast (counted once).
# Every other eligible call lands in exactly ONE category of ``excluded_by_category`` (``category_of``), so
# ``eligible_total == verified.n + excluded_total`` and the categories sum to ``excluded_total`` — by construction,
# pinned by tests/test_verification_headline_cr1.py.
#
# The categories are read off the stored classification records: ``CATEGORY_OF_VALUE`` maps the classification
# VOCABULARY the rulings use to a reader category — never a list of call ids. An unknown value, or a classification
# that is not approved, is "not yet classified" (fail closed: never counted). No category names a private family:
# private calls never reach this module (``web.call_publication``) and the test pins that no key or label could.

#: The classification values that keep a call as a checkable forecast.
CHECKABLE_VALUES = frozenset({"keep", "keep_tested_conditional", "in_headline", "checkable", "forecast"})

#: The reader categories, in the order the accounting lists them, with their plain-English labels.
EXCLUDED_CATEGORIES = (
    ("not_a_forecast", "Not a forecast: the outcome was already on the record when the call was made"),
    ("past_period", "About a past period whose data arrived later: kept as a look back, not a forecast"),
    ("opinion", "An opinion, explanation or hedge: not a measurable forecast"),
    ("different_claim", "The stored test checks a different claim from the words"),
    ("stand_in_measure", "Graded on a stand-in measure that cannot show the claim"),
    ("either_outcome", "Either outcome satisfies the words"),
    ("condition_not_measured", "Depends on a condition that was never measured, or names no checkable direction"),
    ("condition_never_happened", "Its condition never happened, so it was never tested"),
    ("docket", "Head-to-head docket bets, settled by their own rule and audited separately"),
    ("could_not_verify", "Could not be verified under the current rules"),
    ("not_yet_classified", "Not yet classified under the current rules"),
    ("repeat", "The same forecast repeated: counted once"),
)
CATEGORY_LABELS = dict(EXCLUDED_CATEGORIES)

#: The classification vocabulary → the reader category it excludes a call under.
CATEGORY_OF_VALUE = {
    "not_a_forecast": "not_a_forecast",
    "past_period_unobserved": "past_period",
    "past_period": "past_period",
    "noc_interpretation": "opinion",
    "noc_hedged": "opinion",
    "opinion": "opinion",
    "noc_spec_mismatch": "different_claim",
    "different_claim": "different_claim",
    "noc_proxy": "stand_in_measure",
    "stand_in_measure": "stand_in_measure",
    "noc_either_way": "either_outcome",
    "either_outcome": "either_outcome",
    "noc_untested_condition": "condition_not_measured",
    "noc_direction_only": "condition_not_measured",
    "untested": "condition_not_measured",
    "condition_not_measured": "condition_not_measured",
    "cond_void": "condition_never_happened",
    "condition_never_happened": "condition_never_happened",
    "docket": "docket",
    "already_ruled": "could_not_verify",
    "expired_now": "could_not_verify",
    "held_pending_antecedent": "could_not_verify",
    "could_not_verify": "could_not_verify",
    "folded": "repeat",
    "repeat": "repeat",
    "duplicate": "repeat",
}

#: The VERIFY# attributes the calibration route reads (projected; the rest of the audit row never leaves the table).
VERIFY_PROJECTION = ("sk", "prediction_id", "outcome", "verified_at", "classification")

COUNTED = "counted"
FIRST_GRADE_LABEL = "As first graded, before the eligibility and verification rules were corrected"


def _status(value: Any) -> str | None:
    s = str(value or "").strip().lower()
    return s if s in coach_record.GRADED_STATUSES else None


def first_status(row: dict) -> str | None:
    """The call's FIRST grade (right / wrong), from ``original_grade`` when the row was ever corrected."""
    og = (row or {}).get("original_grade")
    if isinstance(og, dict) and og:
        return _status(og.get("status") or og.get("outcome"))
    return now_status(row)


def now_status(row: dict) -> str | None:
    return _status((row or {}).get("status") or (row or {}).get("outcome"))


def eligible_rows(rows: Iterable[dict], *, genesis: str | None) -> list[dict]:
    """The public, this-cycle calls graded right or wrong now or at their first grade, one per call, none under
    classification review — the accounting's starting total. ``rows`` are one coach partition as served (already
    publication-filtered by ``web.call_publication``)."""
    out = []
    for row in coach_record.resolved_once(rows or []):
        if not isinstance(row, dict) or classification_review.is_under_review(row):
            continue
        if first_status(row) is None and now_status(row) is None:
            continue
        if not singleton_visible(row):
            continue
        od = str(row.get("outcome_date") or "")[:10]
        if genesis and od and od < genesis:
            continue
        out.append(row)
    return out


def verify_records_by_sk(records: Iterable[dict]) -> dict:
    """``{sk: VERIFY# row}`` for one coach's audit rows (a malformed row is skipped)."""
    return {str(r.get("sk")): r for r in records or [] if isinstance(r, dict) and str(r.get("sk") or "").startswith("VERIFY#")}


def latest_record(row: dict, by_sk: dict) -> dict | None:
    """The VERIFY# row the call's ``latest_verification`` pointer names — the call's latest verification record."""
    lv = (row or {}).get(verification_record.POINTER_ATTR)
    if not isinstance(lv, dict):
        return None
    return by_sk.get(str(lv.get("sk") or ""))


def _classification_map(row: dict, record: dict | None) -> dict | None:
    for src in (record, (row or {}).get(verification_record.POINTER_ATTR)):
        c = src.get("classification") if isinstance(src, dict) else None
        if isinstance(c, dict) and c.get("value"):
            return c
    return None


def classification(row: dict, record: dict | None) -> tuple[str | None, bool]:
    """``(value, approved)`` — the owner classification stored on the latest VERIFY# record (or on the pointer, should
    a later schema copy it there). Only an approved value with a ruling reference is a ruling."""
    c = _classification_map(row, record)
    if not c:
        return None, False
    approved = bool(c.get("approved")) and bool(str(c.get("ruling_ref") or "").strip())
    return str(c["value"]).strip().lower(), approved


def category_of(row: dict, record: dict | None) -> str:
    """``COUNTED`` (before repeats are folded) or the ONE excluded category of an eligible call."""
    value, approved = classification(row, record)
    category = CATEGORY_OF_VALUE.get(value or "") if approved else None
    if category and category != "repeat":
        return category
    if now_status(row) is None:
        return "could_not_verify"  # graded once, corrected since to "could not be graded"
    if not verification_record.is_verified(row) or record is None:
        return "could_not_verify"
    if not approved:
        return "not_yet_classified"
    if category == "repeat":
        return "repeat"
    return COUNTED if value in CHECKABLE_VALUES else "not_yet_classified"


def _family(row: dict, record: dict | None) -> str | None:
    c = _classification_map(row, record) or {}
    fam = str(c.get("family") or "").strip()
    return fam or None


def _pct(k: int, n: int) -> float | None:
    return round(100.0 * k / n, 1) if n else None


def _pct_whole(k: int, n: int) -> int | None:
    if not n:
        return None
    return int((Decimal(100 * k) / Decimal(n)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _wilson(k: int, n: int) -> list | None:
    ci = stats_core.wilson_interval(k, n)
    return [round(100.0 * ci[0], 1), round(100.0 * ci[1], 1)] if ci else None


def _rule_right(row: dict) -> bool:
    """Was "nothing changes" right on this call? A call it could not be scored on counts as its miss (the owner's
    headline: "they count as guess misses"). Read through ``coach_baseline.effective``: a recorded re-score under the
    current rule (owner ruling 2026-11-09, A) overlays the frozen stamp, which itself is never rewritten."""
    bl = coach_baseline.effective(row or {})
    return isinstance(bl, dict) and bl.get("rule") == coach_baseline.RULE_ID and bl.get("right") is True


def _rule_scored(row: dict) -> bool:
    bl = coach_baseline.effective(row or {})
    return isinstance(bl, dict) and bl.get("rule") == coach_baseline.RULE_ID and isinstance(bl.get("right"), bool)


NO_SAME_CALL_COMPARISON = "No same-call comparison with a simple prediction that nothing would change is published for these calls yet."


def stored_rule_versions(rows: list[dict]) -> dict | None:
    """``{version: calls}`` of the STORED "nothing changes" stamps on ``rows`` — None when any call has no stamp of the
    rule with a version (then a same-call comparison as stored cannot be guaranteed, and none is served)."""
    out: dict = {}
    for r in rows:
        bl = coach_baseline.effective(r or {})
        if not isinstance(bl, dict) or bl.get("rule") != coach_baseline.RULE_ID or bl.get("version") is None:
            return None
        v = str(bl["version"]).split(".")[0] if isinstance(bl["version"], (int, float, Decimal)) else str(bl["version"])
        out[v] = out.get(v, 0) + 1
    return out


def corrected_rows(rows: list[dict]) -> list[dict]:
    """The calls whose frozen "nothing changes" verdict carries a recorded re-score (owner ruling 2026-11-09, A)."""
    return [r for r in rows if coach_baseline.baseline_corrections(r or {})]


def stored_rule_words(versions: dict, corrected: list[dict] | None = None) -> str:
    vs = sorted(versions)
    which = f"version {vs[0]}" if len(vs) == 1 else "versions " + ", ".join(vs)
    if not corrected:
        return f"Scored by the rule's {which}, as stored when each call was graded; earlier verdicts have not been restated."
    n = len(corrected)
    days = sorted({str(coach_baseline.baseline_corrections(r)[-1].get("corrected_at") or "")[:10] for r in corrected} - {""})
    when = f" on {days[0]}" if len(days) == 1 else ""
    calls = "call" if n == 1 else "calls"
    return (
        f"Scored by the rule's {which}, as stored when each call was graded, except {n} {calls} whose stored verdict was"
        f" frozen under an earlier rule: those were re-scored under the current rule{when}, and the original verdicts are kept"
        " on the record."
    )


def headline_sentence(n: int, k: int, rule_right: int | None, verdict: str | None) -> str:
    """The one sentence a reader could repeat, generated from the numbers (the owner's wording, 2026-11-09). An
    advantage is claimed only from the tested comparison (the sign test), never from a point estimate."""
    calls = "forecast" if n == 1 else "forecasts"
    s = f"Of {n} {calls} that could be checked under the current rules, the coaches got {k} right ({_pct_whole(k, n)}%). "
    if rule_right is None:
        return s + NO_SAME_CALL_COMPARISON
    s += f"A simple prediction that nothing would change got {rule_right} right ({_pct_whole(rule_right, n)}%). "
    if verdict == "coaches_better":
        return s + "The coaches did better than that baseline, by more than chance would explain."
    if verdict == "rule_better":
        return s + "That baseline did better than the coaches, by more than chance would explain."
    if verdict == "too_few":
        return s + "That is too few forecasts to tell whether the coaches have an advantage over that baseline."
    return s + "The coaches have not demonstrated an advantage over that baseline."


def counted_block(rows: list[dict], *, with_sentence: bool = True) -> dict | None:
    """The verified numbers over the COUNTED calls: the coaches, the "nothing changes" baseline on EXACTLY these calls,
    and an exact two-sided sign test on the calls only one of the two got right. None on an empty set."""
    rows = [r for r in rows or [] if now_status(r)]
    n = len(rows)
    if not n:
        return None
    k = sum(1 for r in rows if now_status(r) == "confirmed")
    out: dict = {
        "n": n,
        "confirmed": k,
        "accuracy_pct": _pct(k, n),
        "accuracy_ci95": _wilson(k, n),
        "pct_rounded": _pct_whole(k, n),
    }
    versions = stored_rule_versions(rows)
    if versions is None:
        # A call without a stored "nothing changes" stamp: no same-call comparison can be guaranteed, so none is served.
        out.update(baseline_pct_rounded=None, sign_test=None, baseline={"available": False, "n": n, "text": NO_SAME_CALL_COMPARISON})
        if with_sentence:
            out["sentence"] = headline_sentence(n, k, None, None)
            out["skill"] = {"n": n, "sentence": NO_SAME_CALL_COMPARISON}
            out["comparison"] = None
        return out
    rule = sum(1 for r in rows if _rule_right(r))
    scored = sum(1 for r in rows if _rule_scored(r))
    coach_only = sum(1 for r in rows if now_status(r) == "confirmed" and not _rule_right(r))
    rule_only = sum(1 for r in rows if _rule_right(r) and now_status(r) != "confirmed")
    p = stats_core.exact_sign_test_p(coach_only, rule_only)
    if n < coach_baseline.MIN_N_FOR_RATE:
        verdict = "too_few"
    elif p is not None and p < coach_baseline.SIGNIFICANCE:
        verdict = "coaches_better" if coach_only > rule_only else "rule_better"
    else:
        verdict = "no_clear_difference"
    unscored = n - scored
    base_text = f"A simple prediction that nothing would change got {rule} of the same {n} right ({_pct_whole(rule, n)}%)."
    if unscored:
        base_text += f" It could not be scored on {unscored} of them, which count as its misses."
    corrected = corrected_rows(rows)
    base_text += f" {stored_rule_words(versions, corrected)}"
    out.update(
        {
            "baseline_pct_rounded": _pct_whole(rule, n),
            "baseline": {
                "available": True,
                "rule": coach_baseline.RULE_ID,
                # Coordinator 2026-11-09: the comparison is the verdicts AS STORED at grading time (never restated here),
                # with the stored rule version(s) named; restating them waits on an owner decision.
                # Owner ruling 2026-11-09 (A): the stored verdicts, with any recorded re-score under the current rule
                # overlaid ("stored" when there is none); the frozen stamps themselves are never rewritten.
                "basis": "stored_with_corrections" if corrected else "stored",
                "corrected": len(corrected),
                "rule_versions": versions,
                "current_rule_version": coach_baseline.RULE_VERSION,
                "n": n,
                "right": rule,
                "accuracy_pct": _pct(rule, n),
                "accuracy_ci95": _wilson(rule, n),
                "unscorable": unscored,
                "text": base_text,
            },
            "sign_test": {
                "coach_only": coach_only,
                "rule_only": rule_only,
                "n": coach_only + rule_only,
                "k": coach_only,
                "p": round(p, 4) if p is not None else None,
                "verdict": verdict,
                "test": "exact two-sided sign test on the calls only one of the two got right (McNemar's exact test)",
            },
        }
    )
    if with_sentence:
        sentence = headline_sentence(n, k, rule, verdict)
        out["sentence"] = sentence
        out["skill"] = {"n": n, "sentence": sentence.rsplit(". ", 1)[-1]}
        out["comparison"] = {"n": n, "records": coach_baseline.comparison_block(rows)["records"]}
    return out


VERIFY_JOB = "__verify__:"  # a `_parallel_fetch` job-key prefix — never a short coach id


def add_verify_jobs(jobs: dict, coach_pks: dict, query) -> None:
    """Add each coach's VERIFY# read (projected, paginated) to ``/api/calibration``'s concurrent fetch. Read through the
    same governed table, so a private call's record never arrives; a record is joined only through a public pointer."""
    for cid, pk in coach_pks.items():
        jobs[VERIFY_JOB + cid] = lambda pk=pk: query(pk, verification_record.VERIFY_PREFIX, VERIFY_PROJECTION, paginate=True)


def fetch_with_headline(jobs: dict, coach_ids: dict, _g: dict) -> tuple[dict, dict | None]:
    """``/api/calibration``'s ONE concurrent fetch, plus each coach's VERIFY# read: ``(fetched, headline)`` with the
    VERIFY# results popped out of ``fetched`` (the route's own jobs come back exactly as before). ``coach_ids`` =
    {short id: partition coach id}; ``_g`` = the route's injectable globals (its fetch, query and genesis)."""
    parallel_fetch, query, genesis = _g["_parallel_fetch"], _g["_query_partition"], _g["EXPERIMENT_START"]
    coach_pks = {cid: f"COACH#{full}" for cid, full in coach_ids.items()}
    add_verify_jobs(jobs, coach_pks, query)
    failed: list = []
    fetched = parallel_fetch(jobs, failures=failed)
    return fetched, headline_of(fetched, failed, list(coach_pks), genesis=genesis)


def headline_of(fetched: dict, failed: list, cids: list, *, genesis: str | None) -> dict | None:
    """Pop the VERIFY# reads out of ``fetched`` and build the headline — None when ANY coach or VERIFY# read failed (a
    partial read never publishes a partial headline)."""
    verify = {cid: fetched.pop(VERIFY_JOB + cid, []) for cid in cids}
    if any(k in cids or str(k).startswith(VERIFY_JOB) for k in failed):
        return None
    return headline({cid: fetched.get(cid) or [] for cid in cids}, verify, genesis=genesis)


def headline(rows_by_coach: dict, verify_by_coach: dict, *, genesis: str | None) -> dict | None:
    """``verification_summary`` for ``/api/calibration``. ``rows_by_coach`` = {short coach id: the served PREDICTION#
    rows}, ``verify_by_coach`` = {short coach id: the served VERIFY# rows}. None until a call in the eligible set
    carries a verification record (nothing to publish yet, so nothing is)."""
    eligible: list[tuple[str, str, dict, dict | None]] = []
    for cid in sorted(rows_by_coach):
        by_sk = verify_records_by_sk(verify_by_coach.get(cid) or [])
        for row in eligible_rows(rows_by_coach.get(cid) or [], genesis=genesis):
            eligible.append((f"{cid}-{grade_corrections.prediction_id(row)}", cid, row, latest_record(row, by_sk)))
    if not any(verification_record.served(row) for _k, _c, row, _rec in eligible):
        return None

    cats = {key: category_of(row, rec) for key, _c, row, rec in eligible}
    # repeats: within a family the earliest counted forecast stands; the rest are the same forecast, counted once
    seen: set = set()
    for key, _c, row, rec in sorted(eligible, key=lambda t: (str(t[2].get("created_at") or t[2].get("created_date") or ""), t[0])):
        fam = _family(row, rec)
        if cats[key] != COUNTED or not fam:
            continue
        if fam in seen:
            cats[key] = "repeat"
        seen.add(fam)

    counted = [(key, cid, row) for key, cid, row, _rec in eligible if cats[key] == COUNTED]
    verified = counted_block([row for _k, _c, row in counted])
    tally = {c: 0 for c, _label in EXCLUDED_CATEGORIES}
    for cat in cats.values():
        if cat != COUNTED:
            tally[cat] += 1

    first = [row for _k, _c, row, _rec in eligible if first_status(row)]
    ak, an = sum(1 for r in first if first_status(r) == "confirmed"), len(first)
    n = verified["n"] if verified else 0
    return {
        "eligible_total": len(eligible),
        "verified": verified,
        "excluded_by_category": [{"key": c, "label": label, "n": tally[c]} for c, label in EXCLUDED_CATEGORIES if tally[c]],
        "excluded_total": sum(tally.values()),
        "counted_calls": sorted(key for key, _c, _r in counted),
        "by_coach": {cid: counted_block([r for _k, c, r in counted if c == cid], with_sentence=False) for cid in sorted(rows_by_coach)},
        "archive": {
            "label": FIRST_GRADE_LABEL,
            "n": an,
            "confirmed": ak,
            "accuracy_pct": _pct(ak, an),
            "accuracy_ci95": _wilson(ak, an),
        },
        "outcomes": summary(verification_record.served(row) for _k, _c, row, _rec in eligible),
        "why_changed": (
            "The record changed because the rules for which calls count, and for re-checking each grade, were corrected"
            f" — not because the coaches improved. As first graded, the coaches were right on {ak} of {an} calls"
            f"{f' ({_pct_whole(ak, an)}%)' if an else ''}. Under the current rules {n} of the {len(eligible)} graded calls"
            " qualify, and every call left out is listed with the reason."
        ),
        "rules": (
            "Counted: a public call graded right or wrong whose latest verification record reproduced its grade (or the "
            "recorded correction of it) and whose approved classification keeps it as a checkable forecast, counted once "
            "per forecast. The simple prediction that nothing would change is scored on exactly the same calls; a call it "
            "could not be scored on counts as its miss. Intervals are 95% Wilson intervals; the comparison is an exact "
            "two-sided sign test on the calls only one of the two got right. Calls that share a metric and a window are "
            "not independent, so both are optimistic."
        ),
    }
