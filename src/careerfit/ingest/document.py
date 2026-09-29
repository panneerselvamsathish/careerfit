from pathlib import Path

from careerfit.facts.schema import Coverage
from careerfit.ingest.pdf import read_pdf
from careerfit.ingest.text import read_text


def read_document(path: Path) -> tuple[str, Coverage]:
    if path.suffix.lower() == ".txt":
        text, coverage = read_text(path)
    elif path.suffix.lower() == ".pdf":
        text, coverage = read_pdf(path)
    else:
        raise ValueError(f"Unsupported file type: {path.suffix.lower()} Load either .txt or .pdf only ({path.name})")
    return text, coverage