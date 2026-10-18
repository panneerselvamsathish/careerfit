"""The single-pass index (analyze/mentions.py) must give exactly the old regex matcher's answers.

tests/oracle/ holds the matcher and observations code as it was before the index. Every function the
pipeline uses is compared on real documents (fixtures, golden cases, and the saved JDs and resumes
in scratch/ when present) and on seeded random texts built from the skill list's own terms with
tricky punctuation and case.

By default it uses the fixtures, the golden cases and 800 random texts. Before merging a matcher
change, run the full comparison: the saved JDs and resumes in scratch/ (every resume with every JD)
and 20,000 random texts:

    CAREERFIT_DIFF_FULL=1 uv run pytest tests/test_matcher_differential.py
"""

import os
import random
from datetime import datetime, timezone
from pathlib import Path

import pytest

from careerfit.analyze import matcher, observations
from careerfit.analyze.ontology import SkillEntry, load_ontology
from careerfit.facts.schema import Coverage
from careerfit.ingest.document import read_document
from tests.oracle import matcher as old_matcher
from tests.oracle import observations as old_observations

ROOT = Path(__file__).parent.parent
FULL = os.environ.get("CAREERFIT_DIFF_FULL") == "1"
SKILLS = load_ontology(ROOT / "src" / "careerfit" / "ontology" / "skills.yaml")
PLAIN = dict(SKILLS)  # the oracle takes a plain dict, as before
AT = datetime(2026, 10, 18, tzinfo=timezone.utc)
TXT = Coverage(source_format="txt", pages_total=None, pages_with_text=None, chars_extracted=1, known_blind_spots=())
# Symbol terms the curated list doesn't have yet, so their boundaries are tested too.
SYMBOLS = {
    ".net": SkillEntry(aliases=("dotnet", "asp.net"), ambiguous=False),
    "c#": SkillEntry(aliases=("c sharp",), ambiguous=False),
    "c++": SkillEntry(aliases=("cpp",), ambiguous=False),
    "node.js": SkillEntry(aliases=("nodejs", "node"), ambiguous=True),
    "js": SkillEntry(aliases=("javascript",), ambiguous=True),
    "a a": SkillEntry(aliases=(), ambiguous=False),  # overlaps itself in "a a a"
    "k8s": SkillEntry(aliases=("kubernetes",), ambiguous=False),
    "_private": SkillEntry(aliases=("x_y",), ambiguous=False),
}


def _documents() -> list[tuple[str, str]]:
    paths = [*sorted((ROOT / "fixtures").glob("*.txt")), *sorted((ROOT / "evals" / "golden" / "cases").rglob("*.*"))]
    if FULL:  # real documents, kept out of the repo (gitignored scratch/)
        paths += [*sorted((ROOT / "scratch" / "jds").glob("*.txt")), *sorted((ROOT / "scratch").glob("resume*.txt"))]
    docs = []
    for path in paths:
        try:
            text, _ = read_document(path)
        except (OSError, ValueError):
            continue
        if text.strip():
            docs.append((str(path.relative_to(ROOT)), text))
    return docs


DOCS = _documents()


def _units(text: str) -> list[str]:
    """The pieces the pipeline actually scans: whole text, lines, sentences, clauses."""
    units = [text, *text.splitlines()]
    for _line, sentence, levelled in old_matcher.requirement_sentences(text):
        units.append(sentence)
        units.extend(clause for _level, clause in levelled)
    return units


@pytest.mark.parametrize(("name", "text"), DOCS, ids=[d[0] for d in DOCS])
def test_scan_spans_and_alternatives_match_the_oracle_on_documents(name, text):
    for ontology, plain in ((SKILLS, PLAIN), (SYMBOLS, SYMBOLS)):
        for unit in _units(text):
            assert matcher.scan(unit, ontology) == old_matcher.scan(unit, plain), unit
            assert matcher._mention_spans(unit, ontology) == old_matcher._mention_spans(unit, plain), unit
            assert matcher.mention_alternatives(unit, ontology) == old_matcher.mention_alternatives(unit, plain), unit
        assert matcher.requirement_occurrences(text, ontology) == old_matcher.requirement_occurrences(text, plain)
        assert matcher.requirement_alternatives(text, ontology) == old_matcher.requirement_alternatives(text, plain)
        assert matcher.requirement_evidence(text, ontology) == old_matcher.requirement_evidence(text, plain)


def _pairs() -> list[tuple[str, str, str]]:
    resumes = [(n, t) for n, t in DOCS if "resume" in n]
    jds = [(n, t) for n, t in DOCS if "resume" not in n]
    return [(f"{rn} × {jn}", rt, jt) for rn, rt in resumes for jn, jt in jds]


PAIRS = _pairs()


@pytest.mark.parametrize(("name", "resume", "jd"), PAIRS, ids=[p[0] for p in PAIRS])
def test_facts_match_the_oracle_on_every_resume_and_jd_pair(name, resume, jd):
    kwargs = dict(resume_text=resume, resume_coverage=TXT, resume_source="r", jd_text=jd, jd_coverage=TXT,
                  jd_source="j", at=AT, perspective="candidate")
    new = observations.build_facts(ontology=SKILLS, **kwargs)
    old = old_observations.build_facts(ontology=PLAIN, **kwargs)
    assert new.model_dump() == old.model_dump()


def _random_texts(n: int, seed: int) -> list[str]:
    rng = random.Random(seed)
    terms = [t for name, e in SKILLS.items() for t in (*e.aliases, name)] + [t for name, e in SYMBOLS.items()
                                                                              for t in (*e.aliases, name)]
    pieces = [p for t in terms for p in t.replace("/", " / ").replace(".", " . ").split()]
    glue = [" ", " ", " ", ", ", ". ", "; ", " or ", " and ", " and/or ", "/", ".", "-", "_", "+", "#", "(", ")",
            "\n", "\t", "  ", "‐", "‑", "–", "—", "İ", "ı", "ſ", "K", "é", "3", "x"]
    cases = [str.lower, str.upper, str.title, lambda s: s]
    texts = []
    for _ in range(n):
        parts = []
        for _ in range(rng.randint(1, 12)):
            parts.append(rng.choice(cases)(rng.choice(terms if rng.random() < 0.6 else pieces)))
            parts.append(rng.choice(glue))
        texts.append("".join(parts))
    return texts


RANDOM_N = 20_000 if FULL else 800


def test_random_texts_match_the_oracle():
    for text in _random_texts(RANDOM_N, seed=20261018):
        for ontology, plain in ((SKILLS, PLAIN), (SYMBOLS, SYMBOLS)):
            assert matcher.scan(text, ontology) == old_matcher.scan(text, plain), repr(text)
            assert matcher._mention_spans(text, ontology) == old_matcher._mention_spans(text, plain), repr(text)


def test_single_skill_detection_and_first_line_match_the_oracle():
    for text in _random_texts(1_000 if FULL else 150, seed=7) + [t for _, t in DOCS]:
        for name, entry in [*SYMBOLS.items(), *list(SKILLS.items())[:60]]:
            assert matcher.detect(name, entry, text) == old_matcher.detect(name, entry, text), (name, repr(text))
            assert (matcher.first_mention_line(name, entry, text)
                    == old_matcher.first_mention_line(name, entry, text)), (name, repr(text))


@pytest.mark.parametrize(("text", "expected"), [
    ("Built services in Node.js and C# on .NET", {".net", "c#", "node.js"}),  # "js" never inside "Node.js"
    ("Strong JS skills; js. and js", {"js"}),
    ("asp.net and x.net", {".net"}),            # ".net" after a word character is not a mention
    ("c++ and C++11 and c+++", {"c++"}),
    ("a a a", {"a a"}),                          # its own mentions don't overlap
    ("K8S on Kubernetes", {"k8s"}),              # the Kelvin sign folds to k, as in IGNORECASE
    ("_private and x_y", {"_private"}),
])
def test_tricky_boundaries_agree_with_the_oracle(text, expected):
    present = {name for name, result in matcher.scan(text, SYMBOLS).items() if result != "absent"}
    assert present == expected
    assert matcher.scan(text, SYMBOLS) == old_matcher.scan(text, SYMBOLS)
    assert matcher._mention_spans(text, SYMBOLS) == old_matcher._mention_spans(text, SYMBOLS)
