# PG-14 spike — "the data figure"

A self-contained prototype for PG-14 ("AI me dropping weight"): a faceless,
data-driven SVG body silhouette that morphs with the **real** weight number
(304.3 → current → 185).

- **Run it:** open `index.html` in a browser (no build, no deps).
- **Frames:** `frame_304.png` · `frame_245.png` · `frame_185.png`.
- **Findings + go/no-go:** `docs/specs/PG-14_ai_me_spike.md`.

This is a **spike**, not a shipped feature. It lives outside `site/`, so the
site deploy never touches it. Nothing here is live. The decision to productionize
Tier A is the owner's — see the spec.
