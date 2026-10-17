"""Honesty checks that must hold for every careerfit result, with no ground truth needed.

They don't ask whether a verdict is right; the golden cases do that. They ask whether the
result claims more than the run could actually see.
"""

from careerfit.analyze.matcher import detect, requirement_alternatives
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

        if o.status == SkillStatus.ALTERNATIVE_MET:
            # An alternative only counts if the facts themselves show it matched.
            via = o.resume_evidence.via if o.resume_evidence else None
            if not any(m.skill == via and m.status == SkillStatus.MATCHED for m in facts.skill_observations):
                bad.append(f"{o.skill}: alternative_met through {via!r}, which is not matched")

        judged = o.resume_evidence is not None and o.resume_evidence.source == "llm_judge"
        if judged and not facts.llm_used:
            bad.append(f"{o.skill}: judge evidence in a keyword-only run")
        if judged and o.confidence is None:
            bad.append(f"{o.skill}: judge verdict without a confidence")

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
            if evidence.source == "derived":
                # Shown through another skill: the cited line must name that skill, and the skill
                # list must really say it implies this one.
                via = ontology.get(evidence.via or "")
                if via is None or o.skill not in via.implies:
                    bad.append(f"{o.skill}: {label} evidence via {evidence.via!r}, which does not imply it")
                    continue
                problem = _evidence_problem(evidence.via or "", via, evidence, text)
                if problem is None and detect(evidence.via or "", via, evidence.excerpt) != "found":
                    # The matcher only lets a clear mention stand in for another skill ("go-live"
                    # never shows back-end development), so the invariant demands the same.
                    problem = f"names {evidence.via!r} only ambiguously, so it can't show this skill"
            elif evidence.source == "alternative":
                # The JD must really offer the choice, and the cited line must be exactly the evidence
                # the alternative is matched on, which its own row has checked against the resume.
                if not any(evidence.via in m for m in requirement_alternatives(jd_text, ontology).get(o.skill, [])):
                    bad.append(f"{o.skill}: the job description never offers {evidence.via!r} in its place")
                    continue
                met = next((m.resume_evidence for m in facts.skill_observations if m.skill == evidence.via), None)
                same = met is not None and (met.locator, met.excerpt) == (evidence.locator, evidence.excerpt)
                problem = None if same else f"is not the evidence {evidence.via!r} is matched on"
            else:
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
    if evidence.excerpt != lines[line_no - 1].strip():
        return f"quotes {evidence.excerpt!r}, but that line reads {lines[line_no - 1].strip()!r}"
    # The judge may match a paraphrase, so its lines needn't contain the keyword; it must still
    # cite real text. Keyword evidence must mention the skill on the cited line.
    if evidence.source == "llm_judge":
        return "points at a blank line" if not lines[line_no - 1].strip() else None
    if detect(skill, entry, lines[line_no - 1]) == "absent":
        return "points at a line that does not mention the skill"
    return None
