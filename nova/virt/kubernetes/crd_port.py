"""
Port CRD for the Kubernetes Nova driver.

This module defines the Port Custom Resource Definition for network
interface management, matching the monsoon4 nova reimplementation schema.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import ClassVar, Optional, List

from nova.virt.kubernetes.os_crd import (
    Crd, CrdObject, CrdBody, CrdSpec, CrdStatus,
    CrdMetadata, CrdMetadataLabels, Condition
)


class PortPhase(str, Enum):
    """Port binding phase."""
    PENDING = "Pending"
    BINDING = "Binding"
    BOUND = "Bound"
    FAILED = "Failed"


@dataclass
class FixedIpRequest:
    """Fixed IP request configuration."""
    ipAddress: Optional[str] = None
    subnetId: Optional[str] = None


@dataclass
class FixedIpAllocated:
    """Allocated fixed IP address."""
    ipAddress: str
    subnetId: str


@dataclass
class PortSpec(CrdSpec):
    """PortSpec defines the desired state of a Port binding."""
    NAME: ClassVar[str] = "spec"

    instanceRef: str = field(metadata={"print": True, "print_name": "Instance",
                                       "description": "Reference to the Instance UUID"})
    networkId: Optional[str] = field(default=None,
                                     metadata={"print": True, "print_name": "Network",
                                               "description": "Network UUID to allocate port from"})
    portId: Optional[str] = field(default=None,
                                  metadata={"description": "Existing Neutron port UUID to bind"})
    bindingHostId: Optional[str] = field(default=None,
                                         metadata={"print": True, "print_name": "Host",
                                                   "description": "Hypervisor hostname to bind to"})
    fixedIps: Optional[List[FixedIpRequest]] = field(default=None,
                                                     metadata={"description": "Fixed IP addresses to assign"})
    macAddress: Optional[str] = field(default=None,
                                      metadata={"description": "MAC address (auto-assigned if not specified)"})
    tag: Optional[str] = field(default=None,
                               metadata={"description": "Device tag for identification"})


@dataclass
class PortStatus(CrdStatus):
    """PortStatus defines the observed state of a Port."""
    NAME: ClassVar[str] = "status"

    phase: Optional[PortPhase] = field(default=None,
                                       metadata={"print": True, "print_name": "Phase",
                                                 "description": "Current phase of port binding"})
    portId: Optional[str] = field(default=None,
                                  metadata={"description": "Allocated Neutron port UUID"})
    fixedIps: Optional[List[FixedIpAllocated]] = field(default=None,
                                                       metadata={"description": "Allocated fixed IP addresses"})
    macAddress: Optional[str] = field(default=None,
                                      metadata={"description": "MAC address of the port"})
    vifType: Optional[str] = field(default=None,
                                   metadata={"description": "VIF type (bridge, ovs, vhostuser)"})
    vifDetails: Optional[dict] = field(default=None,
                                       metadata={"description": "VIF details from Neutron binding"})
    boundAt: Optional[datetime] = field(default=None,
                                        metadata={"description": "Timestamp when port was bound"})
    conditions: Optional[List[Condition]] = field(default=None,
                                                  metadata={"description": "Current conditions"})


@dataclass
class PortBody(CrdBody):
    """Port body containing spec and status."""
    spec: PortSpec = None
    status: PortStatus = None


@dataclass
class PortObject(CrdObject, PortBody):
    """Full Port CRD object."""

    @staticmethod
    def from_vif(vif: dict, instance_uuid: str, host: str) -> 'PortObject':
        """Create a PortObject from a Nova VIF dict.

        Args:
            vif: VIF dictionary from Nova network_info
            instance_uuid: UUID of the instance this port belongs to
            host: Hostname where the port should be bound
        """
        # Extract network info
        network = vif.get('network', {})
        network_id = network.get('id')

        # Extract fixed IPs
        fixed_ips = None
        if 'fixed_ips' in vif or hasattr(vif, 'fixed_ips'):
            vif_fixed_ips = vif.get('fixed_ips', [])
            if callable(vif_fixed_ips):
                vif_fixed_ips = vif.fixed_ips()
            fixed_ips = [
                FixedIpRequest(
                    ipAddress=ip.get('address'),
                    subnetId=ip.get('subnet_id')
                ) for ip in vif_fixed_ips
            ]

        # Port name: use vif ID or generate from instance + network
        port_name = vif.get('id', f"{instance_uuid}-{network_id}")

        return PortObject(
            metadata=CrdMetadata(
                name=port_name,
                labels=CrdMetadataLabels(host=host)
            ),
            spec=PortSpec(
                instanceRef=instance_uuid,
                networkId=network_id,
                portId=vif.get('id'),
                bindingHostId=host,
                fixedIps=fixed_ips,
                macAddress=vif.get('address'),
                tag=vif.get('tag'),
            ),
            status=PortStatus(
                phase=PortPhase.PENDING,
                portId=vif.get('id'),
                macAddress=vif.get('address'),
                vifType=vif.get('type'),
                vifDetails=vif.get('details'),
            )
        )


class PortCrd(Crd):
    """Port Custom Resource Definition."""

    CRD_KIND = 'Port'
    CRD_PLURAL = 'ports'
    CRD_SINGULAR = 'port'
    CRD_NAME = 'ports.nova.openstack.org'
    CRD_SHORT_NAMES = []
    CRD_SPEC = PortSpec
    CRD_STATUS = PortStatus

    def __init__(self, api_client, namespace: str):
        super().__init__(api_client, namespace)

    def create_from_vif(self, vif: dict, instance_uuid: str, host: str) -> dict:
        """Create a Port CRD from a Nova VIF."""
        obj = PortObject.from_vif(vif, instance_uuid, host)
        return self.create_object(obj)

    def get_port(self, port_id: str) -> Optional[dict]:
        """Get a Port CRD by port ID."""
        return self.get(port_id)

    def list_ports(self, instance_uuid: str = None, host: str = None) -> list:
        """List Port CRDs with optional filters."""
        # Build label selector
        selectors = []
        if host:
            selectors.append(f"host={host}")
        label_selector = ",".join(selectors) if selectors else None

        ports = self.list(label_selector=label_selector)

        # Filter by instance if specified
        if instance_uuid:
            ports = [p for p in ports if p.get('spec', {}).get('instanceRef') == instance_uuid]

        return ports

    def update_binding(self, port_id: str, host: str) -> dict:
        """Update the binding host for a port."""
        return self.patch(port_id, {"spec": {"bindingHostId": host}})

    def update_phase(self, port_id: str, phase: PortPhase) -> dict:
        """Update the phase of a port."""
        return self.patch_status(port_id, {"phase": phase.value})

    def mark_bound(self, port_id: str, vif_type: str = None,
                   vif_details: dict = None, fixed_ips: list = None) -> dict:
        """Mark a port as bound with binding details."""
        status = {
            "phase": PortPhase.BOUND.value,
            "boundAt": datetime.utcnow().isoformat() + "Z"
        }
        if vif_type:
            status["vifType"] = vif_type
        if vif_details:
            status["vifDetails"] = vif_details
        if fixed_ips:
            status["fixedIps"] = [
                {"ipAddress": ip.get('ip_address'), "subnetId": ip.get('subnet_id')}
                for ip in fixed_ips
            ]
        return self.patch_status(port_id, status)

    def mark_failed(self, port_id: str, reason: str = None) -> dict:
        """Mark a port as failed."""
        status = {"phase": PortPhase.FAILED.value}
        if reason:
            status["conditions"] = [{
                "type": "Ready",
                "status": "False",
                "reason": "BindingFailed",
                "message": reason,
                "lastTransitionTime": datetime.utcnow().isoformat() + "Z"
            }]
        return self.patch_status(port_id, status)
