from enum import Enum
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, model_validator, Field

class SkillStatus(str, Enum):
    MATCHED = "matched"
    PARTIAL = "partial"
    GAP = "gap"
    UNRESOLVABLE = "unresolvable"
    NOT_ASSESSED = "not_assessed"

class Provenance(BaseModel):
    """Audit trail for a single claim. Immutable once created."""

    model_config = ConfigDict(frozen=True)

    source: Literal["resume", "jd", "derived", "llm_judge"]
    locator: str
    retrieved_at: datetime

class SkillObservation(BaseModel):
    model_config = ConfigDict(frozen=True)

    skill: str
    status: SkillStatus
    confidence: float | None = None
    jd_evidence: Provenance | None = None
    resume_evidence: Provenance | None = None

    @model_validator(mode="after")
    def check_evidence(self) -> "SkillObservation":
        if self.status == SkillStatus.MATCHED and self.resume_evidence is None:
            raise ValueError("matched status requires resume_evidence")
        if self.status == SkillStatus.GAP and self.jd_evidence is None:
            raise ValueError("gap status requires jd_evidence")
        return self

    @model_validator(mode="after")
    def check_not_assessed(self) -> "SkillObservation":
        if self.status == SkillStatus.NOT_ASSESSED:
            if self.confidence is not None:
                raise ValueError("confidence should not be set for not_assessed status")
        return self

class FitScore(BaseModel):
    model_config = ConfigDict(frozen=True)

    overall: float = Field(..., ge=0.0, le=1.0)
    must_have_coverage: float = Field(..., ge=0.0, le=1.0)
    nice_to_have_coverage: float = Field(..., ge=0.0, le=1.0)
    explanation: str

class LearningStep(BaseModel):

    skill: str
    priority: int
    why_it_matters: str
    resources: list[str]
    estimated_weeks: int | None

class GapAnalysisFacts(BaseModel):
    model_config = ConfigDict(frozen=True)
    jd_source: str
    analyzed_at: datetime
    llm_used: bool
    schema_version: str = "0.1.0"
    fit_score: FitScore | None = None
    skill_observations: list[SkillObservation]
    learning_steps: list[LearningStep] = []
    perspective: Literal["candidate", "hiring_manager"]

    @model_validator(mode="after")
    def check_llm_used(self) -> "GapAnalysisFacts":
        if not self.llm_used:
            if self.fit_score is not None:
                raise ValueError("fit_score should not be set if llm_used is False")
            if self.learning_steps:
                raise ValueError("learning_steps should not be set if llm_used is False")
        return self