
from pathlib import Path

from pypdf import PdfReader

from careerfit.facts.schema import Coverage 


def read_pdf(path: Path) -> tuple[str, Coverage]:
    reader = PdfReader(path)

    pages_with_text = 0
    pages_without_text = 0
    consolidated_text = ""
    total_pages = len(reader.pages)
    known_blind_spots=("layout_order","graphics","tables")

    for page in reader.pages:
        text = page.extract_text().strip()
        
        if text:
            pages_with_text += 1
            consolidated_text += text + "\n"
        else:
           pages_without_text += 1 

    if pages_without_text > 0:
        known_blind_spots += ("scanned_pages",)

    coverage = Coverage(
        source_format="pdf",
        pages_total=total_pages,
        pages_with_text=pages_with_text,
        chars_extracted=len(consolidated_text),
        known_blind_spots=known_blind_spots
    )
    return consolidated_text, coverage