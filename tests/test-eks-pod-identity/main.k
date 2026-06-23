import models.io.upbound.awsm.eks.v1beta1 as eksv1beta1
import models.io.upbound.awsm.iam.v1beta1 as iamv1beta1
import models.io.upbound.dev.meta.v1alpha1 as metav1alpha1
import models.io.upbound.platform.aws.v1alpha1 as platformawsv1alpha1

# Stand-in for the referenced Compute's published status, supplied as an extra
# resource so the composition resolves clusterName/region via the same
# extra-resources path it uses in-cluster. Untyped dict on purpose — the Compute
# model is not a dependency of this package.
_computeExtra = {
    apiVersion = "aws.platform.upbound.io/v1alpha1"
    kind = "Compute"
    metadata = {
        name = "my-compute"
        namespace = "default"
    }
    status = {
        clusterName = "my-cluster"
        region = "us-west-2"
    }
}

_items = [
    metav1alpha1.CompositionTest{
        metadata.name: "test-identity"
        spec = {
            assertResources: [
                platformawsv1alpha1.Identity{
                    metadata = {
                        name = "configuration-aws-eks-pod-identity"
                        namespace = "default"
                    }
                    spec = {
                        parameters = {
                            federationType = "pod-identity"
                            computeRef = {
                                id = "my-compute"
                            }
                            role = "ebs-csi"
                        }
                    }
                }
                iamv1beta1.Role{
                    metadata = {
                        annotations = {
                            "crossplane.io/composition-resource-name" = "iamRole"
                        }
                        generateName = "configuration-aws-eks-pod-identity-"
                        labels = {
                            "crossplane.io/composite" = "configuration-aws-eks-pod-identity"
                        }
                    }
                    spec = {
                        managementPolicies = ["*"]
                        forProvider = {
                            assumeRolePolicy = """{"Version":"2012-10-17","Statement":[{"Sid":"AllowEksAuthToAssumeRoleForPodIdentity","Effect":"Allow","Principal":{"Service":"pods.eks.amazonaws.com"},"Action":["sts:AssumeRole","sts:TagSession"]}]}"""
                            managedPolicyArns = [
                                "arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy"
                            ]
                        }
                        providerConfigRef = {
                            kind = "ProviderConfig"
                            name = "default"
                        }
                    }
                }
                eksv1beta1.PodIdentityAssociation{
                    metadata = {
                        annotations = {
                            "crossplane.io/composition-resource-name" = "podIdentityAssociation"
                        }
                        generateName = "configuration-aws-eks-pod-identity-"
                        labels = {
                            "crossplane.io/composite" = "configuration-aws-eks-pod-identity"
                        }
                    }
                    spec = {
                        managementPolicies = ["*"]
                        forProvider = {
                            clusterName = "my-cluster"
                            namespace = "kube-system"
                            region = "us-west-2"
                            roleArnSelector = {
                                matchControllerRef = True
                            }
                            serviceAccount = "ebs-csi-controller-sa"
                        }
                        providerConfigRef = {
                            kind = "ProviderConfig"
                            name = "default"
                        }
                    }
                }
            ]
            compositionPath: "apis/podidentities/composition.yaml"
            xrPath: "examples/podidentity/pod-identity-xr.yaml"
            xrdPath: "apis/podidentities/definition.yaml"
            extraResources: [_computeExtra]
            timeoutSeconds: 60
            validate: False
        }
    }
]
items= _items
