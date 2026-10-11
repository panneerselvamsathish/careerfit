"""Renderers only. Zero logic. MUST NOT: call an LLM, import judge/, import analyze/."""

from careerfit.facts.schema import GapAnalysisFacts
from careerfit.report import candidate, hiring_manager


def render_markdown(facts: GapAnalysisFacts) -> str:
    """The report for the perspective recorded in the facts."""
    renderer = candidate if facts.perspective == "candidate" else hiring_manager
    return renderer.render(facts)
