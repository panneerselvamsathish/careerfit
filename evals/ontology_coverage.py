"""How much of a job description can the skill list see?

    uv run python -m evals.ontology_coverage JD.txt [JD.txt ...]

For each JD, prints the share of requirement lines that mention at least one known skill, then
lists the lines that mention none. Those lines are where skills.yaml is blind: read them, and add
the concrete skills they name (with unambiguous aliases and a detect test). Concepts that only
paraphrase ("how systems fail in production") are not keyword material; leave them to the judge.

Dev-time tool: it never runs in the product and makes no network or LLM calls.
"""

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from careerfit.analyze.matcher import scan
from careerfit.analyze.ontology import SkillEntry, load_ontology
from careerfit.ingest.document import read_document

DEFAULT_ONTOLOGY = Path(__file__).parent.parent / "src" / "careerfit" / "ontology" / "skills.yaml"
# Sections that never hold requirements: everything after one of these headings is skipped
# until a heading that starts requirements again.
STOP_HEADING = re.compile(r"\b(benefits?|perks|what we offer|equal opportunity|about us|disclaimer|salary)\b", re.I)
START_HEADING = re.compile(r"\b(responsibilit\w*|qualifications?|requirements?|what you will|you bring|"
                           r"set you apart|preferred|must have|nice to have)\b", re.I)
MIN_WORDS = 5  # shorter lines are headings or fragments


@dataclass(frozen=True)
class Coverage:
    covered: tuple[tuple[int, str, tuple[str, ...]], ...]  # (line number, text, skills found)
    uncovered: tuple[tuple[int, str], ...]

    @property
    def share(self) -> float:
        total = len(self.covered) + len(self.uncovered)
        return len(self.covered) / total if total else 0.0


def is_heading(line: str) -> bool:
    words = len(line.split())
    named = (START_HEADING.search(line) or STOP_HEADING.search(line)) and words <= 6 and not line.endswith(".")
    return line.endswith(":") or words < MIN_WORDS or bool(named)


def coverage(jd_text: str, ontology: dict[str, SkillEntry]) -> Coverage:
    covered, uncovered = [], []
    skipping = False
    for number, raw in enumerate(jd_text.splitlines(), start=1):
        line = raw.strip(" \t-•*")
        if not line:
            continue
        if is_heading(line):
            if STOP_HEADING.search(line):
                skipping = True
            elif START_HEADING.search(line):
                skipping = False
            continue
        if skipping:
            continue
        found = tuple(sorted(name for name, result in scan(line, ontology).items() if result != "absent"))
        if found:
            covered.append((number, line, found))
        else:
            uncovered.append((number, line))
    return Coverage(covered=tuple(covered), uncovered=tuple(uncovered))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ontology_coverage", description=__doc__.split("\n\n")[0])
    parser.add_argument("jds", nargs="+", type=Path, help="job description files (.txt or .pdf)")
    parser.add_argument("--ontology", type=Path, default=DEFAULT_ONTOLOGY)
    parser.add_argument("--covered", action="store_true", help="also list the covered lines and their skills")
    args = parser.parse_args(argv)
    ontology = load_ontology(args.ontology)
    print(f"skill list: {len(ontology)} skills")
    for path in args.jds:
        text, _ = read_document(path)
        result = coverage(text, ontology)
        total = len(result.covered) + len(result.uncovered)
        print(f"\n== {path.name}: {len(result.covered)} of {total} requirement lines mention a known skill "
              f"({result.share:.0%})")
        if args.covered:
            for number, line, skills in result.covered:
                print(f"  + line {number} [{', '.join(skills)}]: {line[:110]}")
        for number, line in result.uncovered:
            print(f"  - line {number}: {line[:120]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
