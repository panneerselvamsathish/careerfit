from careerfit.analyze.ontology import load_ontology
from pathlib import Path
import pytest
from pydantic import ValidationError

def test_real_skills_file_loads():
    SKILLS_FILE = Path(__file__).parent.parent / "src" / "careerfit" / "ontology" / "skills.yaml"
    skills = load_ontology(SKILLS_FILE)
    assert skills is not None
    assert isinstance(skills, dict)
    assert "k8s" in skills["kubernetes"].aliases
    assert skills["go"].ambiguous is True

def test_load_ontology_rejects_empty_alias(tmp_path):
    bad = tmp_path / "skills.yaml"
    bad.write_text('swift:\n  aliases: [""]\n  ambiguous: true\n', encoding="utf-8")

    with pytest.raises(ValidationError, match="Aliases must never be empty"):
        load_ontology(bad)

def test_load_ontology_rejects_misspelled_field(tmp_path):
    bad = tmp_path / "skills.yaml"
    bad.write_text('swift:\n  aliasess: ["swift"]\n  ambiguous: true\n', encoding="utf-8")

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        load_ontology(bad)