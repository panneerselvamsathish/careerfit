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

NICE_TO_HAVE_MARKERS = ("nice to have", "nice-to-have", "optional", "bonus", "preferred","a plus", "preferable", "set you apart")

MUST_HAVE_MARKERS = ("required", "must", "mandatory")
MUST_HAVE_HEADINGS = ("requirements", "qualifications", "minimum", "essential", "responsibilities", "what you will do",
                      "what you'll do", "what you will bring", "what you'll bring", "looking for")
# Section headings that job boards (LinkedIn among them) show without a trailing colon. Only a line
# that is exactly one of these forms starts a section, so a short requirement such as "Nice to have
# Kubernetes experience" never changes the section for the lines after it.
SECTION_HEADING = re.compile(
    r"(key |minimum |basic |required |preferred |desired |additional )?"
    r"(qualifications|requirements|responsibilities|skills|skills and experience)"
    r"|what (you will|you'll|you'd) (do|bring|need)"
    r"|what (you will |will )?set you apart"
    r"|what we('re| are) looking for"
    r"|nice[- ]to[- ]haves?|bonus points",
    re.IGNORECASE,
)


def is_heading(line: str) -> bool:
    """A line that starts a section: ends with ':', or is exactly a known section heading."""
    return line.endswith(":") or SECTION_HEADING.fullmatch(" ".join(line.split())) is not None


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

Occurrence = tuple[Literal["must", "nice"], int, Literal["found", "unclear"]]


def requirement_occurrences(jd_text: str, ontology: dict[str, SkillEntry]) -> dict[str, list[Occurrence]]:
    """Every place the JD mentions each skill, as (level, line, detection result), in document order."""
    found: dict[str, list[Occurrence]] = {}
    current: Literal["must", "nice"] = "must"
    for line_no, raw_line in enumerate(jd_text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        if is_heading(line):
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
                    if result != "absent":
                        found.setdefault(name, []).append((level, line_no, result))
    return found


def requirement_evidence(jd_text: str, ontology: dict[str, SkillEntry]) -> dict[str, Occurrence]:
    """Each JD skill's deciding occurrence: must beats nice, then a clear mention beats an unclear one."""
    best: dict[str, Occurrence] = {}
    for name, occurrences in requirement_occurrences(jd_text, ontology).items():
        for level, line_no, result in occurrences:
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

