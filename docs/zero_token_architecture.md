# Zero-token architecture — how careerfit applies it

Analysis date: 2026-09-30. Status: design notes for Milestones 5–8.

## The pattern

- **The main path uses zero tokens.** Anything with a knowable answer (parse,
  match, compute gaps, render) is deterministic code.
- **The LLM is an escalation.** `judge/` runs only for genuine judgment
  (semantic matching, confidence, learning paths), and only on observations
  that `analyze/` has already produced.
- **The tool works without the LLM.** The keyword pass alone gives honest,
  useful output.

Benefits: cost doesn't grow with volume, analysis is deterministic and
unit-testable, and results come back in milliseconds. It also keeps output
honest: code can say "not assessed", where a model tends to guess.

Costs: keyword rules miss paraphrases ("container orchestration" vs
Kubernetes). Anything code can't decide must be `UNRESOLVABLE` /
`NOT_ASSESSED` and never forced into a gap.

## Where careerfit stands

The design already follows this pattern:

- `analyze/` must not call an LLM, hit the network or read the clock.
  `tests/test_architecture.py` enforces a limited import boundary by rejecting
  imports of `judge/` and listed LLM/network modules; it does not detect clock
  reads or every possible network path.
- `judge/` is intended to be the only package that calls the Anthropic API.
- Free tier = `llm_used=False` (keyword pass). Paid tier = `llm_used=True`.
  The free tier *is* the zero-token path.

## Additions to build in

### 1. Grow the ontology offline (dev-time tokens, zero runtime tokens)

Use an LLM at development time to propose aliases and ambiguity flags for
`ontology/skills.yaml`. Review them by hand, then commit them as data. The
runtime matcher stays pure. This moves LLM value into the free tier at no
per-request cost.

Rule to keep: aliases must never be ambiguous (see the top comment in
`skills.yaml`). Reject any LLM-suggested alias that breaks it.

### 2. Cache judge results (Milestone 6/7)

Key the cache using a stable digest (such as SHA-256) of the canonical
serialization of the complete judge input, including the observations sent to
the judge, prompt version and model. This invalidates cached results whenever
the actual judge input changes; do not use Python's process-randomized
`hash()`. A repeat analysis costs zero tokens, which matters for paid-tier
margins.

- The cache belongs in the composition root (`cli.py` / `api.py`), not in
  `judge/`: it needs storage, and `judge/` should stay pure prompt → output.
- Include `prompt_version` in the key so a prompt change invalidates old
  results.

### 3. Report the zero-token share as a metric

Report "X of Y skills decided without an LLM" from the facts, counting only
`MATCHED`, `PARTIAL` and `GAP` observations as decided. Exclude both
`NOT_ASSESSED` and `UNRESOLVABLE`, since neither represents a decision. This:

- shows the free tier's value honestly
- measures the upsell (`NOT_ASSESSED` / `UNRESOLVABLE` count) as a
  `report/` rendering, not billing logic
- is an eval signal in Milestone 5: ontology changes should raise it without
  breaking honesty invariants

### 4. Judge only upgrades, never creates

`judge/` should only refine observations `analyze/` has already made (resolve
`UNRESOLVABLE`, add `confidence`). It must never create a found/absent claim
without provenance. That keeps the zero-token output a correct subset of the
paid output.

## Guardrail

Don't try to replace judgment with ever-growing regex. When a rule needs
context to be right, emit `UNRESOLVABLE` and let `judge/` handle it.
