"""
Instance CRD for the Kubernetes Nova driver.

This module defines the Instance Custom Resource Definition that matches
the monsoon4 nova reimplementation schema, enabling a shared controller
to work with both implementations.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import ClassVar, Optional, List

from nova.objects.instance import Instance
from nova.virt.kubernetes.os_crd import (
    Crd, CrdObject, CrdBody, CrdSpec, CrdStatus,
    CrdMetadata, CrdMetadataLabels, Condition
)


# Enums matching monsoon4 schema

class PowerState(str, Enum):
    """Desired power state for an instance."""
    RUNNING = "RUNNING"
    STOPPED = "STOPPED"
    PAUSED = "PAUSED"


class VmState(str, Enum):
    """Observed VM state."""
    ACTIVE = "ACTIVE"
    BUILDING = "BUILDING"
    PAUSED = "PAUSED"
    SUSPENDED = "SUSPENDED"
    STOPPED = "STOPPED"
    RESCUED = "RESCUED"
    RESIZED = "RESIZED"
    SOFT_DELETED = "SOFT_DELETED"
    DELETED = "DELETED"
    ERROR = "ERROR"
    SHELVED = "SHELVED"
    SHELVED_OFFLOADED = "SHELVED_OFFLOADED"


class ObservedPowerState(str, Enum):
    """Actual power state from hypervisor."""
    NO_STATE = "NO_STATE"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    SHUTDOWN = "SHUTDOWN"
    CRASHED = "CRASHED"
    SUSPENDED = "SUSPENDED"


class RebootType(str, Enum):
    """Reboot type for transient reboot requests."""
    NONE = "none"
    SOFT = "soft"
    HARD = "hard"


class SourceType(str, Enum):
    """Block device source type."""
    VOLUME = "volume"
    IMAGE = "image"
    SNAPSHOT = "snapshot"
    BLANK = "blank"


class DestinationType(str, Enum):
    """Block device destination type."""
    VOLUME = "volume"
    LOCAL = "local"


class InterfaceState(str, Enum):
    """Network interface attachment state."""
    ATTACHING = "ATTACHING"
    ATTACHED = "ATTACHED"
    DETACHING = "DETACHING"


# Nested dataclasses for complex fields

@dataclass
class BlockDeviceMapping:
    """Block device mapping configuration."""
    sourceType: SourceType
    destinationType: DestinationType
    bootIndex: Optional[int] = None
    uuid: Optional[str] = None  # volume/image/snapshot UUID
    volumeSize: Optional[int] = None  # GB
    volumeType: Optional[str] = None
    deviceName: Optional[str] = None  # e.g., /dev/vda
    deleteOnTermination: bool = False
    tag: Optional[str] = None


@dataclass
class NetworkAttachment:
    """Network attachment configuration."""
    uuid: Optional[str] = None  # Network UUID
    port: Optional[str] = None  # Port UUID
    fixedIp: Optional[str] = None
    tag: Optional[str] = None


@dataclass
class SchedulerHints:
    """Scheduler hints for placement."""
    group: Optional[str] = None  # Server group UUID
    sameHost: Optional[List[str]] = None
    differentHost: Optional[List[str]] = None
    buildNearHostIp: Optional[str] = None
    cidr: Optional[str] = None
    targetCell: Optional[str] = None


@dataclass
class FixedIp:
    """Fixed IP address information."""
    ipAddress: str
    subnetId: Optional[str] = None


@dataclass
class InterfaceAttachment:
    """Interface attachment status."""
    portId: str
    state: InterfaceState
    netId: Optional[str] = None
    macAddr: Optional[str] = None
    fixedIps: Optional[List[FixedIp]] = None
    tag: Optional[str] = None


@dataclass
class VolumeAttachment:
    """Volume attachment status."""
    id: str  # Attachment ID
    volumeId: str
    device: Optional[str] = None  # Device path
    deleteOnTermination: bool = False


@dataclass
class NetworkAddress:
    """Network address information."""
    addr: str
    version: int  # 4 or 6
    macAddr: Optional[str] = None
    type: Optional[str] = None  # fixed, floating


@dataclass
class FlavorInfo:
    """Resolved flavor information."""
    id: str
    vcpus: int
    ram: int  # MB
    disk: int  # GB
    ephemeral: int = 0  # GB


@dataclass
class Fault:
    """Fault information for error state."""
    code: int
    message: str
    details: Optional[str] = None
    created: Optional[datetime] = None


# Main Instance spec and status

@dataclass
class InstanceSpec(CrdSpec):
    """InstanceSpec defines the desired state of an Instance."""
    NAME: ClassVar[str] = "spec"

    name: str = field(metadata={"print": True, "print_name": "Name",
                                "description": "Display name of the instance"})
    flavorRef: str = field(metadata={"print": True, "print_name": "Flavor",
                                     "description": "Flavor UUID or name"})
    imageRef: Optional[str] = field(default=None,
                                    metadata={"description": "Image UUID (optional for boot-from-volume)"})
    availabilityZone: Optional[str] = field(default=None,
                                            metadata={"description": "Availability zone for placement"})
    powerState: PowerState = field(default=PowerState.RUNNING,
                                   metadata={"description": "Desired power state"})
    rebootType: RebootType = field(default=RebootType.NONE,
                                   metadata={"description": "Reboot type (none, soft, hard)"})
    locked: bool = field(default=False,
                         metadata={"description": "Whether the instance is locked"})
    lockedReason: Optional[str] = field(default=None,
                                        metadata={"description": "Reason for locking"})
    metadata: Optional[dict] = field(default=None,
                                     metadata={"description": "Instance metadata (key-value pairs)"})
    userData: Optional[str] = field(default=None,
                                    metadata={"description": "Base64-encoded cloud-init user data"})
    keyName: Optional[str] = field(default=None,
                                   metadata={"description": "Name of keypair for SSH access"})
    hostname: Optional[str] = field(default=None,
                                    metadata={"description": "Custom hostname"})
    description: Optional[str] = field(default=None,
                                       metadata={"description": "Instance description"})
    networks: Optional[List[NetworkAttachment]] = field(default=None,
                                                        metadata={"description": "Network configurations"})
    blockDeviceMappingV2: Optional[List[BlockDeviceMapping]] = field(
        default=None, metadata={"description": "Block device mappings"})
    schedulerHints: Optional[SchedulerHints] = field(default=None,
                                                     metadata={"description": "Scheduler hints"})
    tags: Optional[List[str]] = field(default=None,
                                      metadata={"description": "Instance tags"})


@dataclass
class InstanceStatus(CrdStatus):
    """InstanceStatus defines the observed state of an Instance."""
    NAME: ClassVar[str] = "status"

    vmState: Optional[VmState] = field(default=None,
                                       metadata={"print": True, "print_name": "State",
                                                 "description": "VM state"})
    powerState: Optional[ObservedPowerState] = field(default=None,
                                                     metadata={"description": "Actual power state"})
    taskState: Optional[str] = field(default=None,
                                     metadata={"print": True, "print_name": "Task",
                                               "description": "Current task state"})
    hypervisor: Optional[str] = field(default=None,
                                      metadata={"print": True, "print_name": "Hypervisor",
                                                "description": "Current hypervisor name"})
    hypervisorId: Optional[str] = field(default=None,
                                        metadata={"description": "Hypervisor ID"})
    instanceId: Optional[str] = field(default=None,
                                      metadata={"description": "OpenStack instance UUID"})
    conditions: Optional[List[Condition]] = field(default=None,
                                                  metadata={"description": "Current conditions"})
    fault: Optional[Fault] = field(default=None,
                                   metadata={"description": "Fault info if in error state"})
    flavor: Optional[FlavorInfo] = field(default=None,
                                         metadata={"description": "Resolved flavor information"})
    addresses: Optional[dict] = field(default=None,
                                      metadata={"description": "Network addresses by network name"})
    interfaces: Optional[List[InterfaceAttachment]] = field(default=None,
                                                            metadata={"description": "Interface attachments"})
    volumeAttachments: Optional[List[VolumeAttachment]] = field(default=None,
                                                                metadata={"description": "Volume attachments"})
    created: Optional[datetime] = field(default=None,
                                        metadata={"description": "Creation timestamp"})
    launched: Optional[datetime] = field(default=None,
                                         metadata={"description": "Launch timestamp"})
    updated: Optional[datetime] = field(default=None,
                                        metadata={"description": "Last update timestamp"})
    terminated: Optional[datetime] = field(default=None,
                                           metadata={"description": "Termination timestamp"})


@dataclass
class InstanceBody(CrdBody):
    """Instance body containing spec and status."""
    spec: InstanceSpec = None
    status: InstanceStatus = None


@dataclass
class InstanceObject(CrdObject, InstanceBody):
    """Full Instance CRD object."""

    @staticmethod
    def from_nova_instance(instance: Instance, host: str) -> 'InstanceObject':
        """Create an InstanceObject from a Nova Instance object."""
        # Extract flavor info
        flavor = instance.get('flavor')
        flavor_info = None
        if flavor:
            flavor_info = FlavorInfo(
                id=str(flavor.get('flavorid', flavor.get('id', ''))),
                vcpus=flavor.get('vcpus', 0),
                ram=flavor.get('memory_mb', 0),
                disk=flavor.get('root_gb', 0),
                ephemeral=flavor.get('ephemeral_gb', 0)
            )

        # Map Nova power state to our enum
        nova_power_state = instance.get('power_state', 0)
        power_state_map = {
            0: ObservedPowerState.NO_STATE,
            1: ObservedPowerState.RUNNING,
            3: ObservedPowerState.PAUSED,
            4: ObservedPowerState.SHUTDOWN,
            6: ObservedPowerState.CRASHED,
            7: ObservedPowerState.SUSPENDED,
        }
        observed_power = power_state_map.get(nova_power_state, ObservedPowerState.NO_STATE)

        # Map Nova VM state to our enum
        nova_vm_state = instance.get('vm_state', 'building')
        vm_state_map = {
            'active': VmState.ACTIVE,
            'building': VmState.BUILDING,
            'paused': VmState.PAUSED,
            'suspended': VmState.SUSPENDED,
            'stopped': VmState.STOPPED,
            'rescued': VmState.RESCUED,
            'resized': VmState.RESIZED,
            'soft-delete': VmState.SOFT_DELETED,
            'deleted': VmState.DELETED,
            'error': VmState.ERROR,
            'shelved': VmState.SHELVED,
            'shelved_offloaded': VmState.SHELVED_OFFLOADED,
        }
        vm_state = vm_state_map.get(nova_vm_state, VmState.BUILDING)

        # Determine desired power state from VM state
        desired_power = PowerState.RUNNING
        if vm_state in [VmState.STOPPED, VmState.SHELVED, VmState.SHELVED_OFFLOADED]:
            desired_power = PowerState.STOPPED
        elif vm_state == VmState.PAUSED:
            desired_power = PowerState.PAUSED

        return InstanceObject(
            metadata=CrdMetadata(
                name=instance['uuid'],
                labels=CrdMetadataLabels(host=host)
            ),
            spec=InstanceSpec(
                name=instance.get('display_name', ''),
                flavorRef=str(flavor.get('flavorid', '')) if flavor else '',
                imageRef=instance.get('image_ref'),
                availabilityZone=instance.get('availability_zone'),
                powerState=desired_power,
                rebootType=RebootType.NONE,
                locked=instance.get('locked', False),
                lockedReason=instance.get('locked_reason'),
                metadata=instance.get('metadata'),
                keyName=instance.get('key_name'),
                hostname=instance.get('hostname'),
            ),
            status=InstanceStatus(
                vmState=vm_state,
                powerState=observed_power,
                taskState=instance.get('task_state'),
                hypervisor=host,
                instanceId=instance['uuid'],
                flavor=flavor_info,
                created=instance.get('created_at'),
                launched=instance.get('launched_at'),
                updated=instance.get('updated_at'),
                terminated=instance.get('terminated_at'),
            )
        )


class InstanceCrd(Crd):
    """Instance Custom Resource Definition."""

    CRD_KIND = 'Instance'
    CRD_PLURAL = 'instances'
    CRD_SINGULAR = 'instance'
    CRD_NAME = 'instances.nova.openstack.org'
    CRD_SHORT_NAMES = []
    CRD_SPEC = InstanceSpec
    CRD_STATUS = InstanceStatus

    def __init__(self, api_client, namespace: str):
        super().__init__(api_client, namespace)

    def create(self, instance: Instance, host: str) -> dict:
        """Create an Instance CRD from a Nova instance."""
        obj = InstanceObject.from_nova_instance(instance, host)
        return self.create_object(obj)

    def get_instance(self, instance: Instance) -> Optional[dict]:
        """Get an Instance CRD by Nova instance UUID."""
        return self.get(instance['uuid'])

    def list_instances(self, host: str = None) -> list:
        """List Instance CRDs, optionally filtered by host."""
        label_selector = f"host={host}" if host else None
        return self.list(label_selector=label_selector)

    def patch_spec(self, name: str, **kwargs) -> dict:
        """Patch the spec of an Instance CRD."""
        return self.patch(name, {"spec": kwargs})

    def update_power_state(self, name: str, power_state: PowerState) -> dict:
        """Update the desired power state."""
        return self.patch_spec(name, powerState=power_state.value)

    def request_reboot(self, name: str, reboot_type: RebootType) -> dict:
        """Request a reboot."""
        return self.patch_spec(name, rebootType=reboot_type.value)

    def update_status(self, name: str, **kwargs) -> dict:
        """Update the status of an Instance CRD."""
        # Convert enums to values
        status = {}
        for k, v in kwargs.items():
            if isinstance(v, Enum):
                status[k] = v.value
            else:
                status[k] = v
        return self.patch_status(name, status)


# Legacy aliases for backwards compatibility
OsCrdInstance = InstanceCrd
OsCrdObjInstance = InstanceObject
OsCrdObjBodyInstanceBody = InstanceBody
OsCrdObjInstanceAction = None  # Deprecated - use spec.powerState
OsCrdObjInstanceActionState = None  # Deprecated - use PowerState enum
