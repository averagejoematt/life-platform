# coach_sim_replay fixture corpus

**Synthetic. Every line here was hand-written for this fixture.** No reply in it was
produced by the coach engine, and no number in it is one of Matthew's — this repo is
public and real sim run artifacts carry the AUTHORITATIVE FACTS block verbatim, so a
real corpus is never committed (see `lambdas/coach/coach_sim_scoreboard.py`,
limitation `corpus_is_synthetic_and_private`).

**What it is for.** `scripts/coach_sim_replay.py` runs the LLM-free deterministic subset
over it at $0 in CI, so the metric code itself — em-dash rate, assistant-isms, formatting
violations, structural collapse — is exercised on every run and cannot rot between the
on-demand panel runs. It is a *tripwire for the instrument*, not evidence about the coaches.

**What it is not.** It is not the corpus a real trend is read from. That one lives outside
the repo and is pinned into the scoreboard row by sha256 manifest, not by content.

`corpus_v1.jsonl` is deliberately unbalanced: some replies carry an em-dash, an
assistant-ism, a markdown bullet list, a "not X, but Y" frame. If every metric read zero
the fixture would prove nothing about whether the detectors fire.
