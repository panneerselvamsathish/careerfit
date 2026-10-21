"""Do the matcher's stop rules ever swallow a real requirement?

    uv run python -m evals.stop_probe [--lines FILE]

The matcher stops reading a JD at a benefits, equal-opportunity or pay heading, and at the lines
the stop rules treat like one. A rule that fires on a real requirement drops every requirement
after it, and the result still looks complete. Twice in the review of #35 a new rule did this
("You will run our affirmative action plan...", "Ability to apply today's security...").

Each line of evals/probes/requirement_lines.txt (or --lines FILE, "-" for stdin) is put inside a
requirements section, once as a bullet and once as a sentence, followed by a Python requirement.
If Python is no longer read, a stop rule fired on the line. Prints one JSON object per probe line
(`"kind": "line"`) and one per rule that fired (`"kind": "finding"`, anchored on the rule), so
pr-review can post the findings. Exit code 1 when a rule fired.

Dev-time tool: no network, no clock, no LLM.
"""

import argparse
import inspect
import json
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from careerfit.analyze import matcher
from careerfit.analyze.ontology import SkillEntry

CORPUS = Path(__file__).parent / "probes" / "requirement_lines.txt"
SURVIVOR = {"python": SkillEntry(aliases=(), ambiguous=False)}
FORMS = {
    "bullet": "Requirements\n- {line}\n- Python services in production",
    "sentence": "Requirements\n{line}\nPython services in production are required",
}
# The rules that can stop the reading. Older revisions lack some, so each is looked up by name.
STOP_RULES = ("stop_section", "eeo_prose", "call_to_apply")


@dataclass(frozen=True)
class Probe:
    line: str
    form: str
    stopped: bool
    rule: str | None  # the stop rule that fires on the line, when one does


def load_lines(path: Path) -> list[str]:
    text = sys.stdin.read() if str(path) == "-" else path.read_text(encoding="utf-8")
    return [s for s in (raw.strip() for raw in text.splitlines()) if s and not s.startswith("#")]


def _rules() -> list[tuple[str, Callable[[str], bool]]]:
    return [(name, getattr(matcher, name)) for name in STOP_RULES if hasattr(matcher, name)]


def probe(lines: Iterable[str]) -> list[Probe]:
    rules = _rules()
    out = []
    for line in lines:
        for form, template in FORMS.items():
            jd = template.format(line=line)
            stopped = "python" not in matcher.requirement_evidence(jd, SURVIVOR)
            jd_line = jd.splitlines()[1]
            fired = next((name for name, rule in rules if rule(jd_line)), None)
            out.append(Probe(line, form, stopped, fired if stopped else None))
    return out


def findings(probes: Iterable[Probe]) -> list[dict]:
    """One finding per stop rule that swallowed a requirement, listing the lines it fired on."""
    by_rule: dict[str, list[Probe]] = {}
    for p in probes:
        if p.stopped:
            by_rule.setdefault(p.rule or "requirement_sentences", []).append(p)
    out = []
    for name, hits in by_rule.items():
        fn = getattr(matcher, name)
        shown = "; ".join(f'"{p.line}" ({p.form})' for p in hits[:5]) + (f"; and {len(hits) - 5} more" if len(hits) > 5 else "")
        out.append({
            "kind": "finding", "severity": "important",
            "path": "src/careerfit/analyze/matcher.py", "line": inspect.getsourcelines(fn)[1],
            "title": f"`{name}()` stops the reading at a real requirement",
            "body": (f"evals/stop_probe.py put these requirement lines inside a requirements section and the "
                     f"Python requirement after them was no longer read: {shown}. Every requirement after such a "
                     f"line is dropped and the result still looks complete. Narrow the rule, and add the line to "
                     f"tests/test_matcher.py."),
        })
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--lines", type=Path, default=CORPUS, help="requirement lines to probe, '-' for stdin")
    args = parser.parse_args(argv)
    probes = probe(load_lines(args.lines))
    for p in probes:
        print(json.dumps({"kind": "line", "line": p.line, "form": p.form, "stopped": p.stopped, "rule": p.rule}))
    found = findings(probes)
    for f in found:
        print(json.dumps(f))
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
