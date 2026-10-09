from pydantic import BaseModel, model_validator, ConfigDict
import yaml
from pathlib import Path

class SkillEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    aliases: tuple[str, ...]
    ambiguous: bool

    @model_validator(mode="after")
    def check_aliases_not_empty(self) -> "SkillEntry":
        empty_aliases = any(not alias.strip() for alias in self.aliases)
        if empty_aliases:
            raise ValueError("Aliases must never be empty")
        return self

def load_ontology(path: Path) -> dict[str, SkillEntry]:
    raw_text = path.read_text(encoding="utf-8")
    data = yaml.safe_load(raw_text)
    if not isinstance(data, dict):
        raise ValueError(f"{path.name}: expected skill names mapped to entries, got {type(data).__name__}")

    ontology: dict[str, SkillEntry] = {}
    for skill_name, skill_data in data.items():
        if not isinstance(skill_data, dict):
            raise ValueError(f"{path.name}: entry for '{skill_name}' must have aliases and ambiguous fields")
        ontology[skill_name] = SkillEntry(**skill_data)
    return ontology