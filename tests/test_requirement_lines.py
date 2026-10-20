"""A1.3: the result says how much of the JD the skill list could read, and warns below half."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from careerfit.analyze.observations import build_facts
from careerfit.analyze.ontology import SkillEntry
from careerfit.analyze.requirement_lines import requirement_lines
from careerfit.facts.schema import Coverage, RequirementLineCount
from careerfit.report import render_markdown
from careerfit.report.shared import blind_spot_notes, coverage_summary

ONTOLOGY = {"python": SkillEntry(aliases=(), ambiguous=False), "aws": SkillEntry(aliases=(), ambiguous=False)}
TXT = Coverage(source_format="txt", pages_total=None, pages_with_text=None, chars_extracted=1, known_blind_spots=())
JD = """About the company
We build things with Python.
Requirements
- Python services in production
- Strong ownership of ambiguous problems
- Willingness to travel 30% of the time
- Must be authorized to work in the United States without sponsorship
What We Value
- Clear writing for a wide audience
- AWS experience
Apply today and join us!
We are an equal opportunity employer and hire without regard to race or religion.
- Python is all over our benefits too
"""


def facts_for(jd: str, perspective="candidate"):
    return build_facts(resume_text="Python", resume_coverage=TXT, resume_source="r", jd_text=jd, jd_coverage=TXT,
                       jd_source="j", ontology=ONTOLOGY, at=datetime(2026, 10, 20, tzinfo=timezone.utc),
                       perspective=perspective)


def test_requirement_lines_skip_logistics_title_headings_and_eeo_prose():
    result = requirement_lines(JD, ONTOLOGY)
    assert [(n, skills) for n, _, skills in result.read] == [(4, ("python",)), (10, ("aws",))]
    assert [n for n, _ in result.unread] == [5, 9]  # travel, authorization, the heading and the rest: not counted
    assert (len(result.read), result.total) == (2, 4)


def test_build_facts_records_the_count():
    facts = facts_for(JD)
    assert facts.schema_version == "0.7.0"
    assert facts.jd_requirement_lines == RequirementLineCount(read=2, total=4)


def test_the_count_cannot_read_more_lines_than_there_are():
    with pytest.raises(ValidationError):
        RequirementLineCount(read=3, total=2)


@pytest.mark.parametrize("perspective", ["candidate", "hiring_manager"])
def test_both_reports_show_the_count_and_warn_below_half(perspective):
    more = JD.replace("- AWS experience\n", "- AWS experience\n- Kindness\n- Patience with people\n- Calm under pressure\n")
    low = render_markdown(facts_for(more, perspective))
    assert ("- The skill list could read 2 of 7 requirement lines (29%). Less than half, so this result shows only "
            "part of what the job asks for.") in low
    half = render_markdown(facts_for(JD, perspective))
    assert "- The skill list could read 2 of 4 requirement lines (50%)." in half and "Less than half" not in half


def test_the_first_blind_spot_note_carries_the_count():
    assert blind_spot_notes(facts_for(JD))[0] == (
        "careerfit's skill list could read 2 of 4 requirement lines (50%) in the job description. Only skills in its "
        "list were checked; anything else the job asks for is not shown here.")


def test_facts_without_a_count_keep_the_old_note_and_no_summary_line():
    facts = facts_for(JD).model_copy(update={"jd_requirement_lines": None})
    assert blind_spot_notes(facts)[0].startswith("Only skills in careerfit's skill list were checked.")
    assert coverage_summary(facts) is None


def test_a_half_percent_rounds_up_as_on_the_web_page():
    facts = facts_for(JD).model_copy(update={"jd_requirement_lines": RequirementLineCount(read=1, total=8)})
    assert coverage_summary(facts).startswith("The skill list could read 1 of 8 requirement lines (13%).")


@pytest.mark.parametrize("line", [
    # Review of #35: the new filters dropped lines the product reads as requirements.
    "- Python and AWS services, with up to 10% travel",
    "- Experience integrating Visa payment APIs in Python",
    "- Owned a $5M AWS budget across teams",
    "Strong Python Skills",
])
def test_a_line_naming_a_known_skill_always_counts(line):
    result = requirement_lines(f"Requirements\n{line}\n- Clear writing for a wide audience", ONTOLOGY)
    assert (len(result.read), result.total) == (1, 2)


def test_eeo_prose_in_a_jd_without_headings_is_skipped_not_a_stop():
    # Review of #35: with no requirements heading nothing reopened counting, so this gave 0 of 0.
    jd = ("We are an equal opportunity employer and value diversity.\nWe need Python engineers for our data team\n"
          "AWS experience is a plus here")
    result = requirement_lines(jd, ONTOLOGY)
    assert (len(result.read), result.total) == (2, 2)
