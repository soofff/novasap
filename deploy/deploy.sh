#!/usr/bin/env bash
set -euo pipefail

# Configuration
COMPUTE_CONTEXT="cc-b0-qa-de-1"
GARDEN_CONTEXT="g-qa-de-200"
NAMESPACE="monsoon3"
SHOOT_NAME="cc-b0-qa-de-1"
GARDEN_NAMESPACE="garden-ccloud"

# Kubernetes driver specific names
DAEMONSET_NAME="nova-hypervisor-agents-kubernetes-compute-kvm"
CONFIGMAP_NAME="nova-hypervisor-agents-kubernetes-compute"
LABEL_SELECTOR_NAME="nova-hypervisor-agents-kubernetes"
NODE_AGENT_DAEMONSET_NAME="kvm-node-agent-kubernetes-controller-manager"
NODE_AGENT_LABEL_SELECTOR_NAME="kvm-node-agent-kubernetes"
VIRT_DRIVER="kubernetes"

# Worker node to label (modify as needed)
WORKER_NAME_PATTERN="^bb088-dev$"

echo "=== Kubernetes Nova Driver Deployment Script ==="
echo ""

# Check authentication
echo "Checking cluster authentication..."
for CONTEXT in "$COMPUTE_CONTEXT" "$GARDEN_CONTEXT"; do
    if ! kubectl auth can-i get pods --context "$CONTEXT" >/dev/null 2>&1; then
        echo "ERROR: Not authenticated to context $CONTEXT"
        echo "Please run: kubectl-logon -c $CONTEXT"
        exit 1
    fi
done
echo "Authentication OK"
echo ""

# Export existing resources
echo "Exporting existing resources..."
kubectl --context "$COMPUTE_CONTEXT" -n "$NAMESPACE" get daemonsets/nova-hypervisor-agents-compute-kvm -oyaml > NovaDaemonsetOrig.yaml
kubectl --context "$COMPUTE_CONTEXT" -n "$NAMESPACE" get configmaps/nova-hypervisor-agents-compute -oyaml > NovaConfigmapOrig.yaml
kubectl --context "$COMPUTE_CONTEXT" -n "$NAMESPACE" get daemonsets/kvm-node-agent-controller-manager -oyaml > NodeAgentDaemonsetOrig.yaml
echo "Exported: NovaDaemonsetOrig.yaml, NovaConfigmapOrig.yaml, NodeAgentDaemonsetOrig.yaml"
echo ""

# Transform Nova ConfigMap
echo "Transforming Nova ConfigMap..."
yq < NovaConfigmapOrig.yaml > NovaConfigmap.yaml \
  'del(.metadata.resourceVersion, .metadata.uid, .metadata.annotations, .metadata.creationTimestamp, .metadata.labels."app.kubernetes.io/managed-by")
  | .metadata.name = "'"$CONFIGMAP_NAME"'"'

# Add kubernetes driver configuration to nova.conf in the ConfigMap
# This patches the nova.conf data to use the kubernetes driver
echo "Patching nova.conf in ConfigMap for kubernetes driver..."
yq -i '.data["nova.conf"] |= (
  . + "\n\n[DEFAULT]\ncompute_driver = kubernetes.KubernetesDriver\n\n[kubernetes]\nnamespace = monsoon3\napply_crds = True\n"
)' NovaConfigmap.yaml

echo "Created: NovaConfigmap.yaml"
echo ""

# Transform Nova Daemonset
echo "Transforming Nova Daemonset..."
yq < NovaDaemonsetOrig.yaml > NovaDaemonset.yaml \
  'del(.metadata.resourceVersion, .metadata.uid, .metadata.annotations, .metadata.creationTimestamp, .metadata.labels."app.kubernetes.io/managed-by", .status, .metadata.generation, .spec.template.metadata.annotations)
  | .metadata.name = "'"$DAEMONSET_NAME"'"
  | .spec.selector.matchLabels.name = "'"$LABEL_SELECTOR_NAME"'"
  | .spec.template.metadata.labels.name = "'"$LABEL_SELECTOR_NAME"'"
  | .spec.template.metadata.labels.release_name = "'"$LABEL_SELECTOR_NAME"'"
  | (.spec.template.spec.volumes[] |= select(.name == "nova-etc").projected.sources[] |= select(.configMap.name == "nova-hypervisor-agents-compute").configMap.name = "'"$CONFIGMAP_NAME"'")
  | .spec.template.spec.nodeSelector."nova.openstack.cloud.sap/virt-driver" = "'"$VIRT_DRIVER"'"'
echo "Created: NovaDaemonset.yaml"
echo ""

# Transform Node Agent Daemonset
echo "Transforming Node Agent Daemonset..."
yq < NodeAgentDaemonsetOrig.yaml > NodeAgentDaemonset.yaml \
  'del(.metadata.resourceVersion, .metadata.uid, .metadata.annotations, .metadata.creationTimestamp, .metadata.labels."app.kubernetes.io/managed-by", .status, .metadata.generation)
  | .metadata.name = "'"$NODE_AGENT_DAEMONSET_NAME"'"
  | .metadata.labels."app.kubernetes.io/instance" = "'"$NODE_AGENT_LABEL_SELECTOR_NAME"'"
  | .spec.selector.matchLabels."app.kubernetes.io/instance" = "'"$NODE_AGENT_LABEL_SELECTOR_NAME"'"
  | .spec.template.metadata.labels."app.kubernetes.io/instance" = "'"$NODE_AGENT_LABEL_SELECTOR_NAME"'"
  | .spec.template.spec.nodeSelector."nova.openstack.cloud.sap/virt-driver" = "'"$VIRT_DRIVER"'"'
echo "Created: NodeAgentDaemonset.yaml"
echo ""

# Preview changes
echo "=== Previewing changes ==="
echo ""
echo "--- Node Agent Daemonset diff ---"
kubectl --context "$COMPUTE_CONTEXT" -n "$NAMESPACE" diff -f NodeAgentDaemonset.yaml || true
echo ""
echo "--- Nova Daemonset and ConfigMap diff ---"
kubectl --context "$COMPUTE_CONTEXT" -n "$NAMESPACE" diff -f NovaDaemonset.yaml -f NovaConfigmap.yaml || true
echo ""

# Ask for confirmation
read -p "Do you want to apply these changes? (y/N) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 0
fi

# Dry-run
echo "Running dry-run validation..."
kubectl --context "$COMPUTE_CONTEXT" -n "$NAMESPACE" apply --validate=true --dry-run=server -f NovaDaemonset.yaml -f NovaConfigmap.yaml
kubectl --context "$COMPUTE_CONTEXT" -n "$NAMESPACE" apply --validate=true --dry-run=server -f NodeAgentDaemonset.yaml
echo "Dry-run passed"
echo ""

# Apply
echo "Applying Nova resources..."
kubectl --context "$COMPUTE_CONTEXT" -n "$NAMESPACE" apply -f NovaDaemonset.yaml -f NovaConfigmap.yaml
kubectl --context "$COMPUTE_CONTEXT" -n "$NAMESPACE" apply -f NodeAgentDaemonset.yaml
echo "Applied successfully"
echo ""

# Update Shoot worker labels
echo "=== Updating Shoot worker labels ==="
kubectl --context "$GARDEN_CONTEXT" -n "$GARDEN_NAMESPACE" get shoots/"$SHOOT_NAME" -ojson | jq > ShootOrig.json
jq < ShootOrig.json > Shoot.json \
  '(.spec.provider.workers[] | select(.name | test("'"$WORKER_NAME_PATTERN"'")).labels."nova.openstack.cloud.sap/virt-driver") = "'"$VIRT_DRIVER"'"'

echo "--- Shoot diff ---"
kubectl --context "$GARDEN_CONTEXT" -n "$GARDEN_NAMESPACE" diff -f Shoot.json || true
echo ""

read -p "Do you want to apply the Shoot changes? (y/N) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Skipped Shoot changes."
else
    kubectl --context "$GARDEN_CONTEXT" -n "$GARDEN_NAMESPACE" apply -f Shoot.json
    kubectl --context "$GARDEN_CONTEXT" -n "$GARDEN_NAMESPACE" annotate shoots "$SHOOT_NAME" gardener.cloud/operation=retry --overwrite
    echo "Shoot updated and reconciliation triggered"
fi

echo ""
echo "=== Deployment complete ==="
echo ""
echo "Verify with:"
echo "  kubectl --context $COMPUTE_CONTEXT -n $NAMESPACE get pods -l name=$LABEL_SELECTOR_NAME"
echo "  kubectl --context $COMPUTE_CONTEXT -n $NAMESPACE logs -l name=$LABEL_SELECTOR_NAME -c nova-compute --tail=100"
echo "  kubectl --context $COMPUTE_CONTEXT get crd osinstances.sap.com"
