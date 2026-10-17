"""Either/or requirements: "OpenAI or Anthropic APIs" is met by either one, so the other is no gap."""

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from careerfit import usage
from careerfit.analyze.matcher import alternative_groups
from careerfit.analyze.observations import build_facts
from careerfit.analyze.ontology import SkillEntry, load_ontology
from careerfit.facts.schema import Coverage, GapAnalysisFacts, Provenance, SkillObservation, SkillStatus
from careerfit.judge.fit import compute_fit_score
from careerfit.judge.scorer import judge_facts
from careerfit.report import render_markdown
from evals import invariants

AT = datetime(2026, 10, 17, tzinfo=timezone.utc)
SKILLS = load_ontology(Path(__file__).parent.parent / "src" / "careerfit" / "ontology" / "skills.yaml")
TXT = Coverage(source_format="txt", pages_total=None, pages_with_text=None, chars_extracted=50, known_blind_spots=())
SCANNED = Coverage(source_format="pdf", pages_total=2, pages_with_text=1, chars_extracted=50,
                   known_blind_spots=("layout_order", "graphics", "tables", "scanned_pages"))
GEICO_LINE = ("Hands-on AI engineering: Strong experience with Python and modern AI frameworks such as LangChain, "
              "LangGraph, LangSmith, LlamaIndex, Hugging Face, and OpenAI or Anthropic APIs.")


@pytest.mark.parametrize(("clause", "groups"), [
    (GEICO_LINE, [{"openai", "anthropic api"}]),  # the "and" list before it stays separate requirements
    ("4+ years of professional software engineering or applied machine learning experience",
     [{"software engineering", "machine learning"}]),
    ("Experience with Python, Java, or Go", [{"python", "java", "go"}]),
    ("Experience with Python, Java or Go", [{"python", "java", "go"}]),
    ("Python and/or Kubernetes", [{"python", "kubernetes"}]),
    ("Experience with Python, Java, and Kubernetes", []),
    ("Python or a JVM language such as Java", []),  # too far apart to be a plain either/or
    ("PL/SQL or Python", [{"pl/sql", "python"}]),  # "SQL" inside "PL/SQL" is PL/SQL's mention
    ("Python experience", []),
    # Copilot review on #26: a chain of "or"s is one choice, a comma after a choice starts another,
    # and a filler word never swallows the "and" of the next requirement.
    ("Python or Java or Kubernetes", [{"python", "java", "kubernetes"}]),
    ("Python or Java, Kubernetes or Terraform", [{"python", "java"}, {"kubernetes", "terraform"}]),
    ("Python or equivalent and Kubernetes experience", []),
])
def test_alternative_groups(clause, groups):
    assert [set(g) for g in alternative_groups(clause, SKILLS)] == groups


def analyse(resume: str, jd: str, coverage: Coverage = TXT, ontology=SKILLS) -> GapAnalysisFacts:
    return build_facts(resume_text=resume, resume_coverage=coverage, resume_source="r.txt", jd_text=jd,
                       jd_coverage=TXT, jd_source="j.txt", ontology=ontology, at=AT, perspective="candidate")


def by_skill(facts: GapAnalysisFacts) -> dict[str, SkillObservation]:
    return {o.skill: o for o in facts.skill_observations}


def honest(facts: GapAnalysisFacts, resume: str, jd: str, ontology=SKILLS) -> list[str]:
    return invariants.check(facts) + invariants.check_evidence(facts, resume, jd, ontology)


def test_the_unshown_alternative_is_met_by_the_shown_one_and_cites_its_line():
    resume = "Lead engineer\nBuilt an assistant on the Anthropic SDK"
    jd = "Requirements:\n- Experience with OpenAI or Anthropic APIs"
    facts = analyse(resume, jd)
    observed = by_skill(facts)
    assert observed["anthropic api"].status == SkillStatus.MATCHED
    openai = observed["openai"]
    assert openai.status == SkillStatus.ALTERNATIVE_MET
    assert openai.resume_evidence is not None
    assert (openai.resume_evidence.source, openai.resume_evidence.via, openai.resume_evidence.locator,
            openai.resume_evidence.excerpt) == ("alternative", "anthropic api", "line 2",
                                                "Built an assistant on the Anthropic SDK")
    assert honest(facts, resume, jd) == []


def test_neither_alternative_shown_leaves_both_gaps():
    jd = "Requirements:\n- Experience with OpenAI or Anthropic APIs"
    observed = by_skill(analyse("Oracle PL/SQL developer", jd))
    assert observed["openai"].status == observed["anthropic api"].status == SkillStatus.GAP


def test_a_skill_also_asked_for_on_its_own_is_still_a_gap():
    resume = "Built an assistant on the Anthropic SDK"
    jd = "Requirements:\n- Experience with OpenAI or Anthropic APIs\n- OpenAI fine-tuning in production"
    assert by_skill(analyse(resume, jd))["openai"].status == SkillStatus.GAP


def test_an_and_list_is_never_an_either_or():
    jd = "Requirements:\n- Experience with Python, Java, and Kubernetes"
    observed = by_skill(analyse("Python services", jd))
    assert observed["java"].status == observed["kubernetes"].status == SkillStatus.GAP


def test_a_scanned_resume_still_shows_the_alternative_it_could_read():
    resume = "Built an assistant on the Anthropic SDK"
    jd = "Requirements:\n- Experience with OpenAI or Anthropic APIs"
    facts = analyse(resume, jd, coverage=SCANNED)
    assert by_skill(facts)["openai"].status == SkillStatus.ALTERNATIVE_MET
    assert honest(facts, resume, jd) == []


def test_the_geico_requirements_are_met_by_your_resume_wording():
    resume = "**Lead Software Engineer**\nClaude on Amazon Bedrock, Anthropic SDK"
    jd = "\n".join(["Must Have", "Experience: 4+ years of professional software engineering or applied machine "
                    "learning experience.", GEICO_LINE])
    facts = analyse(resume, jd)
    observed = by_skill(facts)
    assert observed["software engineering"].status == SkillStatus.MATCHED
    assert observed["machine learning"].status == SkillStatus.ALTERNATIVE_MET
    assert observed["machine learning"].resume_evidence.via == "software engineering"
    assert observed["openai"].status == SkillStatus.ALTERNATIVE_MET
    assert observed["langchain"].status == SkillStatus.GAP  # named in the "and" list: still asked for
    assert honest(facts, resume, jd) == []


def test_an_alternative_shown_through_another_skill_cites_that_line():
    resume = "Originated and led a SOX compliance initiative"
    jd = "Requirements:\n- Kubernetes or regulatory compliance experience"
    facts = analyse(resume, jd)
    observed = by_skill(facts)
    assert observed["regulatory compliance"].resume_evidence.via == "sox compliance"
    kubernetes = observed["kubernetes"]
    assert kubernetes.status == SkillStatus.ALTERNATIVE_MET
    assert (kubernetes.resume_evidence.via, kubernetes.resume_evidence.excerpt) == ("regulatory compliance", resume)
    assert honest(facts, resume, jd) == []


@pytest.mark.parametrize("shown", ["python", "java", "kubernetes"])
def test_any_option_of_an_or_chain_meets_the_others(shown):
    resume = {"python": "Python services", "java": "Java services", "kubernetes": "Kubernetes clusters"}[shown]
    facts = analyse(resume, "Requirements:\n- Python or Java or Kubernetes experience")
    statuses = {skill: o.status for skill, o in by_skill(facts).items()}
    assert statuses == {s: SkillStatus.MATCHED if s == shown else SkillStatus.ALTERNATIVE_MET
                        for s in ("python", "java", "kubernetes")}
    assert honest(facts, resume, "Requirements:\n- Python or Java or Kubernetes experience") == []


def test_or_equivalent_does_not_waive_the_next_requirement():
    observed = by_skill(analyse("Python services", "Requirements:\n- Python or equivalent and Kubernetes experience"))
    assert observed["kubernetes"].status == SkillStatus.GAP


def test_a_nested_skill_shares_the_choice_it_sits_in():
    resume, jd = "Python services", "Requirements:\n- PL/SQL or Python"
    facts = analyse(resume, jd)
    observed = by_skill(facts)
    assert observed["pl/sql"].status == observed["sql"].status == SkillStatus.ALTERNATIVE_MET  # SQL in "PL/SQL"
    assert observed["sql"].resume_evidence.via == "python"
    assert honest(facts, resume, jd) == []


def test_the_same_skill_asked_for_alone_in_the_same_clause_is_still_a_gap():
    jd = "Requirements:\n- Python or Java experience and Python certification"
    observed = by_skill(analyse("Java services", jd))
    assert observed["python"].status == SkillStatus.GAP


def test_a_partly_shown_skill_is_met_by_a_matched_alternative():
    from careerfit.analyze.observations import apply_alternatives
    jd = "Requirements:\n- Go or Kubernetes experience"
    k8s_line = Provenance(source="resume", locator="line 1", excerpt="Kubernetes clusters", retrieved_at=AT)
    go_line = Provenance(source="llm_judge", locator="line 2", excerpt="Some Go scripts", retrieved_at=AT)
    jd_line = Provenance(source="jd", locator="line 2", excerpt="- Go or Kubernetes experience", retrieved_at=AT)
    observations = (
        SkillObservation(skill="kubernetes", status=SkillStatus.MATCHED, requirement="must", jd_evidence=jd_line,
                         resume_evidence=k8s_line),
        SkillObservation(skill="go", status=SkillStatus.PARTIAL, requirement="must", jd_evidence=jd_line,
                         resume_evidence=go_line, confidence=0.6),
    )
    go = {o.skill: o for o in apply_alternatives(observations, jd, GO_OR_K8S)}["go"]
    assert (go.status, go.confidence, go.resume_evidence.via) == (SkillStatus.ALTERNATIVE_MET, None, "kubernetes")
    fit = compute_fit_score(apply_alternatives(observations, jd, GO_OR_K8S))
    assert fit is not None and fit.overall == 1.0  # the requirement is fully met, not marked down for Go


def test_alternatives_are_not_counted_in_the_fit_score():
    facts = analyse("Built an assistant on the Anthropic SDK",
                    "Requirements:\n- Experience with OpenAI or Anthropic APIs\n- Kubernetes")
    fit = compute_fit_score(facts.skill_observations)
    assert fit is not None and fit.must_have_coverage == 0.5  # anthropic api of {anthropic api, kubernetes}
    assert "1 skill is not counted: the job description accepts a matched skill in its place." in fit.explanation


def test_the_report_says_which_skill_met_the_requirement():
    facts = analyse("Built an assistant on the Anthropic SDK", "Requirements:\n- Experience with OpenAI or Anthropic APIs")
    report = render_markdown(facts)
    assert "| openai | Alternative met |" in report
    assert "line 1 (the job description accepts anthropic api instead)" in report
    assert "- Not counted: openai. The job description asks for either of two skills there" in report


GO_OR_K8S = {
    "go": SkillEntry(aliases=("golang",), ambiguous=True),
    "kubernetes": SkillEntry(aliases=("k8s",), ambiguous=False),
}


class FakeLLM:
    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(stop_reason="end_turn",
                               content=[SimpleNamespace(type="text", text=json.dumps(self.answers.pop(0)))])


def test_an_alternative_the_judge_matches_meets_the_gap_and_skips_the_learning_plan():
    resume, jd = "Backend engineer\nWrote backend services in Go", "Requirements:\n- Go or Kubernetes experience"
    keyword = analyse(resume, jd, ontology=GO_OR_K8S)
    assert by_skill(keyword)["kubernetes"].status == SkillStatus.GAP  # "Go" is still ambiguous here
    llm = FakeLLM({"verdicts": [{"skill": "go", "jd_requires_skill": True, "jd_line": 2, "resume_status": "matched",
                                 "resume_quote": "Wrote backend services in Go", "confidence": 0.9,
                                 "reason": "Go the language"}]})
    judged = judge_facts(keyword, resume_text=resume, jd_text=jd, llm=llm, model="m", at=AT, ontology=GO_OR_K8S)
    observed = by_skill(judged)
    assert observed["go"].status == SkillStatus.MATCHED
    assert observed["kubernetes"].status == SkillStatus.ALTERNATIVE_MET
    assert observed["kubernetes"].resume_evidence.locator == "line 2"
    assert len(llm.calls) == 1  # no gaps left, so no learning plan was asked for
    assert honest(judged, resume, jd, GO_OR_K8S) == []


def test_invariants_refuse_an_alternative_that_is_not_matched_or_not_offered():
    resume = "Built an assistant on the Anthropic SDK"
    jd = "Requirements:\n- Experience with OpenAI or Anthropic APIs\n- Kubernetes"
    facts = analyse(resume, jd)
    data = facts.model_dump()
    for o in data["skill_observations"]:
        if o["skill"] == "anthropic api":
            o.update(status="gap", resume_evidence=None)
    unmatched = GapAnalysisFacts.model_validate(data)
    assert "openai: alternative_met through 'anthropic api', which is not matched" in invariants.check(unmatched)

    stray = Provenance(source="alternative", via="anthropic api", locator="line 1", excerpt=resume, retrieved_at=AT)
    k8s = SkillObservation(skill="kubernetes", status=SkillStatus.ALTERNATIVE_MET, requirement="must",
                           jd_evidence=by_skill(facts)["kubernetes"].jd_evidence, resume_evidence=stray)
    claimed = facts.model_copy(update={"skill_observations": tuple(
        k8s if o.skill == "kubernetes" else o for o in facts.skill_observations)})
    assert ("kubernetes: the job description never offers 'anthropic api' in its place"
            in invariants.check_evidence(claimed, resume, jd, SKILLS))

    # Copilot review on #26: a requirement asked for on its own somewhere can't be waived.
    waived_jd = jd + "\n- OpenAI fine-tuning in production"
    waived_facts = analyse(resume, waived_jd)
    assert by_skill(waived_facts)["openai"].status == SkillStatus.GAP
    waived = waived_facts.model_copy(update={"skill_observations": tuple(
        o.model_copy(update={"status": SkillStatus.ALTERNATIVE_MET,
                             "resume_evidence": by_skill(facts)["openai"].resume_evidence}) if o.skill == "openai" else o
        for o in waived_facts.skill_observations)})
    assert ("openai: not every JD mention offers a matched alternative"
            in invariants.check_evidence(waived, resume, waived_jd, SKILLS))

    moved = by_skill(facts)["openai"].resume_evidence.model_copy(update={"locator": "line 2"})
    wrong_line = facts.model_copy(update={"skill_observations": tuple(
        o.model_copy(update={"resume_evidence": moved}) if o.skill == "openai" else o
        for o in facts.skill_observations)})
    assert any("is not the evidence 'anthropic api' is matched on" in v
               for v in invariants.check_evidence(wrong_line, resume, jd, SKILLS))


def test_the_alternative_filter_is_an_accepted_usage_event():
    assert usage.parse_event({"type": "filter", "props": {"key": "alternative_met"}}) == \
        ("filter", None, {"key": "alternative_met"})


def test_a_mixed_required_and_preferred_sentence_keeps_its_either_or_list():
    # Copilot review on #26: the sentence is split at commas for its levels, never for its choices.
    resume, jd = "Python services", "Requirements:\n- Python, Java, or Kubernetes are required, but Terraform is preferred."
    facts = analyse(resume, jd)
    observed = by_skill(facts)
    assert observed["python"].status == SkillStatus.MATCHED
    assert observed["java"].status == observed["kubernetes"].status == SkillStatus.ALTERNATIVE_MET
    assert (observed["terraform"].status, observed["terraform"].requirement) == (SkillStatus.GAP, "nice")
    assert honest(facts, resume, jd) == []


def go_verdict(jd_line):
    return {"skill": "go", "jd_requires_skill": True, "jd_line": jd_line, "resume_status": "absent",
            "resume_quote": "", "confidence": 0.9, "reason": "not on the resume"}


def test_an_ordinary_word_does_not_block_the_alternative_once_the_judge_has_validated_the_line():
    # Copilot review on #26: "go onsite" is the verb; the judge validated line 3 as the Go requirement.
    resume = "Kubernetes clusters"
    jd = "Requirements:\n- You must go onsite twice a week\n- Go or Kubernetes experience"
    keyword = analyse(resume, jd, ontology=GO_OR_K8S)
    assert by_skill(keyword)["go"].status == SkillStatus.UNRESOLVABLE
    llm = FakeLLM({"verdicts": [go_verdict(3)]})
    judged = judge_facts(keyword, resume_text=resume, jd_text=jd, llm=llm, model="m", at=AT, ontology=GO_OR_K8S)
    go = by_skill(judged)["go"]
    assert (go.status, go.jd_evidence.locator, go.resume_evidence.via) == (SkillStatus.ALTERNATIVE_MET, "line 3",
                                                                          "kubernetes")
    assert len(llm.calls) == 1  # nothing left for a learning plan
    assert honest(judged, resume, jd, GO_OR_K8S) == []


def test_a_standalone_line_the_judge_validated_is_still_a_gap():
    resume = "Kubernetes clusters"
    jd = "Requirements:\n- Go is required\n- Go or Kubernetes experience"
    plan = {"steps": [{"skill": "go", "priority": 1, "why_it_matters": "the JD asks for it",
                       "resources": ["go official documentation"], "estimated_weeks": 4}]}
    llm = FakeLLM({"verdicts": [go_verdict(2)]}, plan)
    judged = judge_facts(analyse(resume, jd, ontology=GO_OR_K8S), resume_text=resume, jd_text=jd, llm=llm, model="m",
                         at=AT, ontology=GO_OR_K8S)
    assert by_skill(judged)["go"].status == SkillStatus.GAP
    assert [step.skill for step in judged.learning_steps] == ["go"]
    assert honest(judged, resume, jd, GO_OR_K8S) == []
