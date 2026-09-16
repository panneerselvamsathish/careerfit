"""Architectural fitness functions.

These test that design boundaries have not eroded.
A docstring saying 'do not import anthropic here' is a wish.
This test is a rule.
"""

import pytest
import ast
import pathlib

#PKG = pathlib.Path(__file__).parent().parent() / "src" / "careerfit"
PKG = pathlib.Path(__file__).parent.parent / "src" / "careerfit"

FORBIDDEN = {
    "analyze": {"careerfit.judge", "anthropic", "openai", "requests", "httpx"},
    "ingest": {"careerfit.judge", "careerfit.analyze", "anthropic", "openai", "requests", "httpx"},
    "report": {"careerfit.judge", "careerfit.analyze", "anthropic", "openai", "requests", "httpx"}
}

def imports_of(path: pathlib.Path) -> set[str]:
    with path.open() as f:
        tree = ast.parse(f.read(), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                found.add(node.module)
    return found

@pytest.mark.parametrize("package,banned", FORBIDDEN.items())
def test_no_forbidden_imports(package: str, banned: set[str]) -> None:
    pkg_path = PKG / package
    for file in pkg_path.glob("**/*.py"):
        imported = imports_of(file)
        intersection = {
            imp for imp in imported
            if any(imp == ban or imp.startswith(ban + ".") for ban in banned)
        }
        assert not intersection, f"{file} imports forbidden modules: {intersection}"