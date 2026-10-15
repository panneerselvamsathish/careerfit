"""The deploy setup's safety properties, checked in code like the architecture boundaries.

A deploy pipeline is easy to loosen by accident (a wildcard in the trust policy, a stored key, a
deploy that runs before the tests). These tests make each of those a failing build.
"""

from pathlib import Path

import yaml

ROOT = Path(__file__).parent.parent
CI = ROOT / ".github" / "workflows" / "ci.yml"
ROLE = ROOT / "infra" / "github-deploy-role.yaml"


class _CloudFormationLoader(yaml.SafeLoader):
    """safe_load plus CloudFormation's short tags (!Sub, !If, !Ref ...), kept as plain values."""


def _any_tag(loader, _suffix, node):
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node, deep=True)
    return loader.construct_mapping(node, deep=True)


_CloudFormationLoader.add_multi_constructor("!", _any_tag)


def workflow() -> dict:
    return yaml.safe_load(CI.read_text(encoding="utf-8"))


def role_template() -> dict:
    return yaml.load(ROLE.read_text(encoding="utf-8"), Loader=_CloudFormationLoader)  # noqa: S506 - SafeLoader subclass


def test_deploy_runs_only_after_tests_and_only_for_main():
    deploy = workflow()["jobs"]["deploy"]
    assert deploy["needs"] == "test"
    assert "github.event_name == 'push'" in deploy["if"]
    assert "github.ref == 'refs/heads/main'" in deploy["if"]
    assert "vars.AWS_DEPLOY_ROLE_ARN != ''" in deploy["if"]  # an unconnected repo stays green


def test_only_the_deploy_job_can_request_an_oidc_token():
    wf = workflow()
    assert wf["permissions"] == {"contents": "read"}
    assert wf["jobs"]["deploy"]["permissions"] == {"contents": "read", "id-token": "write"}
    assert "permissions" not in wf["jobs"]["test"]


def test_no_aws_keys_are_stored_or_read_anywhere():
    text = CI.read_text(encoding="utf-8")
    for forbidden in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "aws-access-key-id", "secrets.AWS"):
        assert forbidden not in text
    sign_in = next(s for s in workflow()["jobs"]["deploy"]["steps"]
                   if s.get("uses", "").startswith("aws-actions/configure-aws-credentials"))
    assert sign_in["with"]["role-to-assume"] == "${{ vars.AWS_DEPLOY_ROLE_ARN }}"


def test_trust_policy_admits_one_repo_on_one_branch_with_no_wildcards():
    statement = role_template()["Resources"]["DeployRole"]["Properties"]["AssumeRolePolicyDocument"]["Statement"]
    assert len(statement) == 1
    condition = statement[0]["Condition"]
    assert set(condition) == {"StringEquals"}  # never StringLike: no wildcard can widen it
    assert condition["StringEquals"]["token.actions.githubusercontent.com:aud"] == "sts.amazonaws.com"
    assert condition["StringEquals"]["token.actions.githubusercontent.com:sub"] == \
        "repo:${GitHubRepo}:ref:refs/heads/${Branch}"
    params = role_template()["Parameters"]
    assert (params["GitHubRepo"]["Default"], params["Branch"]["Default"]) == ("panneerselvamsathish/careerfit", "main")


def test_deploy_permissions_are_scoped_to_careerfit_resources():
    unscoped_ok = {"cloudformation:ValidateTemplate", "cloudformation:GetTemplateSummary",
                   "ecr:GetAuthorizationToken", "logs:DescribeLogGroups"}
    policy = role_template()["Resources"]["DeployRole"]["Properties"]["Policies"][0]["PolicyDocument"]
    for statement in policy["Statement"]:
        actions = statement["Action"] if isinstance(statement["Action"], list) else [statement["Action"]]
        assert not any(a == "*" or a.endswith(":*") for a in actions), statement["Sid"]
        resources = statement["Resource"] if isinstance(statement["Resource"], list) else [statement["Resource"]]
        if "*" in resources:
            assert set(actions) <= unscoped_ok, statement["Sid"]
        else:
            # every scoped resource is named after the app stack (or is the SAM transform)
            assert all("${AppStackName}" in r or "transform/Serverless" in r for r in resources), statement["Sid"]
