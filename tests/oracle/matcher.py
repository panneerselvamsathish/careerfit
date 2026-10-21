import re
from collections.abc import Iterator
from typing import Literal

from careerfit.analyze.ontology import SkillEntry
from careerfit.facts.schema import SkillStatus

DetectResult = Literal["found", "unclear", "absent"]

def mention_pattern(term: str) -> re.Pattern[str]:
    """A whole-word, case-insensitive match for a skill name or alias ("js" never inside "Node.js")."""
    return re.compile(rf'(?<!\w)(?<!\w\.){re.escape(term)}(?!\w)(?!\.\w)', re.IGNORECASE)


def mentions(term: str, text: str) -> bool:
    return mention_pattern(term).search(text) is not None

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
    # a pay heading on its own ("Base Pay Range") or followed by an amount ("Salary Range: $93,000 ...");
    # anything else after it ("Compensation analysis experience") keeps the line a requirement
    r"|((base |annual )?(pay|salary|compensation)( range)?|salary range)(\b.*[$€£]\s?\d.*)?",
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

_EEO_STATEMENT = re.compile(
    r"\b(equal (employment )?opportunity employer|affirmative action employer"
    r"|without regard to (race|colou?r|religion|sex|gender|age|national origin|disability|veteran))", re.I)
_CALL_TO_APPLY = re.compile(r"(?:^|[.!?]\s+)apply (today|now)\b(?!['\u2019])", re.I)
_BULLET = re.compile(r"^\s*([-\u2022*\u25aa\u25cf]|\d+[.)])\s+")


def requirement_sentences(jd_text: str) -> Iterator[tuple[int, str, list[tuple[Level, str]]]]:
    """Every sentence of the JD that can hold a requirement, as (line, sentence, its clauses with their
    levels), in document order. A sentence mixing a must and a nice marker is split into clauses."""
    current: Literal["must", "nice"] = "must"
    counting = True  # off inside a benefits / equal-opportunity / pay section
    # Updated with the product (review of #35): the employer's equal-opportunity statement and a call
    # to apply end the requirements. A copy of the rule, so the differential test checks it.
    has_heading = any(requirement_section(raw.strip()) for raw in jd_text.splitlines())
    for line_no, raw_line in enumerate(jd_text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        if stop_section(line):
            counting = False
            continue
        if not _BULLET.match(line) and (_EEO_STATEMENT.search(line) or _CALL_TO_APPLY.search(line)):
            counting = counting and not has_heading
            continue
        level_here = heading_level(line)
        if level_here is not None:
            current = level_here
            counting = True
        if not counting:
            continue
        for sentence in re.split(r"(?<=[.!?])\s+", line):
            levelled: list[tuple[Level, str]] = []
            for clause in clauses(sentence):
                level: Literal["must", "nice"]
                if has_must_marker(clause):
                    level = "must"
                elif has_nice_marker(clause):
                    level = "nice"
                else:
                    level = current
                levelled.append((level, clause))
            yield line_no, sentence, levelled


def requirement_clauses(jd_text: str) -> Iterator[tuple[Level, int, str]]:
    """Every clause of the JD that can hold a requirement, as (level, line, clause), in document order."""
    for line_no, _sentence, levelled in requirement_sentences(jd_text):
        for level, clause in levelled:
            yield level, line_no, clause


def requirement_occurrences(jd_text: str, ontology: dict[str, SkillEntry]) -> dict[str, list[Occurrence]]:
    """Every place the JD mentions each skill, as (level, line, detection result), in document order."""
    found: dict[str, list[Occurrence]] = {}
    for level, line_no, clause in requirement_clauses(jd_text):
        # Updated with the product (Copilot review on #31): a skill named only inside another
        # skill's name ("SQL Server" in "SQL Server Integration Services") asks for nothing alone.
        own = {skill for _start, _end, skill in _mention_spans(clause, ontology)[0]}
        for name, result in scan(clause, ontology).items():
            if result != "absent" and name in own:
                found.setdefault(name, []).append((level, line_no, result))
    return found


# Skills a clause joins with "or" are alternatives: any one meets the requirement ("OpenAI or
# Anthropic APIs", "Python, Java, or Go", "Python or Java or Go"). Between "or" and the next skill
# only up to two modifiers may sit ("software engineering or applied machine learning", "or the
# Anthropic API"); any other word ("Python or equivalent and Kubernetes", "... on Kubernetes")
# keeps the two separate requirements, and so does anything else between two skills.
# The comma is grouped with its own spaces, so no run of spaces can be split two ways (backtracking).
# Updated with the product (Copilot review on #31, "MySQL or another relational database"): which
# words may join alternatives is not the index's business, so the oracle follows it.
_OR_JOIN = re.compile(r"\s*(,\s*)?(and/)?or\s+((a|an|the|another|other|any|applied|modern|similar|comparable|related)\s+){0,2}",
                      re.IGNORECASE)
_COMMA_JOIN = re.compile(r"\s*,\s*")
MAX_JOIN = 60  # characters: a longer stretch between two skills is never a plain "or" or comma
# "At least two of Python, Java, or Kubernetes" needs more than one: no single skill meets it, so a
# sentence that asks for a count above one offers no either/or choice at all.
# "One of", "1 of" and "1 or more of" are met by any single skill, so only counts above one stop it.
# Up to two nouns may sit before "of", "out of", "from" or "among" ("two technologies from"), but
# never a duration: "4+ years of Python or Java" counts years, not skills.
_COUNTED = re.compile(r"\b(two|three|four|five|six|several|multiple|both|all|([2-9]|[1-9]\d+)\+?)"
                      r"(\s+or\s+more)?(\s+(?!(years?|yrs|months?|weeks?|days?)\b)[a-z-]+){0,2}"
                      r"\s+(out\s+of|of|from|among)\b", re.IGNORECASE)
Span = tuple[int, int, str]


def _mention_spans(clause: str, ontology: dict[str, SkillEntry]) -> tuple[list[Span], list[tuple[Span, int]]]:
    """Each skill mention in the clause as (start, end, skill), left to right, and the nested ones.

    Of two overlapping mentions the longer is kept; the other is nested in it, paired with the index
    of the kept mention it sits in: "SQL" inside "PL/SQL" is nested in PL/SQL's mention.
    """
    # Updated with the product (Copilot review on #31): the longer of two overlapping mentions is
    # kept even when it starts later ("Microsoft SQL Server Integration Services" is SSIS).
    spans = sorted({(m.start(), m.end(), name)
                    for name, entry in ontology.items() for term in (*entry.aliases, name)
                    for m in mention_pattern(term).finditer(clause)},
                   key=lambda span: (span[0] - span[1], span[0], span[2]))
    kept: list[Span] = []
    for span in spans:
        if not any(span[0] < k[1] and k[0] < span[1] for k in kept):
            kept.append(span)
    kept.sort()
    nested = [(span, next(i for i, k in enumerate(kept) if span[0] < k[1] and k[0] < span[1]))
              for span in sorted(set(spans) - set(kept), key=lambda span: (span[0], span[0] - span[1], span[2]))]
    return kept, nested


def _choice_of(clause: str, kept: list[Span]) -> list[int]:
    """For each kept mention, an id shared by every mention in the same either/or choice.

    A comma list ending in "or" is one choice ("A, B, or C"), and so is a chain of "or"s ("A or B or
    C"); a comma after a choice starts a new list ("A or B, C or D" is two choices). A sentence that
    asks for a count above one ("at least two of") gives every mention its own choice.
    """
    parent = list(range(len(kept)))
    if _COUNTED.search(clause):
        return parent

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]  # path halving: a long "or" chain stays near-linear
            i = parent[i]
        return i

    run = [0] if kept else []  # the comma-joined mentions ending at the current one
    after_or = False
    for i in range(1, len(kept)):
        between = clause[kept[i - 1][1]:kept[i][0]]
        if len(between) > MAX_JOIN:
            run, after_or = [i], False
        elif _OR_JOIN.fullmatch(between):
            for j in run:
                parent[root(j)] = root(i)
            run, after_or = [i], True
        elif _COMMA_JOIN.fullmatch(between):
            if after_or:
                run = [i]
            else:
                run.append(i)  # in place: copying the run at every comma would be quadratic
            after_or = False
        else:
            run, after_or = [i], False
    return [root(i) for i in range(len(kept))]


def mention_alternatives(clause: str, ontology: dict[str, SkillEntry]) -> list[tuple[str, frozenset[str]]]:
    """Every skill mention in the clause, nested ones included, with the other skills the clause
    accepts in its place: an empty set for a mention that stands alone. A nested mention shares the
    choice of the mention it sits in ("PL/SQL or Python" offers Python for the SQL in PL/SQL too)."""
    kept, nested = _mention_spans(clause, ontology)
    choice = _choice_of(clause, kept)
    members: dict[int, set[str]] = {}  # built once: looking each choice up again per mention is quadratic
    for span, group in zip(kept, choice):
        members.setdefault(group, set()).add(span[2])

    def others(i: int) -> frozenset[str]:
        return frozenset(members[choice[i]] - {kept[i][2]})

    return ([(span[2], others(i)) for i, span in enumerate(kept)]
            + [(span[2], others(i) - {span[2]}) for span, i in nested])


def alternative_groups(clause: str, ontology: dict[str, SkillEntry]) -> list[frozenset[str]]:
    """The groups of skills the clause offers as either/or choices, in order of first mention."""
    kept, _ = _mention_spans(clause, ontology)
    groups: dict[int, set[str]] = {}
    for span, choice in zip(kept, _choice_of(clause, kept)):
        groups.setdefault(choice, set()).add(span[2])
    return [frozenset(g) for g in groups.values() if len(g) > 1]


def requirement_alternatives(jd_text: str, ontology: dict[str, SkillEntry]) -> dict[str, list[frozenset[str]]]:
    """Every JD mention of each skill, in the sentences requirement_occurrences reads, with the other
    skills the JD accepts in its place. Mentions are kept apart, so "Python or Java experience and
    Python certification" still asks for Python. Choices are read across the whole sentence, so
    "Python, Java, or Kubernetes are required, but Terraform is preferred" keeps its list, though
    the sentence is split into a must clause and a nice clause for the requirement levels.

    Every mention counts, a bare ambiguous word included ("you must go onsite"): telling the verb
    from the skill is the judge's call, and it rules on one line per skill, not on each mention.
    Keeping them all can leave a false gap; dropping them could waive a real requirement."""
    found: dict[str, list[frozenset[str]]] = {}
    for line_no, sentence, _clauses in requirement_sentences(jd_text):
        detected = {name for name, result in scan(sentence, ontology).items() if result != "absent"}
        own = len(_mention_spans(sentence, ontology)[0])  # updated with the product, as above
        for name, others in mention_alternatives(sentence, ontology)[:own]:
            if name in detected:
                found.setdefault(name, []).append(others)
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

