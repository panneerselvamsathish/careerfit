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
- [x] Milestone 3: Ingest — PDF + plain text parsing, Coverage builder
- [x] Milestone 4: Analyze — pure skill extraction, keyword gap computation
- [x] Milestone 5: Evals — honesty invariants + golden expectations (two-layer eval design)
- [ ] Milestone 6: Judge — Anthropic API with structured output, versioned prompt YAML files
- [ ] Milestone 7: Report + CLI — rendering separation, composition root pattern (CLI keyword pass works; report rendering to come)
- [ ] Milestone 8: Web API + UI — FastAPI file upload, vanilla JS client

## Getting started

You need [git](https://git-scm.com/) and [uv](https://docs.astral.sh/uv/getting-started/installation/).
uv installs Python 3.12 for you if it isn't already on your machine.

```bash
# 1. Clone and enter the repo
git clone https://github.com/panneerselvamsathish/careerfit.git
cd careerfit

# 2. Install dependencies (creates a local .venv)
uv sync

# 3. Run the tests
uv run pytest

# 4. Analyse the sample resume against the sample job description
uv run careerfit --resume fixtures/resume.txt --jd fixtures/jd.txt -o facts.json
```

Step 4 prints a one-line summary and writes the full result to `facts.json`:

```text
Wrote facts.json: 9 JD skills (3 gap, 4 matched, 2 unresolvable)
```

To try your own files, pass any `.pdf` or `.txt` resume and job description. Leave out `-o`
to print the JSON to the terminal instead.

### Reading the result

Every skill the job description mentions gets one status and whether the JD treats it as
**must** or **nice** to have. Each result cites the JD line that decided it; results where the
resume mentions the skill also cite that resume line.

| Status | Meaning |
|---|---|
| `matched` | The JD asks for it and the resume clearly shows it |
| `gap` | The JD asks for it and the resume doesn't mention it |
| `unresolvable` | A word like "Go" or "React" could be the skill or an ordinary word, so the keyword pass doesn't guess. The LLM tier (Milestone 6) settles these |
| `not_assessed` | Part of the resume couldn't be read (for example scanned PDF pages), so a missing skill is not reported as a gap |

The keyword pass only knows the skills listed in `src/careerfit/ontology/skills.yaml`.
Skills outside that list are not checked at all.

### Checking quality: the evals

```bash
uv run python -m evals.harness
```

Two independent layers, both run in CI on every pull request:

- **Honesty invariants** (`evals/invariants.py`) need no right answer, so they hold for any
  resume. For example: `not_assessed` only appears when part of the resume really was
  unreadable, no gap is claimed in that case, and every cited line exists and actually
  mentions the skill.
- **Golden cases** (`evals/golden/`) are hand-labelled resume/JD pairs with the expected
  status and must/nice level for each skill. Development cases must all pass. Held-out cases
  only measure the rules and are never used to tune them, so a miss is reported but doesn't
  fail the build.

The report breaks accuracy down by field (status, requirement level), by development vs
held-out, and by document type (`txt`, `pdf`). The current cases were written alongside the
rules, so their 100% is an upper bound; the real test is held-out cases built from real job
descriptions.

### Planned commands

```bash
# Deep analysis with the LLM judge (Milestone 6; needs an API key)
uv run careerfit --resume fixtures/resume.txt --jd fixtures/jd.txt --deep -o facts.json

# Web server (Milestone 8)
uv run careerfit-server
```

## Tech stack

- Python 3.12, [uv](https://docs.astral.sh/uv/)
- [Pydantic v2](https://docs.pydantic.dev/) — schema and validation
- [pypdf](https://pypdf.readthedocs.io/) — PDF parsing
- [Anthropic API](https://docs.anthropic.com/) — LLM judge layer
- [FastAPI](https://fastapi.tiangolo.com/) — web API

## How this was built

Built with [Claude Code](https://claude.com/claude-code) as a pair programmer. I own the
design, schema and boundaries; architectural rules are enforced by tests
(`tests/test_architecture.py`), not trust. Project rules for the agent live in `CLAUDE.md`
and `.claude/`. PRs are reviewed by Copilot and by me.
