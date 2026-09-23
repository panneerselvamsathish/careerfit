import pytest
from pydantic import ValidationError
from careerfit.facts.schema import GapAnalysisFacts, FitScore, SkillObservation, SkillStatus, LearningStep, Provenance
from datetime import datetime

def test_fit_score_valid():
    FitScore(overall=0.5, must_have_coverage=0.5, nice_to_have_coverage=0.5, explanation="test")

def test_fit_score_rejects_overall_above_1():
    with pytest.raises(ValidationError):
        FitScore(overall=1.5, must_have_coverage=0.5, nice_to_have_coverage=0.5, explanation="test")

def test_fit_score_rejects_must_have_coverage_above_1():
    with pytest.raises(ValidationError):
        FitScore(overall=0.5, must_have_coverage=1.5, nice_to_have_coverage=0.5, explanation="test")

def test_fit_score_rejects_nice_to_have_coverage_above_1():
    with pytest.raises(ValidationError):
        FitScore(overall=0.5, must_have_coverage=0.5, nice_to_have_coverage=1.5, explanation="test")

def test_fit_score_requires_explanation():
    with pytest.raises(ValidationError):
        FitScore(overall=0.5, must_have_coverage=0.5, nice_to_have_coverage=0.5) # type: ignore[call-arg]

def test_skill_observation_gap_requires_evidence():
    with pytest.raises(ValidationError):
        SkillObservation(skill="test", status=SkillStatus.GAP) # type: ignore[call-arg]

def test_skill_observation_not_assessed_rejects_confidence():
    with pytest.raises(ValidationError):
        SkillObservation(skill="test", status=SkillStatus.NOT_ASSESSED,confidence=0.5) # type: ignore[call-arg]

def test_skill_observation_valid_matched():
    SkillObservation(skill="test", status=SkillStatus.MATCHED, jd_evidence=Provenance(source="jd", locator="test", retrieved_at=datetime.now()))

def test_skill_observation_matched_requires_evidence():
    with pytest.raises(ValidationError):
        SkillObservation(skill="test", status=SkillStatus.MATCHED) # type: ignore[call-arg]

def test_gap_analysis_facts_llm_true_allows_fit_score():   
    GapAnalysisFacts(llm_used=True, fit_score=FitScore(overall=0.5, must_have_coverage=0.5, nice_to_have_coverage=0.5, explanation="test"),resume_source="test",jd_source="jd test",analyzed_at=datetime.now(),skill_observations=[],perspective="candidate")

def test_gap_analysis_facts_llm_false_rejects_fit_score():
    with pytest.raises(ValidationError):
        GapAnalysisFacts(llm_used=False, fit_score=FitScore(overall=0.5, must_have_coverage=0.5, nice_to_have_coverage=0.5, explanation="test"),resume_source="test",jd_source="jd test",analyzed_at=datetime.now(),skill_observations=[],perspective="candidate") # type: ignore[call-arg]    

def test_gap_analysis_facts_llm_false_rejects_learning_steps():
    with pytest.raises(ValidationError):
        GapAnalysisFacts(llm_used=False, learning_steps=[LearningStep(skill="Python", priority=1, why_it_matters="needed", resources=[], estimated_weeks=4)],resume_source="test",jd_source="jd test",analyzed_at=datetime.now(),skill_observations=[],perspective="candidate") # type: ignore[call-arg]