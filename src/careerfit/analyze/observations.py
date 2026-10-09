from datetime import datetime
from typing import Literal

from careerfit.analyze.matcher import decide_status, detect, first_mention_line, requirement_levels
from careerfit.analyze.ontology import SkillEntry
from careerfit.facts.schema import Coverage, GapAnalysisFacts, Provenance, SkillObservation


def build_observations(
    resume_text: str,
    resume_coverage: Coverage,
    jd_text: str,
    ontology: dict[str, SkillEntry],
    at: datetime,
) -> tuple[SkillObservation, ...]:
    scanned = "scanned_pages" in resume_coverage.known_blind_spots
    observations = []
    for name, level in requirement_levels(jd_text, ontology).items():
        entry = ontology[name]
        jd_result = detect(name, entry, jd_text)
        resume_result = detect(name, entry, resume_text)
        status = decide_status(jd_result, resume_result, scanned)

        jd_line = first_mention_line(name, entry, jd_text)
        jd_evidence = Provenance(source="jd", locator=f"line {jd_line}", retrieved_at=at)

        resume_line = first_mention_line(name, entry, resume_text)
        resume_evidence = None
        if resume_line is not None:
            resume_evidence = Provenance(source="resume", locator=f"line {resume_line}", retrieved_at=at)

        observations.append(SkillObservation(
            skill=name,
            status=status,
            requirement=level,
            jd_evidence=jd_evidence,
            resume_evidence=resume_evidence,
        ))
    return tuple(observations)


def build_facts(
    *,
    resume_text: str,
    resume_coverage: Coverage,
    resume_source: str,
    jd_text: str,
    jd_coverage: Coverage,
    jd_source: str,
    ontology: dict[str, SkillEntry],
    at: datetime,
    perspective: Literal["candidate", "hiring_manager"],
) -> GapAnalysisFacts:
    return GapAnalysisFacts(
        resume_source=resume_source,
        jd_source=jd_source,
        resume_coverage=resume_coverage,
        jd_coverage=jd_coverage,
        analyzed_at=at,
        llm_used=False,
        skill_observations=build_observations(resume_text, resume_coverage, jd_text, ontology, at),
        perspective=perspective,
    )
