import pytest
from careerfit.analyze.matcher import detect
from careerfit.analyze.ontology import SkillEntry

@pytest.mark.parametrize("name, entry, text, expected", [
    ("java", SkillEntry(aliases=(), ambiguous=False), "Senior Java developer", "found"),
    ("java", SkillEntry(aliases=(), ambiguous=False), "Looking for a JavaScript expert", "absent"),
    ("python", SkillEntry(aliases=("py",), ambiguous=False), "Experienced in Python and Django", "found"),
    ("python", SkillEntry(aliases=("py",), ambiguous=True), "Python is a versatile language", "unclear"),
    ("c++", SkillEntry(aliases=("cpp",), ambiguous=False), "C++ developer needed", "found"),
    ("c++", SkillEntry(aliases=("cpp",), ambiguous=True), "C++ can be tricky", "unclear"),
])
def test_detect(name, entry, text, expected):
    assert detect(name, entry, text) == expected
