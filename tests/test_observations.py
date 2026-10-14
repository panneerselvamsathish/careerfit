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


def test_status_uses_the_occurrence_that_decided_the_requirement():
    go = SkillEntry(aliases=("golang",), ambiguous=True)
    jd = "Golang is a plus.\nGo is required."
    result = by_skill(build_observations("Python only", TEXT_COVERAGE, jd, {"go": go}, AT))
    assert result["go"].requirement == "must"
    assert result["go"].status == SkillStatus.UNRESOLVABLE
    assert result["go"].jd_evidence.locator == "line 2"


IMPLIED = {
    "backend development": SkillEntry(aliases=("back-end",), ambiguous=False),
    "sql": SkillEntry(aliases=(), ambiguous=False),
    "pl/sql": SkillEntry(aliases=("plsql",), ambiguous=False, implies=("sql", "backend development")),
    "go": SkillEntry(aliases=("golang",), ambiguous=True, implies=("backend development",)),
}


def test_a_skill_shown_through_an_implying_skill_is_matched_and_cited():
    jd = "Requirements:\n- Back-end development experience"
    resume = "Billing platform engineer\nWrote PL/SQL packages for the finance export"
    backend = by_skill(build_observations(resume, TEXT_COVERAGE, jd, IMPLIED, AT))["backend development"]
    assert backend.status == SkillStatus.MATCHED
    evidence = backend.resume_evidence
    assert (evidence.source, evidence.via, evidence.locator, evidence.excerpt) == (
        "derived", "pl/sql", "line 2", "Wrote PL/SQL packages for the finance export")


def test_implication_needs_a_clear_mention_and_never_runs_backwards():
    jd = "Requirements:\n- Back-end development\n- PL/SQL"
    resume = "Led the go-live of the billing system\nStrong SQL"
    result = by_skill(build_observations(resume, TEXT_COVERAGE, jd, IMPLIED, AT))
    assert result["backend development"].status == SkillStatus.GAP  # "go" here is the verb: it shows nothing
    assert result["pl/sql"].status == SkillStatus.GAP  # SQL does not show PL/SQL


def test_the_implying_skill_named_most_often_is_the_one_cited():
    ontology = {**IMPLIED, "fastapi": SkillEntry(aliases=(), ambiguous=False, implies=("backend development",))}
    jd = "Requirements:\n- Back-end development"
    resume = "Python (FastAPI), PL/SQL\nWrote PL/SQL packages\nTuned PL/SQL for the finance export"
    evidence = by_skill(build_observations(resume, TEXT_COVERAGE, jd, ontology, AT))["backend development"].resume_evidence
    assert (evidence.via, evidence.locator) == ("pl/sql", "line 1")


def test_sql_named_only_inside_pl_sql_is_shown_through_it():
    jd = "Requirements:\n- SQL"
    inside = by_skill(build_observations("Wrote PL/SQL packages", TEXT_COVERAGE, jd, IMPLIED, AT))["sql"]
    assert inside.status == SkillStatus.MATCHED
    assert (inside.resume_evidence.source, inside.resume_evidence.via) == ("derived", "pl/sql")
    resume = "Wrote PL/SQL packages\nStrong SQL tuning"
    standalone = by_skill(build_observations(resume, TEXT_COVERAGE, jd, IMPLIED, AT))["sql"]
    assert (standalone.resume_evidence.source, standalone.resume_evidence.locator) == ("resume", "line 2")
