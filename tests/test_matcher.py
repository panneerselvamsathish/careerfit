import pytest
from careerfit.analyze.matcher import decide_status, detect, first_mention_line, requirement_evidence, requirement_levels, scan
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
    ("Strong experience with Python:\n- 5 years building APIs", {"python": "must"}),
    ("Kubernetes is a plus:\n- AWS", {"kubernetes": "nice", "aws": "nice"}),
    ("Python is preferred BUT AWS is required.", {"python": "nice", "aws": "must"}),
    ("Requirements:\n- Python\nNice to have:\nCloud:\n- AWS\nContainers:\n- Kubernetes", {"python": "must", "aws": "nice", "kubernetes": "nice"}),
    ("Nice to have:\n- Kubernetes\nMinimum qualifications:\n- AWS", {"kubernetes": "nice", "aws": "must"}),
    ("Preferred qualifications:\n- Kubernetes", {"kubernetes": "nice"}),
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



GO = SkillEntry(aliases=("golang",), ambiguous=True)


@pytest.mark.parametrize("text, expected", [
    ("We go live.\nGolang engineer.", 2),
    ("Golang engineer.\nWe go live.", 1),
    ("We go live.\nGo is great.", 1),
    ("Python only.", None),
])
def test_first_mention_line_prefers_found_over_unclear(text, expected):
    assert first_mention_line("go", GO, text) == expected


@pytest.mark.parametrize("jd_text, ontology, expected", [
    ("Python is a plus.\nAWS too.\nPython is required.", ONTOLOGY, {"python": ("must", 3, "found"), "aws": ("must", 2, "found")}),
    ("Requirements:\n- Python\nPython is a plus.", ONTOLOGY, {"python": ("must", 2, "found")}),
    ("We go live weekly.\nGolang is required.", {"go": GO}, {"go": ("must", 2, "found")}),
    ("Golang is a plus.\nGo is required.", {"go": GO}, {"go": ("must", 2, "unclear")}),
])
def test_requirement_evidence_points_at_the_deciding_line(jd_text, ontology, expected):
    assert requirement_evidence(jd_text, ontology) == expected
