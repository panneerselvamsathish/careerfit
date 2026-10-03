import re
from typing import Literal

from careerfit.analyze.ontology import SkillEntry

def mentions(term: str, text: str) -> bool:
    return re.search(rf'(?<!\w){re.escape(term)}(?!\w)', text, re.IGNORECASE) is not None

def detect(name: str, entry: SkillEntry, text: str) -> Literal["found", "unclear", "absent"]:
    
    for alias in entry.aliases:
        if mentions(alias, text):
            return "found"
        
    if mentions(name, text):
        return "unclear" if entry.ambiguous else "found"
    return "absent"

def scan(text: str, ontology: dict[str, SkillEntry]) -> dict[str, Literal["found", "unclear", "absent"]]:

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
        level = "nice" if has_nice_marker(line) else current
        for name, result in scan(line, ontology).items():
            if result == "absent":
                continue
            if levels.get(name) == "must":
                continue
            levels[name] = level
    return levels
