from datetime import datetime

from careerfit.analyze.observations import build_facts, build_observations
from careerfit.analyze.ontology import SkillEntry
from careerfit.facts.schema import Coverage, GapAnalysisFacts, SkillStatus

ONTOLOGY = {
    "python": SkillEntry(aliases=(), ambiguous=False),
    "sql": SkillEntry(aliases=(), ambiguous=False),
    "java": SkillEntry(aliases=(), ambiguous=False),
}
AT = datetime(2026, 10, 4)
RESUME = "Python, SQL"
JD = "Python, SQL, Java"
TEXT_COVERAGE = Coverage(
    source_format="txt", pages_total=None, pages_with_text=None, chars_extracted=11, known_blind_spots=()
)


def by_skill(observations):
    return {o.skill: o for o in observations}


def test_build_observations_statuses_and_evidence():
    result = by_skill(build_observations(RESUME, TEXT_COVERAGE, JD, ONTOLOGY, AT))

    assert set(result) == {"python", "sql", "java"}
    assert result["python"].status == SkillStatus.MATCHED
    assert result["sql"].status == SkillStatus.MATCHED
    assert result["java"].status == SkillStatus.GAP

    assert result["python"].requirement == "must"
    assert result["java"].resume_evidence is None

    java_jd = result["java"].jd_evidence
    assert java_jd is not None
    assert java_jd.locator == "line 1"

    python_resume = result["python"].resume_evidence
    assert python_resume is not None
    assert python_resume.locator == "line 1"
    assert python_resume.retrieved_at == AT


def test_scanned_resume_turns_gaps_into_not_assessed():
    scanned = Coverage(
        source_format="pdf", pages_total=3, pages_with_text=1, chars_extracted=11, known_blind_spots=("scanned_pages",)
    )
    result = by_skill(build_observations(RESUME, scanned, JD, ONTOLOGY, AT))

    assert result["python"].status == SkillStatus.MATCHED
    assert result["java"].status == SkillStatus.NOT_ASSESSED


def test_build_observations_is_deterministic():
    first = build_observations(RESUME, TEXT_COVERAGE, JD, ONTOLOGY, AT)
    second = build_observations(RESUME, TEXT_COVERAGE, JD, ONTOLOGY, AT)
    assert first == second


def make_facts(resume_coverage=TEXT_COVERAGE, jd_coverage=TEXT_COVERAGE):
    return build_facts(
        resume_text=RESUME,
        resume_coverage=resume_coverage,
        resume_source="resume.txt",
        jd_text=JD,
        jd_coverage=jd_coverage,
        jd_source="jd.txt",
        ontology=ONTOLOGY,
        at=AT,
        perspective="candidate",
    )


def test_build_facts_is_keyword_only_free_tier():
    facts = make_facts()
    assert facts.llm_used is False
    assert facts.fit_score is None
    assert facts.learning_steps == ()
    assert facts.analyzed_at == AT
    assert facts.skill_observations == build_observations(RESUME, TEXT_COVERAGE, JD, ONTOLOGY, AT)


def test_build_facts_keeps_both_coverages():
    jd_scanned = Coverage(
        source_format="pdf", pages_total=2, pages_with_text=1, chars_extracted=17, known_blind_spots=("scanned_pages",)
    )
    facts = make_facts(jd_coverage=jd_scanned)
    assert facts.resume_coverage == TEXT_COVERAGE
    assert facts.jd_coverage == jd_scanned


def test_build_facts_survives_json_round_trip():
    facts = make_facts()
    assert GapAnalysisFacts.model_validate_json(facts.model_dump_json()) == facts


def test_jd_evidence_points_at_the_line_that_made_it_must():
    jd = "Python is a plus.\nJava required.\nPython is required."
    result = by_skill(build_observations(RESUME, TEXT_COVERAGE, jd, ONTOLOGY, AT))
    python_jd = result["python"].jd_evidence
    assert result["python"].requirement == "must"
    assert python_jd is not None
    assert python_jd.locator == "line 3"
