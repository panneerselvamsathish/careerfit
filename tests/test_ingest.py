import pytest
from careerfit.ingest.document import read_document
from careerfit.ingest.text import read_text
from careerfit.facts.schema import Coverage
from careerfit.ingest.pdf import read_pdf
from fpdf import FPDF

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
    

    pdf_path = tmp_path / "test.pdf"
    # Create a PDF with 3 blank pages
    
    pdf = FPDF()
    pdf.set_font("Helvetica", size=12)   # fpdf2 needs a font before writing any text
    pdf.add_page()
    pdf.cell(text="Python and AWS")      # writes text on this page
    pdf.add_page()                       # a second, blank page
    pdf.output(pdf_path)


    text, coverage = read_pdf(pdf_path)
    assert "Python and AWS" in text
    assert coverage.known_blind_spots.count("scanned_pages") == 1
    assert coverage.pages_total == 2
    assert coverage.pages_with_text == 1
    assert coverage.chars_extracted == len(text)
    assert coverage.known_blind_spots == ("layout_order", "graphics", "tables", "scanned_pages")


def test_read_pdf_mixed_pages_keeps_text_and_flags_scanned(tmp_path):
    pdf_path = tmp_path / "test_mixed.pdf"
    # Create a PDF with 1 page with text and 1 blank page
    pdf = FPDF()
    pdf.set_font("Helvetica", size=12)
    pdf.add_page()
    pdf.cell(text="Python and AWS")
    pdf.add_page()  # blank page
    pdf.output(pdf_path)

    text, coverage = read_pdf(pdf_path)
    assert "Python and AWS" in text
    assert coverage.known_blind_spots.count("scanned_pages") == 1
    assert coverage.pages_total == 2
    assert coverage.pages_with_text == 1
    assert coverage.chars_extracted == len(text)
    assert coverage.known_blind_spots == ("layout_order", "graphics", "tables", "scanned_pages")

def test_read_pdf_owner_only_encryption_reads_normally(tmp_path):
    pdf_path = tmp_path / "test_encrypted.pdf"
    # Create a PDF with owner-only encryption
    pdf = FPDF()
    pdf.set_font("Helvetica", size=12)
    pdf.add_page()
    pdf.cell(text="Python and AWS")
    pdf.set_encryption(owner_password="owner", user_password="")        # opens without a password

    pdf.output(pdf_path)

    text, coverage = read_pdf(pdf_path)
    assert "Python and AWS" in text
    assert coverage.pages_total == 1
    assert coverage.pages_with_text == 1
    assert coverage.chars_extracted == len(text)
    assert coverage.known_blind_spots == ("layout_order", "graphics", "tables")

def test_read_pdf_password_protected_raises_clear_error(tmp_path):
    pdf_path = tmp_path / "test_protected.pdf"
    # Create a PDF with user password
    pdf = FPDF()
    pdf.set_font("Helvetica", size=12)
    pdf.add_page()
    pdf.cell(text="Python and AWS")
    pdf.set_encryption(owner_password="owner", user_password="user")  # requires a password to open

    pdf.output(pdf_path)

    with pytest.raises(ValueError, match="password-protected"):
        text, coverage = read_pdf(pdf_path)

def test_read_document_routes_txt(tmp_path):
    txt_path = tmp_path / "test.txt"
    txt_path.write_text("Python and AWS", encoding="utf-8")

    text, coverage = read_document(txt_path)
    assert "Python and AWS" in text
    assert coverage.source_format == "txt"
    assert coverage.pages_total is None
    assert coverage.pages_with_text is None
    assert coverage.chars_extracted == len(text)
    assert coverage.known_blind_spots == ()

def test_read_document_routes_pdf(tmp_path):
    pdf_path = tmp_path / "test.pdf"
    pdf = FPDF()
    pdf.set_font("Helvetica", size=12)
    pdf.add_page()
    pdf.cell(text="Python and AWS")
    pdf.output(pdf_path)

    text, coverage = read_document(pdf_path)
    assert "Python and AWS" in text
    assert coverage.source_format == "pdf"
    assert coverage.pages_total == 1
    assert coverage.pages_with_text == 1
    assert coverage.chars_extracted == len(text)
    assert coverage.known_blind_spots == ("layout_order", "graphics", "tables")

def test_read_document_routes_uppercase_pdf(tmp_path):
    pdf_path = tmp_path / "test.PDF"
    pdf = FPDF()
    pdf.set_font("Helvetica", size=12)
    pdf.add_page()
    pdf.cell(text="Python and AWS")
    pdf.output(pdf_path)

    text, coverage = read_document(pdf_path)
    assert "Python and AWS" in text
    assert coverage.source_format == "pdf"
    assert coverage.pages_total == 1
    assert coverage.pages_with_text == 1
    assert coverage.chars_extracted == len(text)
    assert coverage.known_blind_spots == ("layout_order", "graphics", "tables")

def test_read_document_rejects_unsupported_type(tmp_path):
    unsupported_path = tmp_path / "test.docx"
    unsupported_path.write_text("Python and AWS")

    # Ensure that attempting to read an unsupported file type raises a ValueError
    with pytest.raises(ValueError, match="test.docx"):
        text, coverage = read_document(unsupported_path)