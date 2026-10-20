"""Formatting shared by both perspectives. Presentation only: no verdict is decided here."""

import re
from collections.abc import Callable, Iterable

from careerfit.facts.schema import Coverage, GapAnalysisFacts, Provenance, SkillObservation, SkillStatus

STATUS_LABEL = {
    SkillStatus.MATCHED: "Matched",
    SkillStatus.PARTIAL: "Partly shown",
    SkillStatus.ALTERNATIVE_MET: "Alternative met",  # the JD accepts another skill, and the resume shows it
    SkillStatus.GAP: "Gap",
    SkillStatus.UNRESOLVABLE: "Ambiguous",  # never a conclusion: see "GAP ≠ UNRESOLVABLE" in CLAUDE.md
    SkillStatus.NOT_ASSESSED: "Not assessed",
}
STATUS_ORDER = [SkillStatus.MATCHED, SkillStatus.PARTIAL, SkillStatus.ALTERNATIVE_MET, SkillStatus.GAP,
                SkillStatus.UNRESOLVABLE, SkillStatus.NOT_ASSESSED]
DECIDED = (SkillStatus.MATCHED, SkillStatus.PARTIAL, SkillStatus.GAP)
LAYOUT_BLIND_SPOTS = ("layout_order", "graphics", "tables")
LOW_COVERAGE = 0.5  # below this share of requirement lines read, the result gets a plain warning
# What can start HTML or inline Markdown: tags and autolinks (< >), links and images ([ ]),
# emphasis, strikethrough and code (* _ ~ `), the table delimiter (|), and the backslash itself.
_MARKDOWN_ACTIVE = re.compile(r"([\\`*_~\[\]<>|])")


def cell(text: str) -> str:
    """Show untrusted text literally in Markdown, in a table cell or a list item.

    Every value taken from the facts goes through here; only report/'s own wording and numbers don't.

    Excerpts come straight from the resume and JD, so an <img> tag or ![](...) in them must be
    displayed, not rendered: rendered, it could inject markup or fetch a remote image.
    """
    # Every line boundary is flattened, not just \n: Markdown also ends a line at a bare \r.
    # Backslashes are escaped in the same pass, so a backslash in the source cannot cancel a pipe's escape.
    return _MARKDOWN_ACTIVE.sub(r"\\\1", " ".join(text.splitlines()))


def names(items: Iterable[str]) -> str:
    return ", ".join(cell(i) for i in items)


def cite(evidence: Provenance | None) -> str:
    if evidence is None:
        return "—"
    if evidence.source == "llm_judge":
        source = " (Claude)"
    elif evidence.source == "derived":
        source = f" (shown through {evidence.via})"
    elif evidence.source == "alternative":
        source = f" (the job description accepts {evidence.via} instead)"
    else:
        source = ""
    return cell(f'{evidence.locator}{source}: "{evidence.excerpt}"')


def by_requirement(facts: GapAnalysisFacts, requirement: str) -> list[SkillObservation]:
    rows = [o for o in facts.skill_observations if o.requirement == requirement]
    return sorted(rows, key=lambda o: (STATUS_ORDER.index(o.status), o.skill))


def status_counts(observations: list[SkillObservation]) -> str:
    def label(status: SkillStatus, n: int) -> str:
        text = STATUS_LABEL[status].lower()
        return f"{n} {text}s" if status == SkillStatus.GAP and n != 1 else f"{n} {text}"

    parts = [label(s, sum(o.status == s for o in observations))
             for s in STATUS_ORDER if any(o.status == s for o in observations)]
    return ", ".join(parts) + f" (of {len(observations)})" if observations else "none listed"


def mode_line(facts: GapAnalysisFacts) -> str:
    if facts.judge is None:
        return "Keyword pass only (no LLM)"
    return f"Deep analysis with Claude ({cell(facts.judge.model)})"


def header(facts: GapAnalysisFacts, title: str) -> list[str]:
    return [f"# {title}", "",
            f"{mode_line(facts)} · analysed {facts.analyzed_at:%Y-%m-%d} · schema {cell(facts.schema_version)}", ""]


def blind_spots(facts: GapAnalysisFacts) -> list[str]:
    """What the run could not see. Shown in every report, because a gap list without it overclaims."""
    return ["## What this analysis could not see", "", *(f"- {n}" for n in blind_spot_notes(facts, cell)), ""]


def requirement_lines_read(facts: GapAnalysisFacts) -> str | None:
    """"8 of 23 requirement lines (35%)", or None when there is no count."""
    count = facts.jd_requirement_lines
    if count is None or count.total == 0:
        return None
    percent = (200 * count.read + count.total) // (2 * count.total)  # half up, as the web page rounds it
    return f"{count.read} of {count.total} requirement lines ({percent}%)"


def coverage_summary(facts: GapAnalysisFacts) -> str | None:
    """The summary line, with a plain warning when the skill list read less than half of the JD."""
    read = requirement_lines_read(facts)
    if read is None:
        return None
    count = facts.jd_requirement_lines
    low = count.read / count.total < LOW_COVERAGE
    return (f"The skill list could read {read}."
            + (" Less than half, so this result shows only part of what the job asks for." if low else ""))


def blind_spot_notes(facts: GapAnalysisFacts, quote: Callable[[str], str] = str) -> list[str]:
    """The notes themselves. Every value taken from the facts goes through quote: cell() for Markdown,
    plain str for a caller that displays text literally (the web page sets textContent)."""
    def names(items: Iterable[str]) -> str:
        return ", ".join(quote(i) for i in items)

    read = requirement_lines_read(facts)
    notes = [f"careerfit's skill list could read {read} in the job description. Only skills in its list were "
             "checked; anything else the job asks for is not shown here." if read else
             "Only skills in careerfit's skill list were checked. Anything else the job asks for is not shown here."]
    resume, jd = facts.resume_coverage, facts.jd_coverage
    if "scanned_pages" in resume.known_blind_spots:
        unread = (resume.pages_total or 0) - (resume.pages_with_text or 0)
        notes.append(f"{unread} of {resume.pages_total} resume pages had no readable text, so skills that may be on "
                     "them are marked Not assessed rather than Gap.")
    if _layout_limited(resume):
        notes.append(f"The resume is a {resume.source_format.upper()}: skills shown only in tables, graphics or "
                     "unusual layouts can be missed.")
    if _layout_limited(jd):
        notes.append(f"The job description is a {jd.source_format.upper()}: requirements shown only in tables or "
                     "graphics can be missed, and an unusual layout can put one under the wrong heading "
                     "(must-have vs nice-to-have).")
    if "scanned_pages" in jd.known_blind_spots:
        notes.append("Part of the job description could not be read, so its list of requirements may be incomplete.")
    unresolved = [o.skill for o in facts.skill_observations if o.status == SkillStatus.UNRESOLVABLE]
    if unresolved and facts.judge is None:
        notes.append(f"{len(unresolved)} skill(s) could not be decided from keywords alone ({names(unresolved)}). "
                     "Run with --deep to have Claude settle them.")
    elif unresolved:
        notes.append(f"Claude could not settle {len(unresolved)} skill(s) either: {names(unresolved)}.")
    if facts.judge is not None:
        for skill in facts.judge.dismissed_skills:
            notes.append(f"Not counted: {quote(skill)}. The job description uses the word in its everyday sense, "
                         "not as a skill.")
        for failure in facts.judge.failures:
            # Says only what is true for every step: a failed skill match leaves its skills Ambiguous
            # (noted above), and a failed learning plan leaves the plan out. Neither is filled in by keywords.
            notes.append(f"Part of the deep analysis failed, and its results are not in this report: {quote(failure)}")
    return notes


def provenance_section(facts: GapAnalysisFacts) -> list[str]:
    decided = [o for o in facts.skill_observations if o.status in DECIDED]
    by_keywords = sum(o.confidence is None for o in decided)
    lines = ["## How this was decided", "",
             f"- {by_keywords} of {len(decided)} decided skills were settled by keyword matching, without an LLM."]
    alternatives = [o for o in facts.skill_observations if o.status == SkillStatus.ALTERNATIVE_MET]
    if alternatives:
        lines.append(f"- Not counted: {names(o.skill for o in alternatives)}. The job description asks for either "
                     "of two skills there, and the resume shows the other one.")
    if facts.judge is not None:
        by_claude = len(decided) - by_keywords
        served = names(facts.judge.served_by) or cell(facts.judge.model)
        lines.append(f"- {by_claude} {'was' if by_claude == 1 else 'were'} settled by Claude (served by {served}; "
                     f"prompts {names(facts.judge.prompt_versions) or 'none needed'}). Every match Claude made "
                     "quotes a resume line, and the quote was checked in code.")
    lines += [f"- Sources: resume {cell(facts.resume_source)}, job description {cell(facts.jd_source)}.", ""]
    return lines


def _layout_limited(coverage: Coverage) -> bool:
    return any(spot in coverage.known_blind_spots for spot in LAYOUT_BLIND_SPOTS)
