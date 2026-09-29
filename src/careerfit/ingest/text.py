from pathlib import Path
from careerfit.facts.schema import Coverage

def read_text(path: Path) -> tuple[str, Coverage]:
    text = path.read_text(encoding="utf-8")
    # plain text: the parser sees every character, so nothing can be hidden
    coverage = Coverage(source_format="txt", pages_total=None, pages_with_text=None, chars_extracted=len(text), known_blind_spots=()) 
    return text, coverage