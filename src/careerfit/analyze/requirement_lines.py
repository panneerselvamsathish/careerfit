"""How much of a job description the skill list can read.

careerfit only checks the skills in its lists, so a JD built mostly from other skills gives a thin
result that looks complete. This counts the JD's requirement lines and how many of them name at
least one known skill, so the result can say "read 7 of 22 requirement lines" and warn when that
is less than half. The same function backs the dev tool `evals/ontology_coverage.py`.

What counts as a requirement line:
- Lines inside requirement sections ("Requirements", "What you'll bring"...). The preamble before
  the first such heading is skipped. A JD with no such heading at all is counted line by line.
- Counting stops at a benefits, equal-opportunity or pay heading, at "About us", and at unheaded
  equal-opportunity prose ("... without regard to race"), until the next requirements heading. In a
  JD with no requirements heading there is nothing to reopen counting, so that prose line is only
  skipped.
- Not headings: a non-bullet line ending in ":" or of fewer than 3 words. A short Title Case line
  with no sentence punctuation ("What We Value") is a heading too, unless it names a known skill.
- Not logistics: travel, work authorization and sponsorship, relocation, pay, "apply today". They
  are requirements of a kind, but never skills, so they would only shrink the share. A line that
  names a known skill always counts ("Python and AWS, up to 10% travel"; "Visa payment APIs in
  Java"): the product reads it as a requirement, so the count must too.

Pure: no network, no clock, no LLM.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass

from careerfit.analyze.matcher import eeo_prose, requirement_section, scan_present, stop_section
from careerfit.analyze.mentions import dashes_as_hyphens
from careerfit.analyze.ontology import SkillEntry, index_of

# The company blurb is never a requirement line, but the matcher keeps reading after it, because
# "About the Role" often is one.
ABOUT_COMPANY = re.compile(r"about (us|the company)", re.I)
BULLET = re.compile(r"^\s*([-•*▪●]|\d+[.)])\s+")
MIN_WORDS = 3  # a shorter line that isn't a bullet is a title or a fragment
TITLE_MAX_WORDS = 4  # "What We Value": a short Title Case line without punctuation is a heading
LOGISTICS = re.compile(
    r"\b(travel(l?ing)?|sponsor(ship)?|visas?|citizen(ship)?|authori[sz]ed to work|work authori[sz]ation"
    r"|relocat\w*|salary|pay range|apply (now|today|here))\b|\$\s?\d",
    re.I,
)


@dataclass(frozen=True)
class RequirementLines:
    read: tuple[tuple[int, str, tuple[str, ...]], ...]  # (line number, text, skills found)
    unread: tuple[tuple[int, str], ...]
    sections_found: bool  # False: no requirements heading, so every line was counted

    @property
    def total(self) -> int:
        return len(self.read) + len(self.unread)

    @property
    def share(self) -> float:
        return len(self.read) / self.total if self.total else 0.0


def _stop_heading(line: str) -> bool:
    # Normalised like the matcher's headings, so "* About Us" behind a bullet still counts.
    return (stop_section(line)
            or ABOUT_COMPANY.fullmatch(BULLET.sub("", dashes_as_hyphens(line)).strip().rstrip(":").strip()) is not None)


def _title_heading(line: str) -> bool:
    words = line.split()
    return (len(words) <= TITLE_MAX_WORDS and not re.search(r"[.,;!?]", line)
            and all(w[0].isupper() or not w[0].isalpha() for w in words))


def requirement_lines(jd_text: str, ontology: Mapping[str, SkillEntry]) -> RequirementLines:
    """The JD's requirement lines, split into those that name a known skill and those that don't."""
    index = index_of(ontology)
    lines = [(n, raw.strip()) for n, raw in enumerate(jd_text.splitlines(), start=1) if raw.strip()]
    sections_found = any(requirement_section(text) for _, text in lines)
    inside = not sections_found
    read, unread = [], []
    for number, text in lines:
        # Headings count even behind a bullet: some postings bullet them ("* You Have:", "* Our Benefits").
        if _stop_heading(text):
            inside = False
            continue
        if eeo_prose(text):
            inside = inside and not sections_found  # no heading could reopen counting
            continue
        if requirement_section(text):
            inside = True
            continue
        bullet = BULLET.match(dashes_as_hyphens(text))  # same length: bullet.end() still indexes text
        if not bullet and text.endswith(":"):
            continue  # any other heading ("About the Role:", "Cloud:") is skipped and changes nothing
        if not inside:
            continue
        line = text[bullet.end():] if bullet else text
        if not bullet and len(line.split()) < MIN_WORDS:
            continue
        found = tuple(sorted(scan_present(line, ontology, index)))
        if not found and ((not bullet and _title_heading(text)) or LOGISTICS.search(line)):
            continue  # "What We Value", "Willingness to travel 30%": no skill, and not a skill line
        if found:
            read.append((number, line, found))
        else:
            unread.append((number, line))
    return RequirementLines(read=tuple(read), unread=tuple(unread), sections_found=sections_found)
