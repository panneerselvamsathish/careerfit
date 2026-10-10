from pathlib import Path

from careerfit.cli import main
from careerfit.facts.schema import GapAnalysisFacts, SkillStatus

FIXTURES = Path(__file__).parent.parent / "fixtures"

EXPECTED = {
    "python": (SkillStatus.MATCHED, "must"),
    "aws": (SkillStatus.MATCHED, "must"),
    "kubernetes": (SkillStatus.GAP, "must"),
    "terraform": (SkillStatus.GAP, "must"),
    "postgresql": (SkillStatus.MATCHED, "must"),
    "rest": (SkillStatus.MATCHED, "must"),
    "go": (SkillStatus.UNRESOLVABLE, "nice"),
    "kafka": (SkillStatus.GAP, "nice"),
    "react": (SkillStatus.UNRESOLVABLE, "nice"),
}


def run_on_fixtures(tmp_path: Path) -> GapAnalysisFacts:
    out = tmp_path / "facts.json"
    exit_code = main(["--resume", str(FIXTURES / "resume.txt"), "--jd", str(FIXTURES / "jd.txt"), "-o", str(out)])
    assert exit_code == 0
    return GapAnalysisFacts.model_validate_json(out.read_text(encoding="utf-8"))


def test_cli_on_sample_resume_and_jd(tmp_path):
    facts = run_on_fixtures(tmp_path)
    actual = {o.skill: (o.status, o.requirement) for o in facts.skill_observations}
    assert actual == EXPECTED


def test_cli_output_is_keyword_only_and_cites_evidence(tmp_path):
    facts = run_on_fixtures(tmp_path)
    assert facts.llm_used is False
    assert facts.fit_score is None
    assert facts.resume_coverage.source_format == "txt"
    for o in facts.skill_observations:
        assert o.jd_evidence.locator.startswith("line ")
        if o.status == SkillStatus.MATCHED:
            assert o.resume_evidence is not None


def test_cli_skips_resume_skills_the_jd_does_not_ask_for(tmp_path):
    skills = {o.skill for o in run_on_fixtures(tmp_path).skill_observations}
    assert {"docker", "git", "sql", "django", "javascript"}.isdisjoint(skills)


def test_cli_rejects_unsupported_file_with_clear_message(tmp_path, capsys):
    docx = tmp_path / "resume.docx"
    docx.write_text("not really a docx", encoding="utf-8")
    exit_code = main(["--resume", str(docx), "--jd", str(FIXTURES / "jd.txt")])
    assert exit_code == 2
    assert "resume.docx" in capsys.readouterr().err


def test_cli_prints_json_to_stdout_without_output_flag(capsys):
    assert main(["--resume", str(FIXTURES / "resume.txt"), "--jd", str(FIXTURES / "jd.txt")]) == 0
    facts = GapAnalysisFacts.model_validate_json(capsys.readouterr().out)
    assert len(facts.skill_observations) == len(EXPECTED)
