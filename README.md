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
- [x] Milestone 6: Judge — Anthropic API with structured output, versioned prompt YAML files
- [x] Milestone 7: Report + CLI — Markdown reports for two perspectives, every claim quoted, blind spots disclosed
- [x] Milestone 8: Web API + UI — FastAPI file upload, vanilla JS client, strict CSP
- [ ] Milestone 9: Deploy — public-safe server limits, container image, CI deploy, live URL (free keyword tier) · *server limits, image and CI deploy done; the live URL follows the one-time AWS setup below*
- [ ] Milestone 10: Paid tier — accounts, usage metering and rate limits, Stripe, `--deep` on the web

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
Wrote facts.json: 10 JD skills (3 gap, 5 matched, 2 unresolvable)
```

To try your own files, pass any `.pdf` or `.txt` resume and job description. Leave out `-o`
to print the JSON to the terminal instead.

### A readable report

```bash
uv run careerfit --resume fixtures/resume.txt --jd fixtures/jd.txt --report report.md
```

`--report` writes a Markdown report; it works alongside `-o`, and with or without `--deep`.
Every row quotes the line it relies on, so you can check a claim without opening the files:

```markdown
| Skill | Status | The job description says | Your resume shows |
|---|---|---|---|
| python | Matched | line 7: "- 5+ years building production services in Python" | line 6: "Backend engineer with 6 years of experience building REST APIs and data services in Python." |
| kubernetes | Gap | line 9: "- Running Kubernetes in production" | — |
| go | Ambiguous | line 15: "- Experience with Go" | line 17: "- Led the go-live of the new shipment tracking system." |
```

`--perspective` picks who the report is for:

- `candidate` (default): your fit, must-have and nice-to-have skills, and with `--deep` a
  learning plan for the gaps.
- `hiring_manager`: missing must-haves first, then the skills that need a human check, then
  every requirement with its evidence. No learning plan.

Both end with **What this analysis could not see** (skills outside the skill list, unreadable
PDF pages, PDF layout limits for the resume or JD, skills the keyword pass couldn't decide,
anything the LLM judge dismissed or failed on) and **How this was decided** (how many skills
were settled by keywords vs by Claude, which model and prompt versions). A gap list that hides its blind spots overclaims, so these sections
are always present.

### Reading the result

Every skill the job description mentions gets one status and whether the JD treats it as
**must** or **nice** to have. Each result cites the JD line that decided it; results where the
resume mentions the skill also cite that resume line.

| Status | Meaning |
|---|---|
| `matched` | The JD asks for it and the resume clearly shows it |
| `gap` | The JD asks for it and the resume doesn't mention it |
| `unresolvable` | A word like "Go" or "React" could be the skill or an ordinary word, so the keyword pass doesn't guess. `--deep` asks the LLM judge to settle these |
| `not_assessed` | Part of the resume couldn't be read (for example scanned PDF pages), so a missing skill is not reported as a gap |

The keyword pass only knows the skills listed in `src/careerfit/ontology/skills.yaml`.
Skills outside that list are not checked at all.

### Growing the skill list

The keyword pass is only as good as `skills.yaml`, so grow it from real job descriptions and
measure each change:

```bash
uv run python -m evals.ontology_coverage path/to/jd1.txt path/to/jd2.txt
```

It prints how many of each JD's requirement lines mention a known skill, and lists the lines that
mention none. For each of those lines:

1. **Does it name a concrete skill?** ("Kafka", "LangGraph", "SOC 2") Add it, with the other
   spellings as `aliases`.
2. **Does the name have an everyday meaning?** ("at the helm", "harness the power", "in flux")
   Set `ambiguous: true`, so a bare mention is left to `--deep` instead of being guessed.
   Aliases must never be ambiguous.
3. **Is it a paraphrase or a soft skill?** ("how systems fail in production", "mentor engineers")
   Don't add it. Keyword rules can't decide those; the LLM judge can.
4. **Check the resume side too.** If a resume says it differently ("versioned prompts" for prompt
   engineering), add that wording as an alias.
5. **Does a more specific skill show it by definition?** ("PL/SQL" is back-end development and
   SQL.) Add `implies: [backend development, sql]` to the specific skill. A resume that names it
   clearly then matches a JD asking for the broader skill, and the report cites that line as
   "shown through pl/sql". Only strict "X is a kind of Y" facts belong here, never "people who
   know X usually know Y", and implication never runs from the broad skill to the specific one.

`tests/test_ontology.py` fails if any name or alias is claimed by two skills, if an `implies`
names a skill that doesn't exist, and checks the
everyday-meaning words stay ambiguous. Keep real JDs out of the repo (`scratch/` is gitignored)
unless they are labelled held-out cases in `evals/golden/`. A JD used to grow the list can't also
measure it.

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

### Deep analysis with the LLM judge

```bash
# Amazon Bedrock (needs AWS_REGION plus AWS credentials)
export CAREERFIT_LLM_PROVIDER=bedrock
# or the Anthropic API (needs ANTHROPIC_API_KEY or an `ant auth login` profile)
export CAREERFIT_LLM_PROVIDER=anthropic

uv run careerfit --resume fixtures/resume.txt --jd fixtures/jd.txt --deep -o facts.json
```

The keyword pass runs first and costs nothing. `--deep` then asks Claude to settle only the
skills the keyword pass marked `unresolvable`, and writes a fit score and a learning plan for the
gaps.

**What leaves your machine:** each `--deep` run sends the **full text of the resume and the job
description** to Claude through the provider you chose (Amazon Bedrock or the Anthropic API), in
up to four requests: one each for skill matching and the learning plan, plus one retry for each
when an answer is invalid. Without `--deep`, nothing is sent anywhere. Answers are cached locally in `.cache/judge/`; delete that
folder to remove them.

- **Every positive verdict quotes the resume**, and the quote is checked in code before it is
  accepted. A wrong or missing quote is sent back once with the reason; if it's still wrong,
  the skill keeps its keyword verdict and the failure is recorded in `judge.failures`.
- **A skill the JD doesn't really ask for** ("we go live weekly") is dismissed and listed in
  `judge.dismissed_skills`, not silently dropped.
- **The fit score is plain arithmetic** over decided skills (must-haves weighted 75%), with a
  sentence saying how many skills couldn't be assessed.
- **Prompts are versioned data** in `src/careerfit/judge/prompts/`; the versions used are
  recorded in `judge.prompt_versions`.
- **Answers are cached** in `.cache/judge/`, keyed by a SHA-256 of the full request, so a repeat
  analysis costs nothing. Add `--fresh` to bypass the cache.

Optional: `CAREERFIT_MODEL` overrides the model (default `claude-opus-5-5`, or the global
cross-region inference profile `global.anthropic.claude-opus-5-5` on Bedrock).

### The web app

```bash
uv run careerfit-server          # then open http://127.0.0.1:8000/
```

Upload a resume (`.pdf` or `.txt`), then upload the job description or paste it, and pick who
the report is for. The page shows the must-have and nice-to-have tables with the quoted lines,
the same **What this analysis could not see** notes as the Markdown report, and links to download
the report (`.md`) and the facts (`.json`). It uses the same pipeline as the CLI, so the same
files give the same verdicts.

- **Keyword pass only.** The web app never calls an LLM, so nothing leaves the server. `--deep`
  stays in the CLI: a paid LLM call behind a web endpoint needs user identity, usage metering and
  rate limits first.
- **Nothing is kept.** Uploads are buffered and written to temporary files for parsing, and deleted
  before the response is sent; API responses carry `Cache-Control: no-store`.
- **Document text is shown, never run.** The page sets every value with `textContent`, and a
  strict Content-Security-Policy allows only the app's own script and stylesheet.
- **Limits:** 5 MB per file and about 10 MB per request, enforced while the upload streams in;
  20 pages per PDF; 10 analyses per minute per client address (HTTP 429 with `Retry-After`).
  The server binds to `127.0.0.1` by default; `--host`/`--port` (or `CAREERFIT_HOST`/`PORT`)
  change that. There is no authentication yet: accounts come with Milestone 10.

### Running it in a container

```bash
docker build -t careerfit .
docker run --rm -p 8000:8000 careerfit      # then open http://127.0.0.1:8000/
```

The image holds only the installed package (no tests, fixtures or credentials), runs as a
non-root user and checks `GET /healthz`. Behind a hosting platform's proxy, set
`FORWARDED_ALLOW_IPS` to the proxy's address (or `*` when the container is reachable only
through it), so the rate limit sees each visitor's address instead of the proxy's.

### Deploying to AWS Lambda

The same image runs on AWS Lambda. The [Lambda Web Adapter](https://github.com/awslabs/aws-lambda-web-adapter)
in the image turns each invocation into an ordinary HTTP request, and a **Function URL** gives a
public HTTPS address for free. `template.yaml` (AWS SAM) describes the function, its URL, 14-day
log retention and an optional $5/month budget alarm.

```bash
# needs the AWS CLI signed in to your PERSONAL account, Docker, and the SAM CLI (brew install aws-sam-cli)
# once first: the bootstrap stack (image repository, permissions boundary, CI role); see below
sam build
sam deploy --guided --image-repository <ImageRepositoryUri>   # stack name careerfit; prints the URL
sam build && sam deploy                     # later deploys: rebuild, then reuse samconfig.toml
sam delete                                  # removes everything the app stack created
```

- **Architecture: arm64.** The image must be built for the function's architecture; on Apple
  silicon and arm64 CI runners that's the native build.
- **Cost (an estimate, not a cap):** at low traffic, Lambda's always-free allowance (1M requests
  and 400,000 GB-seconds a month) covers the function, leaving a few cents for storing the image
  in ECR. Traffic above the allowance is billed.
- **Upload limit on Lambda: 2 MB per file.** Lambda accepts at most 6 MB per request, counted
  after base64 encoding. The page checks sizes before uploading and reads the limit from
  `GET /api/limits`.
- **Rate limit:** each Lambda instance counts on its own, so the real ceiling is the per-address
  limit times the number of instances running; the account's concurrency limit bounds that
  (`ReservedConcurrency` caps it further once the quota allows).
- **What limits the bill:** the URL is public, so a flood of requests still counts against the
  free allowance and then costs $0.20 per million requests plus compute. The concurrency limit
  bounds how fast that can happen; the budget alarm only sends an email, it doesn't stop charges.

`POST /api/analyze` takes `multipart/form-data` with `resume` (file), either `jd` (file) or
`jd_text`, and `perspective` (`candidate` or `hiring_manager`), and returns `facts`,
`blind_spots` (plain text) and `report_markdown`. Bad input gets a 4xx with a readable `detail`.

### Continuous deployment (GitHub Actions + OIDC)

Every push to `main` deploys, but only after the tests and evals pass: the `deploy` job in
`.github/workflows/ci.yml` builds the arm64 image, runs `sam deploy`, then checks `/healthz` on the
live URL and prints the URL in the run summary. GitHub signs in to AWS with **OpenID Connect**, so
no AWS key is stored anywhere. Until it is connected, the job is skipped and CI stays green.

- **No rollbacks:** deploys run one at a time, and each one first checks that its commit is still
  the head of `main`. An older run whose tests finished late, or a re-run of an old workflow, is
  skipped instead of putting old code back.
- **The running image is never cleaned up:** the image repository keeps the 5 newest images, plus
  the one tagged `live`. After each deploy, CI moves `live` to the image Lambda now runs, so failed
  deploys can't push it out. (Lambda pulls the image again when an idle function wakes up.) A
  manual `sam deploy` doesn't move the tag; the next CI deploy does.

One-time setup, in your **personal** AWS account:

1. **Deploy the bootstrap stack** (`infra/github-deploy-role.yaml`):
   ```bash
   aws cloudformation deploy --template-file infra/github-deploy-role.yaml \
     --stack-name github-deploy-careerfit --capabilities CAPABILITY_NAMED_IAM --profile <personal>
   ```
   It creates the image repository `careerfit-web` (keeps the 5 newest images; only careerfit's
   function may pull), the **permissions boundary** for the function's execution role, and the CI
   role `github-actions-careerfit-deploy`. Add `--parameter-overrides CreateOidcProvider=false` if
   the account already has a GitHub OIDC provider.
2. **Add repository variables** (Settings → Secrets and variables → Actions → *Variables*):
   `AWS_DEPLOY_ROLE_ARN` (the stack's `RoleArn` output), `AWS_REGION`, and `BUDGET_EMAIL` for the
   $5 budget alarm. Leaving it out of a later deploy would delete the alarm. `CAREERFIT_STACK` is
   only needed if the app stack isn't called `careerfit`.
3. **Merge to `main`** (or re-run the workflow). The first green run creates the app stack and
   prints the live URL.

What the CI role can and cannot do:

- **Who:** only workflows on `main` of this repository (an exact match on the token's `sub`
  claim, never a wildcard). Forks, other branches and pull requests are refused.
- **What:** the app stack `careerfit` by exact name, the image repository, the function, its log
  group and budget, and the function's execution role. The bootstrap stack is never in scope.
- **No escalation:** it can create or change the execution role only while the permissions
  boundary is attached, and the boundary allows nothing but writing the function's own logs.
  Explicit denies stop it from touching its own role or the boundary, removing any boundary,
  setting any other boundary, or creating a role without one.
- **Older app stacks:** a stack created before the boundary existed needs no manual step. CI may
  attach this one boundary (and no other), so the next deploy adds it to the execution role.

`tests/test_deploy_config.py` keeps this safe. The build fails if:
- the deploy could run before the tests, outside `main`, or for a commit that is no longer the head of `main`
- an AWS key appears in the workflow, or the trust policy gains a wildcard
- a permission reaches beyond careerfit's own resources, or a stack wildcard brings the bootstrap stack into scope
- the CI role's name falls inside the app's resource names
- an IAM change is allowed without the boundary, or the self-protecting denies go missing
- the boundary allows more than writing the function's own logs
- image cleanup could expire the image tagged `live`, or a deploy stops moving that tag

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
