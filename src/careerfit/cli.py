"""Composition root for terminal use. The only place that reads the clock."""

import argparse
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from careerfit.analyze.observations import build_facts
from careerfit.analyze.ontology import load_ontology
from careerfit.ingest.document import read_document

DEFAULT_ONTOLOGY = Path(__file__).parent / "ontology" / "skills.yaml"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="careerfit",
        description="Compare a resume with a job description (keyword pass, no LLM).",
    )
    parser.add_argument("--resume", type=Path, required=True, help="resume file (.pdf or .txt)")
    parser.add_argument("--jd", type=Path, required=True, help="job description file (.pdf or .txt)")
    parser.add_argument("-o", "--output", type=Path, help="write facts JSON here (default: print to stdout)")
    parser.add_argument("--perspective", choices=["candidate", "hiring_manager"], default="candidate")
    parser.add_argument("--ontology", type=Path, default=DEFAULT_ONTOLOGY, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    try:
        resume_text, resume_coverage = read_document(args.resume)
        jd_text, jd_coverage = read_document(args.jd)
    except (FileNotFoundError, ValueError) as e:
        print(f"careerfit: {e}", file=sys.stderr)
        return 2

    facts = build_facts(
        resume_text=resume_text,
        resume_coverage=resume_coverage,
        resume_source=str(args.resume),
        jd_text=jd_text,
        jd_coverage=jd_coverage,
        jd_source=str(args.jd),
        ontology=load_ontology(args.ontology),
        at=datetime.now(timezone.utc),
        perspective=args.perspective,
    )
    payload = facts.model_dump_json(indent=2)

    if args.output is None:
        print(payload)
        return 0

    args.output.write_text(payload + "\n", encoding="utf-8")
    counts = Counter(o.status.value for o in facts.skill_observations)
    summary = ", ".join(f"{n} {status}" for status, n in sorted(counts.items()))
    print(f"Wrote {args.output}: {len(facts.skill_observations)} JD skills ({summary})", file=sys.stderr)
    return 0
