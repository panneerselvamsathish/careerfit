"""Honesty checks that must hold for every careerfit result, with no ground truth needed.

They don't ask whether a verdict is right; the golden cases do that. They ask whether the
result claims more than the run could actually see.
"""

from careerfit.analyze.matcher import detect
from careerfit.analyze.ontology import SkillEntry
from careerfit.facts.schema import GapAnalysisFacts, Provenance, SkillStatus


def check(facts: GapAnalysisFacts) -> list[str]:
    """Violations visible from the facts alone. An empty list means the result is honest."""
    bad: list[str] = []
    # Cross-check against coverage, not against the observation itself: a buggy analyzer can
    # label a skill GAP or NOT_ASSESSED whatever the coverage says.
    scanned = "scanned_pages" in facts.resume_coverage.known_blind_spots
    seen: set[str] = set()

    for o in facts.skill_observations:
        if o.skill in seen:
            bad.append(f"{o.skill}: reported more than once")
        seen.add(o.skill)

        if o.status == SkillStatus.NOT_ASSESSED and not scanned:
            bad.append(f"{o.skill}: not_assessed, but no part of the resume was unreadable")
        if o.status == SkillStatus.GAP and scanned:
            bad.append(f"{o.skill}: gap claimed although part of the resume could not be read")

        if not facts.llm_used:
            if o.status == SkillStatus.PARTIAL:
                bad.append(f"{o.skill}: partial in a keyword-only run; only the judge can grade partial matches")
            if o.confidence is not None:
                bad.append(f"{o.skill}: confidence {o.confidence} in a keyword-only run")

    return bad


def check_evidence(
    facts: GapAnalysisFacts,
    resume_text: str,
    jd_text: str,
    ontology: dict[str, SkillEntry],
) -> list[str]:
    """Violations that need the source texts: every cited line must really mention the skill."""
    bad: list[str] = []
    for o in facts.skill_observations:
        entry = ontology.get(o.skill)
        if entry is None:
            bad.append(f"{o.skill}: reported but not in the skill list")
            continue
        sources: list[tuple[str, Provenance | None, str]] = [
            ("jd", o.jd_evidence, jd_text),
            ("resume", o.resume_evidence, resume_text),
        ]
        for label, evidence, text in sources:
            if evidence is None:
                continue
            problem = _evidence_problem(o.skill, entry, evidence, text)
            if problem:
                bad.append(f"{o.skill}: {label} evidence {evidence.locator!r} {problem}")
    return bad


def _evidence_problem(skill: str, entry: SkillEntry, evidence: Provenance, text: str) -> str | None:
    prefix, _, number = evidence.locator.partition(" ")
    if prefix != "line" or not number.isdigit():
        return "is not in the 'line N' format"
    lines = text.splitlines()
    line_no = int(number)
    if not 1 <= line_no <= len(lines):
        return f"points past the end of the document ({len(lines)} lines)"
    if detect(skill, entry, lines[line_no - 1]) == "absent":
        return "points at a line that does not mention the skill"
    return None
