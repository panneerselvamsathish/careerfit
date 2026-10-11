import copy
from pathlib import Path
from string import Template
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, model_validator

PROMPT_DIR = Path(__file__).parent / "prompts"


class PromptSpec(BaseModel):
    """Everything that shapes one request: system text, user template and output schema."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    version: int
    system: str
    examples: str = ""
    user: str
    output_schema: dict[str, Any]

    @model_validator(mode="after")
    def check_schema_has_one_skill_list(self) -> "PromptSpec":
        self._skill_property()
        return self

    @property
    def ref(self) -> str:
        """Stable identifier recorded in the facts, e.g. 'skill_match@1'."""
        return f"{self.id}@{self.version}"

    @property
    def full_system(self) -> str:
        return f"{self.system}\n\n{self.examples}".strip() if self.examples else self.system.strip()

    def render_user(self, *, documents: str, skills: str) -> str:
        return Template(self.user).substitute(documents=documents, skills=skills).strip()

    def schema_for(self, skills: list[str]) -> dict[str, Any]:
        """The output schema with `skill` limited to exactly these skills."""
        schema = copy.deepcopy(self.output_schema)
        _, item_key = self._skill_property()
        schema["properties"][item_key]["items"]["properties"]["skill"]["enum"] = list(skills)
        return schema

    def _skill_property(self) -> tuple[dict, str]:
        arrays = [k for k, v in self.output_schema.get("properties", {}).items() if v.get("type") == "array"]
        if len(arrays) != 1:
            raise ValueError(f"{self.id}: output_schema needs exactly one top-level array, found {arrays}")
        skill = self.output_schema["properties"][arrays[0]].get("items", {}).get("properties", {}).get("skill")
        if skill is None:
            raise ValueError(f"{self.id}: the {arrays[0]!r} items need a 'skill' property")
        return skill, arrays[0]


def load_prompt(prompt_id: str) -> PromptSpec:
    spec = PromptSpec(**yaml.safe_load((PROMPT_DIR / f"{prompt_id}.yaml").read_text(encoding="utf-8")))
    if spec.id != prompt_id:
        raise ValueError(f"{prompt_id}.yaml declares id {spec.id!r}")
    return spec
