from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

PROMPT_DIR = Path(__file__).parent / "prompts"


class PromptSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    version: int
    system: str
    examples: str = ""

    @property
    def ref(self) -> str:
        """Stable identifier recorded in the facts and in cache keys, e.g. 'skill_match@1'."""
        return f"{self.id}@{self.version}"

    @property
    def full_system(self) -> str:
        return f"{self.system}\n\n{self.examples}".strip() if self.examples else self.system.strip()


def load_prompt(prompt_id: str) -> PromptSpec:
    spec = PromptSpec(**yaml.safe_load((PROMPT_DIR / f"{prompt_id}.yaml").read_text(encoding="utf-8")))
    if spec.id != prompt_id:
        raise ValueError(f"{prompt_id}.yaml declares id {spec.id!r}")
    return spec
