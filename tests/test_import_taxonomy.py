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
    # Copilot review on #31: the alias keeps the qualifiers, never a bare "enterprise edition".
    ("Oracle Java Enterprise Edition EE", "oracle java ee", {"oracle java enterprise edition"}),
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
    ("sap erp", None),                            # a generic acronym names a kind of system, not SAP's
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


def test_esco_aliases_need_a_person_to_allow_them_and_abstract_concepts_are_dropped():
    # Copilot review on #31: ESCO lists related technologies as alternative labels ("computer
    # programming": Lua, AWK, PowerShell). Accepting them because O*NET has the term made distinct
    # tools interchangeable and swallowed their own entries.
    esco = [
        {"skillType": "knowledge", "preferredLabel": "computer programming", "altLabels": "Lua | AWK | coding"},
        {"skillType": "knowledge", "preferredLabel": "Neo4j (graph database)", "altLabels": "Neo4j graph"},
        {"skillType": "knowledge", "preferredLabel": "concepts of telecommunications", "altLabels": ""},
        {"skillType": "skill/competence", "preferredLabel": "use Neo4j", "altLabels": ""},
    ]
    skills, report = _build([_row("Lua"), _row("AWK"), _row("Neo4j")], esco)
    assert skills["computer programming"].aliases == set()
    assert {"lua", "awk"} <= set(skills)                                   # still their own skills
    assert skills["neo4j"].sources == {"onet", "esco"}                     # same name: one skill
    assert "computer programming: lua" in report.review["esco_alias_not_reviewed"]
    assert "concepts of telecommunications" not in skills
    assert report.counts["esco_not_knowledge"] == 1
    allowed, _ = _build([_row("Neo4j")], esco, {"alias_allow": {"neo4j": ["neo4j graph"]}})
    assert allowed["neo4j"].aliases == {"neo4j graph"}


def test_a_rename_onto_an_existing_alias_does_not_crash_and_the_names_win():
    # Copilot review on #31: renaming to another skill's alias raised KeyError.
    skills, _ = _build([_row("Adobe Photoshop"), _row("OldPhotoshop")], overrides={"rename": {"oldphotoshop": "photoshop"}})
    assert {"adobe photoshop", "photoshop"} <= set(skills)
    assert "photoshop" not in skills["adobe photoshop"].aliases  # an alias never doubles as another skill's name


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


def test_a_rename_merge_checks_the_incoming_aliases_too():
    # Copilot review on #31: renaming OldGraph (K8S) onto neo4j copied the curated alias k8s
    # unchecked, and load_ontology() then dropped the whole imported neo4j entry.
    skills, report = _build([_row("Neo4j"), _row("OldGraph (K8S)")], overrides={"rename": {"oldgraph": "neo4j"}})
    assert "k8s" not in skills["neo4j"].aliases
    assert "neo4j: k8s" in report.review["alias_dropped_curated_collision"]
