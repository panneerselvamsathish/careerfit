"""One pass over a text finds every mention of every skill name and alias.

The matcher used to run one regex per term, `(?<!\\w)(?<!\\w\\.)TERM(?!\\w)(?!\\.\\w)` with
IGNORECASE, over every clause. That is fine at a few hundred terms and far too slow at thousands
(regex compiles stop fitting Python's cache). This index gives the same answers, which
tests/test_matcher_differential.py checks against the old code kept in tests/oracle/:

- Case: ASCII letters fold to lowercase, and so do the four other characters Python's IGNORECASE
  treats as ASCII letters (U+0130 and U+0131 match "i", U+017F matches "s", the Kelvin sign U+212A
  matches "k"). Each character folds to exactly one character, so offsets in the folded text are
  offsets in the text. Terms must be ASCII, so they need no more than that.
- Dashes: the six Unicode dashes U+2010 to U+2015 (hyphen, non-breaking hyphen, figure dash, en
  dash, em dash, horizontal bar) match "-", so "proof-of-concept" typed with non-breaking hyphens
  is still found. Only for matching: excerpts keep the original characters. This is the one place
  the index differs from the old regex, on purpose; the oracle comparison folds dashes first.
- Boundaries, checked on the original text: a mention may not start right after a word character
  or after "word." ("js" is never found inside "Node.js"), and may not end right before a word
  character or before ".word". A word character is what `\\w` means: alphanumeric or "_".
- A term's own mentions never overlap, as with `re.finditer`.
- Negation: a term right after "non-" ("non-relational database", "non-technical") is not a
  mention of it. "non-X" never asks for X, and never shows X on a resume.

Where a mention can start: a term that starts with a word character can only start at the start of
a run of word characters, and then that whole run is the term's first word (the next character
must be the term's own non-word character, or a boundary). So terms are indexed by that first
word, and a term that starts with a symbol is indexed by the symbol.

Non-ASCII characters are written as escapes in this file: a Kelvin sign and a capital K look the
same in an editor.
"""

import re
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from functools import lru_cache

from careerfit.analyze.ontology import SkillEntry

_DASHES = {chr(c): "-" for c in range(0x2010, 0x2016)}
HYPHENS = str.maketrans(_DASHES)
_FOLD = str.maketrans({**{chr(c): chr(c + 32) for c in range(ord("A"), ord("Z") + 1)},
                       "\u0130": "i", "\u0131": "i", "\u017f": "s", "\u212a": "k", **_DASHES})
_TOKEN = re.compile(r"\w+|\W")  # a run of word characters, or one other character


def fold(text: str) -> str:
    """The text as the matcher compares it: same length, character for character."""
    return text.translate(_FOLD)


def dashes_as_hyphens(text: str) -> str:
    """Unicode dashes as "-", same length: for the regexes that read sections, markers and blanking."""
    return text.translate(HYPHENS)


def is_word(ch: str) -> bool:
    return ch.isalnum() or ch == "_"


@dataclass(frozen=True, slots=True)
class Mention:
    start: int
    end: int
    skill: str
    term: str  # the name or alias as written in the skill list
    is_alias: bool


@dataclass(frozen=True, slots=True)
class _Term:
    folded: str
    skill: str
    term: str
    is_alias: bool
    slot: int  # one per (skill, term) entry: a term's own mentions must not overlap


def _first_word(folded: str) -> str:
    if not is_word(folded[0]):
        return folded[0]
    end = 1
    while end < len(folded) and is_word(folded[end]):
        end += 1
    return folded[:end]


def _starts_clear(text: str, i: int) -> bool:
    if i > 0 and is_word(text[i - 1]):
        return False
    return not (i > 1 and text[i - 1] == "." and is_word(text[i - 2]))


def _negated(folded: str, text: str, i: int) -> bool:
    """True when the mention at i follows a "non-" that starts a word ("non-relational")."""
    return i >= 4 and folded[i - 4:i] == "non-" and (i == 4 or not is_word(text[i - 5]))


def _ends_clear(text: str, j: int) -> bool:
    if j < len(text) and is_word(text[j]):
        return False
    return not (j + 1 < len(text) and text[j] == "." and is_word(text[j + 1]))


class MentionIndex:
    """Every name and alias in a skill list, keyed by first word, plus each skill's list position."""

    def __init__(self, terms: Iterable[_Term], rank: dict[str, int]):
        self._by_first: dict[str, list[_Term]] = {}
        for term in terms:
            self._by_first.setdefault(_first_word(term.folded), []).append(term)
        self.rank = rank  # skill -> position in the list, so results can keep the list's order

    @classmethod
    def build(cls, ontology: Mapping[str, SkillEntry]) -> "MentionIndex":
        terms: list[_Term] = []
        for name, entry in ontology.items():
            for term, is_alias in (*((alias, True) for alias in entry.aliases), (name, False)):
                if not term.isascii():
                    raise ValueError(f"{name}: {term!r} is not ASCII; the matcher only folds ASCII case")
                if not term:
                    raise ValueError(f"{name}: empty name or alias")
                terms.append(_Term(fold(term), name, term, is_alias, len(terms)))
        return cls(terms, {name: i for i, name in enumerate(ontology)})

    def find(self, text: str) -> list[Mention]:
        """Every mention in the text, ordered by start, then end."""
        found = list(self.iter_find(text))
        found.sort(key=lambda m: (m.start, m.end))
        return found

    def iter_find(self, text: str) -> Iterator[Mention]:
        """Mentions as they are found, in order of start (not sorted within one start). Lazy, so a
        caller that only needs to know whether a skill is mentioned can stop at the first one."""
        folded = fold(text)
        last_end: dict[int, int] = {}
        for token in _TOKEN.finditer(folded):
            start = token.start()
            candidates = self._by_first.get(token.group())
            if not candidates or not _starts_clear(text, start) or _negated(folded, text, start):
                continue
            for term in candidates:
                end = start + len(term.folded)
                if (folded.startswith(term.folded, start) and _ends_clear(text, end)
                        and last_end.get(term.slot, -1) <= start):
                    last_end[term.slot] = end
                    yield Mention(start, end, term.skill, term.term, term.is_alias)

    def find_by_line(self, text: str) -> list[list[Mention]]:
        """Mentions per line of `text.splitlines()`, offsets relative to each line."""
        return [self.find(line) for line in text.splitlines()]


@lru_cache(maxsize=8192)
def entry_index(name: str, entry: SkillEntry) -> MentionIndex:
    """An index of one skill's terms, for code that asks about one skill at a time."""
    return MentionIndex.build({name: entry})
