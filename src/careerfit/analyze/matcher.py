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

NICE_TO_HAVE_MARKERS = ("nice to have", "nice-to-have", "optional", "bonus", "preferred","a plus", "preferable", "set you apart", "sets you apart")

MUST_HAVE_MARKERS = ("required", "must", "mandatory")
MUST_HAVE_HEADINGS = ("requirements", "qualifications", "minimum", "essential")
# Requirement-section headings, recognised with or without a trailing colon (job boards such as
# LinkedIn drop it). Only a line that is exactly one of these forms counts, so a short requirement
# like "Nice to have Kubernetes experience" never changes the section for the lines after it.
SECTION_HEADING = re.compile(
    r"(key |minimum |basic |required |preferred |desired |primary |secondary )?"
    r"(qualifications|requirements|responsibilities|skills|skills and experience)"
    r"|what (you will|you'll|you'd) (do|bring|need)"
    r"|what will you (do|bring|need)"
    r"|what (will make|makes) you successful"
    r"|how you('ll| will) contribute"
    r"|you will|you'll|you have|you bring|you'll bring"
    r"|what (you will |will )?set you apart|what sets you apart"
    r"|what we('re| are) looking for"
    r"|nice[- ]to[- ]haves?|bonus points",
    re.IGNORECASE,
)
NICE_SECTION = re.compile(r"preferred|desired|bonus|nice[- ]to[- ]have|sets? you apart", re.IGNORECASE)
# Headings of sections that come after the requirements and never hold any (benefits, equal
# opportunity, pay). A skill named there ("Cybersecurity Protection" as a benefit) is not a
# requirement, so counting stops until the next requirements heading. These must never swallow a
# requirement such as "- Compensation analysis experience", so:
#  - exact headings, and pay lines that carry an amount, may sit behind a bullet ("* Our Benefits");
#  - open-ended forms ("Your journey at A&M") count only as a short line that isn't a bullet.
STOP_HEADING = re.compile(
    r"(our )?benefits?(( and | ?& ?|/)perks)?|perks|what we offer( you)?"
    r"|equal (employment )?opportunity( employer)?|disclaimer|salary|compensation|pay"
    r"|((base |annual )?(pay|salary|compensation)( range)?|salary range)\b.*[$€£]\s?\d.*",
    re.IGNORECASE,
)
OPEN_STOP_HEADING = re.compile(r"(your journey|life) (at|with) .+|why (join|work (at|with)) .+", re.IGNORECASE)
OPEN_STOP_MAX_WORDS = 6
_LEADING_BULLET = re.compile(r"^\s*([-•*▪●]|\d+[.)])\s+")
Level = Literal["must", "nice"]


def _heading_form(line: str) -> str:
    """A line as a heading would read: no leading bullet ("* You Have:"), no trailing colon."""
    return " ".join(_LEADING_BULLET.sub("", line).strip().rstrip(":").split())


def requirement_section(line: str) -> Level | None:
    """The level a requirements-section heading opens, or None if the line isn't one.

    The one place a recognised heading is classified, so the matcher and the coverage tool agree.
    """
    form = _heading_form(line)
    if SECTION_HEADING.fullmatch(form) is None:
        return None
    return "nice" if NICE_SECTION.search(form) else "must"


def stop_section(line: str) -> bool:
    """True for a heading that opens a section with no requirements in it (benefits, EEO, pay)."""
    form = _heading_form(line)
    if STOP_HEADING.fullmatch(form):
        return True
    bulleted = _LEADING_BULLET.match(line) is not None
    return (not bulleted and len(form.split()) <= OPEN_STOP_MAX_WORDS
            and OPEN_STOP_HEADING.fullmatch(form) is not None)


def heading_level(line: str) -> Level | None:
    """The level a heading line switches to: a known section heading, or a colon heading that
    carries a marker ("Kubernetes is a plus:"). A colon heading without one ("Cloud:") is a
    sub-heading and returns None, keeping the current section."""
    section = requirement_section(line)
    if section is not None:
        return section
    if line.endswith(":"):
        if has_nice_marker(line):
            return "nice"
        if has_must_marker(line) or any(mentions(word, line) for word in MUST_HAVE_HEADINGS):
            return "must"
    return None


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
    counting = True  # off inside a benefits / equal-opportunity / pay section
    for line_no, raw_line in enumerate(jd_text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        if stop_section(line):
            counting = False
            continue
        level_here = heading_level(line)
        if level_here is not None:
            current = level_here
            counting = True
        if not counting:
            continue
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

