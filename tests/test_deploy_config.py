"""The deploy setup's safety properties, checked in code like the architecture boundaries.

A deploy pipeline is easy to loosen by accident: a wildcard in the trust policy, a stored key, a
deploy that runs before the tests, or a permission wide enough for CI to grant itself more. Each of
those is a failing build here.
"""

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).parent.parent
CI = ROOT / ".github" / "workflows" / "ci.yml"
ROLE = ROOT / "infra" / "github-deploy-role.yaml"
APP = ROOT / "template.yaml"

IAM_CHANGES = {"iam:CreateRole", "iam:AttachRolePolicy", "iam:DetachRolePolicy", "iam:PutRolePolicy",
               "iam:DeleteRolePolicy", "iam:UpdateAssumeRolePolicy", "iam:PutRolePermissionsBoundary",
               "iam:DeleteRolePermissionsBoundary", "iam:CreatePolicyVersion", "iam:SetDefaultPolicyVersion"}
UNSCOPED_LOOKUPS = {"cloudformation:ValidateTemplate", "cloudformation:GetTemplateSummary",
                    "ecr:GetAuthorizationToken", "logs:DescribeLogGroups"}


class _CloudFormationLoader(yaml.SafeLoader):
    """safe_load plus CloudFormation's short tags (!Sub, !If, !Ref ...), kept as plain values."""


def _any_tag(loader, _suffix, node):
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node, deep=True)
    return loader.construct_mapping(node, deep=True)


_CloudFormationLoader.add_multi_constructor("!", _any_tag)


def _cfn(path: Path) -> dict:
    return yaml.load(path.read_text(encoding="utf-8"), Loader=_CloudFormationLoader)  # noqa: S506 - SafeLoader subclass


def workflow() -> dict:
    return yaml.safe_load(CI.read_text(encoding="utf-8"))


def bootstrap() -> dict:
    return _cfn(ROLE)


def deploy_statements() -> list[dict]:
    return bootstrap()["Resources"]["DeployRole"]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"]


def _as_list(value) -> list:
    return value if isinstance(value, list) else [value]


# ---- the workflow ----

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


def test_the_budget_email_is_a_masked_secret():
    # sam deploy prints every parameter value, and a public repo's logs are public
    deploy = next(s for s in workflow()["jobs"]["deploy"]["steps"] if s.get("name") == "Deploy")
    assert deploy["env"]["BUDGET_EMAIL"] == "${{ secrets.BUDGET_EMAIL }}"
    assert "vars.BUDGET_EMAIL" not in CI.read_text(encoding="utf-8")


def test_deploy_pushes_to_the_bootstrap_repository_not_a_companion_stack():
    text = CI.read_text(encoding="utf-8")
    assert "--image-repository" in text
    assert "--resolve-image-repos" not in text  # a companion stack needs S3 and UpdateStack rights
    assert "--resolve-s3" not in text


def test_pending_deploys_queue_instead_of_replacing_each_other():
    # the default (queue: single) keeps one pending job, so a late older run could replace the newest one
    assert workflow()["jobs"]["deploy"]["concurrency"] == {
        "group": "deploy-production", "cancel-in-progress": False, "queue": "max"}


def test_only_the_head_of_main_deploys():
    """Deploys queue in arrival order, not commit order: a late or re-run older commit must not roll back."""
    steps = workflow()["jobs"]["deploy"]["steps"]
    check = next(i for i, s in enumerate(steps) if s.get("id") == "head")
    assert "git ls-remote --exit-code origin refs/heads/main" in steps[check]["run"]
    assert '"$head" = "$GITHUB_SHA"' in steps[check]["run"]
    assert steps[:check] == [{"uses": "actions/checkout@v4"}]  # nothing touches AWS before the check
    for step in steps[check + 1:]:
        assert step.get("if") == "steps.head.outputs.current == 'true'", step["name"]


def test_the_running_image_is_tagged_live_after_each_deploy():
    steps = workflow()["jobs"]["deploy"]["steps"]
    names = [s["name"] for s in steps if "name" in s]
    assert names.index("Tag the running image as live") == names.index("Deploy") + 1
    tag = steps[[s.get("name") for s in steps].index("Tag the running image as live")]["run"]
    assert "Code.ResolvedImageUri" in tag  # the digest Lambda runs, not whatever was pushed last
    assert "--image-tag live --image-digest \"$digest\"" in tag


# ---- the bootstrap's trust and identity ----

def test_trust_policy_admits_one_repo_on_one_branch_with_no_wildcards():
    statement = bootstrap()["Resources"]["DeployRole"]["Properties"]["AssumeRolePolicyDocument"]["Statement"]
    assert len(statement) == 1
    condition = statement[0]["Condition"]
    assert set(condition) == {"StringEquals"}  # never StringLike: no wildcard can widen it
    assert condition["StringEquals"]["token.actions.githubusercontent.com:aud"] == "sts.amazonaws.com"
    assert condition["StringEquals"]["token.actions.githubusercontent.com:sub"] == \
        "repo:${GitHubRepo}:ref:refs/heads/${Branch}"
    params = bootstrap()["Parameters"]
    assert (params["GitHubRepo"]["Default"], params["Branch"]["Default"]) == ("panneerselvamsathish/careerfit", "main")


def test_the_ci_parts_can_be_left_out_but_are_in_by_default():
    """Accounts that deny iam:*Provider* still get what the app stack needs; CI is on unless turned off."""
    template = bootstrap()
    assert template["Parameters"]["GitHubDeployRole"]["Default"] == "true"
    assert template["Conditions"]["MakeRole"] == ["GitHubDeployRole", "true"]
    assert template["Conditions"]["MakeProvider"] == ["MakeRole", ["CreateOidcProvider", "true"]]
    resources = template["Resources"]
    assert resources["DeployRole"]["Condition"] == "MakeRole"
    assert resources["GitHubOidcProvider"]["Condition"] == "MakeProvider"
    assert template["Outputs"]["RoleArn"]["Condition"] == "MakeRole"
    # template.yaml needs these whatever the setting: --image-repository and the PermissionsBoundary
    for always in ("ImageRepository", "ExecutionRoleBoundary"):
        assert "Condition" not in resources[always], always


def test_the_deploy_role_is_named_outside_the_app_resources():
    name = bootstrap()["Resources"]["DeployRole"]["Properties"]["RoleName"]
    assert not name.startswith("${AppStackName}-"), "no app-scoped permission may ever match the deploy role"


# ---- the deploy role's permissions ----

def test_every_allow_names_careerfit_resources_exactly():
    for statement in (s for s in deploy_statements() if s["Effect"] == "Allow"):
        actions = _as_list(statement["Action"])
        assert not any(a == "*" or a.endswith(":*") for a in actions), statement["Sid"]
        resources = _as_list(statement["Resource"])
        if "*" in resources:
            assert set(actions) <= UNSCOPED_LOOKUPS, statement["Sid"]
            continue
        for resource in resources:
            # a stack wildcard such as stack/${AppStackName}-* would also cover the bootstrap stack
            assert ":stack/${AppStackName}-" not in resource, statement["Sid"]
            assert "${AppStackName}" in resource or resource in ("ImageRepository.Arn",) \
                or "transform/Serverless" in resource, statement["Sid"]


def test_iam_changes_are_allowed_only_while_the_boundary_is_attached():
    for statement in (s for s in deploy_statements() if s["Effect"] == "Allow"):
        changes = IAM_CHANGES & set(_as_list(statement["Action"]))
        if not changes:
            continue
        # PutRolePermissionsBoundary is allowed only to attach this same boundary (AWS's delegation pattern)
        assert changes <= {"iam:CreateRole", "iam:AttachRolePolicy", "iam:DetachRolePolicy", "iam:PutRolePolicy",
                           "iam:DeleteRolePolicy", "iam:PutRolePermissionsBoundary"}, statement["Sid"]
        assert statement["Condition"]["StringEquals"]["iam:PermissionsBoundary"] == "ExecutionRoleBoundary"
        assert statement["Resource"].endswith("role/${AppStackName}-WebFunctionRole-*")


def test_explicit_denies_protect_the_deploy_role_and_the_boundary():
    denies = [s for s in deploy_statements() if s["Effect"] == "Deny"]
    assert len(denies) == 3
    self_protection = next(s for s in denies if s["Action"] == "iam:*")
    assert set(self_protection["Resource"]) == {
        "arn:aws:iam::${AWS::AccountId}:role/github-actions-${AppStackName}-deploy", "ExecutionRoleBoundary"}
    never_remove = next(s for s in denies if s["Action"] == "iam:DeleteRolePermissionsBoundary")
    assert never_remove["Resource"] == "*" and "Condition" not in never_remove
    only_this_boundary = next(s for s in denies if isinstance(s["Action"], list))
    assert set(only_this_boundary["Action"]) == {"iam:CreateRole", "iam:PutRolePermissionsBoundary"}
    assert only_this_boundary["Resource"] == "*"
    # StringNotEquals also matches a request with no boundary, so a boundary-less role is denied too
    assert only_this_boundary["Condition"] == {"StringNotEquals": {"iam:PermissionsBoundary": "ExecutionRoleBoundary"}}


# ---- the boundary, the image repository and the app template ----

def test_the_boundary_allows_only_writing_the_functions_own_logs():
    statements = bootstrap()["Resources"]["ExecutionRoleBoundary"]["Properties"]["PolicyDocument"]["Statement"]
    allowed = {a for s in statements for a in _as_list(s["Action"])}
    assert allowed == {"logs:CreateLogStream", "logs:PutLogEvents"}
    assert all("/aws/lambda/${AppStackName}-web" in s["Resource"] for s in statements)


def test_cleanup_never_expires_the_running_image():
    repository = bootstrap()["Resources"]["ImageRepository"]["Properties"]
    assert repository["ImageTagMutability"] == "MUTABLE"  # CI moves "live" to each deployed image
    rules = sorted(json.loads(repository["LifecyclePolicy"]["LifecyclePolicyText"])["rules"],
                   key=lambda r: r["rulePriority"])
    # the image tagged "live" is claimed first; ECR never lets a lower-priority rule expire it
    assert rules[0]["selection"]["tagStatus"] == "tagged"
    assert rules[0]["selection"]["tagPrefixList"] == ["live"]
    assert rules[0]["selection"]["countNumber"] >= 1
    assert all(r["selection"]["tagStatus"] != "any" for r in rules[:-1]), "a tagStatus any rule must come last"


def test_only_careerfits_function_may_pull_the_image():
    policy = bootstrap()["Resources"]["ImageRepository"]["Properties"]["RepositoryPolicyText"]["Statement"]
    assert len(policy) == 1
    assert policy[0]["Principal"] == {"Service": "lambda.amazonaws.com"}
    assert policy[0]["Condition"]["StringLike"]["aws:sourceArn"].endswith("function:${AppStackName}-web")


def test_the_function_carries_the_boundary():
    function = _cfn(APP)["Resources"]["WebFunction"]["Properties"]
    assert function["PermissionsBoundary"] == \
        "arn:aws:iam::${AWS::AccountId}:policy/${AWS::StackName}-execution-boundary"
