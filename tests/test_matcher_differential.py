"""The single-pass index (analyze/mentions.py) must give exactly the old regex matcher's answers.

tests/oracle/ holds the matcher and observations code as it was before the index. Every function the
pipeline uses is compared on real documents (fixtures, golden cases, and the saved JDs and resumes
in scratch/ when present) and on seeded random texts built from the skill list's own terms with
tricky punctuation and case.

One difference is on purpose: the index reads the six Unicode dashes (U+2010 to U+2015) as "-".
So the oracle always gets the text with its dashes already turned into "-" (same length, so every
offset and line number still lines up), and facts are compared with the same folding applied to the
new side's excerpts, which keep the original characters.

Non-ASCII characters are written as escapes: a Kelvin sign and a capital K look the same.

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
from careerfit.analyze.mentions import HYPHENS
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
            hyphened = unit.translate(HYPHENS)
            assert matcher.scan(unit, ontology) == old_matcher.scan(hyphened, plain), unit
            assert matcher._mention_spans(unit, ontology) == old_matcher._mention_spans(hyphened, plain), unit
            assert (matcher.mention_alternatives(unit, ontology)
                    == old_matcher.mention_alternatives(hyphened, plain)), unit
        hyphened = text.translate(HYPHENS)
        assert matcher.requirement_occurrences(text, ontology) == old_matcher.requirement_occurrences(hyphened, plain)
        assert matcher.requirement_alternatives(text, ontology) == old_matcher.requirement_alternatives(hyphened, plain)
        assert matcher.requirement_evidence(text, ontology) == old_matcher.requirement_evidence(hyphened, plain)


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
    old = old_observations.build_facts(ontology=PLAIN, **{**kwargs, "resume_text": resume.translate(HYPHENS),
                                                            "jd_text": jd.translate(HYPHENS)})
    assert new.model_dump_json().translate(HYPHENS) == old.model_dump_json()


def _random_texts(n: int, seed: int) -> list[str]:
    rng = random.Random(seed)
    terms = [t for name, e in SKILLS.items() for t in (*e.aliases, name)] + [t for name, e in SYMBOLS.items()
                                                                              for t in (*e.aliases, name)]
    pieces = [p for t in terms for p in t.replace("/", " / ").replace(".", " . ").split()]
    glue = [" ", " ", " ", ", ", ". ", "; ", " or ", " and ", " and/or ", "/", ".", "-", "_", "+", "#", "(", ")",
            "\n", "\t", "  ", "\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\u2015",
            "\u0130", "\u0131", "\u017f", "\u212a", "\u00e9", "3", "x"]
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
        hyphened = text.translate(HYPHENS)
        for ontology, plain in ((SKILLS, PLAIN), (SYMBOLS, SYMBOLS)):
            assert matcher.scan(text, ontology) == old_matcher.scan(hyphened, plain), repr(text)
            assert matcher._mention_spans(text, ontology) == old_matcher._mention_spans(hyphened, plain), repr(text)


def test_single_skill_detection_and_first_line_match_the_oracle():
    for text in _random_texts(1_000 if FULL else 150, seed=7) + [t for _, t in DOCS]:
        for name, entry in [*SYMBOLS.items(), *list(SKILLS.items())[:60]]:
            hyphened = text.translate(HYPHENS)
            assert matcher.detect(name, entry, text) == old_matcher.detect(name, entry, hyphened), (name, repr(text))
            assert (matcher.first_mention_line(name, entry, text)
                    == old_matcher.first_mention_line(name, entry, hyphened)), (name, repr(text))


@pytest.mark.parametrize(("text", "expected"), [
    ("Built services in Node.js and C# on .NET", {".net", "c#", "node.js"}),  # "js" never inside "Node.js"
    ("Strong JS skills; js. and js", {"js"}),
    ("asp.net and x.net", {".net"}),            # ".net" after a word character is not a mention
    ("c++ and C++11 and c+++", {"c++"}),
    ("a a a", {"a a"}),                          # its own mentions don't overlap
    ("\u212a8S on Kubernetes", {"k8s"}),           # the Kelvin sign folds to k, as in IGNORECASE
    ("_private and x_y", {"_private"}),
])
def test_tricky_boundaries_agree_with_the_oracle(text, expected):
    present = {name for name, result in matcher.scan(text, SYMBOLS).items() if result != "absent"}
    assert present == expected
    assert matcher.scan(text, SYMBOLS) == old_matcher.scan(text, SYMBOLS)
    assert matcher._mention_spans(text, SYMBOLS) == old_matcher._mention_spans(text, SYMBOLS)


DASHES = ["\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\u2015"]


@pytest.mark.parametrize("dash", DASHES)
def test_unicode_dashes_match_a_hyphen_and_excerpts_keep_them(dash):
    jd = f"Requirements:\n- Built a proof{dash}of{dash}concept and the front{dash}end for it"
    resume = f"Shipped a proof{dash}of{dash}concept"
    facts = observations.build_facts(resume_text=resume, resume_coverage=TXT, resume_source="r", jd_text=jd,
                                     jd_coverage=TXT, jd_source="j", ontology=SKILLS, at=AT, perspective="candidate")
    observed = {o.skill: o for o in facts.skill_observations}
    assert observed["proof of concept"].status.value == "matched"
    assert observed["frontend development"].status.value == "gap"
    assert observed["proof of concept"].jd_evidence.excerpt == f"- Built a proof{dash}of{dash}concept and the front{dash}end for it"
    assert observed["proof of concept"].resume_evidence.excerpt == resume  # verbatim, dash and all


def test_a_nice_to_have_heading_with_non_breaking_hyphens_opens_the_nice_section():
    jd = "Requirements:\n- Python\nNice\u2011to\u2011have:\n- Kubernetes"
    assert matcher.requirement_levels(jd, SKILLS) == {"python": "must", "kubernetes": "nice"}
