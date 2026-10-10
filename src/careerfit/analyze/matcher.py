import re
from typing import Literal

from careerfit.analyze.ontology import SkillEntry
from careerfit.facts.schema import SkillStatus

DetectResult = Literal["found", "unclear", "absent"]

def mentions(term: str, text: str) -> bool:
    return re.search(rf'(?<!\w)(?<!\w\.){re.escape(term)}(?!\w)(?!\.\w)', text, re.IGNORECASE) is not None

def detect(name: str, entry: SkillEntry, text: str) -> DetectResult:
    
    for alias in entry.aliases:
        if mentions(alias, text):
            return "found"
        
    if mentions(name, text):
        return "unclear" if entry.ambiguous else "found"
    return "absent"

def scan(text: str, ontology: dict[str, SkillEntry]) -> dict[str, DetectResult]:

    results = {}
    
    for name, entry in ontology.items():
        results[name] = detect(name, entry, text)
    return results

NICE_TO_HAVE_MARKERS = ("nice to have", "optional", "bonus", "preferred","a plus", "preferable")

MUST_HAVE_MARKERS = ("required", "must", "mandatory")
MUST_HAVE_HEADINGS = ("requirements", "qualifications", "minimum", "essential")

def has_nice_marker(text: str) -> bool:
    return any(mentions(marker, text) for marker in NICE_TO_HAVE_MARKERS)

def has_must_marker(text: str) -> bool:
    return any(mentions(marker, text) for marker in MUST_HAVE_MARKERS)

def clauses(sentence: str) -> list[str]:
    # Only split a sentence that mixes both kinds of marker; splitting every comma
    # would cut "Experience with Python, AWS and Docker is a plus" away from its marker.
    if has_nice_marker(sentence) and has_must_marker(sentence):
        return [c for c in re.split(r",|;|\bbut\b", sentence, flags=re.IGNORECASE) if c.strip()]
    return [sentence]

def requirement_evidence(
    jd_text: str, ontology: dict[str, SkillEntry]
) -> dict[str, tuple[Literal["must", "nice"], int, Literal["found", "unclear"]]]:
    """Each JD skill's level, with the line and detection result of the occurrence that decided it."""
    best: dict[str, tuple[Literal["must", "nice"], int, Literal["found", "unclear"]]] = {}
    current: Literal["must", "nice"] = "must"
    for line_no, raw_line in enumerate(jd_text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        if line.endswith(":"):
            # A heading with neither kind of marker ("Cloud:") is a sub-heading and keeps the current section.
            if has_nice_marker(line):
                current = "nice"
            elif has_must_marker(line) or any(mentions(word, line) for word in MUST_HAVE_HEADINGS):
                current = "must"
        for sentence in re.split(r"(?<=[.!?])\s+", line):
            for clause in clauses(sentence):
                level: Literal["must", "nice"]
                if has_must_marker(clause):
                    level = "must"
                elif has_nice_marker(clause):
                    level = "nice"
                else:
                    level = current
                for name, result in scan(clause, ontology).items():
                    if result == "absent":
                        continue
                    previous = best.get(name)
                    upgrades = previous is not None and previous[0] == "nice" and level == "must"
                    clearer = previous is not None and previous[0] == level and previous[2] == "unclear" and result == "found"
                    if previous is None or upgrades or clearer:
                        best[name] = (level, line_no, result)
    return best

def requirement_levels(jd_text: str, ontology: dict[str, SkillEntry]) -> dict[str, Literal["must", "nice"]]:
    return {name: level for name, (level, _, _) in requirement_evidence(jd_text, ontology).items()}

def decide_status(
    jd_result: Literal["found", "unclear"],
    resume_result: DetectResult,
    scanned: bool,
) -> SkillStatus:
    """JD ambiguity is checked first: a skill the JD may not require can't be matched or missed."""
    if jd_result == "unclear":
        return SkillStatus.UNRESOLVABLE
    if resume_result == "unclear":
        return SkillStatus.UNRESOLVABLE
    if resume_result == "found":
        return SkillStatus.MATCHED
    return SkillStatus.NOT_ASSESSED if scanned else SkillStatus.GAP

def first_mention_line(name: str, entry: SkillEntry, text: str) -> int | None:
    # A "found" line is preferred so evidence supports the status; "unclear" is only a fallback.
    unclear_line = None
    for i, line in enumerate(text.splitlines(), start=1):
        result = detect(name, entry, line)
        if result == "found":
            return i
        if result == "unclear" and unclear_line is None:
            unclear_line = i
    return unclear_line

