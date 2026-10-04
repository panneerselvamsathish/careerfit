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

    ontology: dict[str, SkillEntry] = {}
    for skill_name, skill_data in data.items():
        ontology[skill_name] = SkillEntry(**skill_data)
    return ontology