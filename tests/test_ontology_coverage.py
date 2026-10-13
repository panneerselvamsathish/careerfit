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
