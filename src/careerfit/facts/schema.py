from enum import Enum
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, model_validator, Field

class SkillStatus(str, Enum):
    MATCHED = "matched"
    PARTIAL = "partial"
    GAP = "gap"
    # The JD accepts another skill in its place ("OpenAI or Anthropic APIs") and the resume shows that one.
    ALTERNATIVE_MET = "alternative_met"
    UNRESOLVABLE = "unresolvable"
    NOT_ASSESSED = "not_assessed"

class Provenance(BaseModel):
    """Audit trail for a single claim. Immutable once created."""

    model_config = ConfigDict(frozen=True, extra="forbid")


    source: Literal["resume", "jd", "derived", "alternative", "llm_judge"]
    locator: str
    excerpt: str  # the cited text itself, so a reader can check the claim without the source file
    retrieved_at: datetime
    # source="derived": the skill named on the cited line that implies this one.
    # source="alternative": the skill on the cited line that the JD accepts in place of this one.
    via: str | None = None

    @model_validator(mode="after")
    def check_via(self) -> "Provenance":
        if self.source in ("derived", "alternative") and not self.via:
            raise ValueError(f"{self.source} evidence must name the skill it stands on (via)")
        if self.source not in ("derived", "alternative") and self.via is not None:
            raise ValueError("only derived or alternative evidence has a via skill")
        return self

class SkillObservation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    skill: str
    status: SkillStatus
    confidence: float | None = None
    jd_evidence: Provenance
    resume_evidence: Provenance | None = None
    requirement: Literal["must", "nice"]


    @model_validator(mode="after")
    def check_evidence(self) -> "SkillObservation":
        if self.status == SkillStatus.MATCHED and self.resume_evidence is None:
            raise ValueError("matched status requires resume_evidence")
        return self

    @model_validator(mode="after")
    def check_alternative(self) -> "SkillObservation":
        # An alternative stands on another skill's resume line, never on one of this skill's own.
        alternative = self.resume_evidence is not None and self.resume_evidence.source == "alternative"
        if (self.status == SkillStatus.ALTERNATIVE_MET) != alternative:
            raise ValueError("alternative_met status and alternative evidence go together")
        if self.status == SkillStatus.ALTERNATIVE_MET and self.confidence is not None:
            raise ValueError("confidence should not be set for alternative_met status")
        return self

    @model_validator(mode="after")
    def check_not_assessed(self) -> "SkillObservation":
        if self.status == SkillStatus.NOT_ASSESSED:
            if self.confidence is not None:
                raise ValueError("confidence should not be set for not_assessed status")
        return self

class FitScore(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    overall: float = Field(..., ge=0.0, le=1.0)
    must_have_coverage: float = Field(..., ge=0.0, le=1.0)
    nice_to_have_coverage: float = Field(..., ge=0.0, le=1.0)
    explanation: str

class LearningStep(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    skill: str
    priority: int
    why_it_matters: str
    resources: tuple[str, ...]
    estimated_weeks: int | None

class Coverage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source_format: Literal["pdf", "txt"]
    pages_total: int | None = Field(..., ge=0)
    pages_with_text: int | None = Field(..., ge=0)
    chars_extracted: int=Field(..., ge=0)
    known_blind_spots: tuple[Literal["scanned_pages", "layout_order", "graphics", "tables"], ...]

    @model_validator(mode="after")
    def check_pages_with_text(self) -> "Coverage":
        if self.pages_with_text is not None and self.pages_total is not None:
            if self.pages_with_text > self.pages_total:
                raise ValueError("pages_with_text cannot be greater than pages_total")
        return self
class RequirementLineCount(BaseModel):
    """How many of the JD's requirement lines name at least one skill careerfit knows. The rest it
    could not read at all, so the result covers only part of what the job asks for."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    read: int = Field(ge=0)
    total: int = Field(ge=0)

    @model_validator(mode="after")
    def check_read(self) -> "RequirementLineCount":
        if self.read > self.total:
            raise ValueError("read cannot be greater than total")
        return self


class JudgeRun(BaseModel):
    """Audit record of an LLM judge pass: what ran, and what it could not do."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    model: str
    prompt_versions: tuple[str, ...]
    served_by: tuple[str, ...] = ()
    dismissed_skills: tuple[str, ...] = ()
    failures: tuple[str, ...] = ()


class GapAnalysisFacts(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    resume_source: str
    jd_source: str
    resume_coverage: Coverage
    jd_coverage: Coverage
    analyzed_at: datetime
    llm_used: bool
    # 0.5.0: Provenance.via for skills shown through another skill
    # 0.6.0: alternative_met status and alternative evidence for either/or requirements
    # 0.7.0: jd_requirement_lines, how much of the JD the skill list could read
    schema_version: str = "0.7.0"
    jd_requirement_lines: RequirementLineCount | None = None
    fit_score: FitScore | None = None
    judge: JudgeRun | None = None
    skill_observations: tuple[SkillObservation, ...]
    learning_steps: tuple[LearningStep, ...] = ()
    perspective: Literal["candidate", "hiring_manager"]

    @model_validator(mode="after")
    def check_llm_used(self) -> "GapAnalysisFacts":
        if not self.llm_used:
            if self.fit_score is not None:
                raise ValueError("fit_score should not be set if llm_used is False")
            if self.learning_steps:
                raise ValueError("learning_steps should not be set if llm_used is False")
            if self.judge is not None:
                raise ValueError("judge should not be set if llm_used is False")
        elif self.judge is None:
            raise ValueError("judge is required when llm_used is True")
        dismissed = set(self.judge.dismissed_skills) if self.judge else set()
        if dismissed & {o.skill for o in self.skill_observations}:
            raise ValueError("a dismissed skill cannot also be observed")
        return self
