from careerfit.analyze.matcher import decide_status, detect, first_mention_line, requirement_levels
from careerfit.analyze.ontology import SkillEntry
from careerfit.facts.schema import Coverage, Provenance, SkillObservation
from datetime import datetime


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
        entry = ontology[name]                                          # 1
        jd_result = detect(name, entry, jd_text)                        # 2
        resume_result = detect(name, entry, resume_text)                # 2
        status = decide_status(jd_result, resume_result, scanned)       # 3

        jd_line = first_mention_line(name, entry, jd_text)              # 4
        jd_evidence = Provenance(source="jd", locator=f"line {jd_line}", retrieved_at=at)

        resume_line = first_mention_line(name, entry, resume_text)      # 5
        resume_evidence = None
        if resume_line is not None:
            resume_evidence = Provenance(source="resume", locator=f"line {resume_line}", retrieved_at=at)

        observations.append(SkillObservation(                           # 6
            skill=name,
            status=status,
            requirement=level,
            jd_evidence=jd_evidence,
            resume_evidence=resume_evidence,
        ))
    return tuple(observations)
