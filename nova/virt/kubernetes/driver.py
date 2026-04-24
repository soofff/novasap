# Copyright (c) 2013 Hewlett-Packard Development Company, L.P.
# Copyright (c) 2012 VMware, Inc.
# Copyright (c) 2011 Citrix Systems, Inc.
# Copyright 2011 OpenStack Foundation
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""
Compute driver for Kubernetes clusters.

This driver exports Nova instance lifecycle operations to Kubernetes CRDs,
enabling a Kubernetes controller to perform the actual VM operations.
The CRD schema matches the monsoon4 nova reimplementation for compatibility.
"""

import typing as ty

from oslo_log import log as logging

from nova import objects
from nova import context as nova_context
import nova.conf
from nova.objects.instance import Instance
from nova.virt import driver
from nova.virt.hardware import InstanceInfo
from nova.virt.kubernetes.crd_instance import (
    InstanceCrd, InstanceObject, PowerState, RebootType, VmState, ObservedPowerState,
    VolumeAttachment, InterfaceAttachment, InterfaceState
)
from nova.virt.kubernetes.crd_port import PortCrd, PortPhase
from nova.virt.kubernetes.utils import k8s_unit_to_mb
from nova.virt.libvirt import LibvirtDriver
from nova.network import model as network_model

from kubernetes import client, config

LOG = logging.getLogger(__name__)

CONF = nova.conf.CONF


class KubernetesDriver(driver.ComputeDriver):
    """Kubernetes CRD-based compute driver.

    This driver creates Kubernetes Custom Resources for instances and ports
    instead of directly managing VMs. A separate controller watches these
    CRDs and performs the actual VM operations.
    """

    capabilities = {
        "has_imagecache": False,
        "supports_evacuate": False,
        "supports_migrate_to_same_host": False,
        "resource_scheduling": False,
        "supports_attach_interface": True,  # Implemented via Port CRD
        "supports_device_tagging": False,
        "supports_tagged_attach_interface": False,
        "supports_tagged_attach_volume": False,
        "supports_extend_volume": True,  # Implemented via Instance status
        "supports_multiattach": False,
        "supports_trusted_certs": False,
        "supports_pcpus": False,
        "supports_accelerators": False,
        "supports_bfv_rescue": False,
        "supports_vtpm": False,
        "supports_secure_boot": False,
        "supports_socket_pci_numa_affinity": False,
        "supports_remote_managed_ports": False,
        "supports_address_space_passthrough": False,
        "supports_address_space_emulated": False,

        # Ephemeral encryption support flags
        "supports_ephemeral_encryption": False,
        "supports_ephemeral_encryption_luks": False,
        "supports_ephemeral_encryption_plain": False,

        # Image type support flags
        "supports_image_type_aki": False,
        "supports_image_type_ami": False,
        "supports_image_type_ari": False,
        "supports_image_type_iso": False,
        "supports_image_type_qcow2": False,
        "supports_image_type_raw": False,
        "supports_image_type_vdi": False,
        "supports_image_type_vhd": False,
        "supports_image_type_vhdx": False,
        "supports_image_type_vmdk": False,
        "supports_image_type_ploop": False,
        "driver_specific_device_name": False
    }

    def __init__(self, virtapi, scheme="https"):
        super(KubernetesDriver, self).__init__(virtapi)

        self._hostname = None
        self._k8s_node = None

        self._load_kube_config()
        self._kubernetes = client.ApiClient()
        self._kubernetes_v1 = client.CoreV1Api(self._kubernetes)

        # Initialize CRD clients
        namespace = CONF.kubernetes.namespace
        self._instance_crd = InstanceCrd(self._kubernetes, namespace)
        self._port_crd = PortCrd(self._kubernetes, namespace)

    def _load_kube_config(self):
        if CONF.kubernetes.config:
            LOG.info('Loading kubeconfig from %s', CONF.kubernetes.config)
            config.load_kube_config(config_file=CONF.kubernetes.config)
        else:
            try:
                LOG.info('Loading in-cluster kubeconfig')
                config.load_incluster_config()
            except config.ConfigException:
                LOG.info('Loading default kubeconfig')
                config.load_kube_config()

    def _get_node_from_k8s(self):
        LOG.debug('Getting node UUID from Kubernetes for host %s', self._hostname)
        node = self._kubernetes_v1.read_node(self._hostname)
        self._k8s_node = node

    def init_host(self, host):
        """Initialize the driver on a compute host."""
        self._hostname = host

        if CONF.kubernetes.apply_crds:
            LOG.debug('Applying Instance CRD')
            if self._instance_crd.create_manifest():
                LOG.info('Instance CRD created')
            else:
                LOG.debug('Instance CRD already exists')

            LOG.debug('Applying Port CRD')
            if self._port_crd.create_manifest():
                LOG.info('Port CRD created')
            else:
                LOG.debug('Port CRD already exists')

        self._get_node_from_k8s()

    # ==================== Instance Lifecycle ====================

    def spawn(self, context, instance: Instance, image_meta, injected_files,
              admin_password, allocations, network_info=None,
              block_device_info=None, power_on=True, accel_info=None):
        """Create a new instance via CRD."""
        LOG.info('Spawning instance %s', instance['uuid'])

        # Create the Instance CRD
        self._instance_crd.create(instance, self._hostname)

        # Create Port CRDs for each network interface
        if network_info:
            for vif in network_info:
                try:
                    self._port_crd.create_from_vif(vif, instance['uuid'], self._hostname)
                    LOG.debug('Created Port CRD for VIF %s', vif.get('id'))
                except Exception as e:
                    LOG.warning('Failed to create Port CRD for VIF %s: %s',
                                vif.get('id'), e)

        # Update status to indicate spawning
        self._instance_crd.update_status(
            instance['uuid'],
            vmState=VmState.BUILDING,
            taskState='spawning',
            hypervisor=self._hostname
        )

    def destroy(self, context, instance, network_info, block_device_info=None,
                destroy_disks=True, destroy_secrets=True):
        """Destroy an instance by deleting its CRD."""
        LOG.info('Destroying instance %s', instance['uuid'])

        # Delete associated Port CRDs
        ports = self._port_crd.list_ports(instance_uuid=instance['uuid'])
        for port in ports:
            port_name = port.get('metadata', {}).get('name')
            if port_name:
                try:
                    self._port_crd.delete(port_name)
                    LOG.debug('Deleted Port CRD %s', port_name)
                except Exception as e:
                    LOG.warning('Failed to delete Port CRD %s: %s', port_name, e)

        # Delete the Instance CRD
        self._instance_crd.delete(instance['uuid'])

    def cleanup(self, context, instance, network_info, block_device_info=None,
                destroy_disks=True, migrate_data=None, destroy_vifs=True,
                destroy_secrets=True):
        """Clean up after an instance."""
        pass

    def instance_exists(self, instance) -> bool:
        """Check if an instance CRD exists."""
        result = self._instance_crd.get(instance['uuid'])
        return result is not None

    def list_instances(self):
        """List instance display names on this host."""
        results = self._instance_crd.list_instances(self._hostname)
        return [obj.get('spec', {}).get('name', '') for obj in results]

    def list_instance_uuids(self):
        """List instance UUIDs on this host."""
        results = self._instance_crd.list_instances(self._hostname)
        return [obj.get('metadata', {}).get('name', '') for obj in results]

    def get_info(self, instance, use_cache=True):
        """Get instance information from CRD."""
        obj = self._instance_crd.get(instance['uuid'])

        if not obj:
            raise exception.InstanceNotFound(instance_id=instance['uuid'])

        status = obj.get('status', {})

        # Map CRD power state to Nova power state integer
        power_state_str = status.get('powerState', 'NO_STATE')
        power_state_map = {
            'NO_STATE': 0,
            'RUNNING': 1,
            'PAUSED': 3,
            'SHUTDOWN': 4,
            'CRASHED': 6,
            'SUSPENDED': 7,
        }
        power_state = power_state_map.get(power_state_str, 0)

        return InstanceInfo(
            state=power_state,
            internal_id=instance['uuid']
        )

    # ==================== Power Management ====================

    def reboot(self, context, instance, network_info, reboot_type,
               block_device_info=None, bad_volumes_callback=None,
               accel_info=None):
        """Request a reboot via CRD."""
        LOG.info('Rebooting instance %s (type=%s)', instance['uuid'], reboot_type)

        if reboot_type == 'SOFT':
            rt = RebootType.SOFT
        else:
            rt = RebootType.HARD

        self._instance_crd.request_reboot(instance['uuid'], rt)

    def pause(self, instance):
        """Pause an instance."""
        LOG.info('Pausing instance %s', instance['uuid'])
        self._instance_crd.update_power_state(instance['uuid'], PowerState.PAUSED)

    def unpause(self, instance):
        """Unpause an instance."""
        LOG.info('Unpausing instance %s', instance['uuid'])
        self._instance_crd.update_power_state(instance['uuid'], PowerState.RUNNING)

    def power_off(self, instance, timeout=0, retry_interval=0):
        """Power off an instance."""
        LOG.info('Powering off instance %s', instance['uuid'])
        self._instance_crd.update_power_state(instance['uuid'], PowerState.STOPPED)

    def power_on(self, context, instance, network_info,
                 block_device_info=None, accel_info=None):
        """Power on an instance."""
        LOG.info('Powering on instance %s', instance['uuid'])
        self._instance_crd.update_power_state(instance['uuid'], PowerState.RUNNING)

    def suspend(self, context, instance):
        """Suspend an instance."""
        LOG.info('Suspending instance %s', instance['uuid'])
        # Suspended is represented as STOPPED with a different VM state
        self._instance_crd.update_power_state(instance['uuid'], PowerState.STOPPED)
        self._instance_crd.update_status(instance['uuid'], taskState='suspending')

    def resume(self, context, instance, network_info, block_device_info=None):
        """Resume a suspended instance."""
        LOG.info('Resuming instance %s', instance['uuid'])
        self._instance_crd.update_power_state(instance['uuid'], PowerState.RUNNING)

    # ==================== Network Operations ====================

    def plug_vifs(self, instance, network_info):
        """Plug VIFs by creating/updating Port CRDs."""
        LOG.debug('Plugging VIFs for instance %s', instance['uuid'])

        for vif in network_info:
            vif_id = vif.get('id')
            existing = self._port_crd.get_port(vif_id)

            if existing:
                # Update binding host
                self._port_crd.update_binding(vif_id, self._hostname)
            else:
                # Create new Port CRD
                self._port_crd.create_from_vif(vif, instance['uuid'], self._hostname)

            LOG.debug('Plugged VIF %s', vif_id)

    def unplug_vifs(self, instance, network_info):
        """Unplug VIFs by updating Port CRD status."""
        LOG.debug('Unplugging VIFs for instance %s', instance['uuid'])

        for vif in network_info:
            vif_id = vif.get('id')
            try:
                # Mark port as unbound rather than deleting
                self._port_crd.update_phase(vif_id, PortPhase.PENDING)
                LOG.debug('Unplugged VIF %s', vif_id)
            except Exception as e:
                LOG.warning('Failed to unplug VIF %s: %s', vif_id, e)

    def attach_interface(self, context, instance, image_meta, vif):
        """Attach a network interface to an instance."""
        LOG.info('Attaching interface %s to instance %s',
                 vif.get('id'), instance['uuid'])

        # Create Port CRD
        self._port_crd.create_from_vif(vif, instance['uuid'], self._hostname)

        # Update instance status with new interface
        self._update_instance_interfaces(instance)

    def detach_interface(self, context, instance, vif):
        """Detach a network interface from an instance."""
        LOG.info('Detaching interface %s from instance %s',
                 vif.get('id'), instance['uuid'])

        # Delete Port CRD
        self._port_crd.delete(vif.get('id'))

        # Update instance status
        self._update_instance_interfaces(instance)

    def _update_instance_interfaces(self, instance):
        """Update instance status with current interface list."""
        ports = self._port_crd.list_ports(instance_uuid=instance['uuid'])

        interfaces = []
        for port in ports:
            spec = port.get('spec', {})
            status = port.get('status', {})

            phase = status.get('phase', 'Pending')
            state_map = {
                'Pending': InterfaceState.ATTACHING,
                'Binding': InterfaceState.ATTACHING,
                'Bound': InterfaceState.ATTACHED,
                'Failed': InterfaceState.DETACHING,
            }

            interfaces.append({
                'portId': spec.get('portId') or port.get('metadata', {}).get('name'),
                'state': state_map.get(phase, InterfaceState.ATTACHING).value,
                'netId': spec.get('networkId'),
                'macAddr': status.get('macAddress'),
            })

        self._instance_crd.update_status(instance['uuid'], interfaces=interfaces)

    # ==================== Volume Operations ====================

    def attach_volume(self, context, connection_info, instance, mountpoint,
                      disk_bus=None, device_type=None, encryption=None):
        """Attach a volume by updating Instance CRD status."""
        LOG.info('Attaching volume to instance %s at %s',
                 instance['uuid'], mountpoint)

        volume_id = connection_info.get('data', {}).get('volume_id') or \
                    connection_info.get('serial')
        attachment_id = connection_info.get('data', {}).get('attachment_id', volume_id)

        # Get current attachments
        obj = self._instance_crd.get(instance['uuid'])
        current = obj.get('status', {}).get('volumeAttachments', []) if obj else []

        # Add new attachment
        new_attachment = {
            'id': attachment_id,
            'volumeId': volume_id,
            'device': mountpoint,
            'deleteOnTermination': False,
        }
        current.append(new_attachment)

        self._instance_crd.update_status(instance['uuid'], volumeAttachments=current)

    def detach_volume(self, context, connection_info, instance, mountpoint,
                      encryption=None):
        """Detach a volume by updating Instance CRD status."""
        LOG.info('Detaching volume from instance %s at %s',
                 instance['uuid'], mountpoint)

        volume_id = connection_info.get('data', {}).get('volume_id') or \
                    connection_info.get('serial')

        # Get current attachments
        obj = self._instance_crd.get(instance['uuid'])
        current = obj.get('status', {}).get('volumeAttachments', []) if obj else []

        # Remove the attachment
        updated = [a for a in current if a.get('volumeId') != volume_id]

        self._instance_crd.update_status(instance['uuid'], volumeAttachments=updated)

    def swap_volume(self, context, old_connection_info, new_connection_info,
                    instance, mountpoint, resize_to):
        """Swap a volume by updating Instance CRD status."""
        LOG.info('Swapping volume for instance %s at %s',
                 instance['uuid'], mountpoint)

        old_volume_id = old_connection_info.get('data', {}).get('volume_id') or \
                        old_connection_info.get('serial')
        new_volume_id = new_connection_info.get('data', {}).get('volume_id') or \
                        new_connection_info.get('serial')
        new_attachment_id = new_connection_info.get('data', {}).get('attachment_id', new_volume_id)

        # Get current attachments
        obj = self._instance_crd.get(instance['uuid'])
        current = obj.get('status', {}).get('volumeAttachments', []) if obj else []

        # Replace the attachment
        updated = []
        for a in current:
            if a.get('volumeId') == old_volume_id:
                updated.append({
                    'id': new_attachment_id,
                    'volumeId': new_volume_id,
                    'device': mountpoint,
                    'deleteOnTermination': a.get('deleteOnTermination', False),
                })
            else:
                updated.append(a)

        self._instance_crd.update_status(instance['uuid'], volumeAttachments=updated)

    def extend_volume(self, context, connection_info, instance, requested_size):
        """Extend a volume - the CRD controller handles the actual resize."""
        LOG.info('Extending volume for instance %s to %s',
                 instance['uuid'], requested_size)
        # Volume extension is handled by the controller watching the CRD
        # We just need to ensure the instance is aware
        pass

    def get_volume_connector(self, instance):
        """Return volume connector information."""
        # Return basic connector info - the controller handles actual connection
        return {
            'host': self._hostname,
            'instance': instance['uuid'],
        }

    # ==================== Resource Management ====================

    def update_provider_tree(self, provider_tree, nodename, allocations=None):
        """Update the provider tree with resource inventory."""
        from nova.objects import fields as obj_fields
        from nova.virt.libvirt import utils as libvirt_utils
        from oslo_utils import units
        import os_resource_classes as orc

        status = self._k8s_node.status

        cpu_capacity = int(status.capacity.get('cpu', 0))

        memory_str = status.capacity.get('memory', '0Ki')
        memory_mb = k8s_unit_to_mb(memory_str)

        disk = libvirt_utils.get_fs_info(CONF.instances_path)
        disk_gb = int(disk['total'] / units.Gi)

        if not provider_tree.exists(nodename):
            provider_tree.new_root(
                nodename,
                self._k8s_node.metadata.uid,
                generation=0
            )

        inventory = {
            orc.VCPU: {
                'total': cpu_capacity,
                'reserved': 0,
                'min_unit': 1,
                'max_unit': cpu_capacity,
                'step_size': 1,
                'allocation_ratio': 1,
            },
            orc.MEMORY_MB: {
                'total': memory_mb,
                'reserved': 512,
                'min_unit': 1,
                'max_unit': memory_mb,
                'step_size': 1,
                'allocation_ratio': 1,
            },
            orc.DISK_GB: {
                'total': disk_gb,
                'reserved': 0,
                'min_unit': 1,
                'max_unit': disk_gb,
                'step_size': 1,
                'allocation_ratio': 1,
            },
        }

        provider_tree.update_inventory(nodename, inventory)

    def get_available_resource(self, nodename):
        """Get available resources for a node."""
        import psutil
        from nova.objects import fields as obj_fields
        from nova.virt.libvirt import utils as libvirt_utils
        from oslo_utils import units

        status = self._k8s_node.status

        disk = libvirt_utils.get_fs_info(CONF.instances_path)
        for (k, v) in disk.items():
            disk[k] = v / units.Gi

        memory = psutil.virtual_memory()

        host_status = {}
        host_status["hypervisor_type"] = "CHV"
        host_status["supported_instances"] = [
            (
                obj_fields.Architecture.X86_64,
                obj_fields.HVType.KVM,
                obj_fields.VMMode.HVM,
            )
        ]
        host_status["host_hostname"] = nodename
        host_status["host_name_label"] = nodename
        host_status["hypervisor_hostname"] = nodename
        host_status["local_gb"] = disk['total']
        host_status["local_gb_used"] = disk['used']
        host_status["memory_mb"] = memory.total // 1024 // 1024
        host_status["memory_mb_used"] = memory.used // 1024 // 1024
        host_status["vcpus"] = int(status.capacity['cpu'])
        host_status["vcpus_used"] = 0
        host_status["numa_topology"] = None

        return host_status

    def get_available_nodes(self, refresh=False):
        """Return available compute nodes."""
        return [self._hostname]

    def get_nodenames_by_uuid(self, refresh=False):
        """Return mapping of node UUIDs to hostnames."""
        return {self._k8s_node.metadata.uid: self._hostname}

    def get_host_uptime(self):
        """Return host uptime."""
        return LibvirtDriver.get_host_uptime(self)

    # ==================== Stub Methods ====================
    # These methods are not implemented but required by the driver interface

    def cleanup_lingering_instance_resources(self, instance):
        pass

    def emit_event(self, event):
        pass

    def snapshot(self, context, instance, image_id, update_task_state):
        pass

    def set_admin_password(self, instance, new_pass):
        pass

    def quiesce(self, context, instance, image_meta):
        pass

    def unquiesce(self, context, instance, image_meta):
        pass

    def volume_snapshot_create(self, context, instance, volume_id, create_info):
        pass

    def volume_snapshot_delete(self, context, instance, volume_id, snapshot_id,
                               delete_info):
        pass

    def trigger_crash_dump(self, instance):
        pass

    def resume_state_on_host_boot(self, context, instance, network_info,
                                  block_device_info=None):
        pass

    def rescue(self, context, instance, network_info, image_meta,
               rescue_password, block_device_info):
        pass

    def unrescue(self, context: nova_context.RequestContext,
                 instance: 'objects.Instance'):
        pass

    def poll_rebooting_instances(self, timeout, instances):
        pass

    def get_console_output(self, context, instance):
        pass

    def get_host_ip_addr(self):
        pass

    def get_vnc_console(self, context, instance):
        pass

    def get_spice_console(self, context, instance):
        pass

    def get_serial_console(self, context, instance):
        pass

    def get_all_volume_usage(self, context, compute_host_bdms):
        pass

    def block_stats(self, instance, disk_id):
        pass

    def check_instance_shared_storage_local(self, context, instance):
        pass

    def check_instance_shared_storage_remote(self, context, data):
        pass

    def check_instance_shared_storage_cleanup(self, context, data):
        pass

    # Migration methods - not implemented
    def check_can_live_migrate_destination(self, context, instance,
                                           src_compute_info, dst_compute_info,
                                           block_migration=False,
                                           disk_over_commit=False):
        pass

    def post_claim_migrate_data(self, context, instance, migrate_data, claim):
        pass

    def cleanup_live_migration_destination_check(self, context, dest_check_data):
        pass

    def check_can_live_migrate_source(self, context, instance, dest_check_data,
                                      block_device_info=None):
        pass

    def live_migration(self, context, instance, dest, post_method,
                       recover_method, block_migration=False,
                       migrate_data=None):
        pass

    def live_migration_abort(self, instance):
        pass

    def live_migration_force_complete(self, instance):
        pass

    def rollback_live_migration_at_source(self, context, instance, migrate_data):
        pass

    def rollback_live_migration_at_destination(self, context, instance,
                                               network_info, block_device_info,
                                               destroy_disks=True,
                                               migrate_data=None):
        pass

    def pre_live_migration(self, context, instance, block_device_info,
                           network_info, disk_info, migrate_data):
        pass

    def post_live_migration(self, context, instance, block_device_info,
                            migrate_data=None):
        pass

    def post_live_migration_at_source(self, context, instance, network_info):
        pass

    def post_live_migration_at_destination(self, context, instance,
                                           network_info, block_migration=False,
                                           block_device_info=None):
        pass

    def get_instance_disk_info(self, instance, block_device_info=None):
        pass

    def get_host_cpu_stats(self):
        pass

    def manage_image_cache(self, context, all_instances):
        pass

    def cache_image(self, context, image_id):
        pass

    def finish_migration(self, context: nova_context.RequestContext,
                         migration: 'objects.Migration',
                         instance: 'objects.Instance', disk_info: str,
                         network_info: network_model.NetworkInfo,
                         image_meta: 'objects.ImageMeta', resize_instance: bool,
                         allocations: ty.Dict[str, ty.Any],
                         block_device_info: ty.Optional[ty.Dict[str, ty.Any]] = None,
                         power_on: bool = True) -> None:
        pass

    def finish_revert_migration(self, context: nova_context.RequestContext,
                                instance: 'objects.Instance',
                                network_info: network_model.NetworkInfo,
                                migration: 'objects.Migration',
                                block_device_info: ty.Optional[ty.Dict[str, ty.Any]] = None,
                                power_on: bool = True) -> None:
        pass

    def confirm_migration(self, context, migration, instance, network_info):
        pass

    def get_diagnostics(self, instance):
        pass

    def get_instance_diagnostics(self, instance):
        pass

    def instance_on_disk(self, instance):
        pass

    def inject_network_info(self, instance, nw_info):
        pass

    def delete_instance_files(self, instance):
        pass

    def default_root_device_name(self, instance, image_meta, root_bdm):
        pass

    def default_device_names_for_instance(self, instance, root_device_name,
                                          *block_device_lists):
        pass

    def get_device_name_for_instance(self, instance, bdms, block_device_obj):
        pass

    def is_supported_fs_format(self, fs_type):
        pass
