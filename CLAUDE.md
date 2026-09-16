# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with
code in this repository.

## Commands

```bash
# Install all dependencies (including dev)
uv sync --dev

# Run all tests
uv run pytest

# Run a single test file
uv run pytest tests/test_architecture.py -v

# Run the CLI — keyword analysis only (no LLM)
uv run careerfit --resume fixtures/resume.txt --jd fixtures/jd.txt -o facts.json

# Run the CLI — with LLM judge (needs ANTHROPIC_API_KEY)
uv run careerfit --resume fixtures/resume.txt --jd fixtures/jd.txt --deep -o facts.json

# Start the web server
uv run careerfit-server

# Run the eval harness against a facts file
uv run python evals/harness.py facts.json
```

## Architecture

Pipeline: **ingest → analyze → facts → (judge) → report**

```
src/careerfit/
  ingest/      I/O only. Parse PDF or plain-text resume. Parse JD text.
               MUST NOT: call an LLM, import analyze/.
  analyze/     Pure functions. Keyword extraction, gap computation.
               MUST NOT: import judge/, call an LLM, hit the network, read the clock.
  facts/       Pydantic v2 schema. Shared contract between all packages.
               MUST NOT: import any other careerfit package.
  judge/       The ONLY package allowed to call the Anthropic API.
               Prompts are versioned YAML data files in judge/prompts/.
               MUST NOT: be imported by analyze/ or report/.
  ontology/    skills.yaml — data file mapping skill → category → resources.
               No logic lives here.
  report/      Renderers only. Zero logic.
               MUST NOT: call an LLM, import judge/, import analyze/.
  cli.py       Composition root for terminal use.
  api.py       FastAPI composition root for web use.
```

### The enforced boundary

`tests/test_architecture.py` uses `ast.parse()` to enforce forbidden imports
without executing the code. This is not a convention — it is a build constraint.
If analyze/ imports anthropic, the test fails and the PR cannot merge.

### The five-status schema

`SkillStatus` in `facts/schema.py`:

| Status | Meaning | Provenance required? |
|---|---|---|
| `MATCHED` | Resume clearly demonstrates this skill | Yes |
| `PARTIAL` | Weak or indirect evidence | Optional |
| `GAP` | Required by JD, absent in resume | Yes |
| `NOT_ASSESSED` | LLM not run; no opinion | No |
| `UNRESOLVABLE` | Ambiguous mapping; judge/ resolves these | No |

`GAP ≠ UNRESOLVABLE`. A report may state GAP. A report must never state
a conclusion from UNRESOLVABLE — it must say "ambiguous" and defer to judge/.

### Confidence scores

`confidence: float | None` on every `SkillObservation`. ONLY set by judge/
after LLM semantic analysis. When `llm_used=False`, confidence is always None.
An honesty invariant in `evals/invariants.py` enforces this.

### Prompt versioning

Prompts live as YAML files in `judge/prompts/`, not string literals in code.
Each file carries: `version`, `system`, `user`, `output_schema`.
Prompts are reviewable via diff and rollbackable without touching Python.

### Two perspectives, one facts file

The same `GapAnalysisFacts` renders two ways:
- **candidate**: what to work on, why, how long
- **hiring_manager**: how this candidate ranks against the JD

No logic lives in `report/`. If changing the perspective changes a finding,
the finding belongs in `facts/`, not `report/`.

### `at: datetime` from caller

Functions in `analyze/` accept `at: datetime` and never call `datetime.now()`.
The CLI/API passes the current timestamp in. Same input → byte-identical output.

## Milestones

| # | Name | Concept |
|---|---|---|
| 1 | Scaffold | uv + src layout, AST boundary enforcement |
| 2 | Facts schema | Pydantic v2 @model_validator, frozen=True, Literal types |
| 3 | Ingest | pypdf, Coverage builder, known_blind_spots at parse time |
| 4 | Analyze | Pure functions, injected datetime, Provenance locators |
| 5 | Evals | Two-layer eval: honesty invariants vs. golden expectations |
| 6 | Judge | Anthropic tool_use structured output, prompt versioning |
| 7 | Report + CLI | Rendering separation, composition root pattern |
| 8 | Web API + UI | FastAPI file upload, serving static files, client-side render |
