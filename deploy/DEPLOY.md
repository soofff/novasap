# Kubernetes Nova Driver Deployment

This document describes how to deploy the OpenStack Nova Kubernetes driver to the `cc-b0-qa-de-1` cluster.

## Overview

The deployment process clones the existing production Nova hypervisor daemonset and configmap, modifies them to use the Kubernetes driver, and deploys them alongside the production resources. The driver runs only on nodes labeled with `nova.openstack.cloud.sap/virt-driver: kubernetes`.

## Prerequisites

1. **kubectl** with contexts configured for:
   - `cc-b0-qa-de-1` (compute cluster)
   - `g-qa-de-200` (garden/management cluster)

2. **yq** (YAML processor) - install via: `brew install yq`

3. **jq** (JSON processor) - install via: `brew install jq`

4. **Cluster access** - authenticate to both clusters:
   ```bash
   kubectl-logon -c cc-b0-qa-de-1
   kubectl-logon -c g-qa-de-200
   ```

## Deployment Steps

### Option 1: Using the deploy script (recommended)

```bash
cd deploy
./deploy.sh
```

The script will:
1. Export existing production resources
2. Transform them for the Kubernetes driver
3. Patch the ConfigMap to configure `compute_driver = kubernetes.KubernetesDriver`
4. Show diffs and ask for confirmation before applying
5. Optionally update the Gardener Shoot to label worker nodes

### Option 2: Manual deployment

See the `deploy.sh` script for the individual commands.

## Configuration

The script configures the following in `nova.conf`:

```ini
[DEFAULT]
compute_driver = kubernetes.KubernetesDriver

[kubernetes]
namespace = monsoon3
apply_crds = True
```

Configuration options:
- `kubernetes.namespace` - Kubernetes namespace for CRDs (default: `default`)
- `kubernetes.apply_crds` - Auto-create CRDs on driver init (default: `False`)
- `kubernetes.config` - Path to kubeconfig (auto-detects in-cluster)

## Resource Naming

| Original Resource | Kubernetes Driver Resource |
|-------------------|---------------------------|
| `nova-hypervisor-agents-compute-kvm` | `nova-hypervisor-agents-kubernetes-compute-kvm` |
| `nova-hypervisor-agents-compute` (configmap) | `nova-hypervisor-agents-kubernetes-compute` |
| `kvm-node-agent-controller-manager` | `kvm-node-agent-kubernetes-controller-manager` |

## Node Selection

The daemonsets use the node selector:
```yaml
nodeSelector:
  nova.openstack.cloud.sap/virt-driver: kubernetes
```

Only nodes with this label will run the Kubernetes driver pods.

## Labeling Worker Nodes

To label a worker node for the Kubernetes driver, update the Gardener Shoot:

```bash
# Export current Shoot config
kubectl --context g-qa-de-200 -n garden-ccloud get shoots/cc-b0-qa-de-1 -ojson > Shoot.json

# Add label to the worker (e.g., bb088-dev)
jq '(.spec.provider.workers[] | select(.name == "bb088-dev").labels."nova.openstack.cloud.sap/virt-driver") = "kubernetes"' Shoot.json > Shoot-updated.json

# Apply and trigger reconciliation
kubectl --context g-qa-de-200 -n garden-ccloud apply -f Shoot-updated.json
kubectl --context g-qa-de-200 -n garden-ccloud annotate shoots cc-b0-qa-de-1 gardener.cloud/operation=retry
```

## Verification

After deployment, verify:

```bash
# Check pods are running
kubectl --context cc-b0-qa-de-1 -n monsoon3 get pods -l name=nova-hypervisor-agents-kubernetes

# Check nova-compute logs
kubectl --context cc-b0-qa-de-1 -n monsoon3 logs -l name=nova-hypervisor-agents-kubernetes -c nova-compute --tail=100

# Verify CRD exists
kubectl --context cc-b0-qa-de-1 get crd osinstances.sap.com

# List any created instances
kubectl --context cc-b0-qa-de-1 -n monsoon3 get osinstances
```

## Troubleshooting

### Pod not starting
- Check node labels: `kubectl get nodes --show-labels | grep virt-driver`
- Check daemonset status: `kubectl -n monsoon3 describe daemonset nova-hypervisor-agents-kubernetes-compute-kvm`

### CRD not created
- Ensure `apply_crds = True` in nova.conf
- Check RBAC permissions for CRD creation

### Driver not loading
- Verify `compute_driver = kubernetes.KubernetesDriver` in nova.conf
- Check for import errors in nova-compute logs

## Cleanup

To remove the Kubernetes driver deployment:

```bash
kubectl --context cc-b0-qa-de-1 -n monsoon3 delete daemonset nova-hypervisor-agents-kubernetes-compute-kvm
kubectl --context cc-b0-qa-de-1 -n monsoon3 delete configmap nova-hypervisor-agents-kubernetes-compute
kubectl --context cc-b0-qa-de-1 -n monsoon3 delete daemonset kvm-node-agent-kubernetes-controller-manager
```

Then remove the node label from the Gardener Shoot.
