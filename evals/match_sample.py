"""Precision of the imported skills: a sample of their JD mentions for a person to judge.

    uv run python -m evals.match_sample scratch/jds/*.txt --out scratch/match_sample.md
    uv run python -m evals.match_sample --score scratch/match_sample.md

The first form finds every mention of an imported skill (O*NET or ESCO, not hand-curated) in the
requirement sentences of the given JDs, draws a seeded sample stratified by source and by one word
vs several, and writes a sheet. For each mention, read the JD line and write `label: yes` if it
really asks for the named technology, or `label: no` if the match is wrong (an everyday word, a
different product, a generic phrase).

The second form scores a labelled sheet: precision per stratum, and overall as each stratum's
precision weighted by its share of all the mentions (the sheet records each stratum's size). The
sample takes the strata in turn, so a small stratum is over-sampled; the raw share of yes labels
would let it carry a large, noisy one. The import may merge only at 90% or more (the coverage
plan's gate), with every sampled mention labelled and every stratum sampled.
"""

import argparse
import random
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from fractions import Fraction
from datetime import date
from pathlib import Path

from careerfit.analyze.matcher import requirement_sentences
from careerfit.analyze.ontology import Ontology, load_default_ontology
from careerfit.ingest.document import read_document

GATE = Fraction(9, 10)  # exact, so a sheet at exactly 90% passes
SEED = 20261019
_HEADER = re.compile(r"^## \d+\. (?P<skill>.+?) · (?P<source>[a-z+]+) · (?P<words>one word|several words)$")
_LABEL = re.compile(r"^label:\s*(?P<label>[^\s#]*)\s*(#.*)?$", re.IGNORECASE)  # "label: yes  # checked" is fine
_POPULATION = re.compile(r"^- population: (?P<stratum>[a-z+]+ · (?:one word|several words)) = (?P<n>\d+)$")


@dataclass(frozen=True)
class Sample:
    skill: str
    term: str
    source: str
    words: str
    path: str
    line: int
    sentence: str


def mentions(path: str, jd_text: str, ontology: Ontology) -> list[Sample]:
    """Each imported skill mentioned in a requirement sentence, once per JD line."""
    found: dict[tuple[str, int], Sample] = {}
    for line_no, sentence, _clauses in requirement_sentences(jd_text):
        for m in ontology.index.find(sentence):
            sources = ontology[m.skill].sources
            if "curated" in sources or (m.skill, line_no) in found:
                continue
            marked = sentence[:m.start] + "**" + sentence[m.start:m.end] + "**" + sentence[m.end:]
            found[(m.skill, line_no)] = Sample(m.skill, m.term, "+".join(sources),
                                               "one word" if len(m.skill.split()) == 1 else "several words",
                                               path, line_no, marked)
    return list(found.values())


def stratum(s: Sample) -> str:
    return f"{s.source} · {s.words}"


def sample(candidates: list[Sample], n: int, seed: int = SEED) -> list[Sample]:
    """Up to n, spread over the strata (source x one word or several) in turn, seeded."""
    rng = random.Random(seed)
    strata: dict[tuple[str, str], list[Sample]] = defaultdict(list)
    for c in sorted(candidates, key=lambda c: (c.path, c.line, c.skill)):
        strata[(c.source, c.words)].append(c)
    for group in strata.values():
        rng.shuffle(group)
    picked: list[Sample] = []
    while len(picked) < n and any(strata.values()):
        for key in sorted(strata):
            if strata[key] and len(picked) < n:
                picked.append(strata[key].pop())
    return picked


def sheet(picked: list[Sample], candidates: list[Sample], jds: int) -> str:
    population: dict[str, int] = defaultdict(int)
    for c in candidates:
        population[stratum(c)] += 1
    lines = [f"# Match sample, {date.today().isoformat()}: {len(picked)} of {len(candidates)} mentions of imported "
             f"skills in {jds} JDs (seed {SEED})", "",
             "For each mention: does this JD line really ask for the named technology? Write `label: yes` or "
             "`label: no`. Then: `uv run python -m evals.match_sample --score <this file>`.", "",
             "All the mentions, per stratum (the score weights each stratum by these):", "",
             *(f"- population: {key} = {n}" for key, n in sorted(population.items())), ""]
    for i, s in enumerate(picked, start=1):
        lines += [f"## {i}. {s.skill} · {s.source} · {s.words}", f"`{s.path}` line {s.line}, matched `{s.term}`",
                  "", f"> {s.sentence}", "", "label:", ""]
    return "\n".join(lines)


def score(text: str) -> tuple[dict[str, tuple[int, int]], int]:
    """(yes, labelled) per stratum and overall ("all"), and how many mentions are still unlabelled.

    Every mention counts as unlabelled until a valid yes or no follows its header: a missing or
    malformed label line can never make an incomplete sheet pass."""
    counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    unlabelled = 0
    stratum = None
    for line in text.splitlines():
        if header := _HEADER.match(line.strip()):
            unlabelled += 1  # until its label is read
            stratum = f"{header['source']} · {header['words']}"
        elif stratum and (label := _LABEL.match(line.strip())):
            value = label["label"].lower()
            if value in ("yes", "no"):
                unlabelled -= 1
                for key in (stratum, "all"):
                    counts[key][0] += value == "yes"
                    counts[key][1] += 1
            stratum = None
    return {k: (yes, n) for k, (yes, n) in counts.items()}, unlabelled


def populations(text: str) -> dict[str, int]:
    """Each stratum's size: how many mentions of all, not just the sampled ones, fall in it."""
    return {m["stratum"]: int(m["n"]) for line in text.splitlines() if (m := _POPULATION.match(line.strip()))}


def weighted_precision(counts: dict[str, tuple[int, int]], population: dict[str, int]) -> Fraction | None:
    """Each stratum's precision times its share of all the mentions. None when that can't be known:
    a stratum with mentions but none labelled, or labels in a stratum the sheet gives no size for.

    Exact: in floats, strata of 30 and 60 at 9/10 each sum to 0.8999999999999999 and fail the gate."""
    total = sum(population.values())
    strata = {k for k in counts if k != "all"}
    if not total or not strata <= set(population):
        return None
    if any(n and counts.get(key, (0, 0))[1] == 0 for key, n in population.items()):
        return None
    return sum((Fraction(n * counts[key][0], total * counts[key][1]) for key, n in population.items() if n),
               Fraction(0))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("jds", nargs="*", type=Path, help="job descriptions (.txt or .pdf)")
    parser.add_argument("--n", type=int, default=100)
    parser.add_argument("--out", type=Path, default=Path("scratch/match_sample.md"))
    parser.add_argument("--score", type=Path, help="score a labelled sheet instead")
    args = parser.parse_args(argv)

    if args.score:
        text = args.score.read_text(encoding="utf-8")
        counts, unlabelled = score(text)
        population = populations(text)
        for key in sorted(counts, key=lambda k: (k != "all", k)):
            yes, n = counts[key]
            size = "" if key == "all" else f" of {population.get(key, '?')}"
            print(f"{key:<26} {yes}/{n}{size} = {yes / n:.0%}" if n else f"{key:<26} none labelled")
        weighted = weighted_precision(counts, population)
        print(f"weighted by stratum size: {'unknown' if weighted is None else f'{float(weighted):.0%}'}")
        passed = unlabelled == 0 and weighted is not None and weighted >= GATE
        print(f"{unlabelled} unlabelled. Gate {float(GATE):.0%}: {'PASS' if passed else 'FAIL'}")
        return 0 if passed else 1

    if not args.jds:
        parser.error("give the JDs to sample from, or --score a sheet")
    ontology = load_default_ontology()
    candidates = []
    for path in args.jds:
        text, _ = read_document(path)
        candidates += mentions(str(path), text, ontology)
    picked = sample(candidates, args.n)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(sheet(picked, candidates, len(args.jds)), encoding="utf-8")
    print(f"{len(picked)} of {len(candidates)} mentions written to {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
