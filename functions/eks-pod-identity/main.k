import models.io.upbound.awsm.eks.v1beta1 as eksv1beta1
import models.io.upbound.awsm.iam.v1beta1 as iamv1beta1
import json
import iam_policy

oxr = option("params").oxr # observed composite resource
_ocds = option("params").ocds # observed composed resources
_dxr = option("params").dxr # desired composite resource
dcds = option("params").dcds # desired composed resources

params = oxr.spec.parameters

_metadata = lambda name: str -> any {
    { annotations = { "krm.kcl.dev/composition-resource-name" = name }}
}

# reclaimPolicy (PV vocabulary) -> Crossplane management policies. The consumer
# contract speaks Kubernetes; only this line speaks Crossplane.
_reclaimPolicy = params?.reclaimPolicy or "Delete"
_managementPolicies = ["Create", "Observe", "Update", "LateInitialize"] if _reclaimPolicy == "Retain" else ["*"]
_providerConfigName = params?.overrides?.providerConfigName or "default"

_defaults = {
    managementPolicies = _managementPolicies
    providerConfigRef = {
        kind = "ProviderConfig"
        name = _providerConfigName
    }
}

# Inter-domain wiring: resolve the cluster from the Compute domain's published
# status via extra-resources (works nested under Cluster and standalone). The
# consumer references Compute by platform id; no Crossplane ref/selector leaks.
_computeRefId = params?.computeRef?.id or ""
_extra = option("params").extraResources or {}
_computeXRs = _extra?["compute"] or []
_computeXR = _computeXRs[0] if len(_computeXRs) > 0 else {}
_computeStatus = _computeXR?.Resource?.status or _computeXR?.status or {}
_clusterName = _computeStatus?.clusterName or ""
_oidcProviderArn = _computeStatus?.oidcProviderArn or ""
_region = params?.region or _computeStatus?.region or ""

# Hybrid policy: a curated `role` selects an L3 policy template (+ default
# ServiceAccount); overrides.policy / overrides.managedPolicyArns are the bounded
# escape hatch for arbitrary IAM.
_roleCatalog = {
    "aws-lb-controller" = {
        inlinePolicy = [{name = "aws-lb-controller", policy = json.encode(iam_policy.aws_lb_controller_policy)}]
        serviceAccount = {name = "aws-load-balancer-controller", namespace = "kube-system"}
    }
    "ebs-csi" = {
        managedPolicyArns = ["arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy"]
        serviceAccount = {name = "ebs-csi-controller-sa", namespace = "kube-system"}
    }
}
_role = params?.role or ""
_template = _roleCatalog[_role] if _role in _roleCatalog else {}

_inlinePolicy = _template?.inlinePolicy or ([{name = "custom", policy = params.overrides.policy}] if params?.overrides?.policy else None)
_managedPolicyArns = _template?.managedPolicyArns or params?.overrides?.managedPolicyArns or None
# serviceAccount: explicit param wins; otherwise the role template's default.
_sa = params?.serviceAccount or _template?.serviceAccount or {}

_federationType = params?.federationType or "pod-identity"

# IAM role trusted by the cluster's workloads. pod-identity uses the EKS Pod
# Identity service principal; irsa federates the cluster OIDC provider (the
# additive path, used once Compute publishes oidcProviderArn).
_assumeRolePolicyPodIdentity = """{"Version":"2012-10-17","Statement":[{"Sid":"AllowEksAuthToAssumeRoleForPodIdentity","Effect":"Allow","Principal":{"Service":"pods.eks.amazonaws.com"},"Action":["sts:AssumeRole","sts:TagSession"]}]}"""
_oidcHost = _oidcProviderArn.split("/")[-1] if _oidcProviderArn else ""
_assumeRolePolicy = _assumeRolePolicyPodIdentity
if _federationType == "irsa" and _oidcProviderArn:
    _assumeRolePolicy = json.encode({
        Version = "2012-10-17"
        Statement = [{
            Effect = "Allow"
            Principal = {Federated = _oidcProviderArn}
            Action = "sts:AssumeRoleWithWebIdentity"
            Condition = {StringEquals = {
                "{}:sub".format(_oidcHost) = "system:serviceaccount:{}:{}".format(_sa?.namespace or "", _sa?.name or "")
                "{}:aud".format(_oidcHost) = "sts.amazonaws.com"
            }}
        }]
    })

_items: [any] = [
    iamv1beta1.Role{
        metadata = _metadata("iamRole")
        spec = _defaults | {
            forProvider = {
                if _inlinePolicy:
                    inlinePolicy = _inlinePolicy
                if _managedPolicyArns:
                    managedPolicyArns = _managedPolicyArns
                assumeRolePolicy = _assumeRolePolicy
            }
        }
    }
]

# pod-identity: bind the role to the SA via a PodIdentityAssociation. irsa needs
# no association (the binding is the OIDC trust + the SA's role-arn annotation).
if _federationType == "pod-identity":
    _items += [
        eksv1beta1.PodIdentityAssociation{
            metadata = _metadata("podIdentityAssociation")
            spec = _defaults | {
                forProvider = {
                    if _region:
                        region = _region
                    roleArnSelector = {
                        matchControllerRef = True
                    }
                    if _clusterName:
                        clusterName = _clusterName
                    serviceAccount = _sa?.name
                    namespace = _sa?.namespace
                }
            }
        }
    ]

# Request the referenced Compute so its published status can be read.
if _computeRefId:
    _items += [{
        apiVersion: "meta.krm.kcl.dev/v1alpha1"
        kind: "ExtraResources"
        requirements: {
            "compute": {
                apiVersion: "aws.platform.upbound.io/v1alpha1"
                kind: "Compute"
                matchName: _computeRefId
            }
        }
    }]

# Structured status.
_dxr = _dxr | {
    status: {
        roleArn = _ocds?.iamRole?.Resource?.status?.atProvider?.arn
        if _clusterName:
            clusterName = _clusterName
        associationId = _ocds?.podIdentityAssociation?.Resource?.status?.atProvider?.associationId
    }
}

_items += [_dxr]
items = _items
