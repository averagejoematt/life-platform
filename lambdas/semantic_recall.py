"""semantic_recall.py — #1384 (epic #1080): "when did I feel like this before?"

Titan-v2 embeddings over the narrative corpus (chronicle installments, coach
outputs, journal enrichments) + brute-force cosine similarity IN-LAMBDA. NO vector
DB, NO new GSI (ADR-103 complexity posture): the corpus is small, so the whole
embedding partition loads in ONE DynamoDB Query and cosine is a dot product over
normalized vectors. Retrieval spans resets, so the multi-cycle archive becomes
load-bearing memory instead of decoration.

Rigor (ADR-105): similarity is a HYPOTHESIS GENERATOR, never a claim of sameness.
The copy this module renders says "resembles" / "echoes" — never "caused", never
"because". A precedent is a pointer to a dated, openable artifact with its
similarity score shown, not a bare vibe (AC1/AC3).

Grounding (ADR-104): a coach read that cites a precedent must resolve to a REAL
record. resolve_precedent() verifies the artifact still exists; precedent_citation_findings()
is the grounded-generation finding class that BLOCKS an output citing a precedent
date that isn't among the resolved precedents (AC2) — it composes with
grounded_generation.grounding_findings()/regen_once().

Storage decision (justified in the PR + docs/SCHEMA.md): one item per corpus doc in
the single table under pk USER#matthew#SOURCE#recall_embeddings, sk DOC#<kind>#<date>.
The vector is a base64-packed float32 STRING attribute (`emb`) — compact (256-dim
≈ 1.4 KB vs 256 Decimals), exact enough for retrieval, and it sidesteps the
float→Decimal rule entirely. Classified CROSS_PHASE in phase_taxonomy so the
cross-reset memory index survives resets; each item carries its own `cycle` stamp
so every precedent is labeled with its source cycle (AC5).

Pure where it can be (encode/decode/cosine/rank/render/findings — unit-testable
with no AWS); the two AWS touchpoints (load_corpus, resolve_precedent) take an
injected `table` so tests use a fake.
"""

from __future__ import annotations

import base64
import hashlib
import math
import re
import struct

# ── storage layout ──────────────────────────────────────────────────────────
RECALL_SOURCE = "recall_embeddings"
RECALL_PK = f"USER#matthew#SOURCE#{RECALL_SOURCE}"

# Retrieval defaults. THRESHOLD is the cosine floor below which there is NO match —
# the honest-absence boundary (ADR-104): under it, no precedent is returned and the
# recall card does not render.
DEFAULT_TOP_K = 3
DEFAULT_THRESHOLD = 0.75

# Corpus kinds — the sk namespace (DOC#<kind>#<date>) and the caller vocabulary.
KIND_CHRONICLE = "chronicle"
KIND_COACH = "coach_output"
KIND_JOURNAL = "journal"
KINDS = (KIND_CHRONICLE, KIND_COACH, KIND_JOURNAL)


# ── vector codec: base64-packed little-endian float32 ───────────────────────
def encode_vector(vec) -> str:
    """Pack a float vector into a base64 float32 string (the DDB `emb` attribute).

    float32 is exact enough for cosine retrieval and ~4x smaller than a Decimal
    array; a String attribute sidesteps the boto3 float→Decimal rule entirely.
    """
    arr = [float(x) for x in (vec or [])]
    packed = struct.pack("<%df" % len(arr), *arr)
    return base64.b64encode(packed).decode("ascii")


def decode_vector(b64: str) -> list:
    """Inverse of encode_vector — base64 float32 string → list[float]."""
    if not b64:
        return []
    raw = base64.b64decode(b64)
    n = len(raw) // 4
    if n == 0:
        return []
    return list(struct.unpack("<%df" % n, raw[: n * 4]))


def cosine(a, b) -> float:
    """Cosine similarity of two equal-length vectors. 0.0 for empty/mismatched/
    zero-norm inputs (never raises — a degenerate vector is 'no similarity')."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


def sha_text(text: str) -> str:
    """Stable content hash of the embedded text — the backfill's idempotency key
    (unchanged text ⇒ same hash ⇒ skip re-embed)."""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def sk_for(kind: str, date: str) -> str:
    """The deterministic sort key DOC#<kind>#<date>. Deterministic ⇒ re-embedding
    the same doc overwrites its own item (idempotent), never duplicates it."""
    return f"DOC#{kind}#{date}"


def make_embedding_item(
    *,
    kind: str,
    date: str,
    text: str,
    vector,
    doc_date: str = "",
    cycle=None,
    artifact_pk: str,
    artifact_sk: str,
    link: str = "",
    snippet: str = "",
    model: str = "",
    dims: int = 0,
    embedded_at: str = "",
) -> dict:
    """Build the full DDB item for one corpus doc (pure — no I/O, no Decimals).

    `date` is the sk-uniqueness token (may carry a sub-key so two same-day docs
    don't collide, e.g. "2026-04-06#mind_coach"); `doc_date` is the calendar date
    SHOWN to the reader (defaults to the leading YYYY-MM-DD of `date`). The vector
    rides as the base64 String `emb`; every scalar is a str/int so the item needs no
    float→Decimal pass. `cycle` labels the SOURCE cycle for AC5.
    """
    display_date = doc_date or date.split("#", 1)[0]
    item = {
        "pk": RECALL_PK,
        "sk": sk_for(kind, date),
        "source": RECALL_SOURCE,
        "kind": kind,
        "doc_date": display_date,
        "emb": encode_vector(vector),
        "dims": int(dims or (len(vector) if vector else 0)),
        "model": model,
        "text_sha": sha_text(text),
        "artifact_pk": artifact_pk,
        "artifact_sk": artifact_sk,
        "link": link or "",
        "snippet": (snippet or "")[:280],
        "embedded_at": embedded_at or "",
    }
    if cycle is not None:
        item["cycle"] = int(cycle)
    return item


# ── AWS touchpoints (injected table) ────────────────────────────────────────
def load_corpus(table) -> list:
    """Load the whole recall-embeddings partition (ALL cycles) and decode vectors.

    Deliberately does NOT apply phase_filter — cross-reset recall is the point, so
    prior-cycle rows must be visible. Returns a list of corpus docs, each carrying a
    decoded `vector` plus its metadata (kind, doc_date, cycle, link, snippet,
    artifact_pk/sk). Small corpus ⇒ one Query is the whole brute-force index.
    """
    from boto3.dynamodb.conditions import Key

    items: list = []
    kwargs: dict = {"KeyConditionExpression": Key("pk").eq(RECALL_PK)}
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []) or [])
        lek = resp.get("LastEvaluatedKey")
        if not lek:
            break
        kwargs["ExclusiveStartKey"] = lek

    corpus = []
    for it in items:
        vec = decode_vector(it.get("emb", ""))
        if not vec:
            continue
        cyc = it.get("cycle")
        corpus.append(
            {
                "vector": vec,
                "kind": it.get("kind", ""),
                "doc_date": it.get("doc_date", ""),
                "cycle": int(cyc) if cyc is not None else None,
                "link": it.get("link", ""),
                "snippet": it.get("snippet", ""),
                "artifact_pk": it.get("artifact_pk", ""),
                "artifact_sk": it.get("artifact_sk", ""),
                "sk": it.get("sk", ""),
            }
        )
    return corpus


def resolve_precedent(table, precedent: dict) -> bool:
    """AC2: does this precedent resolve to a REAL record? True iff the artifact it
    points at (artifact_pk/artifact_sk) still exists in the table. A precedent whose
    underlying artifact is gone must NOT be cited — the caller drops it and/or the
    grounded gate blocks any output that cites it. Fail-closed: any error ⇒ False."""
    apk = (precedent or {}).get("artifact_pk")
    ask = (precedent or {}).get("artifact_sk")
    if not apk or not ask:
        return False
    try:
        resp = table.get_item(Key={"pk": apk, "sk": ask})
        return bool(resp.get("Item"))
    except Exception:  # noqa: BLE001 — resolution failure is treated as "does not resolve"
        return False


# ── retrieval (pure, deterministic) ─────────────────────────────────────────
def rank_precedents(query_vector, corpus, *, top_k=DEFAULT_TOP_K, threshold=DEFAULT_THRESHOLD, exclude_dates=None) -> list:
    """Rank corpus docs by cosine similarity to `query_vector`. DETERMINISTIC:
    same query + same corpus ⇒ identical ranked list AND identical scores.

    - Similarity is rounded to 4 decimals (stable display + stable tie ordering).
    - Ties break on (doc_date, kind, sk) so the order never depends on dict/Query
      iteration order — the AC1 reproducibility guarantee.
    - Docs at/under `threshold` are dropped (honest absence, AC3).
    - `exclude_dates` (e.g. the current week) are dropped so a period never matches
      itself.
    Returns a list of precedent dicts carrying `similarity` alongside the match.
    """
    exclude = set(exclude_dates or ())
    scored = []
    for doc in corpus or []:
        date = doc.get("doc_date", "")
        if date in exclude:
            continue
        sim = round(cosine(query_vector, doc.get("vector") or []), 4)
        if sim < threshold:
            continue
        scored.append((sim, date, doc.get("kind", ""), doc.get("sk", ""), doc))
    # -sim ascending on the negated value = highest similarity first; the remaining
    # keys are ascending and fully determined by the corpus (no hidden ordering).
    scored.sort(key=lambda t: (-t[0], t[1], t[2], t[3]))
    out = []
    for sim, date, kind, sk, doc in scored[: max(0, int(top_k))]:
        out.append(
            {
                "date": date,
                "similarity": sim,
                "cycle": doc.get("cycle"),
                "kind": kind,
                "source": kind,
                "link": doc.get("link", ""),
                "snippet": doc.get("snippet", ""),
                "artifact_pk": doc.get("artifact_pk", ""),
                "artifact_sk": doc.get("artifact_sk", ""),
            }
        )
    return out


def retrieve(table, query_vector, *, top_k=DEFAULT_TOP_K, threshold=DEFAULT_THRESHOLD, exclude_dates=None, resolve=True) -> list:
    """Convenience: load_corpus + rank_precedents, then (AC2) drop any precedent
    that does not resolve to a real record. The precedents that survive are safe to
    cite — every one points at a dated artifact the reader can open."""
    ranked = rank_precedents(
        query_vector,
        load_corpus(table),
        top_k=top_k,
        threshold=threshold,
        exclude_dates=exclude_dates,
    )
    if not resolve:
        return ranked
    return [p for p in ranked if resolve_precedent(table, p)]


# ── copy (ADR-105: hypothesis, never cause) ─────────────────────────────────
def _cycle_label(cycle) -> str:
    return f"cycle {int(cycle)}" if cycle is not None else "an earlier cycle"


def render_precedent_line(precedent: dict) -> str:
    """One grounded citation line — dated, cycle-labeled, similarity-bearing, with a
    link. 'echoes'/'resembles', never causal. This is what a coach may cite."""
    p = precedent or {}
    date = p.get("date", "")
    sim = p.get("similarity")
    link = p.get("link", "")
    sim_txt = f"{sim:.2f}" if isinstance(sim, (int, float)) else "?"
    tail = f" — {link}" if link else ""
    return f"This period echoes the week of {date} ({_cycle_label(p.get('cycle'))}, similarity {sim_txt}){tail}"


def recall_block(precedents: list) -> str:
    """The prompt-injection block for a coach render (mirrors the coach-corrections
    prompt-memory block). Lists the RESOLVED precedents with dates/links/similarity
    and the hard rules that keep a citation grounded + non-causal. Empty list ⇒ ""
    (no block, so the coach can't be tempted to invent one)."""
    if not precedents:
        return ""
    lines = [
        "SEMANTIC RECALL — earlier periods whose signal RESEMBLES the current one "
        "(cosine similarity over Matthew's own archive, cross-cycle). These are the "
        "ONLY precedents you may cite:",
    ]
    for p in precedents:
        lines.append("  - " + render_precedent_line(p))
    lines.append(
        "RULES: similarity is a HYPOTHESIS, not a cause — say the current period "
        '"resembles" or "echoes" one above; NEVER assert it was CAUSED by it or that '
        'the same thing "will" happen. Cite ONLY a date + link shown above; if none '
        "is shown, do not invent a precedent. Always show the similarity score with "
        "the date."
    )
    return "\n".join(lines)


def recall_card(precedents: list, *, threshold=DEFAULT_THRESHOLD) -> dict | None:
    """AC3: the chronicle recall-card data contract. Returns None when there is no
    precedent at/above threshold — so the card HONESTLY does not render (ADR-104).
    Otherwise returns the structured card for the top precedent: date, similarity,
    cycle, source, link, provenance, and the non-causal display phrase."""
    top = None
    for p in precedents or []:
        sim = p.get("similarity")
        if isinstance(sim, (int, float)) and sim >= threshold:
            top = p
            break
    if top is None:
        return None
    sim = top.get("similarity")
    return {
        "resembles_date": top.get("date", ""),
        "similarity": sim,
        "cycle": top.get("cycle"),
        "source": top.get("source", top.get("kind", "")),
        "link": top.get("link", ""),
        "snippet": top.get("snippet", ""),
        "phrase": f"This week resembles the week of {top.get('date', '')}, similarity {sim:.2f}",
        "provenance": (
            f"cosine similarity {sim:.2f} vs the {top.get('kind', 'archive')} of "
            f"{top.get('date', '')} ({_cycle_label(top.get('cycle'))})"
        ),
    }


# ── grounded-gate: precedent-citation block (AC2) ───────────────────────────
# A precedent citation is a DATE sitting next to precedent framing ("resembles",
# "echoes", "the week of", "reminds me of", "back in/on"). A framed date that is NOT
# among the resolved precedents is an unresolvable/invented precedent — this returns
# the finding that blocks it. Scoping to precedent FRAMING (not every date in the
# text) keeps ordinary data-dates from false-flagging; it is the precedent-specific
# analogue of grounded_generation.fabricated_dates().
_PRECEDENT_FRAMING_RE = re.compile(
    r"\b(resembl\w*|echo\w*|reminiscent|reminds?\s+(?:me|you)\s+of|"
    r"(?:the\s+)?week\s+of|back\s+(?:in|on)|precedent|last\s+time|mirror\w*|parallels?)\b",
    re.IGNORECASE,
)
_ISO_DATE_RE = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")


def _framed_dates(text: str, proximity: int = 60) -> set:
    """ISO dates in `text` that sit within `proximity` chars of precedent framing."""
    text = text or ""
    frames = [(m.start(), m.end()) for m in _PRECEDENT_FRAMING_RE.finditer(text)]
    if not frames:
        return set()
    out = set()
    for dm in _ISO_DATE_RE.finditer(text):
        ds, de = dm.start(), dm.end()
        for fs, fe in frames:
            if fs >= de:
                dist = fs - de
            elif fe <= ds:
                dist = ds - fe
            else:
                dist = 0
            if dist <= proximity:
                out.add(f"{int(dm.group(1)):04d}-{int(dm.group(2)):02d}-{int(dm.group(3)):02d}")
                break
    return out


def precedent_citation_findings(text: str, resolved_precedents: list) -> list:
    """AC2 grounded-generation finding class. Returns [{type:'unresolvable_precedent',
    ...}] for every precedent-FRAMED date cited in `text` that is not among the
    resolved precedents — empty list means every cited precedent resolves.

    `resolved_precedents` is the list from retrieve()/resolve_precedent — a precedent
    is legitimate to cite ONLY if its artifact was confirmed to exist. Composes with
    grounded_generation.grounding_findings(): fold these into the caller's
    findings_fn and regen_once() blocks/rewrites an output that cites a phantom."""
    resolved = {(p or {}).get("date") for p in (resolved_precedents or []) if (p or {}).get("date")}
    findings = []
    for d in sorted(_framed_dates(text)):
        if d not in resolved:
            findings.append(
                {
                    "type": "unresolvable_precedent",
                    "claimed": d,
                    "detail": (
                        f"the narrative cites a precedent for the week of {d}, but that date does not "
                        f"resolve to a real record in the recall archive"
                    ),
                }
            )
    return findings


def resolved_precedent_dates(precedents: list) -> set:
    """The ISO dates of resolved precedents — feed as `allowed_dates` to
    grounded_generation.grounding_findings() so the coach may cite these dates but
    no others (the number/date allow-list already blocks an invented one)."""
    return {(p or {}).get("date") for p in (precedents or []) if (p or {}).get("date")}
