"""ask_retrieval.py — #2348 (epic #1080): the reader's question finally selects context.

THE DEFECT. `/api/ask` did no retrieval. `site_api_ai_lambda._ask_fetch_context()` is a
fixed six-block fetch iterated over a hardcoded tuple, `_ask_build_prompt(ctx)` takes no
question, and there was not one embedding reference anywhere in `lambdas/web/`. Two
readers asking opposite questions got byte-identical context; the only thing that varied
was the model's own paraphrase of the same snapshot.

WHAT THIS ADDS. One relevance-selected block on top of that snapshot: the published
chronicle passages whose Titan-v2 embedding is closest to THIS question. It is additive
and strictly subordinate — the fixed six blocks still run, and when retrieval declines
(budget pause, no embedding, empty corpus, nothing clears the bar, any error at all) the
prompt is byte-identical to today's. `tests/test_ask_retrieval_2348.py` pins that parity.

REUSE, NOT A PARALLEL SUBSTRATE. Every moving part already existed: `bedrock_client.
embed_text` (the ADR-062 chokepoint), `semantic_recall.{load_corpus,cosine,
rank_precedents,reconcile_precedent}` (the base64-float32 codec + brute-force cosine
ADR-150 re-affirmed), and `ai_calls._semantic_recall_for_coach`'s posture — budget-gated,
fail-soft, returns an empty block rather than raising into the caller. This module is the
reader-facing arm of that same machinery, not a second one.

PUBLISHED ONLY (AC1). The recall corpus deliberately spans resets and holds installments
that no longer have a reader page (a wiped prior cycle stays in the index because
cross-cycle memory is the point). Those must never reach a reader through an answer, so
the filter here is DERIVED from the writer's own publication test rather than restated:
`recall_indexer.published_post_links` emits a link ONLY for a phase-visible, published
installment, so "has an openable link" IS "is published". A row with no link is dropped,
and `PUBLISHED_KINDS` classifies the kind namespace so a corpus kind added upstream
(coach output, journal) cannot silently start leaking into reader answers — the guard
test derives its case list from `semantic_recall.KINDS`, so a new kind fails until it is
classified.

MEASURED, NOT ASSUMED (ADR-105). Every call returns telemetry alongside the block and
logs one line: status, n (the published corpus size the scores were computed over), the
top cosine, the separation z, how many passages were selected, and the wall-clock ms.
Retrieval that cannot say whether it hit is indistinguishable from retrieval that never
ran — that is the #1927 dark-gate failure mode, and it is what the log line prevents.

THE BAR IS PARTLY VARIANCE-DERIVED, AND THE ABSOLUTE HALF IS HONESTLY UNCALIBRATED.
ADR-105 asks for thresholds from variance rather than magic numbers, so the primary test
is separation: the top score must sit `ASK_RETRIEVAL_Z_MIN` standard deviations above the
mean of the WHOLE published corpus. That is scale-free — it asks "is this passage
distinctively closer than the rest?", which is exactly the AC4 question (a question with
no relevant archive content must get the honest answer, not the best of a uniform mess).
The z-test needs a distribution to be meaningful, so under MIN_STATS_N rows it is not
computed at all and the gate falls back to the absolute floor alone; `basis` in the
telemetry says which test actually ran, every time.

The absolute floor (`ASK_RETRIEVAL_FLOOR`) is the honest weak point: calibrating a
query-to-document cosine cutoff requires real Titan query embeddings against the live
corpus, i.e. Bedrock spend on production traffic, which has not happened — so the default
is a STARTING VALUE, not a measurement, and nothing in this module or the PR claims
otherwise. It is env-overridable without a code change, and because the top cosine is
logged on every request including the misses, the first weeks of traffic supply the
distribution that sets it properly. Both knobs are read per call (never frozen at import)
so an override takes effect on the next invocation.

CORPUS SIZE, MEASURED 2026-08-10 against the live table (read-only Query): 19 rows, all
kind=chronicle, 256-dim, of which 3 carry a published link. So the reader-visible corpus
is n=3 TODAY and this block will be absent from most answers until more installments
publish — which is the honest state of the archive, not a failure of the gate. Brute
force over n of that order is arithmetically free (ADR-150's revisit trigger is ~5,000
rows AND >500 ms p95 on a synchronous reader path); the cost that matters is the ONE
extra `embed_text` round trip per question, which is why the whole thing sits behind the
budget gate and the endpoint's existing 5/hr/IP rate limit.
"""

from __future__ import annotations

import logging
import os
import statistics
import time

from ai import semantic_recall as sr

logger = logging.getLogger(__name__)

# The corpus kinds a READER may be shown. `semantic_recall.KINDS` also carries coach
# outputs and journal enrichments — internal narrative that has no published page — so
# the reader-facing set is an explicit allow-list, not "everything in the partition".
#
# #2587 moved the decision itself into `semantic_recall.READER_KIND_DECISIONS` (one entry
# per kind, derived into a tuple, so a new kind is excluded until someone decides) because
# the chronicle recall card is a SECOND reader surface reading the same corpus. This name
# stays as the local vocabulary; the value is now derived rather than restated, so the two
# reader surfaces cannot drift apart.
PUBLISHED_KINDS: tuple[str, ...] = sr.READER_KINDS

# Defaults. Read through the helpers below (never frozen into module globals) so an env
# override on the Lambda takes effect on the next invocation rather than the next deploy.
DEFAULT_TOP_K = 3
DEFAULT_FLOOR = 0.35
DEFAULT_Z_MIN = 1.5

# Below this many published rows the separation statistic has no distribution to speak
# of, so it is not computed and the telemetry reports `basis="floor"` instead of quietly
# implying a test that did not run.
MIN_STATS_N = 5

# How much of a passage reaches the prompt. The stored snippet is already capped at 280
# chars by `semantic_recall.make_embedding_item`; this is the prompt-side cap so three
# passages can never crowd out the CURRENT DATA block they are meant to supplement.
SNIPPET_CHARS = 240


def _env_float(name: str, default: float) -> float:
    """One env-override read, fail-soft to `default` on anything unparseable."""
    try:
        raw = os.environ.get(name, "")
        return float(raw) if raw else default
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        raw = os.environ.get(name, "")
        return int(raw) if raw else default
    except (TypeError, ValueError):
        return default


def published_corpus(corpus) -> list:
    """The subset of the recall corpus a reader may be shown (AC1).

    Two conditions, both derived rather than restated: the doc's kind is in
    `PUBLISHED_KINDS`, and it carries an openable link — which the writer
    (`recall_indexer.published_post_links`) emits ONLY for a phase-visible published
    installment. `safe_link` additionally strips the retired `/chronicle/week-N/` form
    (#1827), so a legacy row cannot smuggle a 404 in as evidence of publication.
    """
    out = []
    for doc in corpus or []:
        if (doc or {}).get("kind") not in PUBLISHED_KINDS:
            continue
        if not sr.safe_link(doc.get("link", "")):
            continue
        out.append(doc)
    return out


def similarity_stats(scores) -> dict:
    """The distribution of `scores`, with n on every claim (ADR-105).

    `z` is (top - mean) / population sd — how far the best match stands out from the
    corpus it was chosen from. It is None (and `basis` is "floor") whenever the sample is
    under MIN_STATS_N or the scores are degenerate (sd == 0): the arithmetic would happily
    return a z from three points, and that z would be a number with no evidence behind it.
    """
    vals = [float(s) for s in (scores or [])]
    n = len(vals)
    if n == 0:
        return {"n": 0, "top": None, "mean": None, "sd": None, "z": None, "basis": "empty"}
    top = round(max(vals), 4)
    mean = round(statistics.fmean(vals), 4)
    sd = round(statistics.pstdev(vals), 4) if n >= 2 else 0.0
    z = round((top - mean) / sd, 3) if (n >= MIN_STATS_N and sd > 0) else None
    return {"n": n, "top": top, "mean": mean, "sd": sd, "z": z, "basis": "floor+z" if z is not None else "floor"}


def select_passages(query_vector, corpus, *, top_k: int | None = None, floor: float | None = None, z_min: float | None = None):
    """(passages, telemetry) for one question vector over one corpus. Pure: no AWS, no
    Bedrock, deterministic — same vector + same corpus ⇒ same passages AND same scores.

    The gate is two-part and reported honestly in `telemetry["basis"]`:
      - the top cosine must clear the absolute `floor` (an uncalibrated starting value —
        see the module docstring), and
      - when there are MIN_STATS_N or more published rows, it must ALSO stand `z_min`
        standard deviations above the corpus mean, so "best of a uniform mess" reads as
        the miss it is (AC4).
    A miss returns [] — never the highest-scoring irrelevant passage.
    """
    top_k = _env_int("ASK_RETRIEVAL_TOP_K", DEFAULT_TOP_K) if top_k is None else top_k
    floor = _env_float("ASK_RETRIEVAL_FLOOR", DEFAULT_FLOOR) if floor is None else floor
    z_min = _env_float("ASK_RETRIEVAL_Z_MIN", DEFAULT_Z_MIN) if z_min is None else z_min

    pub = published_corpus(corpus)
    scores = [round(sr.cosine(query_vector, doc.get("vector") or []), 4) for doc in pub]
    tel = similarity_stats(scores)
    tel.update({"n_corpus": len(corpus or []), "floor": floor, "z_min": z_min, "selected": 0})

    if not scores:
        tel["status"] = "miss:no-published-corpus"
        return [], tel
    if tel["top"] is None or tel["top"] < floor:
        tel["status"] = "miss:below-floor"
        return [], tel
    if tel["z"] is not None and tel["z"] < z_min:
        tel["status"] = "miss:no-separation"
        return [], tel

    # The ordering/tie-breaking/rounding contract lives in `rank_precedents` and is
    # reused rather than re-implemented here, which does mean the cosines are computed
    # twice: once above for the DISTRIBUTION (every published row, including the ones the
    # threshold will drop — a statistic over survivors would be a different, useless
    # number) and once inside the ranker for the SELECTION. Measured at 256 dims that is
    # ~1 ms per 19 rows, so paying it twice buys one canonical ranker for free.
    passages = sr.rank_precedents(query_vector, pub, top_k=top_k, threshold=floor)
    tel["selected"] = len(passages)
    tel["status"] = "hit" if passages else "miss:below-floor"
    return passages, tel


def render_block(passages) -> str:
    """The prompt block for the selected passages — "" for none, so an empty retrieval
    adds NOTHING to the prompt (byte-identical to the pre-#2348 prompt) and the model is
    never handed an empty heading it could be tempted to fill.

    Every line is dated, scored and linked: the reader can open what the answer leans on
    (AC2), and the rules keep a dated excerpt from being narrated as today's value.
    """
    kept = [p for p in (passages or []) if sr.safe_link((p or {}).get("link", ""))]
    if not kept:
        return ""
    lines = [
        "",
        f"ARCHIVE PASSAGES ({len(kept)} excerpt(s) selected by embedding similarity to THIS question, "
        "from PUBLISHED installments only — each shown with its cosine score and its page):",
    ]
    for p in kept:
        sim = p.get("similarity")
        sim_txt = f"{sim:.2f}" if isinstance(sim, (int, float)) else "?"
        snippet = " ".join(str(p.get("snippet", "")).split())[:SNIPPET_CHARS]
        lines.append(f"  - {p.get('date', '')} (similarity {sim_txt}, page {sr.safe_link(p.get('link', ''))}): {snippet}")
    lines.append(
        "ARCHIVE RULES: these are DATED EXCERPTS from past published installments, not the current state — "
        "attribute any number in them to its date and never present it as today's value. You may cite these "
        "dates and link the page shown; never invent a passage, a date or a URL, and never quote an installment "
        "that is not listed here. If these passages do not answer the question, say the archive doesn't cover it "
        "rather than stretching one to fit."
    )
    return "\n".join(lines) + "\n"


def retrieve_block(question: str, *, table=None, top_k: int | None = None):
    """(prompt_block, telemetry) for one reader question. NEVER raises.

    Same posture as `ai_calls._semantic_recall_for_coach` (budget-gated, fail-soft,
    returns an empty block): a budget pause, a missing module, an embedding failure, an
    empty corpus or any exception at all yields ("", telemetry-with-a-status), and the
    endpoint then behaves exactly as it did before this shipped. Retrieval is an
    enhancement on a synchronous reader path — it may cost the reader a block, never the
    answer.

    Budget: gated on the EXISTING `semantic_recall` feature (band 2, ADR-125) rather than
    a new name. The ladder's audience ordering already says what to do here — this is a
    reader-narrative enhancement, so it pauses before the endpoint itself (`website_ai`,
    band 3) does. Tier 2 therefore degrades /api/ask to its fixed snapshot instead of
    taking it dark.
    """
    t0 = time.perf_counter()
    tel: dict = {"status": "skipped", "n": 0, "top": None, "z": None, "selected": 0, "resolved": 0}
    block = ""
    try:
        if not (question or "").strip():
            tel["status"] = "skipped:no-question"
            return "", _stamp(tel, t0)
        try:
            from ai.budget_guard import allow as _budget_allow

            if not _budget_allow("semantic_recall"):
                tel["status"] = "skipped:budget"
                return "", _stamp(tel, t0)
        except ImportError:
            pass

        from ai import bedrock_client as _bc

        if table is None:
            import boto3

            table = boto3.resource("dynamodb", region_name=os.environ.get("DYNAMODB_REGION", "us-west-2")).Table(
                os.environ.get("TABLE_NAME", "life-platform")
            )
        query_vector = _bc.embed_text(question)
        passages, tel = select_passages(query_vector, sr.load_corpus(table), top_k=top_k)
        tel.setdefault("resolved", 0)

        # AC2, first half: a passage may only inform an answer if it still resolves to a
        # REAL record. `reconcile_precedent` is that resolution read AND the #1828
        # cycle-label reconciliation, and it fails closed (any error ⇒ dropped). The
        # second half — it must also be OPENABLE — is enforced inside `render_block`, so
        # the guarantee holds for every caller of that function, not just this one.
        resolved = [p for p in (sr.reconcile_precedent(table, p) for p in passages) if p]
        tel["resolved"] = len(resolved)
        if passages and not resolved:
            tel["status"] = "miss:unresolved"
        block = render_block(resolved)
        return block, _stamp(tel, t0)
    except Exception as e:  # noqa: BLE001 — retrieval is never load-bearing on a reader path
        tel["status"] = f"skipped:error:{type(e).__name__}"
        logger.warning(f"[ask retrieval] unavailable (non-blocking): {e}")
        return "", _stamp(tel, t0)
    finally:
        logger.info(
            "[ask retrieval] status=%s n=%s top=%s z=%s basis=%s selected=%s resolved=%s ms=%s",
            tel.get("status"),
            tel.get("n"),
            tel.get("top"),
            tel.get("z"),
            tel.get("basis"),
            tel.get("selected"),
            tel.get("resolved"),
            tel.get("elapsed_ms"),
        )


def _stamp(tel: dict, t0: float) -> dict:
    """Wall-clock ms onto the telemetry — the field that makes the added p95 on this
    synchronous reader path answerable from CloudWatch Logs Insights rather than
    estimated (and it is the exact quantity ADR-150's revisit trigger is stated in)."""
    tel["elapsed_ms"] = round((time.perf_counter() - t0) * 1000.0, 1)
    return tel
