from datetime import datetime

from careerfit.analyze.observations import build_observations
from careerfit.analyze.ontology import SkillEntry
from careerfit.facts.schema import Coverage, SkillStatus

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
