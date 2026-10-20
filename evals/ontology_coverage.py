"""How much of a job description can the skill list see?

    uv run python -m evals.ontology_coverage JD.txt [JD.txt ...]

For each JD, prints the share of requirement lines that mention at least one known skill, then
lists the lines that mention none. Those lines are where skills.yaml is blind: read them, and add
the concrete skills they name (with unambiguous aliases and a detect test). Concepts that only
paraphrase ("how systems fail in production") are not keyword material; leave them to the judge.

Dev-time tool: it never runs in the product and makes no network or LLM calls.
"""

import argparse
import sys
from pathlib import Path

from careerfit.analyze.ontology import load_default_ontology, load_ontology
from careerfit.analyze.requirement_lines import RequirementLines, requirement_lines
from careerfit.ingest.document import read_document

DEFAULT_ONTOLOGY = Path(__file__).parent.parent / "src" / "careerfit" / "ontology" / "skills.yaml"


def coverage(jd_text, ontology) -> RequirementLines:
    """The product's own count (analyze/requirement_lines.py), so the tool measures what users see."""
    return requirement_lines(jd_text, ontology)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ontology_coverage", description=__doc__.split("\n\n")[0])
    parser.add_argument("jds", nargs="+", type=Path, help="job description files (.txt or .pdf)")
    parser.add_argument("--ontology", type=Path, default=DEFAULT_ONTOLOGY)
    parser.add_argument("--covered", action="store_true", help="also list the covered lines and their skills")
    args = parser.parse_args(argv)
    ontology = load_default_ontology() if args.ontology == DEFAULT_ONTOLOGY else load_ontology(args.ontology)
    print(f"skill list: {len(ontology)} skills")
    for path in args.jds:
        text, _ = read_document(path)
        result = coverage(text, ontology)
        total = result.total
        print(f"\n== {path.name}: {len(result.read)} of {total} requirement lines mention a known skill "
              f"({result.share:.0%})")
        if not result.sections_found:
            print("  (no requirements heading found, so every line was counted)")
        if args.covered:
            for number, line, skills in result.read:
                print(f"  + line {number} [{', '.join(skills)}]: {line[:110]}")
        for number, line in result.unread:
            print(f"  - line {number}: {line[:120]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
