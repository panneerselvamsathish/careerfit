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
    assert [(n, skills) for n, _, skills in result.covered] == [(4, ("python",)), (7, ("aws",))]
    assert result.uncovered == ((5, "Mentor engineers and lead design reviews across teams"), (8, "Strong communication"))
    assert result.share == 0.5


def test_coverage_counts_every_line_when_a_jd_has_no_requirements_heading():
    result = coverage("We need Python engineers for the data team\nAWS experience is a plus here", ONTOLOGY)
    assert result.sections_found is False
    assert [n for n, _, _ in result.covered] == [1, 2]


def test_a_short_requirement_is_not_mistaken_for_a_heading():
    jd = "Requirements\nNice to have Python experience\nWhat We Offer You\nPython lunches every Friday"
    result = coverage(jd, ONTOLOGY)
    assert [n for n, _, _ in result.covered] == [2]


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
    assert [n for n, _, _ in result.covered] == [4]
    assert result.uncovered == ()


def test_benefits_and_perks_headings_end_counting():
    for heading in ("Benefits and Perks", "Benefits & Perks", "Benefits/Perks:"):
        jd = f"Qualifications\nFive years running production workloads on AWS\n{heading}\nFree Python lunches for the whole team"
        assert [n for n, _, _ in coverage(jd, ONTOLOGY).covered] == [2], heading


def test_bulleted_about_us_heading_ends_counting():
    jd = "Qualifications\n- Five years running production workloads on AWS\n* About Us\n- We are a Python shop with free lunches"
    assert [n for n, _, _ in coverage(jd, ONTOLOGY).covered] == [2]
