"""The only package that calls an LLM.

It refines observations analyze/ already made and never creates a claim it cannot verify in
the documents. Only UNRESOLVABLE skills are sent to the model, and every positive verdict must
quote the resume; quotes are checked in code before they are accepted.
"""

import json
import re
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any, Literal, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from careerfit.analyze.matcher import detect
from careerfit.analyze.ontology import SkillEntry
from careerfit.facts.schema import (
    GapAnalysisFacts,
    JudgeRun,
    LearningStep,
    Provenance,
    SkillObservation,
    SkillStatus,
)
from careerfit.judge.fit import compute_fit_score
from careerfit.judge.prompts import PromptSpec, load_prompt

MAX_TOKENS = 16000
EFFORT = "medium"
MAX_RESOURCES = 3
MIN_QUOTE_WORDS = 3

T = TypeVar("T", bound=BaseModel)


class LLM(Protocol):
    """Anything with the Messages API's create(); the composition root supplies the real client."""

    def create(self, **kwargs: Any) -> Any: ...


class JudgeFailure(Exception):
    """The LLM's answer could not be used. Affected skills keep their keyword verdict."""


class SkillVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skill: str
    jd_requires_skill: bool
    resume_status: Literal["matched", "partial", "absent", "unclear"]
    resume_quote: str
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str


class SkillVerdicts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdicts: list[SkillVerdict]


class PlannedStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skill: str
    priority: int = Field(ge=1)
    why_it_matters: str
    resources: list[str]
    estimated_weeks: int = Field(ge=0)


class LearningPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    steps: list[PlannedStep]


def judge_facts(
    facts: GapAnalysisFacts,
    *,
    resume_text: str,
    jd_text: str,
    llm: LLM,
    model: str,
    at: datetime,
    ontology: dict[str, SkillEntry],
) -> GapAnalysisFacts:
    """Return a judged copy of keyword-only facts (llm_used=True), with fit score and learning path."""
    if facts.llm_used:
        raise ValueError("these facts were already judged")
    skill_prompt, plan_prompt = load_prompt("skill_match"), load_prompt("learning_path")
    scanned = "scanned_pages" in facts.resume_coverage.known_blind_spots
    observations = list(facts.skill_observations)
    prompts_used: list[str] = []
    dismissed: list[str] = []
    failures: list[str] = []
    served_by: list[str] = []

    unresolved = [o for o in observations if o.status == SkillStatus.UNRESOLVABLE]
    if unresolved:
        prompts_used.append(skill_prompt.ref)
        try:
            verdicts = resolve_skills(unresolved, resume_text=resume_text, jd_text=jd_text, llm=llm, model=model,
                                      prompt=skill_prompt, ontology=ontology, served_by=served_by)
        except JudgeFailure as e:
            failures.append(str(e))
            verdicts = {}
        refined: list[SkillObservation] = []
        for o in observations:
            verdict = verdicts.get(o.skill) if o.status == SkillStatus.UNRESOLVABLE else None
            if verdict is None:
                refined.append(o)
            elif not verdict.jd_requires_skill:
                dismissed.append(o.skill)
            else:
                refined.append(_apply_verdict(o, verdict, resume_text=resume_text, scanned=scanned, at=at))
        observations = refined

    steps: tuple[LearningStep, ...] = ()
    gaps = [o for o in observations if o.status == SkillStatus.GAP]
    if gaps:
        prompts_used.append(plan_prompt.ref)
        try:
            steps = plan_learning(gaps, resume_text=resume_text, jd_text=jd_text,
                                  llm=llm, model=model, prompt=plan_prompt, served_by=served_by)
        except JudgeFailure as e:
            failures.append(str(e))

    data = facts.model_dump()
    data.update(
        llm_used=True,
        skill_observations=tuple(observations),
        fit_score=compute_fit_score(tuple(observations)),
        learning_steps=steps,
        judge=JudgeRun(model=model, prompt_versions=tuple(prompts_used), served_by=tuple(dict.fromkeys(served_by)),
                       dismissed_skills=tuple(dismissed), failures=tuple(failures)),
    )
    return GapAnalysisFacts.model_validate(data)


def resolve_skills(
    unresolved: Sequence[SkillObservation],
    *,
    resume_text: str,
    jd_text: str,
    llm: LLM,
    model: str,
    prompt: PromptSpec,
    ontology: dict[str, SkillEntry],
    served_by: list[str] | None = None,
) -> dict[str, SkillVerdict]:
    names = [o.skill for o in unresolved]
    jd_lines = jd_text.splitlines()
    resume_lines = resume_text.splitlines()
    asks = []
    jd_line_of = {o.skill: _line_text(jd_lines, o.jd_evidence.locator) for o in unresolved}
    for o in unresolved:
        jd_line = _line_text(jd_lines, o.jd_evidence.locator)
        resume_line = _line_text(resume_lines, o.resume_evidence.locator) if o.resume_evidence else None
        resume_part = f'resume mentions it on: "{resume_line}"' if resume_line else "resume: no keyword mention"
        asks.append(f'- {o.skill} ({o.requirement}-have): JD says "{jd_line}"; {resume_part}')
    user = prompt.render_user(documents=_documents(jd_text, resume_text), skills="\n".join(asks))

    def check(answer: SkillVerdicts) -> list[str]:
        problems = _coverage_problems([v.skill for v in answer.verdicts], names)
        for v in answer.verdicts:
            # Enforced in code, so no instruction hidden in a document can override it: a skill the
            # JD names unambiguously (e.g. "Golang") is a real requirement and cannot be dismissed.
            entry = ontology.get(v.skill)
            if not v.jd_requires_skill and entry and detect(v.skill, entry, jd_line_of[v.skill]) == "found":
                problems.append(f"{v.skill}: the job description names it unambiguously "
                                f"(\"{jd_line_of[v.skill]}\"), so it cannot be dismissed")
            if v.resume_status in ("matched", "partial"):
                if len(v.resume_quote.split()) < MIN_QUOTE_WORDS:
                    problems.append(f"{v.skill}: resume_quote must be at least {MIN_QUOTE_WORDS} words copied "
                                    f"from the resume, got {v.resume_quote!r}")
                elif find_quote_line(v.resume_quote, resume_text) is None:
                    problems.append(f"{v.skill}: resume_quote {v.resume_quote!r} is not on any single line "
                                    "of the resume; copy the exact words")
        return problems

    answer = _ask(llm, model=model, prompt=prompt, user=user, schema=prompt.schema_for(names),
                  answer_type=SkillVerdicts, check=check, served_by=served_by)
    return {v.skill: v for v in answer.verdicts}


def plan_learning(
    gaps: Sequence[SkillObservation],
    *,
    resume_text: str,
    jd_text: str,
    llm: LLM,
    model: str,
    prompt: PromptSpec,
    served_by: list[str] | None = None,
) -> tuple[LearningStep, ...]:
    names = [o.skill for o in gaps]
    requirements = {o.skill: o.requirement for o in gaps}
    listed = "\n".join(f"- {o.skill} ({o.requirement}-have)" for o in gaps)
    user = prompt.render_user(documents=_documents(jd_text, resume_text), skills=listed)

    def check(answer: LearningPlan) -> list[str]:
        problems = _coverage_problems([s.skill for s in answer.steps], names)
        priorities = sorted(s.priority for s in answer.steps)
        if priorities != list(range(1, len(answer.steps) + 1)):
            problems.append(f"priorities must be 1..{len(answer.steps)} with each used once, got {priorities}")
        must = [s.priority for s in answer.steps if requirements.get(s.skill) == "must"]
        nice = [s.priority for s in answer.steps if requirements.get(s.skill) == "nice"]
        if must and nice and max(must) > min(nice):
            problems.append("every must-have gap must have a higher priority (lower number) than every nice-to-have gap")
        for s in answer.steps:
            if not 1 <= len(s.resources) <= MAX_RESOURCES:
                problems.append(f"{s.skill}: give 1 to {MAX_RESOURCES} resources, got {len(s.resources)}")
            for resource in s.resources:
                if looks_like_link(resource):
                    problems.append(f"{s.skill}: {resource!r} contains a link; name the title and publisher instead")
        return problems

    answer = _ask(llm, model=model, prompt=prompt, user=user, schema=prompt.schema_for(names),
                  answer_type=LearningPlan, check=check, served_by=served_by)
    return tuple(
        LearningStep(skill=s.skill, priority=s.priority, why_it_matters=s.why_it_matters,
                     resources=tuple(s.resources), estimated_weeks=s.estimated_weeks or None)
        for s in sorted(answer.steps, key=lambda s: s.priority)
    )


# A bare domain naming the publisher, e.g. "(kubernetes.io)", is allowed: it can't point at a page
# that doesn't exist. Anything that addresses a specific location could be made up, so it's rejected.
_LINK_PATTERNS = (
    re.compile(r"\b[a-z][a-z0-9+.-]*:(?=\S)", re.IGNORECASE),     # any scheme: https:, ftp:, mailto:, doi:
    re.compile(r"\bwww\.", re.IGNORECASE),
    re.compile(r"\]\("),                                         # Markdown link [text](target)
    re.compile(r"\b[a-z0-9-]+(\.[a-z0-9-]+)+/\S", re.IGNORECASE),  # domain followed by a path
)


def looks_like_link(resource: str) -> bool:
    return any(p.search(resource) for p in _LINK_PATTERNS)


def find_quote_line(quote: str, text: str) -> int | None:
    """1-based line of the first line containing the quote as whole words, ignoring case and spacing."""
    needle = _normalise(quote)
    if not needle:
        return None
    # Whole words only: a quote of "Go" must not be "found" inside "Google".
    pattern = re.compile(rf"(?<!\w){re.escape(needle)}(?!\w)")
    for line_no, line in enumerate(text.splitlines(), start=1):
        if pattern.search(_normalise(line)):
            return line_no
    return None


def _apply_verdict(
    observation: SkillObservation, verdict: SkillVerdict, *, resume_text: str, scanned: bool, at: datetime
) -> SkillObservation:
    base = dict(skill=observation.skill, requirement=observation.requirement, jd_evidence=observation.jd_evidence)
    if verdict.resume_status in ("matched", "partial"):
        line = find_quote_line(verdict.resume_quote, resume_text)
        status = SkillStatus.MATCHED if verdict.resume_status == "matched" else SkillStatus.PARTIAL
        evidence = Provenance(source="llm_judge", locator=f"line {line}", retrieved_at=at)
        return SkillObservation(**base, status=status, confidence=verdict.confidence, resume_evidence=evidence)
    if verdict.resume_status == "absent":
        if scanned:
            return SkillObservation(**base, status=SkillStatus.NOT_ASSESSED)
        return SkillObservation(**base, status=SkillStatus.GAP, confidence=verdict.confidence)
    return observation


def _ask(
    llm: LLM,
    *,
    model: str,
    prompt: PromptSpec,
    user: str,
    schema: dict,
    answer_type: type[T],
    check: Callable[[T], list[str]],
    served_by: list[str] | None = None,
) -> T:
    """One request, plus one retry that tells the model exactly what was wrong."""
    messages: list[dict[str, Any]] = [{"role": "user", "content": user}]
    for attempt in (1, 2):
        response = llm.create(
            model=model,
            max_tokens=MAX_TOKENS,
            system=prompt.full_system,
            messages=messages,
            output_config={"effort": EFFORT, "format": {"type": "json_schema", "schema": schema}},
        )
        if served_by is not None:
            # A server-side fallback can answer with a different model; record who actually did.
            served_by.append(getattr(response, "model", None) or model)
        stop = getattr(response, "stop_reason", None)
        if stop == "refusal":
            raise JudgeFailure(f"{prompt.ref}: the model declined the request")
        if stop == "max_tokens":
            raise JudgeFailure(f"{prompt.ref}: the answer was cut off at max_tokens")
        text = "".join(_block_text(b) for b in response.content)
        try:
            answer = answer_type.model_validate(json.loads(text))
            problems = check(answer)
        except (json.JSONDecodeError, ValidationError) as e:
            problems = [f"the answer did not match the required format ({str(e)[:300]})"]
        if not problems:
            return answer
        if attempt == 2:
            raise JudgeFailure(f"{prompt.ref}: answer still invalid after one retry: " + "; ".join(problems))
        # Append, never edit: the retry sees its own previous answer and the reasons it was rejected.
        messages = messages + [
            {"role": "assistant", "content": response.content},
            {"role": "user", "content": "Your answer could not be accepted:\n- " + "\n- ".join(problems)
                                        + "\nAnswer again in full, fixing these problems."},
        ]
    raise AssertionError("unreachable")


def _coverage_problems(answered: list[str], expected: list[str]) -> list[str]:
    problems = [f"{name}: missing from the answer" for name in expected if name not in answered]
    problems += [f"{name}: answered more than once" for name in sorted(set(answered)) if answered.count(name) > 1]
    return problems


# Documents are untrusted: they must not be able to open or close the sections that frame them.
_FRAME_TAG = re.compile(r"<\s*/?\s*(resume|job_description)\s*>", re.IGNORECASE)


def _documents(jd_text: str, resume_text: str) -> str:
    jd, resume = _FRAME_TAG.sub("[tag removed]", jd_text), _FRAME_TAG.sub("[tag removed]", resume_text)
    return f"<job_description>\n{jd}\n</job_description>\n\n<resume>\n{resume}\n</resume>"


def _line_text(lines: list[str], locator: str) -> str:
    _, _, number = locator.partition(" ")
    index = int(number) - 1 if number.isdigit() else -1
    return lines[index].strip() if 0 <= index < len(lines) else ""


def _block_text(block: Any) -> str:
    kind = block.get("type") if isinstance(block, dict) else getattr(block, "type", None)
    if kind != "text":
        return ""
    return block["text"] if isinstance(block, dict) else block.text


def _normalise(text: str) -> str:
    return " ".join(text.split()).casefold()
