"""evals/ontology_diff.py and evals/match_sample.py: label stubs never carry careerfit's verdict, and
the precision sample covers only imported skills and scores honestly."""

from fractions import Fraction

from careerfit.analyze.ontology import Ontology, SkillEntry, load_default_ontology
from evals import match_sample, ontology_diff
from evals.harness import case_facts

CASE = {"case": "sample", "doc_type": "txt", "resume": "fixtures/resume.txt", "jd": "fixtures/jd.txt",
        "expected": {"python": {"status": "matched", "requirement": "must"}}, "not_observed": ["docker"]}


def test_label_stubs_cover_only_unlabelled_skills_and_never_carry_a_verdict():
    ontology = load_default_ontology()
    facts = case_facts(CASE, ontology)
    names = {o.skill for o in ontology_diff.unlabelled(CASE, facts)}
    assert "python" not in names and "docker" not in names and "relational database" in names
    lines = ontology_diff.stubs(CASE, facts, {n: e.sources for n, e in ontology.items()})
    stub = next(line for line in lines if line.startswith("  relational database:"))
    assert "{status: ?, requirement: ?}" in stub
    statuses = ("matched", "gap", "unresolvable", "alternative_met", "not_assessed", "partial")
    assert not any(f"status: {s}" in line for line in lines for s in statuses)  # labelled from the documents


ONTOLOGY = Ontology({
    "python": SkillEntry(aliases=(), ambiguous=False),                                       # curated
    "neo4j": SkillEntry(aliases=(), ambiguous=False, sources=("onet",)),
    "graph analytics": SkillEntry(aliases=(), ambiguous=False, sources=("esco",)),
    "apache spark engine": SkillEntry(aliases=("spark engine",), ambiguous=False, sources=("onet", "esco")),
})
JD = "Requirements:\n- Python and Neo4j, Neo4j again\n- Graph analytics on the Spark engine\nBenefits\n- Neo4j socks"


def test_the_sample_takes_imported_skills_from_requirement_lines_once_per_line():
    found = match_sample.mentions("jd.txt", JD, ONTOLOGY)
    assert sorted((s.skill, s.line) for s in found) == [("apache spark engine", 3), ("graph analytics", 3),
                                                         ("neo4j", 2)]           # not python, not benefits
    neo4j = next(s for s in found if s.skill == "neo4j")
    assert (neo4j.source, neo4j.words) == ("onet", "one word")
    assert "**Neo4j**" in neo4j.sentence
    assert next(s for s in found if s.skill == "apache spark engine").term == "spark engine"


def test_the_sample_is_seeded_and_spreads_over_the_strata():
    found = match_sample.mentions("jd.txt", JD, ONTOLOGY)
    first, again = match_sample.sample(found, 2), match_sample.sample(found, 2)
    assert first == again
    assert len({(s.source, s.words) for s in first}) == 2  # two strata, not two from one


def test_scoring_reports_precision_unlabelled_mentions_and_the_gate():
    found = match_sample.mentions("jd.txt", JD, ONTOLOGY)
    text = match_sample.sheet(found, found, 1)
    counts, unlabelled = match_sample.score(text)
    assert (counts, unlabelled) == ({}, 3)
    labels = iter(["yes", "yes", "no"])
    text = "\n".join(f"label: {next(labels)}" if line == "label:" else line for line in text.splitlines())
    counts, unlabelled = match_sample.score(text)
    assert counts["all"] == (2, 3) and unlabelled == 0
    path_ok = text.replace("label: no", "label: yes")
    assert match_sample.score(path_ok)[0]["all"] == (3, 3)


def test_the_gate_fails_below_90_percent_or_with_unlabelled_mentions(tmp_path):
    found = match_sample.mentions("jd.txt", JD, ONTOLOGY)
    sheet = tmp_path / "sample.md"
    sheet.write_text(match_sample.sheet(found, found, 1).replace("label:", "label: yes", 2), encoding="utf-8")
    assert match_sample.main(["--score", str(sheet)]) == 1          # one still unlabelled
    sheet.write_text(match_sample.sheet(found, found, 1).replace("label:", "label: yes"), encoding="utf-8")
    assert match_sample.main(["--score", str(sheet)]) == 0


def test_a_mention_without_a_valid_label_stays_unlabelled():
    # Copilot review on #31: a missing label line, or one the parser didn't read, used to vanish,
    # so a half-labelled sheet could pass the gate.
    found = match_sample.mentions("jd.txt", JD, ONTOLOGY)
    lines = match_sample.sheet(found, found, 1).splitlines()
    label_rows = [i for i, line in enumerate(lines) if line == "label:"]
    assert len(label_rows) == 3
    lines[label_rows[0]] = "label: yes"
    lines[label_rows[1]] = ""                          # no label line at all
    lines[label_rows[2]] = "label: yes  # checked"     # a trailing comment is fine
    counts, unlabelled = match_sample.score("\n".join(lines))
    assert counts["all"] == (2, 2) and unlabelled == 1
    cut = "\n".join(lines[:label_rows[2]])            # the last mention's label cut off at the end
    assert match_sample.score(cut)[1] == 2


def test_the_gate_weights_each_stratum_by_its_size():
    # Copilot review on #31: the sample takes the strata in turn, so a small stratum is over-sampled,
    # and the raw share of yes labels let it hide a large stratum's errors.
    def header(i, source, words):
        return [f"## {i}. skill{i} · {source} · {words}", "", "> line", ""]
    lines = ["- population: onet · one word = 90", "- population: esco · several words = 10", ""]
    for i in range(1, 3):                                            # big stratum: 1 of 2 right
        lines += header(i, "onet", "one word") + [f"label: {'yes' if i == 1 else 'no'}", ""]
    for i in range(3, 11):                                           # small stratum: 8 of 8 right
        lines += header(i, "esco", "several words") + ["label: yes", ""]
    text = "\n".join(lines)
    counts, unlabelled = match_sample.score(text)
    assert counts["all"] == (9, 10) and unlabelled == 0                 # 90% unweighted: would pass
    weighted = match_sample.weighted_precision(counts, match_sample.populations(text))
    assert weighted == Fraction(9, 10) * Fraction(1, 2) + Fraction(1, 10)   # 55%: fails
    assert match_sample.weighted_precision(counts, {"onet · one word": 90}) is None   # a stratum without a size
    unsampled = {**match_sample.populations(text), "onet+esco · one word": 5}
    assert match_sample.weighted_precision(counts, unsampled) is None   # mentions, none labelled


def test_the_sheet_records_every_stratum_size(tmp_path):
    found = match_sample.mentions("jd.txt", JD, ONTOLOGY)
    text = match_sample.sheet(match_sample.sample(found, 1), found, 1)
    assert match_sample.populations(text) == {"esco · several words": 1, "onet · one word": 1,
                                              "onet+esco · several words": 1}
    sheet = tmp_path / "sample.md"
    sheet.write_text(text.replace("label:", "label: yes"), encoding="utf-8")
    assert match_sample.main(["--score", str(sheet)]) == 1               # two strata not sampled at all


def test_exactly_90_percent_passes_the_gate(tmp_path):
    # Copilot review on #31: in floats, strata of 30 and 60 at 9/10 each summed to 0.8999999999999999,
    # printed as 90% and failed.
    lines = ["- population: onet · one word = 30", "- population: esco · one word = 60", ""]
    for i in range(1, 21):
        source = "onet" if i <= 10 else "esco"
        lines += [f"## {i}. skill{i} · {source} · one word", "", "> line", "",
                  f"label: {'no' if i in (1, 11) else 'yes'}", ""]
    text = "\n".join(lines)
    counts, _ = match_sample.score(text)
    assert match_sample.weighted_precision(counts, match_sample.populations(text)) == match_sample.GATE
    sheet = tmp_path / "sample.md"
    sheet.write_text(text, encoding="utf-8")
    assert match_sample.main(["--score", str(sheet)]) == 0


def test_the_sample_skips_a_name_inside_a_longer_skill_name():
    # Copilot review on #31: "Adobe Photoshop Lightroom" asks for Lightroom only, but the sample took
    # Photoshop too, so labelling it "no" failed a correct result.
    ontology = Ontology({
        "adobe photoshop": SkillEntry(aliases=("photoshop",), ambiguous=False, sources=("onet",)),
        "adobe photoshop lightroom": SkillEntry(aliases=(), ambiguous=False, sources=("onet",)),
    })
    jd = "Requirements:\n- Adobe Photoshop Lightroom\n- Photoshop, but Lightroom is a plus"
    found = match_sample.mentions("jd.txt", jd, ontology)
    assert sorted((s.skill, s.line) for s in found) == [("adobe photoshop", 3), ("adobe photoshop lightroom", 2)]
    assert "**Photoshop**" in next(s.sentence for s in found if s.line == 3)
