from collections.abc import Mapping

from careerfit.analyze.ontology import load_ontology
from pathlib import Path
import pytest
from pydantic import ValidationError

def test_real_skills_file_loads():
    SKILLS_FILE = Path(__file__).parent.parent / "src" / "careerfit" / "ontology" / "skills.yaml"
    skills = load_ontology(SKILLS_FILE)
    assert skills is not None
    assert isinstance(skills, Mapping)  # an Ontology: read-only, with its mention index built once
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
    # DLP spelled out as "leakage" (2026-10-16, found on the live site)
    ("dlp", "Security: data-leakage prevention, secret scanning", "found"),
    ("dlp", "Data leakage prevention controls for agent tools", "found"),
    ("dlp", "Rolled out data loss prevention policies", "found"),
    # from the CVS Health Distinguished Engineer JD (2026-10-17)
    ("responsible ai", "Establishes responsible AI, security, compliance, and risk management practices", "found"),
    ("ai governance", "AI governance, cybersecurity and product security review", "found"),
    ("platform engineering", "across software engineering, enterprise architecture, digital transformation, or platform engineering", "found"),
    ("digital transformation", "across software engineering, enterprise architecture, digital transformation, or platform engineering", "found"),
    ("intelligent automation", "Strong understanding of Generative AI, Agentic AI, intelligent automation", "found"),
    ("cloud computing", "Deep expertise in enterprise architecture, cloud platforms, distributed systems", "found"),
    ("cloud computing", "Experience with Salesforce Marketing Cloud", "absent"),
    # from the GEICO Staff Engineer, Applied AI JD (2026-10-17)
    ("document intelligence", "high-value enterprise workflows including automation, document intelligence, decision support", "found"),
    ("workflow orchestration", "Strong understanding of agent architectures, workflow orchestration, retrieval-augmented generation", "found"),
    ("ai safety", "Familiarity with AI safety practices, evaluation frameworks, monitoring", "found"),
    ("fraud detection", "Background in document intelligence, fraud or anomaly modeling", "absent"),  # "fraud or anomaly modeling"
    ("fraud detection", "Built fraud detection models for card payments", "found"),
    ("anomaly detection", "Background in document intelligence, fraud or anomaly modeling", "found"),
    ("performance optimization", "SQL performance tuning, ETL design, data modeling", "found"),
    # bare "reliability engineering" also names hardware and mechanical work (Copilot review on #24)
    ("sre", "Strong competency in distributed systems, service design, performance optimization, and reliability engineering", "absent"),
    ("sre", "Reliability engineering and fatigue testing of mechanical pumps", "absent"),
    ("sre", "Site reliability engineering for the payments platform", "found"),
    ("spring ai", "Experience deploying AI components in Java ecosystems including Spring AI, LangChain4j, or Embabel", "found"),
    ("langchain4j", "Experience deploying AI components in Java ecosystems including Spring AI, LangChain4j, or Embabel", "found"),
    ("embabel", "Experience deploying AI components in Java ecosystems including Spring AI, LangChain4j, or Embabel", "found"),
    # bare "insurance" is ambiguous: benefits prose can sit inside a requirements list (Copilot review on #24)
    ("insurance", "Experience with insurance, financial services, or other regulated industries", "unclear"),
    ("insurance", "We offer health insurance and a 401(k).", "unclear"),
    ("insurance", "Ten years in the insurance industry", "found"),
    ("insurance", "Pricing models for property and casualty lines", "found"),
    ("financial services", "Experience with insurance, financial services, or other regulated industries", "found"),
    ("regulatory compliance", "Familiarity with AI safety practices, evaluation frameworks, monitoring, and regulatory compliance", "found"),
    ("sox compliance", "AI governance, SOX controls, audit logging", "found"),
    ("sox compliance", "Originated and led a SOX compliance initiative", "found"),
    # bare "sox" also names an audio tool and a baseball team (Copilot review on #24)
    ("sox compliance", "Built speech preprocessing pipelines using SoX", "absent"),
    ("sox compliance", "Built ticketing analytics for the Boston Red Sox", "absent"),
    # from the GEICO Senior Engineer - Applied AI JD (2026-10-17)
    ("langsmith", "modern AI frameworks such as LangChain, LangGraph, LangSmith, LlamaIndex, Hugging Face", "found"),
    ("hugging face", "modern AI frameworks such as LangChain, LangGraph, LangSmith, LlamaIndex, Hugging Face", "found"),
    ("anthropic api", "and OpenAI or Anthropic APIs", "found"),
    ("anthropic api", "Anthropic SDK, Claude on Amazon Bedrock, Claude Code", "found"),
    ("contact center", "core contact center experiences for sales, service and claims operations", "found"),
    ("conversational ai", "automation, document intelligence, decision support, and intelligent assistants", "found"),
    # "virtual assistants" and "virtual agents" also name people (Copilot review on #24)
    ("conversational ai", "Managed virtual assistants for scheduling and inbox management", "absent"),
    ("conversational ai", "Scheduled 200 virtual agents working from home across three time zones", "absent"),
    ("software engineering", "4+ years of professional software engineering or applied machine learning", "found"),
    ("software engineering", "**Lead Software Engineer**", "found"),
    # the plural names colleagues, not a skill the JD asks for
    ("software engineering", "Partner with product managers and software engineers", "absent"),
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
    assert SKILLS["aws"].implies == ("cloud computing",)  # AWS and Azure are cloud platforms by definition
    assert SKILLS["azure"].implies == ("cloud computing",)
    assert SKILLS["cloud computing"].implies == ()  # and the broad skill never implies a specific one
    assert SKILLS["banking"].implies == ("financial services",)
    assert SKILLS["sox compliance"].implies == ("regulatory compliance",)
    assert SKILLS["spring ai"].implies == SKILLS["langchain4j"].implies == ("java",)
    assert SKILLS["embabel"].implies == ()  # JVM, but Kotlin or Java


def test_sox_the_tool_or_the_team_shows_no_compliance_even_through_implication():
    from datetime import datetime
    from careerfit.analyze.observations import build_observations
    from careerfit.facts.schema import Coverage, SkillStatus
    coverage = Coverage(source_format="txt", pages_total=None, pages_with_text=None, chars_extracted=11,
                        known_blind_spots=())
    jd = "Requirements:\n- SOX compliance\n- Regulatory compliance"
    def status(resume):
        observed = build_observations(resume, coverage, jd, SKILLS, datetime(2026, 10, 17))
        return {o.skill: o.status for o in observed}
    unrelated = status("Built speech preprocessing pipelines using SoX\nBuilt ticketing analytics for the Boston Red Sox")
    assert unrelated["sox compliance"] == unrelated["regulatory compliance"] == SkillStatus.GAP
    shown = status("Originated and led a SOX compliance initiative")
    assert shown["sox compliance"] == shown["regulatory compliance"] == SkillStatus.MATCHED


# ---- curated + imported skill lists (A1.2) ----

def _write(path, text):
    path.write_text(text, encoding="utf-8")
    return path


CURATED = """
kubernetes:
  aliases: ["k8s"]
  ambiguous: false
"""


def test_imported_skills_join_the_list_and_the_curated_file_always_wins(tmp_path):
    from careerfit.analyze.ontology import load_ontology
    curated = _write(tmp_path / "skills.yaml", CURATED)
    imported = _write(tmp_path / "skills_imported.yaml", """
rancher:
  aliases: ["rancher kubernetes engine"]
  ambiguous: false
  sources: [onet]
Kubernetes:
  aliases: ["kube"]
  ambiguous: false
  sources: [esco]
helm charts:
  aliases: ["K8S"]
  ambiguous: false
  sources: [onet, esco]
""")
    merged = load_ontology(curated, imported=imported)
    assert list(merged) == ["kubernetes", "rancher"]  # curated first; collisions dropped whole
    assert merged["kubernetes"].sources == ("curated",)
    assert merged["rancher"].sources == ("onet",)


@pytest.mark.parametrize(("imported", "message"), [
    ("x tool:\n  aliases: []\n  ambiguous: false\n  implies: [kubernetes]\n  sources: [onet]\n", "may not imply"),
    ("x tool:\n  aliases: []\n  ambiguous: false\n  sources: [curated]\n", "cannot have source 'curated'"),
    ("x tool:\n  aliases: [same]\n  ambiguous: false\n  sources: [onet]\n"
     "y tool:\n  aliases: [Same]\n  ambiguous: false\n  sources: [esco]\n", "shares a name or alias"),
])
def test_bad_imported_entries_are_refused(tmp_path, imported, message):
    from careerfit.analyze.ontology import load_ontology
    curated = _write(tmp_path / "skills.yaml", CURATED)
    with pytest.raises(ValueError, match=message):
        load_ontology(curated, imported=_write(tmp_path / "skills_imported.yaml", imported))


def test_a_non_ascii_name_or_alias_is_refused(tmp_path):
    # The matcher folds ASCII case only, so a non-ASCII term could silently never match.
    from careerfit.analyze.ontology import load_ontology
    bad = _write(tmp_path / "skills.yaml", 'café tools:\n  aliases: []\n  ambiguous: false\n')
    with pytest.raises(ValueError, match="non-ASCII"):
        load_ontology(bad)


def test_the_packaged_lists_load_together():
    from careerfit.analyze.ontology import IMPORTED_SKILLS, load_default_ontology
    assert IMPORTED_SKILLS.exists()
    curated_only = load_default_ontology(with_imported=False)
    merged = load_default_ontology()
    assert list(merged)[:len(curated_only)] == list(curated_only)  # curated skills first, unchanged
    assert all(merged[name] == curated_only[name] for name in curated_only)
