from datetime import datetime
from typing import Literal

from careerfit.analyze.matcher import (decide_status, detect, first_mention_line, mention_pattern,
                                      requirement_alternatives, requirement_evidence)
from careerfit.analyze.ontology import SkillEntry
from careerfit.facts.schema import Coverage, GapAnalysisFacts, Provenance, SkillObservation, SkillStatus

# What an alternative can stand in for: a skill the resume doesn't show, or can't be read for.
REPLACEABLE = (SkillStatus.GAP, SkillStatus.NOT_ASSESSED)


def build_observations(
    resume_text: str,
    resume_coverage: Coverage,
    jd_text: str,
    ontology: dict[str, SkillEntry],
    at: datetime,
) -> tuple[SkillObservation, ...]:
    scanned = "scanned_pages" in resume_coverage.known_blind_spots
    jd_lines, resume_lines = jd_text.splitlines(), resume_text.splitlines()
    observations = []
    for name, (level, jd_line, jd_result) in requirement_evidence(jd_text, ontology).items():
        entry = ontology[name]
        # "SQL" inside "PL/SQL" is not a standalone SQL mention: the skill is shown through PL/SQL.
        own_mentions = without_implying_mentions(name, ontology, resume_text)
        resume_result = detect(name, entry, own_mentions)
        implied = implied_evidence(name, ontology, resume_text) if resume_result != "found" else None
        if implied is not None:
            resume_result = "found"  # e.g. PL/SQL on the resume shows the back-end development the JD asks for
        status = decide_status(jd_result, resume_result, scanned)

        jd_evidence = Provenance(source="jd", locator=f"line {jd_line}", excerpt=jd_lines[jd_line - 1].strip(),
                                 retrieved_at=at)

        resume_evidence = None
        if implied is not None:
            via, line_no = implied
            resume_evidence = Provenance(source="derived", locator=f"line {line_no}", via=via,
                                         excerpt=resume_lines[line_no - 1].strip(), retrieved_at=at)
        elif (resume_line := first_mention_line(name, entry, own_mentions)) is not None:
            resume_evidence = Provenance(source="resume", locator=f"line {resume_line}",
                                         excerpt=resume_lines[resume_line - 1].strip(), retrieved_at=at)

        observations.append(SkillObservation(
            skill=name,
            status=status,
            requirement=level,
            jd_evidence=jd_evidence,
            resume_evidence=resume_evidence,
        ))
    return apply_alternatives(tuple(observations), jd_text, ontology)


def apply_alternatives(
    observations: tuple[SkillObservation, ...],
    jd_text: str,
    ontology: dict[str, SkillEntry],
) -> tuple[SkillObservation, ...]:
    """A skill the resume doesn't show is no gap when the JD accepts a matched one in its place
    ("OpenAI or Anthropic APIs" with Anthropic on the resume). Every JD mention of the skill must
    offer a matched alternative: asked for on its own anywhere, it is still a requirement.

    The evidence is the alternative's own resume line, marked as such, so the claim can be checked.
    """
    matched = {o.skill: o for o in observations if o.status == SkillStatus.MATCHED}
    alternatives = requirement_alternatives(jd_text, ontology)
    result = []
    for o in observations:
        mentions = alternatives.get(o.skill, [])
        if o.status in REPLACEABLE and mentions and all(m & matched.keys() for m in mentions):
            via = min(mentions[0] & matched.keys())
            shown = matched[via].resume_evidence
            assert shown is not None  # a matched observation always cites the resume
            evidence = Provenance(source="alternative", via=via, locator=shown.locator, excerpt=shown.excerpt,
                                  retrieved_at=shown.retrieved_at)
            o = SkillObservation(skill=o.skill, status=SkillStatus.ALTERNATIVE_MET, requirement=o.requirement,
                                 jd_evidence=o.jd_evidence, resume_evidence=evidence)
        result.append(o)
    return tuple(result)


def without_implying_mentions(name: str, ontology: dict[str, SkillEntry], text: str) -> str:
    """The text with every mention of a skill that implies `name` blanked out, so a skill named only
    inside another's name ("SQL" in "PL/SQL") isn't taken as its own mention. Blanks keep each
    line's length and the line breaks, so line numbers still point at the original text."""
    for other, entry in ontology.items():
        if name in entry.implies:
            for term in (*entry.aliases, other):
                text = mention_pattern(term).sub(lambda m: " " * len(m.group()), text)
    return text


def implied_evidence(name: str, ontology: dict[str, SkillEntry], resume_text: str) -> tuple[str, int] | None:
    """The resume's strongest evidence for `name` through a skill that implies it, as (that skill,
    the first line naming it).

    Only a clear mention counts: an ambiguous one ("Go" that may be the verb) can't stand in for
    another skill. The implying skill the resume names on the most lines wins (15 years of PL/SQL
    over one FastAPI project), then the earliest line, then the name, so the result is deterministic.
    """
    lines = resume_text.splitlines()
    best: tuple[int, int, str] | None = None  # (-lines naming it, first line, skill) sorts best first
    for other, entry in ontology.items():
        if name not in entry.implies:
            continue
        found = [i for i, line in enumerate(lines, start=1) if detect(other, entry, line) == "found"]
        if found and (best is None or (-len(found), found[0], other) < best):
            best = (-len(found), found[0], other)
    return None if best is None else (best[2], best[1])


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
