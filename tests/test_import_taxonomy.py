"""scripts/import_taxonomy.py: the cleaning and drop rules, and the committed generated files."""

import importlib.util
from pathlib import Path

import pytest
import yaml

from careerfit.analyze.ontology import CURATED_SKILLS, IMPORTED_SKILLS, SkillEntry, load_ontology

ROOT = Path(__file__).parent.parent
_spec = importlib.util.spec_from_file_location("import_taxonomy", ROOT / "scripts" / "import_taxonomy.py")
importer = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(importer)

WORDS = {"word", "team", "cloud", "platform", "spark", "chef", "shiny", "switch", "manager", "experience"}


@pytest.mark.parametrize(("example", "name", "aliases"), [
    ("Learning management system LMS", "lms", {"learning management system"}),       # spelled out at the end
    ("Amazon Web Services AWS CloudFormation", "aws cloudformation", set()),          # spelled out in the middle
    ("Adobe Experience Manager (AEM)", "adobe experience manager", {"aem"}),           # parenthetical acronym
    ("EpicCare Electronic Medical Records (EMR) software", "epiccare electronic medical records", {"emr"}),
    ("Database design software", "database design", set()),
    ("Neo4j", "neo4j", set()),
])
def test_onet_names_are_cleaned(example, name, aliases):
    assert importer.clean_onet(example) == (name, aliases)


def test_esco_tags_in_parentheses_are_dropped():
    assert importer.clean_esco("Python (computer programming)") == "python"


@pytest.mark.parametrize(("token", "expected"), [
    ("team", True), ("teams", True), ("switches", True), ("switched", True), ("switching", True),
    ("neo4j", False), ("photoshop", False),
])
def test_everyday_words_include_their_inflected_forms(token, expected):
    words = WORDS | {"switch"}
    assert importer.everyday(token, words) is expected


@pytest.mark.parametrize(("name", "alias"), [
    ("adobe photoshop", "photoshop"),
    ("microsoft sql server", "sql server"),       # "sql" isn't an everyday word
    ("microsoft word", None),                     # would match "word" in any JD
    ("microsoft teams", None),                    # "teams" is "team", inflected
    ("google cloud platform", None),              # every word is everyday
])
def test_a_vendor_prefix_adds_the_rest_as_an_alias_only_if_it_is_distinctive(name, alias):
    assert importer.vendor_alias(name, WORDS) == alias


def _row(example, soc="15-1252.00", hot="N", demand="N", element="Development environment software"):
    return {"O*NET-SOC Code": soc, "Title": "t", "Workplace Example": example, "Element ID": "x",
            "Element Name": element, "Hot Technology": hot, "In Demand": demand}


CURATED = {"kubernetes": SkillEntry(aliases=("k8s",), ambiguous=False),
           "pl/sql": SkillEntry(aliases=("plsql",), ambiguous=False)}


def _build(onet=(), esco=(), overrides=None):
    return importer.build(list(onet), list(esco), CURATED, WORDS, overrides or {})


def test_scope_categories_everyday_words_and_curated_collisions():
    skills, report = _build([
        _row("Neo4j"),
        _row("Some accounting tool", soc="13-2011.00"),                  # not a computer occupation...
        _row("Hot accounting tool", soc="13-2011.00", hot="Y"),          # ...unless Hot or In Demand
        _row("Development environment software"),                        # O*NET's own category label
        _row("Spark"),                                                   # everyday word
        _row("Kubernetes"),                                              # curated name
        _row("Oracle PL/SQL"),                                           # its alias "pl/sql" is curated
        _row("Database software"),                                       # "database": a modern everyday word
        _row("Ansible software"),                                        # a product named "X software"
    ])
    assert sorted(skills) == ["ansible", "hot accounting tool", "neo4j", "oracle pl/sql"]
    assert report.counts["dropped_everyday_word"] == 2  # spark, database
    assert skills["oracle pl/sql"].aliases == set()
    assert report.counts["dropped_curated_collision"] == 1
    assert "oracle pl/sql: pl/sql" in report.review["alias_dropped_curated_collision"]


def test_overrides_keep_drop_and_allow():
    overrides = {"keep": ["spark"], "drop": ["neo4j"], "alias_allow": {"spark": ["apache spark engine"]}}
    skills, _ = _build([_row("Spark"), _row("Neo4j")], overrides=overrides)
    assert sorted(skills) == ["spark"]
    assert skills["spark"].aliases == {"apache spark engine"}


def test_esco_aliases_need_o_net_to_agree_and_abstract_concepts_are_dropped():
    esco = [
        {"skillType": "knowledge", "preferredLabel": "Neo4j (graph database)", "altLabels": "neo4j graph | Neo Prog"},
        {"skillType": "knowledge", "preferredLabel": "concepts of telecommunications", "altLabels": ""},
        {"skillType": "skill/competence", "preferredLabel": "use Neo4j", "altLabels": ""},
    ]
    skills, report = _build([_row("Neo4j graph")], esco)
    # O*NET names "neo4j graph" too: one tool, so the two merge under ESCO's name.
    assert "neo4j graph" not in skills
    assert (skills["neo4j"].aliases, skills["neo4j"].sources) == ({"neo4j graph"}, {"onet", "esco"})
    assert "neo prog" not in {a for s in skills.values() for a in s.aliases}  # O*NET doesn't have it
    assert "concepts of telecommunications" not in skills
    assert report.counts["esco_not_knowledge"] == 1


def test_a_vendor_duplicate_merges_into_the_plain_name_unless_two_vendors_claim_it():
    esco = [{"skillType": "knowledge", "preferredLabel": "Hadoop", "altLabels": ""},
            {"skillType": "knowledge", "preferredLabel": "iOS", "altLabels": ""}]
    skills, _ = _build([_row("Apache Hadoop"), _row("Apple iOS"), _row("Cisco IOS")], esco)
    assert "apache hadoop" not in skills and skills["hadoop"].aliases == {"apache hadoop"}
    assert skills["hadoop"].sources == {"onet", "esco"}
    assert {"apple ios", "cisco ios", "ios"} <= set(skills)
    assert all("ios" not in skills[n].aliases for n in ("apple ios", "cisco ios"))


def test_rendered_skills_load_next_to_the_curated_list(tmp_path):
    skills, _ = _build([_row("Neo4j"), _row("Adobe Photoshop")])
    curated = tmp_path / "skills.yaml"
    curated.write_text("kubernetes:\n  aliases: [k8s]\n  ambiguous: false\n", encoding="utf-8")
    imported = tmp_path / "skills_imported.yaml"
    imported.write_text(importer.render_skills(skills), encoding="utf-8")
    merged = load_ontology(curated, imported=imported)
    assert list(merged) == ["kubernetes", "adobe photoshop", "neo4j"]
    assert merged["adobe photoshop"].aliases == ("photoshop",)
    assert merged["neo4j"].sources == ("onet",)


# ---- the committed generated files ----

IMPORTED = yaml.safe_load(IMPORTED_SKILLS.read_text(encoding="utf-8"))
MANIFEST = yaml.safe_load((IMPORTED_SKILLS.parent / "IMPORT_MANIFEST.yaml").read_text(encoding="utf-8"))


def test_the_generated_file_is_current_with_the_curated_list():
    # Nothing imported may collide with skills.yaml; if it does, the curated list grew after the last
    # import: regenerate with scripts/import_taxonomy.py.
    curated = load_ontology(CURATED_SKILLS)
    merged = load_ontology(CURATED_SKILLS, imported=IMPORTED_SKILLS)
    assert len(merged) == len(curated) + len(IMPORTED)


def test_generated_entries_are_lowercase_ascii_without_implications():
    for name, entry in IMPORTED.items():
        assert name == name.lower() and name.isascii(), name
        assert all(a == a.lower() and a.isascii() for a in entry["aliases"]), name
        assert "implies" not in entry and set(entry["sources"]) <= {"onet", "esco"}, name


def test_the_manifest_counts_match_the_generated_file():
    assert MANIFEST["counts"]["imported_skills"] == len(IMPORTED)
    assert MANIFEST["counts"]["imported_aliases"] == sum(len(e["aliases"]) for e in IMPORTED.values())
