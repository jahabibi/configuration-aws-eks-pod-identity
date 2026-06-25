"""Composition function for the Identity (EKS Pod Identity / IRSA) cell.

Python port of the former KCL function. Reason for Python: the role->cluster
binding (PodIdentityAssociation) is gated on the cluster name, which is resolved
from the *namespaced* Compute XR via a cross-domain lookup. The function-kcl
server baked into `up` is too old to honour `matchNamespace`, so the namespaced
lookup silently returns empty and the association is never created (see repo
ISSUE-matchnamespace-function-kcl.md). The Python SDK speaks the Crossplane v2
`required_resources` mechanism, whose ResourceSelector carries a `namespace`
field, so it resolves the namespaced Compute correctly.
"""

import json

from crossplane.function import request, resource, response
from crossplane.function.proto.v1 import run_function_pb2 as fnv1

# Curated, platform-blessed permission set for the AWS LB Controller workload
# (role catalog entry "aws-lb-controller"). An L3 implementation detail.
_AWS_LB_CONTROLLER_POLICY = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": ["iam:CreateServiceLinkedRole"],
            "Resource": "*",
            "Condition": {
                "StringEquals": {
                    "iam:AWSServiceName": "elasticloadbalancing.amazonaws.com"
                }
            },
        },
        {
            "Effect": "Allow",
            "Action": [
                "ec2:DescribeAccountAttributes",
                "ec2:DescribeAddresses",
                "ec2:DescribeAvailabilityZones",
                "ec2:DescribeInternetGateways",
                "ec2:DescribeVpcs",
                "ec2:DescribeVpcPeeringConnections",
                "ec2:DescribeSubnets",
                "ec2:DescribeSecurityGroups",
                "ec2:DescribeInstances",
                "ec2:DescribeNetworkInterfaces",
                "ec2:DescribeTags",
                "ec2:GetCoipPoolUsage",
                "ec2:DescribeCoipPools",
                "elasticloadbalancing:DescribeLoadBalancers",
                "elasticloadbalancing:DescribeLoadBalancerAttributes",
                "elasticloadbalancing:DescribeListeners",
                "elasticloadbalancing:DescribeListenerCertificates",
                "elasticloadbalancing:DescribeSSLPolicies",
                "elasticloadbalancing:DescribeRules",
                "elasticloadbalancing:DescribeTargetGroups",
                "elasticloadbalancing:DescribeTargetGroupAttributes",
                "elasticloadbalancing:DescribeTargetHealth",
                "elasticloadbalancing:DescribeTags",
                "elasticloadbalancing:DescribeTrustStores",
            ],
            "Resource": "*",
        },
        {
            "Effect": "Allow",
            "Action": [
                "cognito-idp:DescribeUserPoolClient",
                "acm:ListCertificates",
                "acm:DescribeCertificate",
                "iam:ListServerCertificates",
                "iam:GetServerCertificate",
                "waf-regional:GetWebACL",
                "waf-regional:GetWebACLForResource",
                "waf-regional:AssociateWebACL",
                "waf-regional:DisassociateWebACL",
                "wafv2:GetWebACL",
                "wafv2:GetWebACLForResource",
                "wafv2:AssociateWebACL",
                "wafv2:DisassociateWebACL",
                "shield:GetSubscriptionState",
                "shield:DescribeProtection",
                "shield:CreateProtection",
                "shield:DeleteProtection",
            ],
            "Resource": "*",
        },
        {
            "Effect": "Allow",
            "Action": [
                "ec2:AuthorizeSecurityGroupIngress",
                "ec2:RevokeSecurityGroupIngress",
            ],
            "Resource": "*",
        },
        {
            "Effect": "Allow",
            "Action": ["ec2:CreateSecurityGroup"],
            "Resource": "*",
        },
        {
            "Effect": "Allow",
            "Action": ["ec2:CreateTags"],
            "Resource": "arn:aws:ec2:*:*:security-group/*",
            "Condition": {
                "StringEquals": {"ec2:CreateAction": "CreateSecurityGroup"},
                "Null": {"aws:RequestTag/elbv2.k8s.aws/cluster": "false"},
            },
        },
        {
            "Effect": "Allow",
            "Action": ["ec2:CreateTags", "ec2:DeleteTags"],
            "Resource": "arn:aws:ec2:*:*:security-group/*",
            "Condition": {
                "Null": {
                    "aws:RequestTag/elbv2.k8s.aws/cluster": "true",
                    "aws:ResourceTag/elbv2.k8s.aws/cluster": "false",
                }
            },
        },
        {
            "Effect": "Allow",
            "Action": [
                "ec2:AuthorizeSecurityGroupIngress",
                "ec2:RevokeSecurityGroupIngress",
                "ec2:DeleteSecurityGroup",
            ],
            "Resource": "*",
            "Condition": {
                "Null": {"aws:ResourceTag/elbv2.k8s.aws/cluster": "false"}
            },
        },
        {
            "Effect": "Allow",
            "Action": [
                "elasticloadbalancing:CreateLoadBalancer",
                "elasticloadbalancing:CreateTargetGroup",
            ],
            "Resource": "*",
            "Condition": {
                "Null": {"aws:RequestTag/elbv2.k8s.aws/cluster": "false"}
            },
        },
        {
            "Effect": "Allow",
            "Action": [
                "elasticloadbalancing:CreateListener",
                "elasticloadbalancing:DeleteListener",
                "elasticloadbalancing:CreateRule",
                "elasticloadbalancing:DeleteRule",
            ],
            "Resource": "*",
        },
        {
            "Effect": "Allow",
            "Action": [
                "elasticloadbalancing:AddTags",
                "elasticloadbalancing:RemoveTags",
            ],
            "Resource": [
                "arn:aws:elasticloadbalancing:*:*:targetgroup/*/*",
                "arn:aws:elasticloadbalancing:*:*:loadbalancer/net/*/*",
                "arn:aws:elasticloadbalancing:*:*:loadbalancer/app/*/*",
            ],
            "Condition": {
                "Null": {
                    "aws:RequestTag/elbv2.k8s.aws/cluster": "true",
                    "aws:ResourceTag/elbv2.k8s.aws/cluster": "false",
                }
            },
        },
        {
            "Effect": "Allow",
            "Action": [
                "elasticloadbalancing:AddTags",
                "elasticloadbalancing:RemoveTags",
            ],
            "Resource": [
                "arn:aws:elasticloadbalancing:*:*:listener/net/*/*/*",
                "arn:aws:elasticloadbalancing:*:*:listener/app/*/*/*",
                "arn:aws:elasticloadbalancing:*:*:listener-rule/net/*/*/*",
                "arn:aws:elasticloadbalancing:*:*:listener-rule/app/*/*/*",
            ],
        },
        {
            "Effect": "Allow",
            "Action": [
                "elasticloadbalancing:ModifyLoadBalancerAttributes",
                "elasticloadbalancing:SetIpAddressType",
                "elasticloadbalancing:SetSecurityGroups",
                "elasticloadbalancing:SetSubnets",
                "elasticloadbalancing:DeleteLoadBalancer",
                "elasticloadbalancing:ModifyTargetGroup",
                "elasticloadbalancing:ModifyTargetGroupAttributes",
                "elasticloadbalancing:DeleteTargetGroup",
            ],
            "Resource": "*",
            "Condition": {
                "Null": {"aws:ResourceTag/elbv2.k8s.aws/cluster": "false"}
            },
        },
        {
            "Effect": "Allow",
            "Action": ["elasticloadbalancing:AddTags"],
            "Resource": [
                "arn:aws:elasticloadbalancing:*:*:targetgroup/*/*",
                "arn:aws:elasticloadbalancing:*:*:loadbalancer/net/*/*",
                "arn:aws:elasticloadbalancing:*:*:loadbalancer/app/*/*",
            ],
            "Condition": {
                "StringEquals": {
                    "elasticloadbalancing:CreateAction": [
                        "CreateTargetGroup",
                        "CreateLoadBalancer",
                    ]
                },
                "Null": {"aws:RequestTag/elbv2.k8s.aws/cluster": "false"},
            },
        },
        {
            "Effect": "Allow",
            "Action": [
                "elasticloadbalancing:RegisterTargets",
                "elasticloadbalancing:DeregisterTargets",
            ],
            "Resource": "arn:aws:elasticloadbalancing:*:*:targetgroup/*/*",
        },
        {
            "Effect": "Allow",
            "Action": [
                "elasticloadbalancing:SetWebAcl",
                "elasticloadbalancing:ModifyListener",
                "elasticloadbalancing:AddListenerCertificates",
                "elasticloadbalancing:RemoveListenerCertificates",
                "elasticloadbalancing:ModifyRule",
            ],
            "Resource": "*",
        },
    ],
}

# Hybrid policy: a curated `role` selects an L3 policy template + default SA.
_ROLE_CATALOG = {
    "aws-lb-controller": {
        "inlinePolicy": [
            {
                "name": "aws-lb-controller",
                "policy": json.dumps(_AWS_LB_CONTROLLER_POLICY),
            }
        ],
        "serviceAccount": {
            "name": "aws-load-balancer-controller",
            "namespace": "kube-system",
        },
    },
    "ebs-csi": {
        "managedPolicyArns": [
            "arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy"
        ],
        "serviceAccount": {
            "name": "ebs-csi-controller-sa",
            "namespace": "kube-system",
        },
    },
}

_ASSUME_ROLE_POLICY_POD_IDENTITY = (
    '{"Version":"2012-10-17","Statement":[{"Sid":'
    '"AllowEksAuthToAssumeRoleForPodIdentity","Effect":"Allow","Principal":'
    '{"Service":"pods.eks.amazonaws.com"},"Action":["sts:AssumeRole",'
    '"sts:TagSession"]}]}'
)


def _resolved_compute(req: fnv1.RunFunctionRequest):
    """Resolved Compute as a dict, or None. Primary: v2 required_resources;
    fallback: deprecated extra_resources (offline CompositionTest harness)."""
    compute = request.get_required_resource(req, "compute")
    if compute is not None:
        return compute
    extra = req.extra_resources
    if "compute" in extra and len(extra["compute"].items) > 0:
        return resource.struct_to_dict(extra["compute"].items[0].resource)
    return None


def _observed(req: fnv1.RunFunctionRequest, name: str) -> dict:
    resources = req.observed.resources
    if name in resources:
        return resource.struct_to_dict(resources[name].resource)
    return {}


def compose(req: fnv1.RunFunctionRequest, rsp: fnv1.RunFunctionResponse):
    oxr = resource.struct_to_dict(req.observed.composite.resource)
    namespace = oxr.get("metadata", {}).get("namespace", "")
    params = oxr.get("spec", {}).get("parameters", {})
    overrides = params.get("overrides") or {}

    reclaim_policy = params.get("reclaimPolicy", "Delete")
    management_policies = (
        ["Create", "Observe", "Update", "LateInitialize"]
        if reclaim_policy == "Retain"
        else ["*"]
    )
    provider_config_name = overrides.get("providerConfigName", "default")
    defaults = {
        "managementPolicies": management_policies,
        "providerConfigRef": {
            "kind": "ProviderConfig",
            "name": provider_config_name,
        },
    }

    # Inter-domain wiring: resolve the cluster from Compute's published status.
    compute_ref_id = (params.get("computeRef") or {}).get("id", "")
    if compute_ref_id:
        response.require_resources(
            rsp,
            name="compute",
            api_version="aws.platform.upbound.io/v1alpha1",
            kind="Compute",
            match_name=compute_ref_id,
            namespace=namespace,
        )

    compute_status = (_resolved_compute(req) or {}).get("status", {})
    cluster_name = compute_status.get("clusterName", "")
    oidc_provider_arn = compute_status.get("oidcProviderArn", "")
    region = params.get("region") or compute_status.get("region", "")

    # Role catalog: curated role -> template; else overrides escape hatch.
    role = params.get("role", "")
    template = _ROLE_CATALOG.get(role, {})

    inline_policy = template.get("inlinePolicy")
    if inline_policy is None and overrides.get("policy"):
        inline_policy = [{"name": "custom", "policy": overrides["policy"]}]
    managed_policy_arns = template.get("managedPolicyArns") or overrides.get(
        "managedPolicyArns"
    )
    service_account = (
        params.get("serviceAccount") or template.get("serviceAccount") or {}
    )

    federation_type = params.get("federationType", "pod-identity")

    # IAM role trust policy: pod-identity service principal, or IRSA OIDC.
    assume_role_policy = _ASSUME_ROLE_POLICY_POD_IDENTITY
    if federation_type == "irsa" and oidc_provider_arn:
        oidc_host = oidc_provider_arn.split("/")[-1]
        assume_role_policy = json.dumps(
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {"Federated": oidc_provider_arn},
                        "Action": "sts:AssumeRoleWithWebIdentity",
                        "Condition": {
                            "StringEquals": {
                                "{}:sub".format(oidc_host): (
                                    "system:serviceaccount:{}:{}".format(
                                        service_account.get("namespace", ""),
                                        service_account.get("name", ""),
                                    )
                                ),
                                "{}:aud".format(oidc_host): "sts.amazonaws.com",
                            }
                        },
                    }
                ],
            }
        )

    # IAM Role (always emitted).
    role_for_provider = {"assumeRolePolicy": assume_role_policy}
    if inline_policy:
        role_for_provider["inlinePolicy"] = inline_policy
    if managed_policy_arns:
        role_for_provider["managedPolicyArns"] = managed_policy_arns
    resource.update(
        rsp.desired.resources["iamRole"],
        {
            "apiVersion": "iam.aws.m.upbound.io/v1beta1",
            "kind": "Role",
            "spec": {**defaults, "forProvider": role_for_provider},
        },
    )

    # pod-identity: bind the role to the SA. Gated on cluster_name (resolved from
    # Compute) — emitting it empty makes the provider's observe fail with
    # "clusterName must not be empty".
    if federation_type == "pod-identity" and cluster_name:
        association_for_provider = {
            "roleArnSelector": {"matchControllerRef": True},
            "clusterName": cluster_name,
            "serviceAccount": service_account.get("name"),
            "namespace": service_account.get("namespace"),
        }
        if region:
            association_for_provider["region"] = region
        resource.update(
            rsp.desired.resources["podIdentityAssociation"],
            {
                "apiVersion": "eks.aws.m.upbound.io/v1beta1",
                "kind": "PodIdentityAssociation",
                "spec": {**defaults, "forProvider": association_for_provider},
            },
        )

    # Structured status — guard nulls (XRD types these as string; an explicit
    # null fails status validation and blocks readiness).
    status = {}
    role_arn = (
        _observed(req, "iamRole").get("status", {}).get("atProvider", {}).get("arn")
    )
    association_id = (
        _observed(req, "podIdentityAssociation")
        .get("status", {})
        .get("atProvider", {})
        .get("associationId")
    )
    if role_arn:
        status["roleArn"] = role_arn
    if cluster_name:
        status["clusterName"] = cluster_name
    if association_id:
        status["associationId"] = association_id
    if status:
        resource.update(
            rsp.desired.composite,
            {
                "apiVersion": oxr.get("apiVersion"),
                "kind": oxr.get("kind"),
                "status": status,
            },
        )
