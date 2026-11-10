"""tests/narrative_publication_reference.py — the #5645 publication gate's per-item logic exactly as it stood
before the #5728 follow-up speed-up (origin/main c12d7f793), frozen as the REFERENCE the equivalence walk
(``tests/narrative_publication_equivalence.py``) holds the live gate to, decision for decision and byte for byte.

Copied verbatim from ``lambdas/web/narrative_publication.py`` (``_withhold_value``, ``_norm_words``,
``_prose_strings``, ``_wordy``, ``_taint``, ``is_tainted``, ``gate_item``, ``gate_document``, ``scrub_payload``)
with ONE change: module state (the taint sets, the per-request counts) lives on a ``Reference`` instance, so
the reference and the live gate never share a set. The policy tables (``STRUCTURAL_KEYS``, ``PROSE_KEYS``,
``TAINT_SKIP_KEYS``, ...) and the provenance/allowlist modules are read from the live code: they are the
policy, not the hot path, and this file must not become a second copy of them. Never edit this file to make
the walk pass — a diff is the gate changing a decision.
"""

from __future__ import annotations

import re
from typing import Any

from common import narrative_allowlist as NA, narrative_provenance as NP
from web import narrative_publication as G


class Reference:
    def __init__(self) -> None:
        self.state = {"withheld": 0, "served": 0, "scrubbed": 0}
        self.taint_exact: set = set()
        self.taint_shingles: set = set()

    # ── verbatim (module globals -> self) ─────────────────────────────────────────────────
    def _structural_key(self, key: Any) -> bool:
        k = str(key or "")
        return k in G.STRUCTURAL_KEYS or k.endswith(G._STRUCTURAL_SUFFIXES)

    def _withhold_value(self, value: Any, key: Any = None, in_list: bool = False) -> Any:
        if isinstance(value, str):
            if str(key or "") in G.PROSE_KEYS:
                return ""
            if re.search(r"\s", value):
                return ""
            if in_list and not self._structural_key(key):
                return ""
            return value
        if isinstance(value, dict):
            return {k: self._withhold_value(v, k) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._withhold_value(v, key, in_list=True) for v in value]
        if isinstance(value, set):
            return {self._withhold_value(v, key, in_list=True) for v in value}
        return value

    @staticmethod
    def _norm_words(text: str) -> tuple:
        t = re.sub(r"\[n\]", "0", text.lower())
        t = re.sub(r"\d+(?:[.,]\d+)*", "0", t)
        return tuple(re.sub(r"[^a-z0-9]+", " ", t).split())

    def _prose_strings(self, value: Any, key: Any = None):
        if isinstance(value, str):
            if str(key or "") in G.PROSE_KEYS or re.search(r"\s", value):
                yield value
        elif isinstance(value, dict):
            for k, v in value.items():
                yield from self._prose_strings(v, k)
        elif isinstance(value, (list, tuple, set)):
            for v in value:
                yield from self._prose_strings(v, key)

    @staticmethod
    def _wordy(gram: tuple) -> bool:
        return sum(1 for w in gram if len(w) >= 3 and not w.isdigit()) >= 4

    def _taint(self, row: dict) -> None:
        for key, value in row.items():
            if key in G.TAINT_SKIP_KEYS:
                continue
            for text in self._prose_strings(value, key):
                words = self._norm_words(text)
                if len(words) < G.EXACT_MIN_WORDS:
                    continue
                self.taint_exact.add(hash(words))
                for i in range(len(words) - G.SHINGLE + 1):
                    gram = words[i : i + G.SHINGLE]
                    if self._wordy(gram):
                        self.taint_shingles.add(hash(gram))

    def is_tainted(self, text: Any) -> bool:
        if not isinstance(text, str) or not self.taint_exact or NA.is_approved_text(text):
            return False
        words = self._norm_words(text)
        if len(words) < G.EXACT_MIN_WORDS:
            return False
        if hash(words) in self.taint_exact:
            return True
        return any(hash(words[i : i + G.SHINGLE]) in self.taint_shingles for i in range(len(words) - G.SHINGLE + 1))

    def gate_item(self, item: Any, pk_hint: Any = None, *, strict: bool = False) -> Any:
        if not isinstance(item, dict):
            return item
        pk = item.get("pk", pk_hint)
        if not G.is_narrative_row(pk, item.get("sk")):
            return item
        ok, reason = NP.eligibility(item)
        if not ok and reason == NP.R_UNRECORDED:
            approved = NA.record_for(item, pk)
            if approved is not None:
                ok, reason = NP.eligibility(approved)
        out = {k: v for k, v in item.items() if k != NP.PROVENANCE_KEY}
        if ok:
            self.state["served"] += 1
            return out
        self.state["withheld"] += 1
        if G._is_counted(item.get("sk")) and not strict:
            self._taint(out)
            return out
        gated = {k: self._withhold_value(v, k) for k, v in out.items()}
        gated[G.PUBLICATION_KEY] = {"state": "withheld", "reason": G.PUBLIC_WITHHELD_REASON}
        return gated

    def gate_document(self, doc: Any) -> Any:
        if not isinstance(doc, dict):
            return doc
        ok, reason = NP.eligibility(doc)
        out = {k: v for k, v in doc.items() if k != NP.PROVENANCE_KEY}
        if ok:
            self.state["served"] += 1
            return out
        self.state["withheld"] += 1
        gated = {k: self._withhold_value(v, k) for k, v in out.items()}
        gated[G.PUBLICATION_KEY] = {"state": "withheld", "reason": G.PUBLIC_WITHHELD_REASON}
        return gated

    def scrub_payload(self, node: Any) -> Any:
        if isinstance(node, str):
            if self.is_tainted(node):
                self.state["scrubbed"] += 1
                return ""
            return node
        if isinstance(node, dict):
            return {k: (v if (k in G.WIRE_SKIP_KEYS and isinstance(v, str)) else self.scrub_payload(v)) for k, v in node.items()}
        if isinstance(node, list):
            return [self.scrub_payload(v) for v in node]
        return node
