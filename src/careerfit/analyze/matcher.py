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

def has_nice_marker(text: str) -> bool:
    return any(mentions(marker, text) for marker in NICE_TO_HAVE_MARKERS)

def requirement_levels(jd_text: str, ontology: dict[str, SkillEntry]) -> dict[str, Literal["must", "nice"]]:
    levels = {}
    current = "must"
    for line in jd_text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.endswith(":"):
            current = "nice" if has_nice_marker(line) else "must"
            continue
        for sentence in re.split(r"(?<=[.!?])\s+", line):
            level = "nice" if has_nice_marker(sentence) else current
            for name, result in scan(sentence, ontology).items():
                if result == "absent":
                    continue
                if levels.get(name) == "must":
                    continue
                levels[name] = level
    return levels

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
        for i, line in enumerate(text.splitlines(), start=1):
            if detect(name, entry, line) != "absent":
                return i
        return None

