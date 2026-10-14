from careerfit.analyze.ontology import load_ontology
from pathlib import Path
import pytest
from pydantic import ValidationError

def test_real_skills_file_loads():
    SKILLS_FILE = Path(__file__).parent.parent / "src" / "careerfit" / "ontology" / "skills.yaml"
    skills = load_ontology(SKILLS_FILE)
    assert skills is not None
    assert isinstance(skills, dict)
    assert "k8s" in skills["kubernetes"].aliases
    assert skills["go"].ambiguous is True

def test_load_ontology_rejects_empty_alias(tmp_path):
    bad = tmp_path / "skills.yaml"
    bad.write_text('swift:\n  aliases: [""]\n  ambiguous: true\n', encoding="utf-8")

    with pytest.raises(ValidationError, match="Aliases must never be empty"):
        load_ontology(bad)

def test_load_ontology_rejects_misspelled_field(tmp_path):
    bad = tmp_path / "skills.yaml"
    bad.write_text('swift:\n  aliasess: ["swift"]\n  ambiguous: true\n', encoding="utf-8")

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        load_ontology(bad)

@pytest.mark.parametrize("content, message", [
    ("", "got NoneType"),
    ("- python\n- aws\n", "got list"),
    ("python: yes\n", "entry for 'python'"),
    ('"":\n  aliases: []\n  ambiguous: false\n', "skill name '' must be"),
    ("1:\n  aliases: []\n  ambiguous: false\n", "skill name 1 must be"),
])
def test_load_ontology_rejects_wrong_shape(tmp_path, content, message):
    bad = tmp_path / "skills.yaml"
    bad.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        load_ontology(bad)


SKILLS = load_ontology(Path(__file__).parent.parent / "src" / "careerfit" / "ontology" / "skills.yaml")


def test_no_name_or_alias_belongs_to_two_skills():
    owner: dict[str, str] = {}
    clashes = []
    for name, entry in SKILLS.items():
        for term in (name, *entry.aliases):
            key = term.lower()
            if key in owner and owner[key] != name:
                clashes.append((term, owner[key], name))
            owner[key] = name
    assert clashes == []


def test_skill_names_are_lowercase_and_aliases_are_not_repeated():
    assert [n for n in SKILLS if n != n.lower()] == []
    assert [n for n, e in SKILLS.items() if len(set(a.lower() for a in e.aliases)) != len(e.aliases)] == []


@pytest.mark.parametrize("skill, text, expected", [
    # everyday meanings stay unclear, so a keyword alone never decides them
    ("helm", "She has been at the helm of the platform team", "unclear"),
    ("helm", "Packaged every service as Helm charts", "found"),
    ("harness", "Harness the power of data", "unclear"),
    ("bedrock", "Trust is the bedrock of our culture", "unclear"),
    ("bedrock", "Built agents on Amazon Bedrock", "found"),
    ("retrieval", "Fast data retrieval from the warehouse", "unclear"),
    ("retrieval", "Designed RAG pipelines over policy documents", "found"),
    ("retrieval", "Reported weekly RAG status to leadership", "absent"),
    ("retrieval", "Tuned the retrieval systems behind the order database", "unclear"),
    ("lambda", "Sorted with a lambda", "unclear"),
    ("lambda", "Serverless APIs on AWS Lambda", "found"),
    ("flux", "Requirements are in flux", "unclear"),
    ("vault", "Records kept in a fireproof vault", "unclear"),
    ("vault", "Secrets in HashiCorp Vault", "found"),
    ("claude", "Reports to Claude, the VP of Engineering", "unclear"),
    ("ai agents", "Define agentic AI architecture patterns", "found"),
    ("tool calling", "Patterns for tool and function calling", "found"),
    ("ci/cd", "Owns CI/CD pipeline design", "found"),
    ("soc 2", "Compliance frameworks (SOC 2, ISO 27001)", "found"),
    ("event-driven architecture", "async event-driven integration", "found"),
    ("prompt injection", "prompt-injection defences", "found"),
    # aliases are conclusive, so none may match an everyday phrase
    ("tool calling", "Monitor developer tool usage across teams", "absent"),
    ("llm evaluation", "Completed annual performance evals", "absent"),
    ("agent memory", "Designed cache-coherent memory systems", "absent"),
    ("snowflake", "Star and snowflake schema design", "unclear"),
    ("snowflake", "Pipelines into the Snowflake Data Cloud", "found"),
    ("control tower", "Ran the operations control tower", "unclear"),
    ("control tower", "Landing zones with AWS Control Tower", "found"),
    ("ecs", "Built an ECS game engine in Rust", "unclear"),
    ("ecs", "Containers on Amazon ECS with Fargate", "found"),
    ("adr", "Settled ADR and equity trades", "unclear"),
    ("adr", "Wrote architecture decision records for each change", "found"),
    # added 2026-10-14 from four more real JDs
    ("azure", "Deep experience designing and deploying enterprise solutions within Microsoft Azure", "found"),
    ("banking", "We are banking on a fast launch", "unclear"),
    ("banking", "Banking industry experience, including regulation and risk", "found"),
    ("agile", "Thrives in an agile, fast-moving team", "unclear"),
    ("agile", "Delivered with agile methodology across three teams", "found"),
    ("waterfall", "Modelled the fund's distribution waterfall", "unclear"),
    ("waterfall", "Ability to apply architecture principles to Agile and Waterfall delivery", "found"),
    ("proof of concept", "Point of contact (POC) for vendor escalations", "absent"),
    ("proof of concept", "Took the assistant from proof of concept to production", "found"),
    ("sso", "Single sign-on through Okta", "found"),
    ("oauth", "SSO, SAML, OAuth/OIDC, role-based access controls", "found"),
    ("openid connect", "SSO, SAML, OAuth/OIDC, role-based access controls", "found"),
    ("data center", "Prior experience in Data Center operations", "found"),
    ("frontend development", "across front-end, back-end, and cloud environments", "found"),
    ("frontend development", "at the front end of the sales funnel", "absent"),
    ("solution architecture", "5+ years of experience working as Solution Architect", "found"),
    ("aiops", "Familiarity with cybersecurity practices and AI-driven operations", "found"),
    ("ai-assisted development", "get them up and running on our AI-assisted development platform", "found"),
    # a case for every other entry added 2026-10-14, aliases included (Copilot review on #15)
    ("devops", "Strong grasp of DevOps practices", "found"),
    ("saml", "Federation over SAML 2.0", "found"),
    ("cybersecurity", "Information security policies and controls", "found"),
    ("cybersecurity", "Cyber security awareness training", "found"),
    ("enterprise architecture", "Worked as an Enterprise Architect for the bank", "found"),
    ("togaf", "Experience with TOGAF or equivalent architecture frameworks", "found"),
    ("archimate", "Knowledge of ArchiMate Enterprise Architecture Modeling Language", "found"),
    ("service-oriented architecture", "Experience working with SOA, microservices", "found"),
    ("sdlc", "Understanding of the software development life cycle", "found"),
    ("scrum", "Ran Scrum ceremonies for two teams", "found"),
    ("kanban", "Moved support work onto a Kanban board", "found"),
    ("backend development", "Built the backend for the checkout service", "found"),
    ("backend development", "Back-end development in Python", "found"),
    # the Oracle stack from the resume side (2026-10-14); bare "Oracle" is the company
    ("pl/sql", "Wrote PL/SQL packages for the billing flow", "found"),
    ("pl/sql", "Tuned plsql procedures", "found"),
    ("oracle database", "Oracle 19c, AWS RDS, Informix", "found"),
    ("oracle database", "Oracle Health is seeking a Principal AI Agent Architect", "absent"),
    ("informix", "Oracle 19c, AWS RDS, Informix", "found"),
    ("fastapi", "A FastAPI backend and a browser front end", "found"),
    ("jaspersoft", "Own the enterprise Jaspersoft reporting platform", "found"),
    ("jaspersoft", "Built JasperReports templates", "found"),
    ("oracle forms", "Oracle Forms/Reports, WebLogic", "found"),
    ("weblogic", "Oracle Forms/Reports, WebLogic", "found"),
])
def test_new_skills_detect_as_intended(skill, text, expected):
    from careerfit.analyze.matcher import detect
    assert detect(skill, SKILLS[skill], text) == expected


def test_load_ontology_rejects_bad_implications(tmp_path):
    bad = tmp_path / "skills.yaml"
    bad.write_text("pl/sql:\n  aliases: []\n  ambiguous: false\n  implies: [cobol]\n", encoding="utf-8")
    with pytest.raises(ValueError, match="implies unknown skill"):
        load_ontology(bad)
    bad.write_text("sql:\n  aliases: []\n  ambiguous: false\n  implies: [sql]\n", encoding="utf-8")
    with pytest.raises(ValueError, match="cannot imply itself"):
        load_ontology(bad)


def test_implications_run_from_the_specific_skill_to_the_broad_one():
    assert set(SKILLS["pl/sql"].implies) == {"sql", "backend development"}
    assert set(SKILLS["fastapi"].implies) == {"python", "backend development"}
    assert SKILLS["sql"].implies == ()  # SQL alone does not show back-end development
