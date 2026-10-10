from datetime import datetime, timezone

import yaml

from careerfit.analyze.ontology import SkillEntry
from careerfit.facts.schema import Coverage, GapAnalysisFacts, Provenance, SkillObservation, SkillStatus
from evals import harness, invariants

AT = datetime(2026, 1, 1, tzinfo=timezone.utc)
TXT = Coverage(source_format="txt", pages_total=None, pages_with_text=None, chars_extracted=10, known_blind_spots=())
SCANNED = Coverage(
    source_format="pdf", pages_total=2, pages_with_text=1, chars_extracted=10,
    known_blind_spots=("layout_order", "graphics", "tables", "scanned_pages"),
)
ONTOLOGY = {"python": SkillEntry(aliases=(), ambiguous=False), "aws": SkillEntry(aliases=(), ambiguous=False)}


def jd_line(n: int) -> Provenance:
    return Provenance(source="jd", locator=f"line {n}", retrieved_at=AT)


def obs(skill: str, status: SkillStatus, **extra) -> SkillObservation:
    return SkillObservation(skill=skill, status=status, requirement="must", jd_evidence=jd_line(1), **extra)


def facts_with(*observations: SkillObservation, resume_coverage: Coverage = TXT) -> GapAnalysisFacts:
    return GapAnalysisFacts(
        resume_source="r", jd_source="j", resume_coverage=resume_coverage, jd_coverage=TXT,
        analyzed_at=AT, llm_used=False, skill_observations=observations, perspective="candidate",
    )


def test_every_golden_case_passes_and_is_honest():
    ontology = harness.load_ontology(harness.ONTOLOGY_PATH)
    results = [harness.run_case(case, ontology) for case in harness.load_cases()]
    assert len(results) >= 2
    for r in results:
        assert r.failed == [], r.name
        assert r.violations == [], r.name


def test_harness_exits_nonzero_when_a_golden_expectation_is_wrong(tmp_path, capsys):
    case = yaml.safe_load((harness.GOLDEN_DIR / "backend_engineer.yaml").read_text(encoding="utf-8"))
    case["expected"]["kubernetes"]["status"] = "matched"
    (tmp_path / "wrong.yaml").write_text(yaml.safe_dump(case), encoding="utf-8")
    assert harness.main(["--golden-dir", str(tmp_path)]) == 1
    assert "kubernetes: expected matched/must, got gap/must" in capsys.readouterr().out


def test_honest_facts_have_no_violations():
    assert invariants.check(facts_with(obs("python", SkillStatus.GAP))) == []


def test_not_assessed_without_unreadable_pages_is_a_violation():
    violations = invariants.check(facts_with(obs("python", SkillStatus.NOT_ASSESSED)))
    assert violations == ["python: not_assessed, but no part of the resume was unreadable"]


def test_gap_on_a_partly_unreadable_resume_is_a_violation():
    violations = invariants.check(facts_with(obs("python", SkillStatus.GAP), resume_coverage=SCANNED))
    assert violations == ["python: gap claimed although part of the resume could not be read"]


def test_partial_or_confidence_in_a_keyword_run_is_a_violation():
    violations = invariants.check(facts_with(obs("python", SkillStatus.PARTIAL), obs("aws", SkillStatus.GAP, confidence=0.4)))
    assert len(violations) == 2


def test_duplicate_skill_is_a_violation():
    violations = invariants.check(facts_with(obs("python", SkillStatus.GAP), obs("python", SkillStatus.GAP)))
    assert violations == ["python: reported more than once"]


def test_evidence_must_point_at_a_line_that_mentions_the_skill():
    jd = "Requirements:\n- Python"
    good = facts_with(SkillObservation(skill="python", status=SkillStatus.GAP, requirement="must", jd_evidence=jd_line(2)))
    wrong_line = facts_with(SkillObservation(skill="python", status=SkillStatus.GAP, requirement="must", jd_evidence=jd_line(1)))
    past_end = facts_with(SkillObservation(skill="python", status=SkillStatus.GAP, requirement="must", jd_evidence=jd_line(9)))

    assert invariants.check_evidence(good, "", jd, ONTOLOGY) == []
    assert invariants.check_evidence(wrong_line, "", jd, ONTOLOGY) == [
        "python: jd evidence 'line 1' points at a line that does not mention the skill"
    ]
    assert "points past the end" in invariants.check_evidence(past_end, "", jd, ONTOLOGY)[0]


def test_skill_outside_the_ontology_is_a_violation():
    facts = facts_with(obs("cobol", SkillStatus.GAP))
    assert invariants.check_evidence(facts, "", "COBOL", ONTOLOGY) == ["cobol: reported but not in the skill list"]
