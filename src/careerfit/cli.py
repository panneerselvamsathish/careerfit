"""Composition root for terminal use. The only place that reads the clock."""

import argparse
import os
import re
import sys
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from careerfit.analyze.observations import build_facts
from careerfit.analyze.ontology import load_ontology
from careerfit.ingest.document import read_document
from careerfit.judge.scorer import judge_facts
from careerfit.cache import CachingLLM
from careerfit.judge.llm import LLMConfigError, make_llm
from careerfit.report import render_markdown

DEFAULT_ONTOLOGY = Path(__file__).parent / "ontology" / "skills.yaml"
CACHE_DIR = Path(".cache") / "judge"


def _same_file(a: Path, b: Path) -> bool:
    # Conservative on purpose: macOS and Windows treat names that differ only in case or Unicode
    # normalisation as one file, even before either exists, so such names are refused everywhere.
    if _path_key(a) == _path_key(b):
        return True
    try:
        return a.samefile(b)  # hard links
    except OSError:  # one of them doesn't exist yet
        return False


def _same_model(requested: str, served: str) -> bool:
    """A Bedrock ID ("global.anthropic.claude-haiku-4-5-20251001-v1:0") or an alias ("claude-haiku-4-5")
    names the model the response reports as "claude-haiku-4-5-20251001"; neither is a fallback."""
    base = re.sub(r"-v\d+(:\d+)?$", "", requested.rsplit("anthropic.", 1)[-1])
    return re.fullmatch(re.escape(base) + r"(-\d{8})?", served) is not None


def _path_key(path: Path) -> str:
    return unicodedata.normalize("NFC", str(path.resolve())).casefold()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="careerfit",
        description="Compare a resume with a job description. Keyword pass by default; --deep adds the LLM judge.",
    )
    parser.add_argument("--resume", type=Path, required=True, help="resume file (.pdf or .txt)")
    parser.add_argument("--jd", type=Path, required=True, help="job description file (.pdf or .txt)")
    parser.add_argument("-o", "--output", type=Path, help="write facts JSON here")
    parser.add_argument("--report", type=Path, help="write a Markdown report for the chosen perspective here")
    parser.add_argument("--perspective", choices=["candidate", "hiring_manager"], default="candidate")
    parser.add_argument("--deep", action="store_true", help="resolve ambiguous skills and plan learning with the LLM judge")
    parser.add_argument("--fresh", action="store_true", help="with --deep: ignore cached judge answers")
    parser.add_argument("--ontology", type=Path, default=DEFAULT_ONTOLOGY, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.output is not None and args.report is not None and _same_file(args.output, args.report):
        print("careerfit: -o and --report must be different files", file=sys.stderr)
        return 2

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

    if args.output is None and args.report is None:
        print(payload)
        return 0

    for path, text in ((args.output, payload + "\n"), (args.report, render_markdown(facts))):
        if path is None:
            continue
        try:
            path.write_text(text, encoding="utf-8")
        except OSError as e:
            print(f"careerfit: could not write {path}: {e}", file=sys.stderr)
            return 2
    counts = Counter(o.status.value for o in facts.skill_observations)
    summary = ", ".join(f"{n} {status}" for status, n in sorted(counts.items()))
    written = " and ".join(str(p) for p in (args.output, args.report) if p is not None)
    print(f"Wrote {written}: {len(facts.skill_observations)} JD skills ({summary})", file=sys.stderr)
    if facts.judge is not None:
        fit = f"fit {facts.fit_score.overall:.0%}" if facts.fit_score else "no fit score"
        dismissed = len(facts.judge.dismissed_skills)
        print(f"Judge ({facts.judge.model}): {fit}, {dismissed} dismissed, {len(facts.learning_steps)} learning steps",
              file=sys.stderr)
        others = [m for m in facts.judge.served_by if not _same_model(facts.judge.model, m)]
        if others:
            print(f"careerfit: judge answers were served by a fallback model: {', '.join(others)}", file=sys.stderr)
    return 0
