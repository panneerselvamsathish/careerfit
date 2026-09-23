# careerfit

Resume ↔ job description gap analyser with AI-powered learning path generation.

> **Status:** Work in progress — building milestone by milestone as a public learning project.

## What it does

Takes a resume (PDF or plain text) and a job description, computes a gap analysis,
and generates a prioritised learning path to close the gaps.

Two perspectives:
- **Candidate** — what skills to work on, why they matter, and specific resources to get there
- **Hiring manager** — how this candidate ranks against must-have and nice-to-have requirements

## Architecture

`ingest → analyze → facts → judge → report` — one-directional pipeline. No layer reaches back.

```
ingest/    Parse PDF/text resume and JD. I/O only — no interpretation.
analyze/   Pure keyword extraction and gap computation. No LLM, no network.
facts/     Pydantic v2 schema. The shared contract between all packages.
judge/     The only layer allowed to call the Anthropic API. Semantic matching,
           confidence scoring, learning path generation.
ontology/  Skills taxonomy data file (skills.yaml). Data, not code.
report/    Renderers only. Zero logic. Two perspectives: candidate, hiring_manager.
```

Architectural boundaries are enforced by `tests/test_architecture.py` using `ast.parse()` —
not conventions, not comments. A build constraint.

## Milestones

- [x] Milestone 1: Scaffold — uv, src layout, AST boundary enforcement
- [x] Milestone 2: Facts schema — Pydantic v2 models, five-status enum, model validators
- [ ] Milestone 3: Ingest — PDF + plain text parsing, Coverage builder
- [ ] Milestone 4: Analyze — pure skill extraction, keyword gap computation
- [ ] Milestone 5: Evals — honesty invariants + golden expectations (two-layer eval design)
- [ ] Milestone 6: Judge — Anthropic API with structured output, versioned prompt YAML files
- [ ] Milestone 7: Report + CLI — rendering separation, composition root pattern
- [ ] Milestone 8: Web API + UI — FastAPI file upload, vanilla JS client

## Running locally

```bash
# Install dependencies
uv sync --dev

# Run tests
uv run pytest

# Analyse a resume against a JD (keyword pass, no LLM)
uv run careerfit --resume fixtures/resume.txt --jd fixtures/jd.txt -o facts.json

# Deep analysis with LLM (needs ANTHROPIC_API_KEY)
uv run careerfit --resume fixtures/resume.txt --jd fixtures/jd.txt --deep -o facts.json

# Start the web server
uv run careerfit-server
```

## Tech stack

- Python 3.12, [uv](https://docs.astral.sh/uv/)
- [Pydantic v2](https://docs.pydantic.dev/) — schema and validation
- [pypdf](https://pypdf.readthedocs.io/) — PDF parsing
- [Anthropic API](https://docs.anthropic.com/) — LLM judge layer
- [FastAPI](https://fastapi.tiangolo.com/) — web API
