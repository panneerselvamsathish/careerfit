import re
from typing import Literal

from careerfit.analyze.ontology import SkillEntry

def mentions(term: str, text: str) -> bool:
    return re.search(rf'(?<!\w){re.escape(term)}(?!\w)', text, re.IGNORECASE) is not None

def detect(name: str, entry: SkillEntry, text: str) -> Literal["found", "unclear", "absent"]:
    
    for alias in entry.aliases:
        if mentions(alias, text):
            return "found"
        
    if mentions(name, text):
        return "unclear" if entry.ambiguous else "found"
    return "absent"