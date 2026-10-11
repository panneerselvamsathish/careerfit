"""Composition root for terminal use. The only place that reads the clock."""

import argparse
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from careerfit.analyze.observations import build_facts
from careerfit.analyze.ontology import load_ontology
from careerfit.ingest.document import read_document
from careerfit.judge.scorer import judge_facts
from careerfit.cache import CachingLLM
from careerfit.judge.llm import LLMConfigError, make_llm

DEFAULT_ONTOLOGY = Path(__file__).parent / "ontology" / "skills.yaml"
CACHE_DIR = Path(".cache") / "judge"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="careerfit",
        description="Compare a resume with a job description. Keyword pass by default; --deep adds the LLM judge.",
    )
    parser.add_argument("--resume", type=Path, required=True, help="resume file (.pdf or .txt)")
    parser.add_argument("--jd", type=Path, required=True, help="job description file (.pdf or .txt)")
    parser.add_argument("-o", "--output", type=Path, help="write facts JSON here (default: print to stdout)")
    parser.add_argument("--perspective", choices=["candidate", "hiring_manager"], default="candidate")
    parser.add_argument("--deep", action="store_true", help="resolve ambiguous skills and plan learning with the LLM judge")
    parser.add_argument("--fresh", action="store_true", help="with --deep: ignore cached judge answers")
    parser.add_argument("--ontology", type=Path, default=DEFAULT_ONTOLOGY, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    try:
        resume_text, resume_coverage = read_document(args.resume)
        jd_text, jd_coverage = read_document(args.jd)
    except (OSError, ValueError) as e:
        print(f"careerfit: {e}", file=sys.stderr)
        return 2

    at = datetime.now(timezone.utc)
    ontology = load_ontology(args.ontology)
    facts = build_facts(
        resume_text=resume_text,
        resume_coverage=resume_coverage,
        resume_source=str(args.resume),
        jd_text=jd_text,
        jd_coverage=jd_coverage,
        jd_source=str(args.jd),
        ontology=ontology,
        at=at,
        perspective=args.perspective,
    )
    if args.deep:
        try:
            llm, model = make_llm(os.environ)
        except LLMConfigError as e:
            print(f"careerfit: {e}", file=sys.stderr)
            return 2
        if not args.fresh:
            llm = CachingLLM(llm, CACHE_DIR)
        facts = judge_facts(facts, resume_text=resume_text, jd_text=jd_text, llm=llm, model=model, at=at,
                            ontology=ontology)
        for failure in facts.judge.failures if facts.judge else ():
            print(f"careerfit: judge warning: {failure}", file=sys.stderr)
    payload = facts.model_dump_json(indent=2)

    if args.output is None:
        print(payload)
        return 0

    try:
        args.output.write_text(payload + "\n", encoding="utf-8")
    except OSError as e:
        print(f"careerfit: could not write {args.output}: {e}", file=sys.stderr)
        return 2
    counts = Counter(o.status.value for o in facts.skill_observations)
    summary = ", ".join(f"{n} {status}" for status, n in sorted(counts.items()))
    print(f"Wrote {args.output}: {len(facts.skill_observations)} JD skills ({summary})", file=sys.stderr)
    if facts.judge is not None:
        fit = f"fit {facts.fit_score.overall:.0%}" if facts.fit_score else "no fit score"
        dismissed = len(facts.judge.dismissed_skills)
        print(f"Judge ({facts.judge.model}): {fit}, {dismissed} dismissed, {len(facts.learning_steps)} learning steps",
              file=sys.stderr)
        others = [m for m in facts.judge.served_by if m != facts.judge.model]
        if others:
            print(f"careerfit: judge answers were served by a fallback model: {', '.join(others)}", file=sys.stderr)
    return 0
