"""Scores every golden case against its hand-labelled expectations and the honesty invariants.

Usage: uv run python -m evals.harness [--golden-dir DIR]
Exits 1 if any expectation fails or any invariant is violated.
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
        want = f"{exp['status']}/{exp['requirement']}"
        obs = actual.get(skill)
        if obs is None:
            result.failed.append(f"{skill}: expected {want}, not reported")
            continue
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


def report(results: list[CaseResult]) -> str:
    lines = []
    for r in results:
        total = len(r.passed) + len(r.failed)
        honesty = "honesty clean" if not r.violations else f"{len(r.violations)} HONESTY VIOLATIONS"
        tag = ", held out" if r.held_out else ""
        lines.append(f"{r.name} ({r.doc_type}{tag}): {len(r.passed)}/{total} expectations passed, {honesty}")
        lines += [f"  FAIL       {f}" for f in r.failed]
        lines += [f"  VIOLATION  {v}" for v in r.violations]
    n_pass = sum(len(r.passed) for r in results)
    n_total = n_pass + sum(len(r.failed) for r in results)
    n_violations = sum(len(r.violations) for r in results)
    lines.append(f"TOTAL: {n_pass}/{n_total} expectations across {len(results)} cases, {n_violations} honesty violations")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="careerfit-evals")
    parser.add_argument("--golden-dir", type=Path, default=GOLDEN_DIR)
    args = parser.parse_args(argv)

    ontology = load_ontology(ONTOLOGY_PATH)
    results = [run_case(case, ontology) for case in load_cases(args.golden_dir)]
    print(report(results))
    return 1 if any(r.failed or r.violations for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
