import pytest,inspect
from pydantic import BaseModel, ValidationError
from careerfit.facts import schema 
from datetime import datetime

FACTS_MODELS = [
    cls for _, cls in inspect.getmembers(schema, inspect.isclass)
    if issubclass(cls, BaseModel) and cls.__module__ == schema.__name__
]

@pytest.mark.parametrize("model", FACTS_MODELS, ids=lambda m: m.__name__)
def test_facts_models_forbid_extra_and_are_frozen(model):
    assert model.model_config.get("extra") == "forbid"
    assert model.model_config.get("frozen") is True
        
def test_fit_score_valid():
    schema.FitScore(overall=0.5, must_have_coverage=0.5, nice_to_have_coverage=0.5, explanation="test")

def test_fit_score_rejects_overall_above_1():
    with pytest.raises(ValidationError):
        schema.FitScore(overall=1.5, must_have_coverage=0.5, nice_to_have_coverage=0.5, explanation="test")

def test_fit_score_rejects_must_have_coverage_above_1():
    with pytest.raises(ValidationError):
        schema.FitScore(overall=0.5, must_have_coverage=1.5, nice_to_have_coverage=0.5, explanation="test")

def test_fit_score_rejects_nice_to_have_coverage_above_1():
    with pytest.raises(ValidationError):
        schema.FitScore(overall=0.5, must_have_coverage=0.5, nice_to_have_coverage=1.5, explanation="test")

def test_fit_score_requires_explanation():
    with pytest.raises(ValidationError):
        schema.FitScore(overall=0.5, must_have_coverage=0.5, nice_to_have_coverage=0.5) # type: ignore[call-arg]

def test_skill_observation_gap_requires_evidence():
    with pytest.raises(ValidationError, match="gap status requires jd_evidence"):
        schema.SkillObservation(skill="test", status=schema.SkillStatus.GAP) # type: ignore[call-arg]

def test_skill_observation_not_assessed_rejects_confidence():
    with pytest.raises(ValidationError, match="confidence should not be set for not_assessed status"):
        schema.SkillObservation(skill="test", status=schema.SkillStatus.NOT_ASSESSED,confidence=0.5) # type: ignore[call-arg]

def test_skill_observation_valid_matched():
    schema.SkillObservation(skill="test", status=schema.SkillStatus.MATCHED, resume_evidence=schema.Provenance(source="resume", locator="experience[0]", retrieved_at=datetime.now()))

def test_skill_observation_matched_requires_evidence():
    with pytest.raises(ValidationError, match="matched status requires resume_evidence"):
        schema.SkillObservation(skill="test", status=schema.SkillStatus.MATCHED) # type: ignore[call-arg]

def test_gap_analysis_facts_llm_true_allows_fit_score():   
    schema.GapAnalysisFacts(llm_used=True, fit_score=schema.FitScore(overall=0.5, must_have_coverage=0.5, nice_to_have_coverage=0.5, explanation="test"),resume_source="test",jd_source="jd test",analyzed_at=datetime.now(),skill_observations=[],perspective="candidate")

def test_gap_analysis_facts_llm_false_rejects_fit_score():
    with pytest.raises(ValidationError, match="fit_score should not be set if llm_used is False"):
        schema.GapAnalysisFacts(llm_used=False, fit_score=schema.FitScore(overall=0.5, must_have_coverage=0.5, nice_to_have_coverage=0.5, explanation="test"),resume_source="test",jd_source="jd test",analyzed_at=datetime.now(),skill_observations=[],perspective="candidate") # type: ignore[call-arg]    

def test_gap_analysis_facts_llm_false_rejects_learning_steps():
    with pytest.raises(ValidationError, match="learning_steps should not be set if llm_used is False"):
        schema.GapAnalysisFacts(llm_used=False, learning_steps=[schema.LearningStep(skill="Python", priority=1, why_it_matters="needed", resources=(), estimated_weeks=4)],resume_source="test",jd_source="jd test",analyzed_at=datetime.now(),skill_observations=[],perspective="candidate") # type: ignore[call-arg]

def test_gap_analysis_facts_fails_append_to_tuples():
    gaf = schema.GapAnalysisFacts(llm_used=True, fit_score=None, resume_source="test", jd_source="jd test", analyzed_at=datetime.now(), skill_observations=[], perspective="candidate")
    with pytest.raises(AttributeError):
        gaf.skill_observations.append(schema.SkillObservation(skill="test", status=schema.SkillStatus.MATCHED, resume_evidence=schema.Provenance(source="resume", locator="experience[0]", retrieved_at=datetime.now()))) # type: ignore[call-arg]
    with pytest.raises(AttributeError):
        gaf.learning_steps.append(schema.LearningStep(skill="test", priority=1, why_it_matters="needed", resources=(), estimated_weeks=4))

def test_coverage_valid_pdf():
    schema.Coverage(source_format="pdf", pages_total=3, pages_with_text=2, chars_extracted=100, known_blind_spots=['scanned_pages']) # type: ignore[call-arg]

def test_coverage_valid_txt():
    schema.Coverage(source_format="txt", pages_total=None, pages_with_text=None, chars_extracted=100, known_blind_spots=[]) #type: ignore[call-arg] 

def test_coverage_rejects_more_text_pages_than_total():
    with pytest.raises(ValidationError, match="pages_with_text cannot be greater than pages_total"):
        schema.Coverage(source_format="pdf", pages_total=3, pages_with_text=4, chars_extracted=100, known_blind_spots=['scanned_pages']) # type: ignore[call-arg] 

def test_coverage_rejects_unknown_blind_spot():
    with pytest.raises(ValidationError):
        schema.Coverage(source_format="pdf", pages_total=3, pages_with_text=2, chars_extracted=100, known_blind_spots=['images']) # type: ignore[call-arg] 

def test_coverage_requires_blind_spots():
    with pytest.raises(ValidationError):
        schema.Coverage(source_format="pdf", pages_total=3, pages_with_text=2, chars_extracted=100) # type: ignore[call-arg]


'''@pytest.mark.parametrize("model,kwargs", [
    (FitScore, {"overall": 0.5, "must_have_coverage": 0.5, "nice_to_have_coverage": 0.5, "explanation": "test"}),
    (Coverage, {"source_format": "pdf", "pages_total": 3, "pages_with_text": 2, "chars_extracted": 100, "known_blind_spots": ['scanned_pages']}),
    (SkillObservation, {"skill": "test", "status": SkillStatus.MATCHED, "resume_evidence": Provenance(source="resume", locator="experience[0]", retrieved_at=datetime.now())}),
    (LearningStep, {"skill": "test", "priority": 1, "why_it_matters": "needed", "resources": (), "estimated_weeks": 4}),
    (GapAnalysisFacts, {"llm_used": True, "fit_score": None, "resume_source": "test", "jd_source": "jd test", "analyzed_at": datetime.now(), "skill_observations": [], "perspective": "candidate"}),
])'''

