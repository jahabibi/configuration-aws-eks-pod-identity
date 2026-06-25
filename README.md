# AWS EKS Pod Identity Configuration

This repository contains an Upbound project, tailored for users establishing their initial control plane with [Upbound](https://cloud.upbound.io). This configuration provisions AWS cloud identities for Kubernetes workloads (EKS Pod Identity or IRSA) behind a clean, intent-based API.

## Overview

The core components of a custom API in [Upbound Project](https://docs.upbound.io/learn/control-plane-project/) include:

- **CompositeResourceDefinition (XRD):** Defines the API's structure.
- **Composition(s):** Configures the Functions Pipeline
- **Embedded Function(s):** Encapsulates the Composition logic and implementation within a self-contained, reusable unit

In this specific configuration, the API contains:

- **an [Identity](/apis/podidentities/definition.yaml) custom resource type** (`kind: Identity`, namespaced).
- **Composition:** Configured in [/apis/podidentities/composition.yaml](/apis/podidentities/composition.yaml)
- **Embedded Function:** The Composition logic is encapsulated within the Python [embedded function](/functions/eks-pod-identity-py/main.py)

## What changed in this rework

This configuration was reworked to remove leaky AWS/Crossplane APIs from the contract and present a clean abstraction. The headline changes versus `main`:

- **`kind: PodIdentity` → `kind: Identity`** (plural `identities`). The API now models *granting a workload a cloud identity*, with the federation mechanism (Pod Identity vs IRSA) as an implementation detail rather than leaked API surface.
- **Embedded function ported from KCL to Python** (`functions/eks-pod-identity/main.k` → `functions/eks-pod-identity-py/main.py`). The role→cluster binding (`PodIdentityAssociation`) needs the cluster name resolved from the *namespaced* `Compute` XR via a cross-domain lookup. The `function-kcl` server bundled in `up` is too old to honour `matchNamespace`, so the namespaced lookup silently returned empty and the association was never created. The Python SDK speaks the Crossplane v2 `required_resources` mechanism, whose `ResourceSelector` carries a `namespace` field, and resolves the namespaced `Compute` correctly.
- **Cluster is referenced by platform id, not Crossplane refs/selectors.** `computeRef.id` names a `Compute` (cell), and the composition resolves its published `status` (cluster name, region, OIDC provider ARN) — no `clusterNameRef`/`clusterNameSelector` machinery in the contract.
- **Permissions are curated, not hand-rolled.** A `role` selects a platform-blessed policy template plus a default ServiceAccount. Arbitrary IAM is still possible through a bounded `overrides` escape hatch.
- **Crossplane vocabulary no longer leaks.** `managementPolicies`/`providerConfigName` are replaced by `reclaimPolicy` (`Delete`/`Retain`, borrowed from the PersistentVolume vocabulary) and an optional `overrides.providerConfigName`.
- **Dependency bump:** `configuration-aws-eks` pinned to `v3.0.0-dev.11`.

## The Identity API

```yaml
apiVersion: aws.platform.upbound.io/v1alpha1
kind: Identity
metadata:
  name: configuration-aws-eks-pod-identity
  namespace: default
spec:
  parameters:
    federationType: pod-identity     # pod-identity (default) | irsa
    computeRef:
      id: my-compute                 # platform id of the target Compute (cluster)
    role: ebs-csi                     # curated permission set + default ServiceAccount
    # region: us-west-2              # optional; resolved from Compute when omitted
    # serviceAccount:               # optional; the curated role supplies a default
    #   name: my-controller
    #   namespace: kube-system
    # reclaimPolicy: Delete         # Delete (default) | Retain
    # overrides:                    # bounded escape hatch for unsupported cases
    #   policy: '{ ... raw IAM JSON ... }'
    #   managedPolicyArns: [ ... ]
    #   providerConfigName: default
```

### Spec parameters

| Field | Required | Description |
| --- | --- | --- |
| `computeRef.id` | yes | Platform id (metadata name) of the `Compute` this identity targets. Cluster name/region/OIDC are resolved from its published status. |
| `federationType` | no (default `pod-identity`) | How the ServiceAccount federates: `pod-identity` (EKS Pod Identity) or `irsa` (OIDC web-identity). |
| `role` | no | Selects a curated permission set for a well-known workload. The function currently ships templates for `aws-lb-controller` and `ebs-csi`; the API also advertises `external-dns`, `cert-manager`, and `cluster-autoscaler`. |

> **TODO:** The `role` enum advertises five workloads, but the function's role catalog (`_ROLE_CATALOG` in [`main.py`](/functions/eks-pod-identity-py/main.py)) only implements `aws-lb-controller` and `ebs-csi`. Selecting `external-dns`, `cert-manager`, or `cluster-autoscaler` currently emits an IAM role with no attached policy (unless `overrides.policy`/`overrides.managedPolicyArns` is set). Add curated templates for these entries, or trim the enum to match the catalog.
| `serviceAccount` | no | The Kubernetes ServiceAccount granted the identity. Optional when `role` is set (the template supplies a default). |
| `region` | no | Cloud region; resolved from `Compute` when omitted. |
| `reclaimPolicy` | no (default `Delete`) | Outcome intent. `Retain` maps to non-destructive Crossplane management policies. |
| `overrides.policy` | no | Raw IAM policy document (JSON) for cases no curated `role` covers. |
| `overrides.managedPolicyArns` | no | Managed policy ARNs to attach (escape hatch). |
| `overrides.providerConfigName` | no (default `default`) | Crossplane `ProviderConfig` for account/credential selection. |

### Status

| Field | Description |
| --- | --- |
| `roleArn` | ARN of the IAM role backing this identity. |
| `clusterName` | Name of the cluster the identity targets. |
| `associationId` | EKS Pod Identity association id (pod-identity federation). |

## How It Works

At a high level, EKS Pod Identity allows you to use the AWS API to define permissions that specific Kubernetes service accounts should have in AWS:

Setting up Pod Identity starts by installing an add-on:
https://github.com/aws/eks-pod-identity-agent

```bash
aws eks create-addon \
  --cluster-name cluster-name \
  --addon-name eks-pod-identity-agent
```

This sets up a new DaemonSet in the kube-system namespace:

```bash
$ kubectl get daemonset -n kube-system
NAME                     DESIRED   CURRENT   READY   UP-TO-DATE   AVAILABLE   NODE SELECTOR   AGE
eks-pod-identity-agent   2         2         2       2            2           <none>
```

![pod-identity](images/s3-access-podidentity.png)

### EKS Pod Identity at a glance

```bash
aws eks create-pod-identity-association \
  --cluster-name your-cluster \
  --namespace default \
  --service-account pod-service-account \
  --role-arn arn:aws:iam::012345678901:role/YourPodRole
```

Here, YourPodRole has the following trust policy:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {
      "Service": "pods.eks.amazonaws.com"
    },
    "Action": ["sts:AssumeRole","sts:TagSession"]
  }]
}
```

Once you've run the commands to configure Pod Identity, any pod that runs under the pod-service-account service account magically has access to AWS resources, through temporary Security Token Service (STS) credentials:

```bash
$ kubectl apply -f - <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: pod-with-aws-access
spec:
  serviceAccountName: pod-service-account
  containers:
  - name: main
    image: public.ecr.aws/aws-cli/aws-cli
    command: ["sleep", "infinity"]
EOF

$ kubectl exec pod/pod-with-aws-access -- aws sts get-caller-identity
{
    "UserId": "XXXX",
    "Account": "012345678901",
    "Arn": "arn:aws:sts::012345678901:assumed-role/YourPodRole/eks-cluster-pod-xxx"
}
```

For a given EKS cluster, you can easily see which pods have access to AWS resources using eks:ListPodIdentityAssociations:

```bash
aws eks list-pod-identity-associations --cluster-name your-cluster

{
  "associations": [{
    {
            "clusterName": "your-cluster",
            "namespace": "default",
            "serviceAccount": "pod-service-account",
            "associationArn": "arn:aws:eks:us-east-1:012345678901:podidentityassociation/your-cluster/a-0123",
            "associationId": "a-0123"
        },

  }]
}
```

Then, you can use eks:DescribePodIdentityAssociation to retrieve the ARN of the role it maps to:

```bash
aws eks describe-pod-identity-association \
  --cluster-name your-cluster \
  --association-id a-0123

{
    "association": {
        "clusterName": "your-cluster",
        "namespace": "default",
        "serviceAccount": "pod-service-account",
        "roleArn": "arn:aws:iam::012345678901:role/YourRole"
    }
}
```

## Testing

The configuration can be tested using:

- `up composition render --xrd=apis/podidentities/definition.yaml apis/podidentities/composition.yaml examples/podidentity/pod-identity-xr.yaml` to render the composition
- `up composition render --xrd=apis/podidentities/definition.yaml apis/podidentities/composition.yaml examples/podidentity/pod-identity-xr.yaml -o examples/podidentity/observed-podidentityassociation.yaml` to render the composition with an observed PodIdentityAssociation and test XR status propagation
- `up test run tests/*` to run composition tests in `tests/test-eks-pod-identity/`
- `up test run tests/* --e2e` to run end-to-end tests in `tests/e2etest-eks-pod-identity/`

> The composition tests supply the referenced `Compute`'s published status as an extra resource, so the function resolves `clusterName`/`region` the same way it does in-cluster.

## Deployment

- Execute `up project run`
- Alternatively, install the Configuration from the [Upbound Marketplace](https://marketplace.upbound.io/configurations/upbound/configuration-aws-eks-pod-identity)
- Check [examples](/examples/) for example XR(Composite Resource)

## Next steps

This repository serves as a foundational step. To enhance the configuration, consider:

1. create new API definitions in this same repo
2. editing the existing API definition to your needs
3. adding curated `role` templates to the function's role catalog for more well-known workloads

To learn more about how to build APIs for your managed control planes in Upbound, read the guide on [Upbound's docs](https://docs.upbound.io/).
