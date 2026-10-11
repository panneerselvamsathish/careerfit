"""Hiring-manager view: which requirements this candidate meets, misses, or leaves uncertain."""

from careerfit.facts.schema import GapAnalysisFacts, SkillStatus
from careerfit.report.shared import (STATUS_LABEL, blind_spots, by_requirement, cell, cite, header,
                                     provenance_section, status_counts)

UNCERTAIN = (SkillStatus.UNRESOLVABLE, SkillStatus.NOT_ASSESSED)
LEVEL_LABEL = {"must": "must-have", "nice": "nice-to-have"}


def render(facts: GapAnalysisFacts) -> str:
    must, nice = by_requirement(facts, "must"), by_requirement(facts, "nice")
    missing = [o.skill for o in must if o.status == SkillStatus.GAP]
    uncertain = [o.skill for o in must + nice if o.status in UNCERTAIN]
    lines = header(facts, "Candidate fit against this role")
    lines += ["## Summary", ""]
    if facts.fit_score is not None:
        lines.append(f"- Fit: **{facts.fit_score.overall:.0%}** "
                     f"(must-have coverage {facts.fit_score.must_have_coverage:.0%}). {facts.fit_score.explanation}")
    lines += [f"- Must-have requirements: {status_counts(must)}",
              f"- Missing must-haves: {', '.join(missing) if missing else 'none'}",
              f"- Needs a human check: {', '.join(uncertain) if uncertain else 'nothing'}",
              f"- Nice-to-have requirements: {status_counts(nice)}", ""]
    lines += ["## Requirements", "", "| Requirement | Level | Status | Evidence in the resume | Asked for in the JD |",
              "|---|---|---|---|---|"]
    lines += [f"| {cell(o.skill)} | {LEVEL_LABEL[o.requirement]} | {STATUS_LABEL[o.status]} | {cite(o.resume_evidence)} | "
              f"{cite(o.jd_evidence)} |" for o in must + nice]
    lines.append("")
    return "\n".join(lines + blind_spots(facts) + provenance_section(facts)).rstrip() + "\n"
