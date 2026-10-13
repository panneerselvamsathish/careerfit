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

from careerfit.analyze.matcher import requirement_section, scan
from careerfit.analyze.ontology import SkillEntry, load_ontology
from careerfit.ingest.document import read_document

DEFAULT_ONTOLOGY = Path(__file__).parent.parent / "src" / "careerfit" / "ontology" / "skills.yaml"
# Sections that never hold requirements: everything after one of these headings is skipped
# until a requirements heading starts again.
STOP_HEADING = re.compile(r"(about (us|the company)|benefits?(( and | ?& ?|/)perks)?|perks|what we offer( you)?|equal opportunity.*|"
                          r"disclaimer|salary.*|compensation)", re.I)
BULLET = re.compile(r"^\s*([-•*▪●]|\d+[.)])\s+")
MIN_WORDS = 3  # a shorter line that isn't a bullet is a title or a fragment


@dataclass(frozen=True)
class Coverage:
    covered: tuple[tuple[int, str, tuple[str, ...]], ...]  # (line number, text, skills found)
    uncovered: tuple[tuple[int, str], ...]
    sections_found: bool  # False: no requirements heading, so every line was counted

    @property
    def share(self) -> float:
        total = len(self.covered) + len(self.uncovered)
        return len(self.covered) / total if total else 0.0


def _stop_heading(line: str) -> bool:
    return STOP_HEADING.fullmatch(line.rstrip(":").strip()) is not None


def coverage(jd_text: str, ontology: dict[str, SkillEntry]) -> Coverage:
    """Requirement lines are the lines inside requirement sections. The preamble before the first
    such heading is skipped; a JD with no such heading at all is counted line by line."""
    lines = [(n, raw.strip()) for n, raw in enumerate(jd_text.splitlines(), start=1) if raw.strip()]
    sections_found = any(requirement_section(text) for _, text in lines)
    inside = not sections_found
    covered, uncovered = [], []
    for number, text in lines:
        bullet = BULLET.match(text)
        if not bullet:
            if _stop_heading(text):
                inside = False
                continue
            if requirement_section(text):
                inside = True
                continue
            if text.endswith(":"):
                continue  # any other heading ("About the Role:", "Cloud:") is skipped and changes nothing
        if not inside:
            continue
        line = text[bullet.end():] if bullet else text
        if not bullet and len(line.split()) < MIN_WORDS:
            continue
        found = tuple(sorted(name for name, result in scan(line, ontology).items() if result != "absent"))
        if found:
            covered.append((number, line, found))
        else:
            uncovered.append((number, line))
    return Coverage(covered=tuple(covered), uncovered=tuple(uncovered), sections_found=sections_found)


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
        if not result.sections_found:
            print("  (no requirements heading found, so every line was counted)")
        if args.covered:
            for number, line, skills in result.covered:
                print(f"  + line {number} [{', '.join(skills)}]: {line[:110]}")
        for number, line in result.uncovered:
            print(f"  - line {number}: {line[:120]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
