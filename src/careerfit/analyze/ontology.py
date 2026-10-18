from collections.abc import Iterator, Mapping
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from pydantic import BaseModel, ConfigDict, model_validator

if TYPE_CHECKING:
    from careerfit.analyze.mentions import MentionIndex

class SkillEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    aliases: tuple[str, ...]
    ambiguous: bool
    # Broader skills this one demonstrates by definition ("pl/sql" is back-end development and SQL).
    # Only strict "X is a kind of Y" facts belong here, never "people who know X often know Y".
    implies: tuple[str, ...] = ()

    @model_validator(mode="after")
    def check_aliases_not_empty(self) -> "SkillEntry":
        empty_aliases = any(not alias.strip() for alias in self.aliases)
        if empty_aliases:
            raise ValueError("Aliases must never be empty")
        return self

class Ontology(Mapping[str, SkillEntry]):
    """The skill list, read-only, with its mention index and reverse implications built once.

    Behaves like the plain dict it wraps, so any code that takes a mapping of skills takes this too.
    """

    def __init__(self, entries: Mapping[str, SkillEntry]):
        self._entries = dict(entries)

    def __getitem__(self, name: str) -> SkillEntry:
        return self._entries[name]

    def __iter__(self) -> Iterator[str]:
        return iter(self._entries)

    def __len__(self) -> int:
        return len(self._entries)

    @cached_property
    def index(self) -> "MentionIndex":
        from careerfit.analyze.mentions import MentionIndex  # mentions imports SkillEntry from here
        return MentionIndex.build(self)

    @cached_property
    def implied_by(self) -> dict[str, tuple[str, ...]]:
        return implied_by_of(self._entries)


def index_of(ontology: Mapping[str, SkillEntry]) -> "MentionIndex":
    """The mention index: built once for a loaded Ontology, built on the spot for a plain dict."""
    if isinstance(ontology, Ontology):
        return ontology.index
    from careerfit.analyze.mentions import MentionIndex
    return MentionIndex.build(ontology)


def implied_by_of(ontology: Mapping[str, SkillEntry]) -> dict[str, tuple[str, ...]]:
    """For each skill, the skills that imply it, in the list's order ("sql" ← "pl/sql")."""
    if isinstance(ontology, Ontology):
        return ontology.implied_by  # computed once, on first use
    reverse: dict[str, list[str]] = {}
    for name, entry in ontology.items():
        for implied in entry.implies:
            reverse.setdefault(implied, []).append(name)
    return {name: tuple(by) for name, by in reverse.items()}


def load_ontology(path: Path) -> Ontology:
    raw_text = path.read_text(encoding="utf-8")
    data = yaml.safe_load(raw_text)
    if not isinstance(data, dict):
        raise ValueError(f"{path.name}: expected skill names mapped to entries, got {type(data).__name__}")

    ontology: dict[str, SkillEntry] = {}
    for skill_name, skill_data in data.items():
        if not isinstance(skill_name, str) or not skill_name.strip():
            raise ValueError(f"{path.name}: skill name {skill_name!r} must be a non-empty string")
        if not isinstance(skill_data, dict):
            raise ValueError(f"{path.name}: entry for '{skill_name}' must have aliases and ambiguous fields")
        ontology[skill_name] = SkillEntry(**skill_data)
    for skill_name, entry in ontology.items():
        if skill_name in entry.implies:
            raise ValueError(f"{path.name}: '{skill_name}' cannot imply itself")
        unknown = [name for name in entry.implies if name not in ontology]
        if unknown:
            raise ValueError(f"{path.name}: '{skill_name}' implies unknown skill(s) {unknown}")
    return Ontology(ontology)