"""Label stubs for the skills a golden case reports but its file doesn't label yet.

    uv run python -m evals.ontology_diff

When the skill list grows (an import, a curated batch), golden cases start reporting skills nobody
has labelled, and the harness fails them. This prints, for each case, one YAML stub per unlabelled
skill with the JD and resume lines careerfit cited, so a person can read those lines in the
documents and fill in the labels.

The status and requirement are left as "?" on purpose, and careerfit's own verdict isn't shown:
golden cases are labelled from the documents, never copied from careerfit's output.
"""

import argparse
from pathlib import Path

from careerfit.analyze.ontology import load_default_ontology
from careerfit.facts.schema import GapAnalysisFacts
from evals.harness import GOLDEN_DIR, case_facts, load_cases


def unlabelled(case: dict, facts: GapAnalysisFacts) -> list:
    labelled = set(case.get("expected", {})) | set(case.get("not_observed", []))
    return [o for o in facts.skill_observations if o.skill not in labelled]


def stubs(case: dict, facts: GapAnalysisFacts, sources: dict[str, tuple[str, ...]]) -> list[str]:
    lines = []
    for o in unlabelled(case, facts):
        lines.append(f"  {o.skill}: {{status: ?, requirement: ?}}   # from {'+'.join(sources.get(o.skill, ('?',)))}")
        lines.append(f'    # JD {o.jd_evidence.locator}: "{o.jd_evidence.excerpt}"')
        if o.resume_evidence is not None:
            lines.append(f'    # resume {o.resume_evidence.locator}: "{o.resume_evidence.excerpt}"')
        else:
            lines.append("    # resume: careerfit cited no line; search the resume yourself")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--golden-dir", type=Path, default=GOLDEN_DIR)
    args = parser.parse_args(argv)
    ontology = load_default_ontology()
    sources = {name: entry.sources for name, entry in ontology.items()}
    total = 0
    for case in load_cases(args.golden_dir):
        facts = case_facts(case, ontology)
        lines = stubs(case, facts, sources)
        if not lines:
            continue
        total += len(unlabelled(case, facts))
        kind = "held out" if case.get("held_out") else "dev"
        print(f"# {case['case']} ({kind}): add under `expected:` (or list in `not_observed:`), then set labelled_at")
        print("\n".join(lines))
        print()
    print(f"{total} unlabelled skill(s)." if total else "Every reported skill is labelled.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
