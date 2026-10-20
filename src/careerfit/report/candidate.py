"""Candidate view: where you stand against this job, and what to learn next."""

from careerfit.facts.schema import GapAnalysisFacts
from careerfit.report.shared import (STATUS_LABEL, blind_spots, by_requirement, cell, cite, header,
                                     coverage_summary, provenance_section, status_counts)


def render(facts: GapAnalysisFacts) -> str:
    must, nice = by_requirement(facts, "must"), by_requirement(facts, "nice")
    lines = header(facts, "Your resume against this job")
    lines += ["## Summary", ""]
    if facts.fit_score is not None:
        lines.append(f"- Fit: **{facts.fit_score.overall:.0%}**. {cell(facts.fit_score.explanation)}")
    lines += [f"- Must-have skills: {status_counts(must)}", f"- Nice-to-have skills: {status_counts(nice)}", ""]
    if summary := coverage_summary(facts):
        lines.insert(len(lines) - 1, f"- {summary}")
    for title, rows in (("Must-have skills", must), ("Nice-to-have skills", nice)):
        if not rows:
            continue
        lines += [f"## {title}", "", "| Skill | Status | The job description says | Your resume shows |",
                  "|---|---|---|---|"]
        lines += [f"| {cell(o.skill)} | {STATUS_LABEL[o.status]} | {cite(o.jd_evidence)} | {cite(o.resume_evidence)} |"
                  for o in rows]
        lines.append("")
    if facts.learning_steps:
        lines += ["## Learning plan", ""]
        for step in facts.learning_steps:
            weeks = step.estimated_weeks
            effort = f"about {weeks} week{'' if weeks == 1 else 's'}" if weeks else "time not estimated"
            lines.append(f"{step.priority}. **{cell(step.skill)}** ({effort}): {cell(step.why_it_matters)}")
            lines += [f"   - {cell(r)}" for r in step.resources]
        lines.append("")
    return "\n".join(lines + blind_spots(facts) + provenance_section(facts)).rstrip() + "\n"
