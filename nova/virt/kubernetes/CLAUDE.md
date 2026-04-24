# Kubernetes Nova Driver

This directory contains a Nova compute driver that exports instance lifecycle operations to Kubernetes CRDs instead of directly managing VMs. A separate Kubernetes controller watches these CRDs and performs the actual VM operations.

## Architecture

The driver creates two types of Custom Resource Definitions:

- **Instance** (`instances.nova.openstack.org`) - Represents Nova instances with declarative power state
- **Port** (`ports.nova.openstack.org`) - Represents network interface bindings

The CRD schema matches the [monsoon4](../../../monsoon4/generated/crds/) nova reimplementation, enabling a shared controller to work with both implementations.

## Files

| File | Description |
|------|-------------|
| `driver.py` | Main KubernetesDriver implementation |
| `crd_instance.py` | Instance CRD definition and operations |
| `crd_port.py` | Port CRD definition and operations |
| `os_crd.py` | Base CRD framework with schema generation |
| `utils.py` | Utility functions (unit conversion) |

## Configuration

Configuration options in `nova.conf`:

```ini
[kubernetes]
# Kubernetes namespace for CRD resources
namespace = default

# Auto-create CRDs on driver init (requires RBAC permissions)
apply_crds = False

# Path to kubeconfig file (auto-detects in-cluster config if not set)
config = /path/to/kubeconfig

# API group for CRDs (should match monsoon4)
api_group = nova.openstack.org

# Create separate Port CRDs for network interfaces
create_port_crds = True
```

## CRD Schema

### Instance

```yaml
apiVersion: nova.openstack.org/v1
kind: Instance
metadata:
  name: <instance-uuid>
  labels:
    host: <hypervisor-hostname>
spec:
  name: "display-name"
  flavorRef: "flavor-id"
  imageRef: "image-uuid"
  powerState: RUNNING | STOPPED | PAUSED  # desired state
  rebootType: none | soft | hard           # triggers reboot when != none
  networks: [...]
  blockDeviceMappingV2: [...]
status:
  vmState: ACTIVE | BUILDING | ERROR | ...
  powerState: RUNNING | PAUSED | SHUTDOWN | ...  # actual state
  taskState: "spawning" | "deleting" | ...
  hypervisor: "hostname"
  volumeAttachments: [...]
  interfaces: [...]
  conditions: [...]
```

### Port

```yaml
apiVersion: nova.openstack.org/v1
kind: Port
metadata:
  name: <port-uuid>
  labels:
    host: <hypervisor-hostname>
spec:
  instanceRef: <instance-uuid>
  networkId: <network-uuid>
  portId: <neutron-port-uuid>
  bindingHostId: <hypervisor-hostname>
status:
  phase: Pending | Binding | Bound | Failed
  vifType: "bridge" | "ovs" | ...
  vifDetails: {...}
```

## Driver Capabilities

Currently implemented:
- Instance lifecycle: spawn, destroy, get_info, list_instances
- Power management: power_on, power_off, pause, unpause, suspend, resume, reboot
- Network operations: plug_vifs, unplug_vifs, attach_interface, detach_interface
- Volume operations: attach_volume, detach_volume, swap_volume, extend_volume
- Resource reporting: get_available_resource, update_provider_tree

Not implemented (stubs):
- Live/cold migration
- Console access (VNC, SPICE, serial)
- Snapshots
- Rescue/unrescue

## Testing

Run unit tests:

```bash
cd deploy
./run-tests.sh
```

Run specific test file:

```bash
./run-tests.sh nova.tests.unit.virt.kubernetes.test_driver
./run-tests.sh nova.tests.unit.virt.kubernetes.test_crd_instance
./run-tests.sh nova.tests.unit.virt.kubernetes.test_crd_port
```

## Deployment

See [deploy/DEPLOY.md](../../../deploy/DEPLOY.md) for deployment instructions.
