"""The matcher must stay fast with a skill list in the thousands (an imported taxonomy).

The old one-regex-per-term matcher took about 430 ms per clause at 16,000 terms, roughly 100 s for
a long JD, against Lambda's 30 s timeout. Best-of-five timings keep a shared CI runner's pauses out.
"""

import random
import time
from datetime import datetime, timezone

from careerfit.analyze.matcher import requirement_alternatives, requirement_evidence
from careerfit.analyze.observations import build_facts
from careerfit.analyze.ontology import Ontology, SkillEntry
from careerfit.facts.schema import Coverage

AT = datetime(2026, 10, 18, tzinfo=timezone.utc)
TXT = Coverage(source_format="txt", pages_total=None, pages_with_text=None, chars_extracted=1, known_blind_spots=())


def _big_ontology(skills: int, rng: random.Random) -> Ontology:
    syllables = ["ka", "zo", "ri", "pel", "tor", "mi", "dax", "lun", "ves", "quo", "bri", "sto"]
    seen: set[str] = set()

    def word() -> str:
        return "".join(rng.choice(syllables) for _ in range(rng.randint(2, 3)))

    def term() -> str:
        while True:
            parts = [word() for _ in range(rng.randint(1, 3))]
            candidate = rng.choice([" ", ".", "/", "-"]).join(parts) if len(parts) > 1 else parts[0]
            if rng.random() < 0.05:
                candidate += rng.choice(["#", "++", ".js"])
            if candidate not in seen:
                seen.add(candidate)
                return candidate

    entries = {}
    for _ in range(skills):
        name = term()
        entries[name] = SkillEntry(aliases=tuple(term() for _ in range(3)), ambiguous=rng.random() < 0.1)
    return Ontology(entries)


def _best_of(times: int, run) -> float:
    best = float("inf")
    for _ in range(times):
        started = time.perf_counter()
        run()
        best = min(best, time.perf_counter() - started)
    return best


def test_a_5000_skill_list_reads_a_long_jd_and_resume_in_time():
    rng = random.Random(20261018)
    ontology = _big_ontology(5_000, rng)
    names = list(ontology)
    filler = ["experience", "with", "strong", "or", "and", "building", "teams", "services", "using", "required"]

    def line() -> str:
        words = [rng.choice(filler) for _ in range(rng.randint(6, 14))]
        for _ in range(rng.randint(1, 3)):
            words.insert(rng.randrange(len(words)), rng.choice(names))
        return "- " + " ".join(words).capitalize() + "."

    jd = "Requirements:\n" + "\n".join(line() for _ in range(80))
    resume = "\n".join(line() for _ in range(120))

    started = time.perf_counter()
    ontology.index  # built once per loaded skill list
    build_seconds = time.perf_counter() - started

    jd_seconds = _best_of(5, lambda: (requirement_evidence(jd, ontology), requirement_alternatives(jd, ontology)))
    facts_seconds = _best_of(3, lambda: build_facts(resume_text=resume, resume_coverage=TXT, resume_source="r",
                                                    jd_text=jd, jd_coverage=TXT, jd_source="j", ontology=ontology,
                                                    at=AT, perspective="candidate"))
    assert build_seconds < 2.0, build_seconds
    assert jd_seconds < 1.5, jd_seconds
    assert facts_seconds < 3.0, facts_seconds


def test_single_skill_detection_stops_at_the_first_conclusive_mention():
    # Copilot review on #29: detect() needs one answer, not every mention of a skill named
    # 100,000 times. Against the full scan, the early exit must win by a wide margin.
    from careerfit.analyze.matcher import detect
    from careerfit.analyze.mentions import entry_index
    entry = SkillEntry(aliases=("k8s",), ambiguous=False)
    text = "k8s, kubernetes " * 100_000
    assert detect("kubernetes", entry, text) == "found"
    early = _best_of(3, lambda: detect("kubernetes", entry, text))
    full = _best_of(3, lambda: entry_index("kubernetes", entry).find(text))
    assert early * 5 < full, (early, full)
