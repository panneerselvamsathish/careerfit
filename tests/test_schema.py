from typing import Literal

import pytest
from pydantic import ValidationError
from careerfit.facts.schema import GapAnalysisFacts, FitScore, SkillObservation, SkillStatus, LearningStep, Provenance, Coverage
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
    with pytest.raises(ValidationError, match="gap status requires jd_evidence"):
        SkillObservation(skill="test", status=SkillStatus.GAP) # type: ignore[call-arg]

def test_skill_observation_not_assessed_rejects_confidence():
    with pytest.raises(ValidationError, match="confidence should not be set for not_assessed status"):
        SkillObservation(skill="test", status=SkillStatus.NOT_ASSESSED,confidence=0.5) # type: ignore[call-arg]

def test_skill_observation_valid_matched():
    SkillObservation(skill="test", status=SkillStatus.MATCHED, resume_evidence=Provenance(source="resume", locator="experience[0]", retrieved_at=datetime.now()))

def test_skill_observation_matched_requires_evidence():
    with pytest.raises(ValidationError, match="matched status requires resume_evidence"):
        SkillObservation(skill="test", status=SkillStatus.MATCHED) # type: ignore[call-arg]

def test_gap_analysis_facts_llm_true_allows_fit_score():   
    GapAnalysisFacts(llm_used=True, fit_score=FitScore(overall=0.5, must_have_coverage=0.5, nice_to_have_coverage=0.5, explanation="test"),resume_source="test",jd_source="jd test",analyzed_at=datetime.now(),skill_observations=[],perspective="candidate")

def test_gap_analysis_facts_llm_false_rejects_fit_score():
    with pytest.raises(ValidationError, match="fit_score should not be set if llm_used is False"):
        GapAnalysisFacts(llm_used=False, fit_score=FitScore(overall=0.5, must_have_coverage=0.5, nice_to_have_coverage=0.5, explanation="test"),resume_source="test",jd_source="jd test",analyzed_at=datetime.now(),skill_observations=[],perspective="candidate") # type: ignore[call-arg]    

def test_gap_analysis_facts_llm_false_rejects_learning_steps():
    with pytest.raises(ValidationError, match="learning_steps should not be set if llm_used is False"):
        GapAnalysisFacts(llm_used=False, learning_steps=[LearningStep(skill="Python", priority=1, why_it_matters="needed", resources=[], estimated_weeks=4)],resume_source="test",jd_source="jd test",analyzed_at=datetime.now(),skill_observations=[],perspective="candidate") # type: ignore[call-arg]

def test_coverage_valid_pdf():
    Coverage(source_format="pdf", pages_total=3, pages_with_text=2, chars_extracted=100, known_blind_spots=['scanned_pages'])

def test_coverage_valid_txt():
    Coverage(source_format="txt", pages_total=None, pages_with_text=None, chars_extracted=100, known_blind_spots=[]) #type: ignore[call-arg] 

def test_coverage_rejects_more_text_pages_than_total():
    with pytest.raises(ValidationError, match="pages_with_text cannot be greater than pages_total"):
        Coverage(source_format="pdf", pages_total=3, pages_with_text=4, chars_extracted=100, known_blind_spots=['scanned_pages'])

def test_coverage_rejects_unknown_blind_spot():
    with pytest.raises(ValidationError):
        Coverage(source_format="pdf", pages_total=3, pages_with_text=2, chars_extracted=100, known_blind_spots=['images']) #type: ignore[call-arg] 

def test_coverage_requires_blind_spots():
    with pytest.raises(ValidationError):
        Coverage(source_format="pdf", pages_total=3, pages_with_text=2, chars_extracted=100) # type: ignore[call-arg]