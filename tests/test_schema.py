import inspect
import pytest

from pydantic import BaseModel, ValidationError
from careerfit.facts import schema 
from datetime import datetime

FACTS_MODELS = [
    cls for _, cls in inspect.getmembers(schema, inspect.isclass)
    if issubclass(cls, BaseModel) and cls.__module__ == schema.__name__
]

JD_EVIDENCE = schema.Provenance(source="jd", locator="line 1", excerpt="- Python", retrieved_at=datetime(2026, 10, 10))

JUDGE = schema.JudgeRun(model="claude-opus-5-5", prompt_versions=("skill_match@1",))

TXT_COVERAGE = schema.Coverage(
    source_format="txt", pages_total=None, pages_with_text=None, chars_extracted=10, known_blind_spots=()
)

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
    with pytest.raises(ValidationError, match="jd_evidence"):
        schema.SkillObservation(skill="test", status=schema.SkillStatus.GAP, requirement="must") # type: ignore[call-arg]

def test_skill_observation_not_assessed_rejects_confidence():
    with pytest.raises(ValidationError, match="confidence should not be set for not_assessed status"):
        schema.SkillObservation(skill="test", status=schema.SkillStatus.NOT_ASSESSED,confidence=0.5, requirement="must", jd_evidence=JD_EVIDENCE)

def test_skill_observation_valid_matched():
    schema.SkillObservation(skill="test", status=schema.SkillStatus.MATCHED, resume_evidence=schema.Provenance(source="resume", locator="experience[0]", excerpt="Built APIs in Python", retrieved_at=datetime.now()), requirement="must", jd_evidence=JD_EVIDENCE)

def test_skill_observation_matched_requires_evidence():
    with pytest.raises(ValidationError, match="matched status requires resume_evidence"):
        schema.SkillObservation(skill="test", status=schema.SkillStatus.MATCHED, requirement="must", jd_evidence=JD_EVIDENCE)

def test_gap_analysis_facts_llm_true_allows_fit_score():   
    schema.GapAnalysisFacts(llm_used=True, judge=JUDGE, fit_score=schema.FitScore(overall=0.5, must_have_coverage=0.5, nice_to_have_coverage=0.5, explanation="test"),resume_source="test",jd_source="jd test",analyzed_at=datetime.now(),skill_observations=(),perspective="candidate", resume_coverage=TXT_COVERAGE, jd_coverage=TXT_COVERAGE)

def test_gap_analysis_facts_llm_false_rejects_fit_score():
    with pytest.raises(ValidationError, match="fit_score should not be set if llm_used is False"):
        schema.GapAnalysisFacts(llm_used=False, fit_score=schema.FitScore(overall=0.5, must_have_coverage=0.5, nice_to_have_coverage=0.5, explanation="test"),resume_source="test",jd_source="jd test",analyzed_at=datetime.now(),skill_observations=(),perspective="candidate", resume_coverage=TXT_COVERAGE, jd_coverage=TXT_COVERAGE) # type: ignore[call-arg]    

def test_gap_analysis_facts_llm_false_rejects_learning_steps():
    with pytest.raises(ValidationError, match="learning_steps should not be set if llm_used is False"):
        schema.GapAnalysisFacts(llm_used=False, learning_steps=[schema.LearningStep(skill="Python", priority=1, why_it_matters="needed", resources=(), estimated_weeks=4)],resume_source="test",jd_source="jd test",analyzed_at=datetime.now(),skill_observations=(),perspective="candidate", resume_coverage=TXT_COVERAGE, jd_coverage=TXT_COVERAGE) # type: ignore[call-arg]

def test_gap_analysis_facts_fails_append_to_tuples():
    gaf = schema.GapAnalysisFacts(llm_used=True, judge=JUDGE, fit_score=None, resume_source="test", jd_source="jd test", analyzed_at=datetime.now(), skill_observations=(), perspective="candidate", resume_coverage=TXT_COVERAGE, jd_coverage=TXT_COVERAGE)
    with pytest.raises(AttributeError):
        gaf.skill_observations.append(schema.SkillObservation(skill="test", status=schema.SkillStatus.MATCHED, requirement="must", jd_evidence=JD_EVIDENCE, resume_evidence=schema.Provenance(source="resume", locator="experience[0]", excerpt="Built APIs in Python", retrieved_at=datetime.now())))  # type: ignore[attr-defined]
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


def _facts(**overrides):
    base = dict(resume_source="r", jd_source="j", analyzed_at=datetime(2026, 1, 1), skill_observations=(),
                perspective="candidate", resume_coverage=TXT_COVERAGE, jd_coverage=TXT_COVERAGE)
    return schema.GapAnalysisFacts(**{**base, **overrides})


def test_gap_analysis_facts_llm_true_requires_judge_record():
    with pytest.raises(ValidationError, match="judge is required when llm_used is True"):
        _facts(llm_used=True)


def test_gap_analysis_facts_llm_false_rejects_judge_record():
    with pytest.raises(ValidationError, match="judge should not be set if llm_used is False"):
        _facts(llm_used=False, judge=JUDGE)


def test_dismissed_skill_cannot_also_be_observed():
    obs = schema.SkillObservation(skill="go", status=schema.SkillStatus.UNRESOLVABLE, requirement="nice", jd_evidence=JD_EVIDENCE)
    judge = schema.JudgeRun(model="m", prompt_versions=("skill_match@1",), dismissed_skills=("go",))
    with pytest.raises(ValidationError, match="a dismissed skill cannot also be observed"):
        _facts(llm_used=True, judge=judge, skill_observations=(obs,))


def test_derived_provenance_must_name_its_via_skill():
    with pytest.raises(ValidationError, match="derived evidence must name the skill"):
        schema.Provenance(source="derived", locator="line 1", excerpt="x", retrieved_at=datetime(2026, 10, 14))
    with pytest.raises(ValidationError, match="only derived or alternative evidence has a via skill"):
        schema.Provenance(source="resume", locator="line 1", excerpt="x", retrieved_at=datetime(2026, 10, 14),
                          via="pl/sql")


ALTERNATIVE = schema.Provenance(source="alternative", via="anthropic api", locator="line 3", excerpt="Anthropic SDK",
                                retrieved_at=datetime(2026, 10, 17))


def test_alternative_evidence_must_name_the_skill_it_stands_on():
    with pytest.raises(ValidationError, match="alternative evidence must name the skill"):
        schema.Provenance(source="alternative", locator="line 1", excerpt="x", retrieved_at=datetime(2026, 10, 17))


def test_alternative_met_and_alternative_evidence_go_together():
    met = schema.SkillObservation(skill="openai", status=schema.SkillStatus.ALTERNATIVE_MET, requirement="must",
                                  jd_evidence=JD_EVIDENCE, resume_evidence=ALTERNATIVE)
    assert met.resume_evidence.via == "anthropic api"
    with pytest.raises(ValidationError, match="go together"):  # the status without the evidence
        schema.SkillObservation(skill="openai", status=schema.SkillStatus.ALTERNATIVE_MET, requirement="must",
                                jd_evidence=JD_EVIDENCE)
    with pytest.raises(ValidationError, match="go together"):  # the evidence under another status
        schema.SkillObservation(skill="openai", status=schema.SkillStatus.MATCHED, requirement="must",
                                jd_evidence=JD_EVIDENCE, resume_evidence=ALTERNATIVE)
    with pytest.raises(ValidationError, match="confidence should not be set"):
        schema.SkillObservation(skill="openai", status=schema.SkillStatus.ALTERNATIVE_MET, requirement="must",
                                jd_evidence=JD_EVIDENCE, resume_evidence=ALTERNATIVE, confidence=0.9)
