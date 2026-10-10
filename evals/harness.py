"""Scores every golden case against its hand-labelled expectations and the honesty invariants.

Usage: uv run python -m evals.harness [--golden-dir DIR]

Development cases are regression tests: every expectation must pass. Held-out cases measure
the rules and are never used to tune them, so their misses are reported but don't fail the
run. Honesty violations fail the run on any case.
"""

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

from careerfit.analyze.observations import build_facts
from careerfit.analyze.ontology import SkillEntry, load_ontology
from careerfit.ingest.document import read_document
from evals import invariants

ROOT = Path(__file__).parent.parent
GOLDEN_DIR = Path(__file__).parent / "golden"
ONTOLOGY_PATH = ROOT / "src" / "careerfit" / "ontology" / "skills.yaml"
EVAL_AT = datetime(2026, 1, 1, tzinfo=timezone.utc)


@dataclass
class CaseResult:
    name: str
    doc_type: str
    held_out: bool
    passed: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)
    status_correct: int = 0
    requirement_correct: int = 0
    labelled: int = 0


def load_cases(golden_dir: Path = GOLDEN_DIR) -> list[dict]:
    return [yaml.safe_load(p.read_text(encoding="utf-8")) for p in sorted(golden_dir.glob("*.yaml"))]


def run_case(case: dict, ontology: dict[str, SkillEntry]) -> CaseResult:
    resume_text, resume_coverage = read_document(ROOT / case["resume"])
    jd_text, jd_coverage = read_document(ROOT / case["jd"])
    facts = build_facts(
        resume_text=resume_text,
        resume_coverage=resume_coverage,
        resume_source=case["resume"],
        jd_text=jd_text,
        jd_coverage=jd_coverage,
        jd_source=case["jd"],
        ontology=ontology,
        at=EVAL_AT,
        perspective="candidate",
    )
    result = CaseResult(case["case"], case["doc_type"], case.get("held_out", False))
    actual = {o.skill: o for o in facts.skill_observations}
    expected: dict[str, dict] = case["expected"]
    not_observed: list[str] = case.get("not_observed", [])

    for skill, exp in expected.items():
        result.labelled += 1
        want = f"{exp['status']}/{exp['requirement']}"
        obs = actual.get(skill)
        if obs is None:
            result.failed.append(f"{skill}: expected {want}, not reported")
            continue
        result.status_correct += obs.status.value == exp["status"]
        result.requirement_correct += obs.requirement == exp["requirement"]
        got = f"{obs.status.value}/{obs.requirement}"
        (result.passed if got == want else result.failed).append(f"{skill}: expected {want}, got {got}")

    for skill in not_observed:
        if skill in actual:
            result.failed.append(f"{skill}: should not be reported, got {actual[skill].status.value}")
    for skill in actual:
        if skill not in expected and skill not in not_observed:
            result.failed.append(f"{skill}: reported but not labelled in the golden file")

    result.violations = invariants.check(facts) + invariants.check_evidence(facts, resume_text, jd_text, ontology)
    return result


def _pct(n: int, total: int) -> str:
    return f"{n}/{total} ({100 * n // total}%)" if total else "n/a"


def _accuracy_line(label: str, group: list[CaseResult]) -> str:
    labelled = sum(r.labelled for r in group)
    status = sum(r.status_correct for r in group)
    requirement = sum(r.requirement_correct for r in group)
    return f"  {label:<10} status {_pct(status, labelled):<14} requirement {_pct(requirement, labelled)}"


def report(results: list[CaseResult]) -> str:
    lines = []
    for r in results:
        total = len(r.passed) + len(r.failed)
        honesty = "honesty clean" if not r.violations else f"{len(r.violations)} HONESTY VIOLATIONS"
        tag = ", held out" if r.held_out else ""
        lines.append(f"{r.name} ({r.doc_type}{tag}): {len(r.passed)}/{total} expectations passed, {honesty}")
        lines += [f"  {'MISS' if r.held_out else 'FAIL'}       {f}" for f in r.failed]
        lines += [f"  VIOLATION  {v}" for v in r.violations]

    lines.append("Accuracy on labelled skills:")
    for label, group in (("dev", [r for r in results if not r.held_out]), ("held-out", [r for r in results if r.held_out])):
        if group:
            lines.append(_accuracy_line(label, group))
    for doc_type in sorted({r.doc_type for r in results}):
        lines.append(_accuracy_line(doc_type, [r for r in results if r.doc_type == doc_type]))

    n_violations = sum(len(r.violations) for r in results)
    n_dev_failures = sum(len(r.failed) for r in results if not r.held_out)
    lines.append(f"TOTAL: {len(results)} cases, {n_dev_failures} dev failures, {n_violations} honesty violations")
    return "\n".join(lines)


def gate_failed(results: list[CaseResult]) -> bool:
    return any(r.violations or (r.failed and not r.held_out) for r in results)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="careerfit-evals")
    parser.add_argument("--golden-dir", type=Path, default=GOLDEN_DIR)
    args = parser.parse_args(argv)

    ontology = load_ontology(ONTOLOGY_PATH)
    results = [run_case(case, ontology) for case in load_cases(args.golden_dir)]
    print(report(results))
    return 1 if gate_failed(results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
