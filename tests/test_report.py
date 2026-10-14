from datetime import datetime, timezone

import pytest

from careerfit.analyze.observations import build_facts
from careerfit.analyze.ontology import SkillEntry, load_ontology
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
    assert "8 of 8 decided skills were settled by keyword matching" in report


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


def test_ambiguous_skills_are_labelled_ambiguous_not_as_a_conclusion():
    report = render_markdown(sample_facts()[0])
    assert '| go | Ambiguous | line 15: "- Experience with Go" |' in report
    assert "- Nice-to-have skills: 1 gap, 2 ambiguous (of 3)" in report


def test_failed_learning_plan_is_reported_as_missing_not_as_kept_keyword_results():
    facts, resume_text, jd_text = sample_facts()
    linked = plan("kubernetes", "terraform", "kafka", "react")
    linked["steps"][0]["resources"] = ["https://kubernetes.io/docs"]
    llm = FakeLLM({"verdicts": [verdict("go", requires=False), verdict("react", jd_line=17)]}, linked, linked)
    judged = judge_facts(facts, resume_text=resume_text, jd_text=jd_text, llm=llm, model="claude-opus-5-5", at=AT,
                         ontology=load_ontology(DEFAULT_ONTOLOGY))
    report = render_markdown(judged)
    assert ("- Part of the deep analysis failed, and its results are not in this report: "
            r"learning\_path@2: answer still invalid after one retry") in report
    assert "keyword results were kept" not in report
    assert "## Learning plan" not in report


def test_schema_version_is_shown_literally():
    facts = sample_facts()[0].model_copy(update={"schema_version": "<b>0.4.0</b>"})
    assert r"· schema \<b\>0.4.0\</b\>" in render_markdown(facts)


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
    ("safe\r# forged heading", "safe # forged heading"),  # a bare \r also ends a Markdown line
    ("a\r\nb\u2028c", "a b c"),  # \r\n, and a Unicode line separator some viewers break on
], ids=["pipe-and-newline", "backslash-before-pipe", "plain-backslash", "html", "image", "emphasis", "plain-text",
        "bare-carriage-return", "crlf-and-line-separator"])
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


def test_crafted_file_names_cannot_inject_markup():
    source = "cv`![x](https://evil.example/p.png)`.txt"
    facts = build_facts(resume_text="Python developer", resume_coverage=TXT, resume_source=source,
                        jd_text="Requirements:\n- Python", jd_coverage=TXT, jd_source="j.txt",
                        ontology=load_ontology(DEFAULT_ONTOLOGY), at=AT, perspective="hiring_manager")
    report = render_markdown(facts)
    assert r"- Sources: resume cv\`!\[x\](https://evil.example/p.png)\`.txt, job description j.txt." in report
    assert "![" not in report


def test_skill_names_from_a_custom_ontology_are_escaped_in_summaries():
    ontology = {"<b>x</b>": SkillEntry(aliases=(), ambiguous=False)}
    facts = build_facts(resume_text="Python developer", resume_coverage=TXT, resume_source="r.txt",
                        jd_text="Requirements:\n- <b>x</b>", jd_coverage=TXT, jd_source="j.txt",
                        ontology=ontology, at=AT, perspective="hiring_manager")
    report = render_markdown(facts)
    assert r"- Missing must-haves: \<b\>x\</b\>" in report
    assert "<b>" not in report


@pytest.mark.parametrize("output, report", [
    ("out.md", "{tmp}/out.md"),
    ("Out.md", "out.md"),                      # one file on macOS and Windows, even before it exists
    ("caf\u00e9.md", "cafe\u0301.md"),       # é precomposed vs e + combining accent: one file on macOS
], ids=["relative-vs-absolute", "case-only", "unicode-normalisation"])
def test_output_and_report_cannot_be_the_same_file(tmp_path, monkeypatch, capsys, output, report):
    monkeypatch.chdir(tmp_path)
    args = ["--resume", str(FIXTURES / "resume.txt"), "--jd", str(FIXTURES / "jd.txt")]
    assert main(args + ["-o", output, "--report", report.format(tmp=tmp_path)]) == 2
    assert "-o and --report must be different files" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []


def test_output_and_report_cannot_be_two_names_for_one_existing_file(tmp_path, capsys):
    (tmp_path / "out.md").write_text("keep me", encoding="utf-8")
    (tmp_path / "alias.md").hardlink_to(tmp_path / "out.md")
    args = ["--resume", str(FIXTURES / "resume.txt"), "--jd", str(FIXTURES / "jd.txt")]
    assert main(args + ["-o", str(tmp_path / "out.md"), "--report", str(tmp_path / "alias.md")]) == 2
    assert (tmp_path / "out.md").read_text(encoding="utf-8") == "keep me"


def test_cli_writes_the_report(tmp_path, capsys):
    out = tmp_path / "report.md"
    assert main(["--resume", str(FIXTURES / "resume.txt"), "--jd", str(FIXTURES / "jd.txt"), "--report", str(out)]) == 0
    assert out.read_text(encoding="utf-8").startswith("# Your fit for this job")
    assert f"Wrote {out}:" in capsys.readouterr().err


def test_derived_evidence_says_which_skill_shows_it():
    from careerfit.facts.schema import Provenance
    from careerfit.report.shared import cite
    evidence = Provenance(source="derived", via="pl/sql", locator="line 13", excerpt="Wrote PL/SQL packages",
                          retrieved_at=AT)
    assert cite(evidence) == 'line 13 (shown through pl/sql): "Wrote PL/SQL packages"'
