import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from careerfit.analyze.observations import build_facts
from careerfit.analyze.ontology import SkillEntry
from careerfit.facts.schema import Coverage, SkillObservation, SkillStatus
from careerfit.judge.fit import compute_fit_score
from careerfit.judge.scorer import find_quote_line, judge_facts, looks_like_link
from evals import invariants

AT = datetime(2026, 1, 1, tzinfo=timezone.utc)
MODEL = "claude-opus-5-5"
ONTOLOGY = {
    "python": SkillEntry(aliases=(), ambiguous=False),
    "kubernetes": SkillEntry(aliases=("k8s",), ambiguous=False),
    "go": SkillEntry(aliases=("golang",), ambiguous=True),
    "react": SkillEntry(aliases=("react.js",), ambiguous=True),
}
TXT = Coverage(source_format="txt", pages_total=None, pages_with_text=None, chars_extracted=50, known_blind_spots=())
SCANNED = Coverage(source_format="pdf", pages_total=2, pages_with_text=1, chars_extracted=50,
                   known_blind_spots=("layout_order", "graphics", "tables", "scanned_pages"))

JD = "Requirements:\n- Python\n- Kubernetes\n- Go is required\nNice to have:\n- React for dashboards"
RESUME = "Backend engineer\nWrote backend services in Go and Python.\nI react quickly to incidents."


class FakeLLM:
    """Returns scripted answers in order and records every request it received."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        answer = self.answers.pop(0)
        if isinstance(answer, SimpleNamespace):
            return answer
        return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=json.dumps(answer))])


def verdict(skill, *, requires=True, status="absent", quote="", confidence=0.8):
    return {"skill": skill, "jd_requires_skill": requires, "resume_status": status,
            "resume_quote": quote, "confidence": confidence, "reason": "test"}


def plan(*skills):
    return {"steps": [{"skill": s, "priority": i, "why_it_matters": "the JD asks for it",
                       "resources": [f"{s} official documentation"], "estimated_weeks": 4}
                      for i, s in enumerate(skills, start=1)]}


def keyword_facts(resume=RESUME, jd=JD, coverage=TXT):
    return build_facts(resume_text=resume, resume_coverage=coverage, resume_source="r.txt", jd_text=jd,
                       jd_coverage=TXT, jd_source="j.txt", ontology=ONTOLOGY, at=AT, perspective="candidate")


def run(llm, facts=None, resume=RESUME, jd=JD):
    return judge_facts(facts or keyword_facts(resume, jd), resume_text=resume, jd_text=jd, llm=llm, model=MODEL, at=AT)


def by_skill(facts):
    return {o.skill: o for o in facts.skill_observations}


def schema_skills(call):
    return call["output_config"]["format"]["schema"]["properties"]["verdicts"]["items"]["properties"]["skill"]["enum"]


def test_keyword_pass_leaves_go_and_react_unresolvable():
    observed = by_skill(keyword_facts())
    assert observed["go"].status == SkillStatus.UNRESOLVABLE
    assert observed["react"].status == SkillStatus.UNRESOLVABLE


def test_only_unresolvable_skills_are_sent_to_the_judge():
    llm = FakeLLM({"verdicts": [verdict("go", status="matched", quote="backend services in Go"),
                                verdict("react", requires=False)]},
                  plan("kubernetes"))
    run(llm)
    assert sorted(schema_skills(llm.calls[0])) == ["go", "react"]


def test_matched_verdict_cites_the_quoted_resume_line():
    llm = FakeLLM({"verdicts": [verdict("go", status="matched", quote="backend services in Go", confidence=0.9),
                                verdict("react", requires=False)]},
                  plan("kubernetes"))
    go = by_skill(run(llm))["go"]
    assert go.status == SkillStatus.MATCHED
    assert go.confidence == 0.9
    assert go.resume_evidence is not None
    assert (go.resume_evidence.source, go.resume_evidence.locator) == ("llm_judge", "line 2")


def test_skill_the_jd_does_not_really_ask_for_is_dismissed():
    llm = FakeLLM({"verdicts": [verdict("go", status="matched", quote="backend services in Go"),
                                verdict("react", requires=False)]},
                  plan("kubernetes"))
    facts = run(llm)
    assert "react" not in by_skill(facts)
    assert facts.judge is not None and facts.judge.dismissed_skills == ("react",)


def test_quote_not_in_resume_is_retried_with_the_reason():
    llm = FakeLLM({"verdicts": [verdict("go", status="matched", quote="Built Go microservices at scale"),
                                verdict("react", requires=False)]},
                  {"verdicts": [verdict("go", status="absent"), verdict("react", requires=False)]},
                  plan("kubernetes", "go"))
    facts = run(llm)
    retry = llm.calls[1]["messages"]
    assert [m["role"] for m in retry] == ["user", "assistant", "user"]
    assert "is not on any single line of the resume" in retry[2]["content"]
    assert by_skill(facts)["go"].status == SkillStatus.GAP


def test_still_invalid_after_retry_keeps_keyword_verdicts_and_records_why():
    bad = {"verdicts": [verdict("go", status="matched", quote="nowhere in the resume")]}
    llm = FakeLLM(bad, bad, plan("kubernetes"))
    facts = run(llm)
    assert by_skill(facts)["go"].status == SkillStatus.UNRESOLVABLE
    assert by_skill(facts)["react"].status == SkillStatus.UNRESOLVABLE
    assert facts.judge is not None
    assert "skill_match@1: answer still invalid after one retry" in facts.judge.failures[0]
    assert "react: missing from the answer" in facts.judge.failures[0]


def test_refusal_is_recorded_not_turned_into_gaps():
    llm = FakeLLM(SimpleNamespace(stop_reason="refusal", content=[]), plan("kubernetes"))
    facts = run(llm)
    assert by_skill(facts)["go"].status == SkillStatus.UNRESOLVABLE
    assert facts.judge is not None and facts.judge.failures == ("skill_match@1: the model declined the request",)


def test_absent_on_a_partly_unreadable_resume_is_not_assessed_not_gap():
    llm = FakeLLM({"verdicts": [verdict("go"), verdict("react")]}, plan("kubernetes"))
    facts = run(llm, facts=keyword_facts(coverage=SCANNED))
    assert by_skill(facts)["go"].status == SkillStatus.NOT_ASSESSED
    assert by_skill(facts)["go"].confidence is None


def test_no_llm_call_when_nothing_needs_judging():
    jd, resume = "Requirements:\n- Python", "Python developer"
    llm = FakeLLM()
    facts = run(llm, resume=resume, jd=jd)
    assert llm.calls == []
    assert facts.llm_used is True
    assert facts.judge is not None and facts.judge.prompt_versions == ()
    assert facts.fit_score is not None and facts.fit_score.overall == 1.0


def test_learning_plan_with_urls_is_retried_then_kept():
    with_url = plan("kubernetes")
    with_url["steps"][0]["resources"] = ["https://kubernetes.io/docs"]
    llm = FakeLLM({"verdicts": [verdict("go", status="matched", quote="backend services in Go"),
                                verdict("react", requires=False)]},
                  with_url, plan("kubernetes"))
    facts = run(llm)
    assert "'https://kubernetes.io/docs' contains a link" in llm.calls[2]["messages"][2]["content"]
    assert [s.skill for s in facts.learning_steps] == ["kubernetes"]
    assert facts.learning_steps[0].estimated_weeks == 4


def test_unknown_estimate_becomes_none():
    answer = plan("kubernetes")
    answer["steps"][0]["estimated_weeks"] = 0
    llm = FakeLLM({"verdicts": [verdict("go", status="matched", quote="backend services in Go"),
                                verdict("react", requires=False)]}, answer)
    assert run(llm).learning_steps[0].estimated_weeks is None


def test_judged_facts_still_pass_every_honesty_invariant():
    llm = FakeLLM({"verdicts": [verdict("go", status="matched", quote="backend services in Go"),
                                verdict("react", requires=False)]},
                  plan("kubernetes"))
    facts = run(llm)
    assert invariants.check(facts) == []
    assert invariants.check_evidence(facts, RESUME, JD, ONTOLOGY) == []


def test_judging_twice_is_refused():
    llm = FakeLLM({"verdicts": [verdict("go"), verdict("react", requires=False)]}, plan("kubernetes", "go"))
    facts = run(llm)
    with pytest.raises(ValueError, match="already judged"):
        judge_facts(facts, resume_text=RESUME, jd_text=JD, llm=FakeLLM(), model=MODEL, at=AT)


@pytest.mark.parametrize("quote, expected", [
    ("backend services in Go", 2),
    ("BACKEND   services in go", 2),
    ("services in Go and Python. I react", None),
    ("", None),
    ("services in G", None),
])
def test_find_quote_line(quote, expected):
    assert find_quote_line(quote, RESUME) == expected


def _obs(skill, status, requirement="must"):
    from careerfit.facts.schema import Provenance
    jd = Provenance(source="jd", locator="line 1", retrieved_at=AT)
    resume = Provenance(source="resume", locator="line 1", retrieved_at=AT) if status == SkillStatus.MATCHED else None
    return SkillObservation(skill=skill, status=status, requirement=requirement, jd_evidence=jd, resume_evidence=resume)


def test_fit_score_weights_must_haves_and_skips_undecided_skills():
    observations = (
        _obs("a", SkillStatus.MATCHED), _obs("b", SkillStatus.GAP),
        _obs("c", SkillStatus.MATCHED, "nice"), _obs("d", SkillStatus.UNRESOLVABLE, "nice"),
    )
    fit = compute_fit_score(observations)
    assert fit is not None
    assert (fit.must_have_coverage, fit.nice_to_have_coverage, fit.overall) == (0.5, 1.0, 0.625)
    assert "1 skill could not be assessed and is not counted." in fit.explanation


def test_fit_score_is_none_when_nothing_was_decided():
    assert compute_fit_score((_obs("a", SkillStatus.UNRESOLVABLE),)) is None


@pytest.mark.parametrize("resource, is_link", [
    ("https://kubernetes.io/docs", True),
    ("ftp://example.org/course", True),
    ("kubernetes.io/docs/tutorials", True),
    ("[Kubernetes docs](kubernetes.io)", True),
    ("www.example.com", True),
    ("Kubernetes official documentation (kubernetes.io)", False),
    ("Kafka: The Definitive Guide (O'Reilly)", False),
    ("A Tour of Go (go.dev)", False),
])
def test_looks_like_link(resource, is_link):
    assert looks_like_link(resource) is is_link


def test_nice_to_have_ahead_of_a_must_have_is_retried():
    def step(skill, priority):
        return {"skill": skill, "priority": priority, "why_it_matters": "x",
                "resources": [f"{skill} official documentation"], "estimated_weeks": 4}

    react_first = {"steps": [step("react", 1), step("kubernetes", 2), step("go", 3)]}
    llm = FakeLLM({"verdicts": [verdict("go"), verdict("react")]},
                  react_first, plan("kubernetes", "go", "react"))
    facts = run(llm)
    assert by_skill(facts)["react"].requirement == "nice"
    assert "every must-have gap must have a higher priority" in llm.calls[2]["messages"][2]["content"]
    assert [s.skill for s in facts.learning_steps] == ["kubernetes", "go", "react"]


def test_quote_inside_a_longer_word_is_not_found():
    assert find_quote_line("Go", "Deployed on Google Cloud") is None
    assert find_quote_line("on Google Cloud", "Deployed on Google Cloud") == 1


def test_one_word_quote_is_retried():
    llm = FakeLLM({"verdicts": [verdict("go", status="matched", quote="Go"), verdict("react", requires=False)]},
                  {"verdicts": [verdict("go", status="matched", quote="backend services in Go"),
                                verdict("react", requires=False)]},
                  plan("kubernetes"))
    facts = run(llm)
    assert "resume_quote must be at least 3 words" in llm.calls[1]["messages"][2]["content"]
    assert by_skill(facts)["go"].status == SkillStatus.MATCHED
