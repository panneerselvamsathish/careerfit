import pytest
from careerfit.ingest.text import read_text
from careerfit.facts.schema import Coverage

def test_read_text_returns_text_and_coverage(tmp_path):
    file_path = tmp_path / "test.txt"
    file_path.write_text("Python and AWS", encoding="utf-8")
    text, coverage = read_text(file_path)
    assert text == "Python and AWS"
    assert isinstance(coverage, Coverage)
    assert coverage.source_format == "txt"
    assert coverage.pages_total is None
    assert coverage.pages_with_text is None
    assert coverage.chars_extracted == len("Python and AWS")
    assert coverage.known_blind_spots == ()

def test_read_text_missing_file_raises(tmp_path):
    file_path = tmp_path / "nonexistent.txt"
    with pytest.raises(FileNotFoundError):
        read_text(file_path)

def test_read_pdf_blank_pages_are_flagged_as_scanned(tmp_path):
    from careerfit.ingest.pdf import read_pdf
    from pathlib import Path

    pdf_path = tmp_path / "test.pdf"
    # Create a PDF with 3 blank pages
    from fpdf import FPDF
    pdf = FPDF()
    pdf.add_page()
    pdf.add_page()
    pdf.add_page()
    pdf.output(pdf_path)

    text, coverage = read_pdf(pdf_path)
    assert text == ""
    assert coverage.known_blind_spots.count("scanned_pages") == 1
    assert coverage.pages_total == 3
    assert coverage.pages_with_text == 0
    assert coverage.chars_extracted == 0
    assert coverage.known_blind_spots == ("layout_order", "graphics", "tables", "scanned_pages")