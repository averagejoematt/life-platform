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

FIX-FORWARD (2026-08-06, #2148 continued — PR #2154 shipped and deployed but
the SAME error recurred verbatim on regen): #2154's `_split_oversized()` only
enforced CHUNK_CHARS (4500) — a REQUEST-size cap. The Aug-2 episode's actual
offending sentence (queried from the chronicle content behind that episode)
is 489 chars / 493 UTF-8 bytes — comfortably under CHUNK_CHARS, so #2154's
splitter correctly left it as ONE piece, and Google 400'd it anyway. Google
re-segments the request text with its OWN sentence splitter and enforces a
per-SENTENCE limit far smaller than the 5000-byte request limit — no official
number is published for Chirp 3: HD, but a community report against the same
voice family and the same error text recommends keeping spoken lines under
~80-100 characters. `google_tts.PER_SENTENCE_CHARS` (200) adds a second,
smaller cap on top of CHUNK_CHARS: real margin above that folklore floor, but
well under the measured 493-byte failure. Every piece produced at that cap is
also stamped with terminal punctuation via `_terminate()` — a comma/em-dash
cut point left dangling still reads to Google as ONE continuing sentence,
which would silently reintroduce the exact same 400.
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

# A short, comma-free clause — sized so several of them joined by em-dashes
# clear PER_SENTENCE_CHARS (200) without any single clause needing a deeper
# (comma/semicolon) split on its own. Used to isolate em-dash-boundary
# preference at the per-sentence cap, distinct from the CHUNK_CHARS-level
# `_CLAUSE` fixture above (292 chars alone — already over PER_SENTENCE_CHARS,
# so it's the wrong fixture for isolating em-dash-only behavior).
_SHORT_CLAUSE = "the plan was never a straight line to the number on the scale"

# The real Aug-2 prologue sentence that triggered the live 400 — queried from
# the chronicle content behind that episode (already-published, public site
# prose; not a record identifier). 489 chars / 493 UTF-8 bytes, well under
# CHUNK_CHARS (4500) and over PER_SENTENCE_CHARS (200) — the exact shape
# #2154 left untouched and Google rejected anyway.
_REAL_AUG2_SENTENCE = (
    "A plan on the record is only as good as its tamper-proofing, so the frozen record "
    "behind this page — every prediction above and the formal hypotheses, byte for byte — "
    'is published as <a href="https://averagejoematt.com/experiments/prereg/'
    'genesis-2026-08-03.json">a public, content-addressed artifact</a>, and its SHA-256 '
    "fingerprint is printed here in the open:\n\n"
    "<code>3a4f5872b934ec376d057647f2c96f7c3939c67248b07a8ebb3b6bcf30c70527</code>\n\n"
    "Claims frozen and fingerprinted August 3, 2026."
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


def _naive_pack_whole_sentences_at_chunk_chars(text: str, limit: int) -> list:
    """The #2154 (pre-fix-forward) `_chunks()` body: splits a sentence that
    alone exceeds `limit`, but has NO separate per-sentence cap — this is
    what shipped in #2154 and still failed on the real Aug-2 sentence,
    because that sentence (489 chars) never exceeds a CHUNK_CHARS-sized
    `limit` (4500) and so is never split at all."""
    pieces = []
    for sent in re.split(r"(?<=[.!?])\s+", text or ""):
        if sent:
            pieces.extend(google_tts._split_oversized(sent, limit))
    return google_tts._pack(pieces, limit)


def _words_ignoring_terminal_punctuation(s: str) -> list:
    """Word tokens with any sentence/clause punctuation this module's
    splitter can append, strip, or convert (. , ; : —) removed, and any
    resulting empty token (a bare "—" that stood as its own whitespace-
    separated token, now converted to a terminal period elsewhere) dropped —
    used to confirm no WORD (actual content) was fragmented, dropped, or
    reordered, independent of where a terminal period got added or a clause
    delimiter got absorbed into one."""
    return [w for w in (tok.strip(".,;:—") for tok in s.split()) if w]


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


def test_real_aug2_sentence_reproduces_against_the_2154_fix_alone():
    """#2154's fix (CHUNK_CHARS-only splitting) pins the REMAINING bug: the
    real Aug-2 sentence is under CHUNK_CHARS, so #2154's `_split_oversized`
    at the CHUNK_CHARS cap leaves it as ONE untouched, unterminated-mid-clause
    piece — which is exactly what shipped, deployed, and still 400'd twice on
    the sanctioned regen invoke."""
    assert len(_REAL_AUG2_SENTENCE) < google_tts.CHUNK_CHARS, "the real sentence must fit under the #2154 cap to reproduce its miss"

    chunks_2154_only = _naive_pack_whole_sentences_at_chunk_chars(_REAL_AUG2_SENTENCE, google_tts.CHUNK_CHARS)

    assert len(chunks_2154_only) == 1, "#2154's CHUNK_CHARS-only split leaves the real sentence as a single unsplit request"
    assert chunks_2154_only[0].startswith("A plan on the record"), "sanity: this is the same sentence Google rejected as 'A pla...'"


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


def test_split_never_breaks_a_word_when_a_boundary_exists():
    sentence = _long_emdash_sentence(20)
    chunks = google_tts._chunks(sentence)
    reassembled_words = _words_ignoring_terminal_punctuation(" ".join(chunks))
    original_words = _words_ignoring_terminal_punctuation(sentence)
    assert reassembled_words == original_words, "splitting must never drop, reorder, or fragment a word"


# ── 3. the fix-forward — no EMITTED SENTENCE exceeds PER_SENTENCE_CHARS ──────


def test_no_sentence_piece_exceeds_the_per_sentence_cap():
    """The core fix-forward assertion: every individual SENTENCE `_sentence_pieces`
    produces — the unit Google's own segmenter actually sees, distinct from the
    (larger, request-level) CHUNK_CHARS a `_chunks()` request may still pack
    several of these into — must be under PER_SENTENCE_CHARS. This is what
    #2154 never enforced."""
    sentence = _long_emdash_sentence(20)
    pieces = google_tts._sentence_pieces(sentence)
    assert pieces, "must produce at least one sentence piece"
    for p in pieces:
        assert (
            len(p) <= google_tts.PER_SENTENCE_CHARS
        ), f"sentence piece of {len(p)} chars exceeds PER_SENTENCE_CHARS={google_tts.PER_SENTENCE_CHARS}"


def test_every_sentence_piece_ends_with_terminal_punctuation():
    """A piece cut at a comma/semicolon/em-dash clause boundary must be
    re-terminated with real sentence-ending punctuation — left dangling, it
    still reads to Google's segmenter as ONE continuing (long) sentence,
    silently reintroducing the exact bug this fix-forward closes."""
    sentence = _long_emdash_sentence(20)
    pieces = google_tts._sentence_pieces(sentence)
    assert len(pieces) > 1, "fixture must actually require splitting to exercise termination"
    for p in pieces:
        assert p and p[-1] in ".!?", f"sentence piece does not end with terminal punctuation: {p!r}"


def test_real_aug2_sentence_passes_the_fixed_chunker():
    """The concrete reproduction: the real (489-char / 493-byte) Aug-2
    sentence — which #2154 left as a single untouched, unterminated piece —
    now gets split into per-sentence-cap-compliant, terminated pieces. This is
    the fix-forward's actual regression test for the live incident."""
    assert len(_REAL_AUG2_SENTENCE) > google_tts.PER_SENTENCE_CHARS, "fixture must exceed the per-sentence cap to exercise the fix"

    pieces = google_tts._sentence_pieces(_REAL_AUG2_SENTENCE)

    assert len(pieces) > 1, "the real sentence must be split into more than one piece"
    for p in pieces:
        assert len(p) <= google_tts.PER_SENTENCE_CHARS, f"piece of {len(p)} chars still exceeds PER_SENTENCE_CHARS — would still 400"
        assert p[-1] in ".!?", f"piece not sentence-terminated, would still read as one continuing sentence to Google: {p!r}"
    # And the request-level chunks built from those pieces still respect
    # CHUNK_CHARS and never break a word.
    chunks = google_tts._chunks(_REAL_AUG2_SENTENCE)
    for c in chunks:
        assert len(c) <= google_tts.CHUNK_CHARS


def test_per_sentence_cap_has_margin_below_the_measured_failure():
    """Pin the chosen constant against the measured real-world failure point
    (not a guess): the cap must leave real margin below the actual sentence
    Google rejected, so a similarly-sized future sentence doesn't just barely
    clear it."""
    assert len(_REAL_AUG2_SENTENCE) - google_tts.PER_SENTENCE_CHARS >= 200, (
        "PER_SENTENCE_CHARS should sit with clear margin below the measured " "493-byte / 489-char real failure, not right at its edge"
    )


def test_sentence_at_the_cap_boundary_is_left_alone():
    """A sentence sitting right at (just under) PER_SENTENCE_CHARS must pass
    through unmodified — the cap should not fragment sentences that are
    already within the safe margin."""
    sentence = ("x" * (google_tts.PER_SENTENCE_CHARS - 1)) + "."
    pieces = google_tts._sentence_pieces(sentence)
    assert pieces == [sentence]


def test_sentence_just_over_the_cap_gets_split():
    """A sentence just barely over PER_SENTENCE_CHARS (no natural boundary —
    the degenerate case) must still be split, never pass through whole."""
    sentence = ("x" * (google_tts.PER_SENTENCE_CHARS + 50)) + "."
    pieces = google_tts._sentence_pieces(sentence)
    assert len(pieces) > 1
    for p in pieces:
        assert len(p) <= google_tts.PER_SENTENCE_CHARS


# ── 4. boundary preference, re-tested at the per-sentence cap ────────────────


def test_split_prefers_em_dash_boundaries_at_the_sentence_cap():
    """The house style's dominant clause break is the em-dash; splitting an
    oversized sentence must not fall through to a lower-preference boundary
    (comma) while an em-dash split is available and sufficient. Uses a
    comma-free clause sized so em-dash splitting alone clears the cap —
    isolating boundary preference at PER_SENTENCE_CHARS, distinct from the
    CHUNK_CHARS-level test below."""
    sentence = (" — ".join([_SHORT_CLAUSE] * 5)) + "."
    assert len(sentence) > google_tts.PER_SENTENCE_CHARS

    pieces = google_tts._sentence_pieces(sentence)

    assert len(pieces) > 1
    for p in pieces:
        assert len(p) <= google_tts.PER_SENTENCE_CHARS
        # Every word in the fixture is comma-free; a piece boundary that fell
        # through to a comma split would be a bug — there are none to fall on
        # honestly, so any comma present would mean a mid-word/mid-clause
        # corruption, not a legitimate lower-preference split.
        assert "," not in p


def test_semicolon_and_comma_boundaries_used_when_no_em_dash():
    clause = "revenue climbed steadily; costs stayed flat, margins widened, and morale improved across the floor"
    sentence = (clause + ", ") * 80 + "and that was the whole story."
    assert len(sentence) > google_tts.CHUNK_CHARS
    chunks = google_tts._chunks(sentence)
    assert len(chunks) > 1
    for c in chunks:
        assert len(c) <= google_tts.CHUNK_CHARS
    reassembled = _words_ignoring_terminal_punctuation(" ".join(chunks))
    original = _words_ignoring_terminal_punctuation(sentence)
    assert reassembled == original


# ── 5. degenerate case — no natural boundary at all ───────────────────────────


def test_degenerate_no_boundary_hard_splits_instead_of_failing():
    """A single run with no punctuation and no whitespace at all (the
    word-salad degenerate case) must still be split, never raise, and never
    produce an oversized chunk. Each split-off piece gets a terminal period
    appended (#2148 fix-forward); when a piece is cut exactly at
    PER_SENTENCE_CHARS with nothing to trade for that period (no delimiter —
    this degenerate run has none), `_terminate` trims one trailing character
    to make room rather than push the piece over the cap. So the
    reconstructed text (periods and packing spaces removed) must equal the
    original run MINUS at most one dropped char per per-sentence-cap piece —
    not necessarily an exact match, but bounded, proving nothing beyond that
    documented trade-off was dropped, reordered, or duplicated."""
    word_salad = "x" * 6000
    chunks = google_tts._chunks(word_salad)  # must not raise
    assert chunks
    for c in chunks:
        assert len(c) <= google_tts.CHUNK_CHARS
    reconstructed = "".join(c.replace(".", "").replace(" ", "") for c in chunks)
    assert set(reconstructed) <= {"x"}, "no foreign character introduced"
    max_pieces = -(-len(word_salad) // google_tts.PER_SENTENCE_CHARS)  # ceil division
    dropped = len(word_salad) - len(reconstructed)
    assert 0 <= dropped <= max_pieces, f"dropped {dropped} chars, expected at most {max_pieces} (one per sentence-cap piece)"


def test_degenerate_no_boundary_with_spaces_cuts_at_whitespace():
    """No punctuation, but plenty of whitespace: the hard-split fallback must
    prefer a whitespace cut over a mid-word cut. Every word token (terminal
    punctuation stripped) must still be exactly 'lorem' — proving no word was
    fragmented, even though per-sentence-cap termination now sprinkles
    periods through the interior of the long request-level chunks."""
    long_run = " ".join(["lorem"] * 1200)  # long, no punctuation, plenty of spaces
    assert len(long_run) > google_tts.CHUNK_CHARS
    chunks = google_tts._chunks(long_run)
    for c in chunks:
        assert len(c) <= google_tts.CHUNK_CHARS
        for word in c.split():
            assert word.rstrip(".") == "lorem", f"hard split fragmented a word: {word!r}"


# ── 6. existing short-sentence behavior is unchanged ──────────────────────────


def test_normal_short_paragraph_still_chunks_exactly_as_before():
    paragraph = (
        "The Measured Life: Before the Numbers. Written by Elena Voss — a language model "
        "embedded with the experiment — and read by a synthetic voice.\n\n"
        "It starts, as these things do, with a number nobody wants to say out loud. "
        "Three hundred and twenty-one pounds. Not a milestone, not a low point dramatized "
        "for effect — just where things stood on a Tuesday morning."
    )
    # Every sentence in this fixture is already well under PER_SENTENCE_CHARS
    # and already terminated — the fix-forward must be a no-op here.
    for s in re.split(r"(?<=[.!?])\s+", paragraph):
        assert len(s) <= google_tts.PER_SENTENCE_CHARS
    chunks = google_tts._chunks(paragraph)
    assert len(chunks) == 1, "a normal short chronicle paragraph must still fit in a single request"
    assert chunks[0] == paragraph.replace("\n\n", " ").strip() or chunks[0].split() == paragraph.split()


def test_multiple_normal_sentences_still_pack_together():
    text = "One. Two. Three. Four. Five."
    chunks = google_tts._chunks(text)
    assert chunks == ["One. Two. Three. Four. Five."]


# ── 7. reassembly — synthesize() sends chunks in order and concatenates ──────


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
