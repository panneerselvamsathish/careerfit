import json
from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from careerfit import cli
from careerfit.facts.schema import GapAnalysisFacts, SkillStatus
from careerfit.judge.scorer import JudgeFailure
from careerfit.cache import CachingLLM
from careerfit.judge.llm import LLMConfigError, SdkLLM, make_llm
from tests.test_cli import FIXTURES
from tests.test_judge import FakeLLM, plan, verdict

GAPS_AFTER_JUDGE = ("kubernetes", "terraform", "go", "kafka", "react")


def answers():
    return [{"verdicts": [verdict("go", jd_line=15), verdict("react", jd_line=17)]}, plan(*GAPS_AFTER_JUDGE)]


def run_deep(tmp_path, monkeypatch, llm, *extra):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "make_llm", lambda env: (llm, "fake-model"))
    out = tmp_path / "facts.json"
    code = cli.main(["--resume", str(FIXTURES / "resume.txt"), "--jd", str(FIXTURES / "jd.txt"),
                     "-o", str(out), "--deep", *extra])
    assert code == 0
    return GapAnalysisFacts.model_validate_json(out.read_text(encoding="utf-8"))


def test_deep_run_produces_judged_facts(tmp_path, monkeypatch, capsys):
    facts = run_deep(tmp_path, monkeypatch, FakeLLM(*answers()))
    observed = {o.skill: o for o in facts.skill_observations}
    assert facts.llm_used is True
    assert facts.judge is not None and facts.judge.model == "fake-model"
    assert facts.judge.prompt_versions == ("skill_match@3", "learning_path@2")
    assert observed["go"].status == SkillStatus.GAP and observed["go"].confidence == 0.8
    assert [s.skill for s in facts.learning_steps] == list(GAPS_AFTER_JUDGE)
    assert facts.fit_score is not None
    assert "Judge (fake-model): fit" in capsys.readouterr().err


def test_second_identical_run_is_served_from_the_cache(tmp_path, monkeypatch):
    first = run_deep(tmp_path, monkeypatch, FakeLLM(*answers()))
    no_answers = FakeLLM()
    second = run_deep(tmp_path, monkeypatch, no_answers)
    assert no_answers.calls == []
    assert verdicts(second) == verdicts(first)
    assert second.learning_steps == first.learning_steps


def verdicts(facts):
    return [(o.skill, o.status, o.requirement, o.confidence, o.jd_evidence.locator,
             o.resume_evidence.locator if o.resume_evidence else None) for o in facts.skill_observations]


def test_fresh_ignores_the_cache(tmp_path, monkeypatch):
    run_deep(tmp_path, monkeypatch, FakeLLM(*answers()))
    again = FakeLLM(*answers())
    run_deep(tmp_path, monkeypatch, again, "--fresh")
    assert len(again.calls) == 2


def test_bad_provider_setting_is_a_clean_cli_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CAREERFIT_LLM_PROVIDER", "nope")
    code = cli.main(["--resume", str(FIXTURES / "resume.txt"), "--jd", str(FIXTURES / "jd.txt"), "--deep"])
    assert code == 2
    assert "CAREERFIT_LLM_PROVIDER must be one of" in capsys.readouterr().err


def test_bedrock_needs_a_region():
    with pytest.raises(LLMConfigError, match="needs AWS_REGION"):
        make_llm({"CAREERFIT_LLM_PROVIDER": "bedrock"})


def test_bedrock_uses_the_bedrock_model_id_and_override_wins():
    assert make_llm({"CAREERFIT_LLM_PROVIDER": "bedrock", "AWS_REGION": "us-east-1"})[1] == "global.anthropic.claude-opus-5-5"
    env = {"CAREERFIT_LLM_PROVIDER": "bedrock", "AWS_REGION": "us-east-1", "CAREERFIT_MODEL": "anthropic.custom"}
    assert make_llm(env)[1] == "anthropic.custom"


def test_sdk_errors_become_judge_failures():
    def broken(**kwargs):
        raise anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.example"))

    with pytest.raises(JudgeFailure, match="LLM request failed \\(APIConnectionError\\)"):
        SdkLLM(broken).create(model="m")


def test_cache_only_stores_complete_answers(tmp_path):
    refused = FakeLLM(SimpleNamespace(stop_reason="refusal", content=[]))
    CachingLLM(refused, tmp_path).create(model="m", messages=[])
    assert list(tmp_path.iterdir()) == []

    answered = FakeLLM({"verdicts": []})
    CachingLLM(answered, tmp_path).create(model="m", messages=[])
    stored = json.loads(next(tmp_path.iterdir()).read_text(encoding="utf-8"))
    assert stored == {"stop_reason": "end_turn", "model": None, "content": [{"type": "text", "text": '{"verdicts": []}'}]}


def test_unreadable_cache_entry_is_a_miss_and_gets_replaced(tmp_path):
    answered = FakeLLM({"verdicts": []})
    cache = CachingLLM(answered, tmp_path)
    cache.create(model="m", messages=[])
    entry = next(tmp_path.iterdir())
    entry.write_text('{"stop_reason": "end_tu', encoding="utf-8")

    again = FakeLLM({"verdicts": []})
    CachingLLM(again, tmp_path).create(model="m", messages=[])
    assert len(again.calls) == 1
    assert json.loads(entry.read_text(encoding="utf-8"))["stop_reason"] == "end_turn"
    assert [p.name for p in tmp_path.iterdir()] == [entry.name]


@pytest.mark.parametrize("entry", ["{}", "[]", '{"stop_reason": "end_turn"}',
                                   '{"stop_reason": "end_turn", "content": [{"type": "text"}]}',
                                   '{"stop_reason": "refusal", "content": []}'])
def test_malformed_cache_entry_is_a_miss(tmp_path, entry):
    answered = FakeLLM({"verdicts": []})
    CachingLLM(answered, tmp_path).create(model="m", messages=[])
    next(tmp_path.iterdir()).write_text(entry, encoding="utf-8")

    again = FakeLLM({"verdicts": []})
    response = CachingLLM(again, tmp_path).create(model="m", messages=[])
    assert len(again.calls) == 1
    assert response.stop_reason == "end_turn"


def test_cache_write_failure_does_not_lose_the_answer(tmp_path):
    blocker = tmp_path / "not-a-folder"
    blocker.write_text("x", encoding="utf-8")
    answered = FakeLLM({"verdicts": []})
    response = CachingLLM(answered, blocker / "judge").create(model="m", messages=[])
    assert response.stop_reason == "end_turn"


def test_cache_replays_the_model_that_answered(tmp_path):
    served = SimpleNamespace(stop_reason="end_turn", model="claude-opus-4-8",
                             content=[SimpleNamespace(type="text", text="{}")])
    CachingLLM(FakeLLM(served), tmp_path).create(model="m", messages=[])
    assert CachingLLM(FakeLLM(), tmp_path).create(model="m", messages=[]).model == "claude-opus-4-8"


def test_fallback_model_is_reported_by_the_cli(tmp_path, monkeypatch, capsys):
    import json as _json
    def answer(payload, model):
        return SimpleNamespace(stop_reason="end_turn", model=model,
                               content=[SimpleNamespace(type="text", text=_json.dumps(payload))])
    llm = FakeLLM(answer({"verdicts": [verdict("go", jd_line=15), verdict("react", jd_line=17)]}, "claude-opus-4-8"),
                  answer(plan(*GAPS_AFTER_JUDGE), "fake-model"))
    facts = run_deep(tmp_path, monkeypatch, llm)
    assert facts.judge is not None
    assert facts.judge.served_by == ("claude-opus-4-8", "fake-model")
    assert "served by a fallback model: claude-opus-4-8" in capsys.readouterr().err
