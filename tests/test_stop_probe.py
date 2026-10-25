"""evals/stop_probe.py: no stop rule may swallow a real requirement."""

import json

from careerfit.analyze import matcher
from evals.stop_probe import CORPUS, findings, load_lines, main, probe


def test_no_stop_rule_fires_on_a_requirement_line():
    stopped = [(p.line, p.form, p.rule) for p in probe(load_lines(CORPUS)) if p.stopped]
    assert stopped == []


def test_the_corpus_never_names_the_survivor():
    assert not [line for line in load_lines(CORPUS) if "python" in line.lower()]


def test_a_rule_that_swallows_a_requirement_is_reported_on_the_rule(monkeypatch, capsys, tmp_path):
    original = matcher.stop_section
    monkeypatch.setattr(matcher, "stop_section", lambda line: "payroll" in line or original(line))
    lines = tmp_path / "lines.txt"
    lines.write_text("Experience running payroll for 2,000 employees\nAWS in production\n", encoding="utf-8")
    assert main(["--lines", str(lines)]) == 1
    rows = [json.loads(r) for r in capsys.readouterr().out.splitlines()]
    assert [(r["line"], r["form"]) for r in rows if r["kind"] == "line" and r["stopped"]] == [
        ("Experience running payroll for 2,000 employees", "bullet"),
        ("Experience running payroll for 2,000 employees", "sentence")]
    [finding] = [r for r in rows if r["kind"] == "finding"]
    assert finding["path"] == "src/careerfit/analyze/matcher.py" and "stop_section" in finding["title"]


def test_findings_are_empty_when_nothing_stopped():
    assert findings(probe(["AWS in production"])) == []
