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

# Raw HTTP clients, including httpx2 (what the Anthropic SDK itself is built on).
RAW_HTTP = {"requests", "httpx", "httpx2", "aiohttp", "urllib3", "urllib.request", "http.client"}

# The web framework belongs to the composition root (api.py); the pipeline never sees a request.
WEB = {"fastapi", "starlette", "uvicorn", "multipart", "python_multipart", "careerfit.api", "careerfit.cli"}

FORBIDDEN = {
    "analyze": {"careerfit.judge", "anthropic", "openai"} | RAW_HTTP | WEB,
    "ingest": {"careerfit.judge", "careerfit.analyze", "anthropic", "openai"} | RAW_HTTP | WEB,
    "report": {"careerfit.judge", "careerfit.analyze", "anthropic", "openai"} | RAW_HTTP | WEB,
    "judge": {"careerfit.ingest", "careerfit.report", "careerfit.cli", "careerfit.api"} | RAW_HTTP | WEB,
    "facts": RAW_HTTP | WEB,  # plus every other careerfit module: see test_facts_imports_no_other_careerfit_module
}

def imports_of(path: pathlib.Path) -> set[str]:
    """Every module or name imported, fully qualified, so dotted bans can't be sidestepped."""
    with path.open() as f:
        tree = ast.parse(f.read(), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = _resolve_from(path, node)
            if module:
                found.add(module)
            # "from urllib import request" imports urllib.request; "from careerfit import judge"
            # imports careerfit.judge. Record those too, or a dotted ban never matches.
            for alias in node.names:
                found.add(f"{module}.{alias.name}" if module else alias.name)
    return found


def _resolve_from(path: pathlib.Path, node: ast.ImportFrom) -> str:
    if node.level == 0:
        return node.module or ""
    # Relative import: walk up from the file's own package, e.g. "from ..judge import x" in
    # careerfit/analyze/matcher.py resolves to careerfit.judge.
    package = path.relative_to(PKG.parent).with_suffix("").parts[:-1]
    base = package[: len(package) - (node.level - 1)]
    return ".".join([*base, *(node.module.split(".") if node.module else [])])

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

LLM_SDKS = {"anthropic", "openai"}


def test_only_judge_imports_an_llm_sdk() -> None:
    offenders = {}
    for file in PKG.glob("**/*.py"):
        if (PKG / "judge") in file.parents:
            continue
        sdk_imports = {imp for imp in imports_of(file) if imp.split(".")[0] in LLM_SDKS}
        if sdk_imports:
            offenders[str(file.relative_to(PKG))] = sdk_imports
    assert not offenders, f"only judge/ may import an LLM SDK: {offenders}"


def test_facts_imports_no_other_careerfit_module() -> None:
    """facts/ is the shared contract, so it depends on nothing else in careerfit, including modules added later."""
    offenders = {}
    for file in (PKG / "facts").glob("**/*.py"):
        own = {
            imp for imp in imports_of(file)
            if (imp == "careerfit" or imp.startswith("careerfit."))
            and not (imp == "careerfit.facts" or imp.startswith("careerfit.facts."))  # not careerfit.facts_extra
        }
        if own:
            offenders[str(file.relative_to(PKG))] = own
    assert not offenders, f"facts/ may only import from careerfit.facts: {offenders}"


def test_only_store_talks_to_aws() -> None:
    """boto3 stays in store.py: the pipeline, the report and the usage rules never reach DynamoDB."""
    offenders = {}
    for file in PKG.glob("**/*.py"):
        if file == PKG / "store.py":
            continue
        aws = {imp for imp in imports_of(file) if imp.split(".")[0] in {"boto3", "botocore"}}
        if aws:
            offenders[str(file.relative_to(PKG))] = aws
    assert not offenders, f"only store.py may import boto3: {offenders}"


def test_the_usage_rules_are_pure() -> None:
    """usage.py decides what may be stored about a visitor; it reaches no web framework, network or store."""
    banned = WEB | RAW_HTTP | LLM_SDKS | {"boto3", "botocore", "careerfit.store"}
    imported = imports_of(PKG / "usage.py")
    found = {imp for imp in imported if any(imp == ban or imp.startswith(ban + ".") for ban in banned)}
    assert not found, f"usage.py imports {found}"
