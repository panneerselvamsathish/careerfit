import pytest
from careerfit.analyze.ontology import SkillEntry
from evals.ontology_coverage import coverage, main

ONTOLOGY = {"python": SkillEntry(aliases=(), ambiguous=False), "aws": SkillEntry(aliases=(), ambiguous=False)}

JD = """Senior Engineer
We are a fast-growing company building payments infrastructure for small businesses everywhere.
Responsibilities
Build data services in Python for the billing team
Mentor engineers and lead design reviews across teams
Qualifications
- AWS
- Strong communication
What We Offer You
Generous paid time off and a strong pension plan
"""


def test_coverage_skips_preamble_and_benefits_and_counts_short_bullets():
    result = coverage(JD, ONTOLOGY)
    assert result.sections_found is True
    assert [(n, skills) for n, _, skills in result.read] == [(4, ("python",)), (7, ("aws",))]
    assert result.unread == ((5, "Mentor engineers and lead design reviews across teams"), (8, "Strong communication"))
    assert result.share == 0.5


def test_coverage_counts_every_line_when_a_jd_has_no_requirements_heading():
    result = coverage("We need Python engineers for the data team\nAWS experience is a plus here", ONTOLOGY)
    assert result.sections_found is False
    assert [n for n, _, _ in result.read] == [1, 2]


def test_a_short_requirement_is_not_mistaken_for_a_heading():
    jd = "Requirements\nNice to have Python experience\nWhat We Offer You\nPython lunches every Friday"
    result = coverage(jd, ONTOLOGY)
    assert [n for n, _, _ in result.read] == [2]


def test_coverage_cli_reports_each_jd(tmp_path, capsys):
    jd = tmp_path / "jd.txt"
    jd.write_text(JD, encoding="utf-8")
    assert main([str(jd)]) == 0
    out = capsys.readouterr().out
    assert "jd.txt: 2 of 4 requirement lines mention a known skill (50%)" in out
    assert "- line 8: Strong communication" in out


def test_generic_colon_headings_neither_start_nor_reopen_counting():
    jd = ("About the Role:\nYou will build payments infrastructure in Python for merchants\n"
          "Qualifications:\nFive years running production workloads on AWS\n"
          "Benefits:\nGenerous paid time off and a strong pension plan\n"
          "Our Culture:\nWe write Python and ship small changes every day here")
    result = coverage(jd, ONTOLOGY)
    assert [n for n, _, _ in result.read] == [4]
    assert result.unread == ()


def test_benefits_and_perks_headings_end_counting():
    for heading in ("Benefits and Perks", "Benefits & Perks", "Benefits/Perks:"):
        jd = f"Qualifications\nFive years running production workloads on AWS\n{heading}\nFree Python lunches for the whole team"
        assert [n for n, _, _ in coverage(jd, ONTOLOGY).read] == [2], heading


def test_bulleted_about_us_heading_ends_counting():
    jd = "Qualifications\n- Five years running production workloads on AWS\n* About Us\n- We are a Python shop with free lunches"
    assert [n for n, _, _ in coverage(jd, ONTOLOGY).read] == [2]


def test_a_heading_with_unicode_dashes_reopens_counting_as_in_the_product():
    # Copilot review on #30: the product reads "Nice\u2011to\u2011have:" (non-breaking hyphens) as a
    # heading; the coverage tool must too, or it drops the lines under it from its totals.
    from careerfit.analyze.matcher import requirement_levels
    jd = "Requirements:\nBenefits:\nNice\u2011to\u2011have:\n- Python"
    assert [(n, skills) for n, _, skills in coverage(jd, ONTOLOGY).read] == [(4, ("python",))]
    assert requirement_levels(jd, ONTOLOGY) == {"python": "nice"}


def test_a_marker_with_unicode_dashes_is_found_by_every_caller():
    from careerfit.analyze.matcher import has_nice_marker, heading_level
    assert has_nice_marker("Kubernetes is nice\u2011to\u2011have")
    assert heading_level("Kubernetes is nice\u2013to\u2013have:") == "nice"


@pytest.mark.parametrize("bullet", ["-", "\u2014", "\u2013", "\u2011"])
def test_a_dash_bullet_is_a_bullet_for_the_coverage_tool_and_the_product(bullet):
    # Copilot review on #30: "\u2014 Your journey at A&M" was a stop heading (unbulleted) while
    # "- Your journey at A&M" was not, so the coverage tool dropped the lines after it.
    from careerfit.analyze.matcher import requirement_levels, stop_section
    assert stop_section(f"{bullet} Your journey at A&M") is False
    jd = f"Requirements:\n{bullet} Your journey at A&M\n- Python"
    assert [(n, skills) for n, _, skills in coverage(jd, ONTOLOGY).read] == [(3, ("python",))]
    assert requirement_levels(jd, ONTOLOGY) == {"python": "must"}


def test_a_dash_bulleted_short_requirement_is_counted_like_a_hyphen_bulleted_one():
    # The tool's own bullet check reads dashes as "-" too: "\u2014 AWS" is a bullet, so it counts
    # even though it is shorter than MIN_WORDS, and the excerpt keeps the original text.
    for bullet in ("-", "\u2014"):
        result = coverage(f"Requirements:\n{bullet} AWS", ONTOLOGY)
        assert [(n, line, skills) for n, line, skills in result.read] == [(2, "AWS", ("aws",))]
