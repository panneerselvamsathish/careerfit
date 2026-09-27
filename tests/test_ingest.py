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