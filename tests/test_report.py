from datetime import datetime, timezone

import pytest

from careerfit.analyze.observations import build_facts
from careerfit.analyze.ontology import load_ontology
from careerfit.cli import DEFAULT_ONTOLOGY, main
from careerfit.facts.schema import Coverage
from careerfit.ingest.document import read_document
from careerfit.judge.scorer import judge_facts
from careerfit.report import render_markdown
from careerfit.report.shared import cell
from tests.test_cli import FIXTURES
from tests.test_judge import FakeLLM, plan, verdict

AT = datetime(2026, 10, 11, tzinfo=timezone.utc)
TXT = Coverage(source_format="txt", pages_total=None, pages_with_text=None, chars_extracted=50, known_blind_spots=())
SCANNED = Coverage(source_format="pdf", pages_total=3, pages_with_text=1, chars_extracted=50,
                   known_blind_spots=("layout_order", "graphics", "tables", "scanned_pages"))


def sample_facts(perspective="candidate", resume_coverage=None, jd_coverage=None):
    resume_text, resume_cov = read_document(FIXTURES / "resume.txt")
    jd_text, jd_cov = read_document(FIXTURES / "jd.txt")
    facts = build_facts(resume_text=resume_text, resume_coverage=resume_coverage or resume_cov,
                        resume_source="resume.txt", jd_text=jd_text, jd_coverage=jd_coverage or jd_cov,
                        jd_source="jd.txt", ontology=load_ontology(DEFAULT_ONTOLOGY), at=AT, perspective=perspective)
    return facts, resume_text, jd_text


def judged_facts(perspective="candidate", learning=None):
    facts, resume_text, jd_text = sample_facts(perspective)
    llm = FakeLLM({"verdicts": [verdict("go", requires=False), verdict("react", jd_line=17)]},
                  learning or plan("kubernetes", "terraform", "kafka", "react"))
    return judge_facts(facts, resume_text=resume_text, jd_text=jd_text, llm=llm, model="claude-opus-5-5", at=AT,
                       ontology=load_ontology(DEFAULT_ONTOLOGY))


def test_keyword_report_cites_both_documents_and_suggests_deep():
    report = render_markdown(sample_facts()[0])
    assert "Keyword pass only (no LLM)" in report
    assert '| python | Matched | line 7: "- 5+ years building production services in Python" |' in report
    assert '| kubernetes | Gap | line 9: "- Running Kubernetes in production" | — |' in report
    assert "Run with --deep to have Claude settle them." in report
    assert "## Learning plan" not in report
    assert "7 of 7 decided skills were settled by keyword matching" in report


def test_every_report_says_unlisted_skills_were_not_checked():
    for perspective in ("candidate", "hiring_manager"):
        assert "Only skills in careerfit's skill list were checked." in render_markdown(sample_facts(perspective)[0])


def test_judged_candidate_report_shows_fit_plan_dismissals_and_provenance():
    report = render_markdown(judged_facts())
    assert "Deep analysis with Claude (claude-opus-5-5)" in report
    assert "- Fit: **" in report
    assert "## Learning plan" in report and "1. **kubernetes** (about 4 weeks): the JD asks for it" in report
    assert "Not counted: go." in report
    assert "1 was settled by Claude" in report


def test_learning_plan_effort_reads_naturally():
    answer = plan("kubernetes", "terraform", "kafka", "react")
    answer["steps"][0]["estimated_weeks"], answer["steps"][1]["estimated_weeks"] = 1, 0
    report = render_markdown(judged_facts(learning=answer))
    assert "1. **kubernetes** (about 1 week):" in report
    assert "2. **terraform** (time not estimated):" in report


def test_hiring_manager_report_leads_with_missing_must_haves_and_has_no_learning_plan():
    report = render_markdown(sample_facts("hiring_manager")[0])
    assert "- Missing must-haves: kubernetes, terraform" in report
    assert "- Needs a human check: go, react" in report
    assert "| kafka | nice-to-have | Gap |" in report
    assert "## Learning plan" not in report


def test_unreadable_resume_pages_and_scanned_jd_are_disclosed():
    facts, _, _ = sample_facts(resume_coverage=SCANNED, jd_coverage=SCANNED)
    report = render_markdown(facts)
    assert "2 of 3 resume pages had no readable text" in report
    assert "The resume is a PDF: skills shown only in tables, graphics or unusual layouts can be missed." in report
    assert "its list of requirements may be incomplete" in report
    assert "The job description is a PDF:" in report


def test_readable_pdf_job_description_still_discloses_layout_limits():
    readable_pdf = Coverage(source_format="pdf", pages_total=2, pages_with_text=2, chars_extracted=900,
                            known_blind_spots=("layout_order", "graphics", "tables"))
    report = render_markdown(sample_facts(jd_coverage=readable_pdf)[0])
    assert "The job description is a PDF: requirements shown only in tables or graphics can be missed" in report
    assert "its list of requirements may be incomplete" not in report
    assert "The resume is a" not in report  # the resume here is plain text


@pytest.mark.parametrize("text, expected", [
    ("a | b\nc", r"a \| b c"),
    (r"a\|b", r"a\\\|b"),  # an existing backslash must not cancel the pipe's escape
    (r"C:\tools", r"C:\\tools"),
    ('<img src="https://evil.example/p.png">', r'\<img src="https://evil.example/p.png"\>'),
    ("![pixel](https://evil.example/p.png)", r"!\[pixel\](https://evil.example/p.png)"),
    ("*bold* _it_ ~gone~ `code`", r"\*bold\* \_it\_ \~gone\~ \`code\`"),
    ("- 5+ years of C# & SQL!", "- 5+ years of C# & SQL!"),
], ids=["pipe-and-newline", "backslash-before-pipe", "plain-backslash", "html", "image", "emphasis", "plain-text"])
def test_cells_show_untrusted_text_literally(text, expected):
    assert cell(text) == expected


def test_markup_in_a_cited_resume_line_is_shown_not_rendered():
    resume = 'Python developer <img src="https://evil.example/p.png"> ![x](https://evil.example/t.png)'
    facts = build_facts(resume_text=resume, resume_coverage=TXT, resume_source="r.txt", jd_text="Requirements:\n- Python",
                        jd_coverage=TXT, jd_source="j.txt", ontology=load_ontology(DEFAULT_ONTOLOGY), at=AT,
                        perspective="candidate")
    report = render_markdown(facts)
    assert r'\<img src="https://evil.example/p.png"\>' in report
    assert r"!\[x\](https://evil.example/t.png)" in report
    assert "<img" not in report.replace(r"\<img", "") and "![" not in report


def test_cli_writes_the_report(tmp_path, capsys):
    out = tmp_path / "report.md"
    assert main(["--resume", str(FIXTURES / "resume.txt"), "--jd", str(FIXTURES / "jd.txt"), "--report", str(out)]) == 0
    assert out.read_text(encoding="utf-8").startswith("# Your fit for this job")
    assert f"Wrote {out}:" in capsys.readouterr().err
