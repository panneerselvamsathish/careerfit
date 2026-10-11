"""Fit score: deterministic arithmetic over decided observations. No tokens needed."""

from careerfit.facts.schema import FitScore, SkillObservation, SkillStatus

DECIDED = (SkillStatus.MATCHED, SkillStatus.PARTIAL, SkillStatus.GAP)
MUST_WEIGHT = 0.75


def _coverage(observations: list[SkillObservation]) -> float:
    if not observations:
        return 0.0
    credit = sum(1.0 if o.status == SkillStatus.MATCHED else 0.5 if o.status == SkillStatus.PARTIAL else 0.0
                 for o in observations)
    return credit / len(observations)


def _describe(label: str, observations: list[SkillObservation]) -> str:
    if not observations:
        return f"{label}: none assessed."
    matched = sum(o.status == SkillStatus.MATCHED for o in observations)
    partial = sum(o.status == SkillStatus.PARTIAL for o in observations)
    text = f"{label}: {matched} of {len(observations)} matched"
    return text + (f", {partial} partly." if partial else ".")


def compute_fit_score(observations: tuple[SkillObservation, ...]) -> FitScore | None:
    """None when nothing was decided: a score with no basis would be a fabricated number."""
    decided = [o for o in observations if o.status in DECIDED]
    if not decided:
        return None
    must = [o for o in decided if o.requirement == "must"]
    nice = [o for o in decided if o.requirement == "nice"]
    must_cov, nice_cov = _coverage(must), _coverage(nice)
    if must and nice:
        overall = MUST_WEIGHT * must_cov + (1 - MUST_WEIGHT) * nice_cov
    else:
        overall = must_cov if must else nice_cov

    excluded = len(observations) - len(decided)
    parts = [_describe("Must-have", must), _describe("Nice-to-have", nice)]
    if excluded:
        parts.append(f"{excluded} skill{'s' if excluded != 1 else ''} could not be assessed and "
                     f"{'are' if excluded != 1 else 'is'} not counted.")
    # Round once, at the end: combining already-rounded coverages can shift the overall score.
    return FitScore(overall=round(overall, 3), must_have_coverage=round(must_cov, 3),
                    nice_to_have_coverage=round(nice_cov, 3), explanation=" ".join(parts))
