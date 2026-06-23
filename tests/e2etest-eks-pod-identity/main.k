import models.io.upbound.awsm.v1beta1 as awsv1beta1
import models.io.upbound.dev.meta.v1alpha1 as metav1alpha1
import models.io.upbound.platform.aws.v1alpha1 as platformawsv1alpha1

# NOTE: the cluster manifest below is still kind EKS because this package
# resolves the currently-published eks package. It flips to kind Compute as part
# of the coordinated v3 republish (see plan task 9 / configuration-aws-eks).
_items = [
    metav1alpha1.E2ETest {
        metadata.name: "pod-identity"
        spec = {
            crossplane.autoUpgrade.channel: "None"
            crossplane.version = "2.0.2-up.5"
            defaultConditions: ["Ready"]
            manifests: [
                platformawsv1alpha1.Identity {
                    metadata = {
                        name = "configuration-aws-eks-pod-identity"
                        namespace = "default"
                    }
                    spec = {
                        parameters = {
                            federationType = "pod-identity"
                            computeRef = {
                                id = "configuration-aws-eks-pod-identity"
                            }
                            serviceAccount = {
                                name = "my-controller"
                                namespace = "kube-system"
                            }
                            # arbitrary workload IAM via the bounded escape hatch
                            overrides = {
                                managedPolicyArns = [
                                    "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy"
                                ]
                                policy = r"""{"Version":"2012-10-17","Statement":[{"Action":["kms:Decrypt","kms:DescribeKey"],"Effect":"Allow","Resource":"*"}]}"""
                            }
                        }
                    }
                }
                platformawsv1alpha1.EKS{
                    metadata = {
                        name = "configuration-aws-eks-pod-identity"
                        namespace = "default"
                    }
                    spec = {
                        parameters = {
                            id = "configuration-aws-eks-pod-identity"
                            region = "us-west-2"
                            version = "1.33"
                            nodes = {
                                count = 1
                                instanceType = "t3.small"
                            }
                        }
                    }
                }
                platformawsv1alpha1.Network{
                    metadata = {
                        name = "configuration-aws-eks-pod-identity"
                        namespace = "default"
                    }
                    spec = {
                        parameters = {
                            region = "us-west-2"
                        }
                    }
                }
            ]
            extraResources: [
                # Define the provider configuration
                awsv1beta1.ProviderConfig{
                    metadata = {
                        name = "default"
                        namespace = "default"
                    }
                    spec = {
                        credentials = {
                            source = "Upbound"
                            upbound = {
                                webIdentity = {
                                    roleARN = "arn:aws:iam::609897127049:role/solutions-e2e-provider-aws"
                                }
                            }
                        }
                    }
                }
            ]
            skipDelete: False
            timeoutSeconds: 4500
        }
    }
]
items = _items
