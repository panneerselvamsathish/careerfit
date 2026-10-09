import pytest
from careerfit.analyze.matcher import detect, requirement_levels, scan, decide_status
from careerfit.facts.schema import SkillStatus
from careerfit.analyze.ontology import SkillEntry

ONTOLOGY = {
    "python": SkillEntry(aliases=(), ambiguous=False),
    "aws": SkillEntry(aliases=("amazon web services",), ambiguous=False),
    "kubernetes": SkillEntry(aliases=("k8s", "kube"), ambiguous=False),
    "javascript": SkillEntry(aliases=("js",), ambiguous=False),
}

@pytest.mark.parametrize("name, entry, text, expected", [
    ("java", SkillEntry(aliases=(), ambiguous=False), "Senior Java developer", "found"),
    ("java", SkillEntry(aliases=(), ambiguous=False), "Looking for a JavaScript expert", "absent"),
    ("python", SkillEntry(aliases=("py",), ambiguous=False), "Experienced in Python and Django", "found"),
    ("python", SkillEntry(aliases=("py",), ambiguous=True), "Python is a versatile language", "unclear"),
    ("c++", SkillEntry(aliases=("cpp",), ambiguous=False), "C++ developer needed", "found"),
    ("c++", SkillEntry(aliases=("cpp",), ambiguous=True), "C++ can be tricky", "unclear"),
    ("kubernetes", SkillEntry(aliases=("k8s", "kube"), ambiguous=False), "We deploy on kube", "found"),
    ("go", SkillEntry(aliases=("golang",), ambiguous=True), "Go and Golang", "found"),
    ("go", SkillEntry(aliases=("golang",), ambiguous=True), "We go live weekly", "unclear"),
])
def test_detect(name, entry, text, expected):
    assert detect(name, entry, text) == expected

def test_scan_reports_every_skill():
    ontology = {
        "python": SkillEntry(aliases=(), ambiguous=False),
        "go": SkillEntry(aliases=("golang",), ambiguous=True),
        "java": SkillEntry(aliases=(), ambiguous=False),
    }
    result = scan("Python services, we go live weekly", ontology)
    assert result == {"python": "found", "go": "unclear", "java": "absent"}


@pytest.mark.parametrize("jd_text, expected", [
    ("Requirements:\n- Python\n- AWS\nNice to have:\n- Kubernetes", {"python": "must", "aws": "must", "kubernetes": "nice"}),
    ("Python is required.\nExperience with Python and AWS is a plus.", {"python": "must", "aws": "nice"}),
    ("Requirements:\n- Python\nKubernetes is nice to have.\n- AWS", {"python": "must", "kubernetes": "nice", "aws": "must"}),
    ("We value curiosity and teamwork.", {}),
    ("Python is required. Experience with Python and AWS is a plus.", {"python": "must", "aws": "nice"}),
    ("Node.js and Python are required.", {"python": "must"}),
    ("Python is preferred, but AWS is required.", {"python": "nice", "aws": "must"}),
    ("Experience with Python, AWS and Kubernetes is a plus.", {"python": "nice", "aws": "nice", "kubernetes": "nice"}),
    ("Nice to have:\n- Kubernetes\n- AWS is required", {"kubernetes": "nice", "aws": "must"}),
])
def test_requirement_levels(jd_text, expected):
   
    assert requirement_levels(jd_text, ONTOLOGY) == expected

@pytest.mark.parametrize("jd_result, resume_result, scanned, expected", [
    ("found", "found", False, SkillStatus.MATCHED),
    # ...one line per row of the table
    ("found", "absent", False, SkillStatus.GAP),
    ("found", "unclear", False, SkillStatus.UNRESOLVABLE),
    ("found", "found", True, SkillStatus.MATCHED),
    ("found", "absent", True, SkillStatus.NOT_ASSESSED),
    ("found", "unclear", True, SkillStatus.UNRESOLVABLE),
    ("unclear", "found", False, SkillStatus.UNRESOLVABLE),
    ("unclear", "absent", False, SkillStatus.UNRESOLVABLE),
    ("unclear", "unclear", False, SkillStatus.UNRESOLVABLE),
    ("unclear", "found", True, SkillStatus.UNRESOLVABLE),
    ("unclear", "absent", True, SkillStatus.UNRESOLVABLE),
    ("unclear", "unclear", True, SkillStatus.UNRESOLVABLE),
])
def test_decide_status(jd_result, resume_result, scanned, expected):
    assert decide_status(jd_result, resume_result, scanned) == expected

