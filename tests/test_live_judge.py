"""Real API call. Skipped unless CAREERFIT_LIVE_LLM=1, so CI and normal runs spend nothing."""

import os
from datetime import datetime, timezone

import pytest

from careerfit.analyze.observations import build_facts
from careerfit.analyze.ontology import load_ontology
from careerfit.cli import DEFAULT_ONTOLOGY
from careerfit.facts.schema import SkillStatus
from careerfit.ingest.document import read_document
from careerfit.judge.scorer import judge_facts
from careerfit.llm import make_llm
from evals import invariants
from tests.test_cli import FIXTURES

pytestmark = pytest.mark.skipif(os.environ.get("CAREERFIT_LIVE_LLM") != "1", reason="set CAREERFIT_LIVE_LLM=1 to call the real API")


def test_live_judge_on_the_sample_documents():
    at = datetime.now(timezone.utc)
    resume_text, resume_cov = read_document(FIXTURES / "resume.txt")
    jd_text, jd_cov = read_document(FIXTURES / "jd.txt")
    ontology = load_ontology(DEFAULT_ONTOLOGY)
    keyword = build_facts(resume_text=resume_text, resume_coverage=resume_cov, resume_source="resume.txt",
                          jd_text=jd_text, jd_coverage=jd_cov, jd_source="jd.txt", ontology=ontology,
                          at=at, perspective="candidate")
    llm, model = make_llm(os.environ)
    facts = judge_facts(keyword, resume_text=resume_text, jd_text=jd_text, llm=llm, model=model, at=at)

    assert facts.judge is not None
    assert facts.judge.failures == ()
    assert not any(o.status == SkillStatus.UNRESOLVABLE for o in facts.skill_observations)
    assert facts.learning_steps
    assert invariants.check(facts) == []
    assert invariants.check_evidence(facts, resume_text, jd_text, ontology) == []
