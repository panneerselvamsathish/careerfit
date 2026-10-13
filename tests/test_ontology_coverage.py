from careerfit.analyze.ontology import SkillEntry
from evals.ontology_coverage import coverage, main

ONTOLOGY = {"python": SkillEntry(aliases=(), ambiguous=False), "aws": SkillEntry(aliases=(), ambiguous=False)}

JD = """Senior Engineer
Responsibilities
Build data services in Python for the billing team
Mentor engineers and lead design reviews across teams
Qualifications
Five years running production workloads on AWS
What We Offer You
Generous paid time off and a strong pension plan
"""


def test_coverage_counts_requirement_lines_and_skips_benefits():
    result = coverage(JD, ONTOLOGY)
    assert [(n, skills) for n, _, skills in result.covered] == [(3, ("python",)), (6, ("aws",))]
    assert result.uncovered == ((4, "Mentor engineers and lead design reviews across teams"),)
    assert round(result.share, 2) == 0.67


def test_coverage_cli_reports_each_jd(tmp_path, capsys):
    jd = tmp_path / "jd.txt"
    jd.write_text(JD, encoding="utf-8")
    assert main([str(jd)]) == 0
    out = capsys.readouterr().out
    assert "jd.txt: 2 of 3 requirement lines mention a known skill (67%)" in out
    assert "- line 4: Mentor engineers and lead design reviews across teams" in out
