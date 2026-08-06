"""tests/test_google_tts_chunker_2148.py — #2148: the read-aloud chunker must
split sentences that alone exceed the TTS request limit, instead of failing
the whole episode.

Real incident (2026-08-04, first exercise of the #1243/PR #2107 regen path):
Google TTS returned 400 INVALID_ARGUMENT — "This request contains sentences
that are too long… Sentence starting with: 'A pla' is too long" — for the
Aug-2 prologue episode ("The Plan, On the Record"). Run summary: 0 rendered,
0 indexed, 1 errors. Root cause: `google_tts._chunks()` only ever PACKED
whole sentences up to CHUNK_CHARS; a single sentence longer than CHUNK_CHARS
on its own (the house style is em-dash-heavy long compound sentences) was
never split, so it went out as one oversized request and Google rejected it —
which, because chronicle_podcast_lambda's per-episode try/except only
protects OTHER episodes, killed the one episode outright.

`test_oversized_sentence_reproduces_against_a_naive_packer` pins the OLD
(pre-fix) behavior directly against a reimplementation of the original
`_chunks()` — proving the reproduction — before the rest of this file
exercises the FIXED `google_tts._chunks()`.
"""

import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from ai import google_tts  # noqa: E402

# ── shared fixture prose ──────────────────────────────────────────────────────
# House style (em-dash-heavy long compound sentences), well over CHUNK_CHARS
# when repeated — reconstructed from the chronicle's actual narrative voice
# (see lambdas/emails/chronicle_podcast_lambda.py's docstring + the published
# prologue titles), not real DDB content.
_CLAUSE = (
    "the plan was never a straight line to the number on the scale — it was a slow, "
    "unglamorous accumulation of Tuesday workouts nobody photographed, of protein logged "
    "at eleven at night out of stubbornness more than hunger, of a hundred small refusals "
    "to quit that never made it into any headline"
)


def _long_emdash_sentence(repeats: int) -> str:
    """A single SENTENCE (one terminal period) built from `repeats` em-dash-joined
    clauses — long enough that `repeats=20` clears CHUNK_CHARS on its own."""
    return " — ".join([_CLAUSE] * repeats) + "."


def _naive_pack_whole_sentences(text: str, limit: int) -> list:
    """The ORIGINAL (pre-#2148) `_chunks()` body, reproduced verbatim here so
    the reproduction test pins the bug against the actual old algorithm
    without depending on git history. Packs whole sentences up to `limit`;
    never splits an individual oversized sentence."""
    out, cur = [], ""
    for sent in re.split(r"(?<=[.!?])\s+", text or ""):
        if len(cur) + len(sent) + 1 > limit and cur:
            out.append(cur)
            cur = sent
        else:
            cur = f"{cur} {sent}".strip()
    if cur:
        out.append(cur)
    return out


# ── 1. reproduction — pins the bug against the naive (pre-fix) packer ────────


def test_oversized_sentence_reproduces_against_a_naive_packer():
    """A single em-dash-heavy sentence well over CHUNK_CHARS, run through the
    ORIGINAL whole-sentence-only packer, produces an oversized chunk — the
    exact failure mode behind the Aug-2 episode's Google TTS 400."""
    sentence = _long_emdash_sentence(20)
    assert len(sentence) > google_tts.CHUNK_CHARS, "fixture must exceed the real limit to reproduce the bug"

    naive_chunks = _naive_pack_whole_sentences(sentence, google_tts.CHUNK_CHARS)

    assert len(naive_chunks) == 1, "the naive packer never splits a single oversized sentence"
    assert len(naive_chunks[0]) > google_tts.CHUNK_CHARS, (
        "reproduction failed: the naive packer's single chunk should exceed CHUNK_CHARS " "(this is the request Google TTS 400'd on)"
    )


# ── 2. the fix — google_tts._chunks() splits at natural boundaries ───────────


def test_oversized_sentence_gets_split_by_the_fixed_chunker():
    sentence = _long_emdash_sentence(20)
    assert len(sentence) > google_tts.CHUNK_CHARS

    chunks = google_tts._chunks(sentence)

    assert len(chunks) > 1, "the fixed chunker must split an oversized sentence into multiple requests"


def test_no_chunk_exceeds_the_measured_provider_limit():
    """Assert against the ACTUAL constant the code enforces (google_tts.CHUNK_CHARS),
    not a guessed literal — this is what 'the measured limit' means here."""
    sentence = _long_emdash_sentence(20)
    chunks = google_tts._chunks(sentence)
    assert chunks, "must produce at least one chunk"
    for c in chunks:
        assert len(c) <= google_tts.CHUNK_CHARS, f"chunk of {len(c)} chars exceeds CHUNK_CHARS={google_tts.CHUNK_CHARS}"


def test_split_prefers_em_dash_boundaries():
    """The house style's dominant clause break is the em-dash; splitting an
    oversized sentence must not fall through to a lower-preference boundary
    (comma) while an em-dash split is available and sufficient."""
    sentence = _long_emdash_sentence(20)
    chunks = google_tts._chunks(sentence)
    # Every chunk boundary in the fixture sentence falls exactly on an
    # em-dash clause edge — so no chunk should be truncated mid-clause on a
    # bare comma (every comma in the fixture sits INSIDE a clause, not at a
    # chunk boundary we created).
    for c in chunks:
        assert not c.rstrip().endswith(","), "a chunk boundary landed mid-clause on a comma, not an em-dash edge"


def test_split_never_breaks_a_word_when_a_boundary_exists():
    sentence = _long_emdash_sentence(20)
    chunks = google_tts._chunks(sentence)
    reassembled_words = " ".join(chunks).split()
    original_words = sentence.split()
    assert reassembled_words == original_words, "splitting must never drop, reorder, or fragment a word"


def test_semicolon_and_comma_boundaries_used_when_no_em_dash():
    clause = "revenue climbed steadily; costs stayed flat, margins widened, and morale improved across the floor"
    sentence = (clause + ", ") * 80 + "and that was the whole story."
    assert len(sentence) > google_tts.CHUNK_CHARS
    chunks = google_tts._chunks(sentence)
    assert len(chunks) > 1
    for c in chunks:
        assert len(c) <= google_tts.CHUNK_CHARS
    assert " ".join(chunks).split() == sentence.split()


# ── 3. degenerate case — no natural boundary at all ───────────────────────────


def test_degenerate_no_boundary_hard_splits_instead_of_failing():
    """A single run with no punctuation and no whitespace at all (the
    word-salad degenerate case) must still be split, never raise, and never
    produce an oversized chunk."""
    word_salad = "x" * 6000
    chunks = google_tts._chunks(word_salad)  # must not raise
    assert chunks
    assert sum(len(c) for c in chunks) == len(word_salad)
    for c in chunks:
        assert len(c) <= google_tts.CHUNK_CHARS


def test_degenerate_no_boundary_with_spaces_cuts_at_whitespace():
    """No punctuation, but plenty of whitespace: the hard-split fallback must
    prefer a whitespace cut over a mid-word cut."""
    long_run = " ".join(["lorem"] * 1200)  # long, no punctuation, plenty of spaces
    assert len(long_run) > google_tts.CHUNK_CHARS
    chunks = google_tts._chunks(long_run)
    for c in chunks:
        assert len(c) <= google_tts.CHUNK_CHARS
        # every chunk boundary should be a real word, never a fragment of "lorem"
        for word in c.split():
            assert word == "lorem", f"hard split fragmented a word: {word!r}"


# ── 4. existing short-sentence behavior is unchanged ──────────────────────────


def test_normal_short_paragraph_still_chunks_exactly_as_before():
    paragraph = (
        "The Measured Life: Before the Numbers. Written by Elena Voss — a language model "
        "embedded with the experiment — and read by a synthetic voice.\n\n"
        "It starts, as these things do, with a number nobody wants to say out loud. "
        "Three hundred and twenty-one pounds. Not a milestone, not a low point dramatized "
        "for effect — just where things stood on a Tuesday morning."
    )
    chunks = google_tts._chunks(paragraph)
    assert len(chunks) == 1, "a normal short chronicle paragraph must still fit in a single request"
    assert chunks[0] == paragraph.replace("\n\n", " ").strip() or chunks[0].split() == paragraph.split()


def test_multiple_normal_sentences_still_pack_together():
    text = "One. Two. Three. Four. Five."
    chunks = google_tts._chunks(text)
    assert chunks == ["One. Two. Three. Four. Five."]


# ── 5. reassembly — synthesize() sends chunks in order and concatenates ──────


def test_synthesize_sends_chunks_in_order_and_concatenates(monkeypatch):
    sentence = _long_emdash_sentence(20)
    seen = []

    def fake_synth_chunk(text, voice_name, lang, volume_gain_db=0.0):
        seen.append(text)
        return f"[{len(seen)}]".encode()

    monkeypatch.setattr(google_tts, "_synthesize_chunk", fake_synth_chunk)
    audio = google_tts.synthesize(sentence, "en-US-Chirp3-HD-Aoede")

    expected_chunks = google_tts._chunks(sentence)
    assert len(seen) == len(expected_chunks) > 1
    assert seen == expected_chunks, "chunks must be sent to TTS in original order"
    assert audio == b"".join(f"[{i + 1}]".encode() for i in range(len(expected_chunks))), "audio must reassemble in order"
