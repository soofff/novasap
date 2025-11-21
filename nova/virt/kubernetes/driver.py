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
"""


import time
from oslo_log import log as logging
from nova.network import model as network_model
import typing as ty

from nova import objects
from nova import context as nova_context
import nova.conf
from nova.objects.instance import Instance
from nova.virt import driver

from kubernetes import client, config, utils

from nova.virt.kubernetes.os_crd_instance import OsCrdInstance, OsCrdObjBodyInstanceBody, OsCrdObjInstanceAction, OsCrdObjInstanceActionState
from nova.virt.libvirt import LibvirtDriver

LOG = logging.getLogger(__name__)

CONF = nova.conf.CONF


class KubernetesDriver(driver.ComputeDriver):
    capabilities = {
        "has_imagecache": False,
        "supports_evacuate": False,
        "supports_migrate_to_same_host": False,
        "resource_scheduling": False,
        "supports_attach_interface": False,
        "supports_device_tagging": False,
        "supports_tagged_attach_interface": False,
        "supports_tagged_attach_volume": False,
        "supports_extend_volume": False,
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

        LOG.debug('Loading Kubernetes configuration')
        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config()

        self._kubernetes = client.ApiClient()
        self._os_crd_instance = OsCrdInstance(
            self._kubernetes, CONF.kubernetes.namespace)

    def init_host(self, host):
        LOG.debug('trying to apply OS Instance CRD')
        created = self._os_crd_instance.create_manifest()

        if created:
            LOG.info('OS Instance CRD created')
        else:
            LOG.info('OS Instance CRD already exists')

    def instance_exists(self, instance) -> bool:
        result = self._os_crd_instance.get(instance)
        return result is not None

    def list_instances(self):
        results = self._os_crd_instance.list(self._hostname)
        return [obj.spec["display_name"] for obj in results]

    def list_instance_uuids(self):
        results = self._os_crd_instance.list(self._hostname)
        return [obj.spec["uuid"] for obj in results]

    def plug_vifs(self, instance, network_info):
        pass

    def unplug_vifs(self, instance, network_info):
        pass

    def destroy(self, context, instance, network_info, block_device_info=None,
                destroy_disks=True, destroy_secrets=True):
        self._os_crd_instance.patch(
            instance,
            OsCrdObjBodyInstanceBody(
                action=OsCrdObjInstanceAction(destroy=True)
            )
        )

        # TODO self._os_crd_instance.wait_status(instance['uuid'], 'destroyed')

    def cleanup(self, context, instance, network_info, block_device_info=None,
                destroy_disks=True, migrate_data=None, destroy_vifs=True, destroy_secrets=True):
        pass

    def cleanup_lingering_instance_resources(self, instance):
        pass

    def get_volume_connector(self, instance):
        pass

    def attach_volume(self, context, connection_info, instance, mountpoint,
                      disk_bus=None, device_type=None, encryption=None):
        pass

    def swap_volume(self, context, old_connection_info, new_connection_info, instance, mountpoint, resize_to):
        pass

    def emit_event(self, event):
        pass

    def detach_volume(self, context, connection_info, instance, mountpoint, encryption=None):
        pass

    def extend_volume(self, context, connection_info, instance, requested_size):
        pass

    def attach_interface(self, context, instance, image_meta, vif):
        pass

    def detach_interface(self, context, instance, vif):
        pass

    def snapshot(self, context, instance, image_id, update_task_state):
        pass

    def set_admin_password(self, instance, new_pass):
        pass

    def quiesce(self, context, instance, image_meta):
        pass

    def unquiesce(self, context, instance, image_meta):
        pass

    def volume_snapshot_create(self, context, instance, volume_id,
                               create_info):
        pass

    def volume_snapshot_delete(self, context, instance, volume_id, snapshot_id,
                               delete_info):
        pass

    def reboot(self, context, instance, network_info, reboot_type,
               block_device_info=None, bad_volumes_callback=None,
               accel_info=None):
        if reboot_type == 'SOFT':
            reboot_type = OsCrdObjInstanceActionState.REBOOT_SOFT
        else:
            reboot_type = OsCrdObjInstanceActionState.REBOOT_HARD

        self._os_crd_instance.patch(
            instance,
            OsCrdObjBodyInstanceBody(
                action=OsCrdObjInstanceAction(state=reboot_type)
            )
        )

    def pause(self, instance):
        self._os_crd_instance.patch(
            instance,
            OsCrdObjBodyInstanceBody(
                action=OsCrdObjInstanceAction(
                    state=OsCrdObjInstanceActionState.PAUSE)
            )
        )

    def unpause(self, instance):
        self._os_crd_instance.patch(
            instance,
            OsCrdObjBodyInstanceBody(
                action=OsCrdObjInstanceAction(
                    state=OsCrdObjInstanceActionState.UNPAUSE)
            )
        )

    def power_off(self, instance, timeout=0, retry_interval=0):
        self._os_crd_instance.patch(
            instance,
            OsCrdObjBodyInstanceBody(
                action=OsCrdObjInstanceAction(
                    state=OsCrdObjInstanceActionState.POWER_OFF)
            )
        )

    def power_on(self, context, instance, network_info,
                 block_device_info=None, accel_info=None):
        self._os_crd_instance.patch(
            instance,
            OsCrdObjBodyInstanceBody(
                action=OsCrdObjInstanceAction(
                    state=OsCrdObjInstanceActionState.POWER_ON)
            )
        )

    def trigger_crash_dump(self, instance):
        pass

    def suspend(self, context, instance):
        self._os_crd_instance.patch(
            instance,
            OsCrdObjBodyInstanceBody(
                action=OsCrdObjInstanceAction(
                    state=OsCrdObjInstanceActionState.SUSPEND)
            )
        )

    def resume(self, context, instance, network_info, block_device_info=None):
        self._os_crd_instance.patch(
            instance,
            OsCrdObjBodyInstanceBody(
                action=OsCrdObjInstanceAction(
                    state=OsCrdObjInstanceActionState.RESUME)
            )
        )

    def resume_state_on_host_boot(self, context, instance, network_info,
                                  block_device_info=None):
        pass

    def rescue(self, context, instance, network_info, image_meta,
               rescue_password, block_device_info):
        pass

    def unrescue(
        self,
        context: nova_context.RequestContext,
        instance: 'objects.Instance',
    ):
        pass

    def poll_rebooting_instances(self, timeout, instances):
        pass

    def spawn(self, context, instance: Instance, image_meta, injected_files,
              admin_password, allocations, network_info=None,
              block_device_info=None, power_on=True, accel_info=None):
        self._os_crd_instance.create(instance)
        # TODO wait

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

    def update_provider_tree(self, provider_tree, nodename, allocations=None):
        pass

    def get_available_resource(self, nodename):
        pass

    def check_instance_shared_storage_local(self, context, instance):
        pass

    def check_instance_shared_storage_remote(self, context, data):
        pass

    def check_instance_shared_storage_cleanup(self, context, data):
        pass

    def check_can_live_migrate_destination(self, context, instance,
                                           src_compute_info, dst_compute_info,
                                           block_migration=False,
                                           disk_over_commit=False):
        pass

    def post_claim_migrate_data(self, context, instance, migrate_data, claim):
        pass

    def cleanup_live_migration_destination_check(self, context,
                                                 dest_check_data):
        pass

    def check_can_live_migrate_source(self, context, instance,
                                      dest_check_data,
                                      block_device_info=None):
        pass

    def live_migration(self, context, instance, dest,
                       post_method, recover_method, block_migration=False,
                       migrate_data=None):
        pass

    def live_migration_abort(self, instance):
        pass

    def live_migration_force_complete(self, instance):
        pass

    def rollback_live_migration_at_source(self, context, instance,
                                          migrate_data):
        pass

    def rollback_live_migration_at_destination(self, context, instance,
                                               network_info,
                                               block_device_info,
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

    def post_live_migration_at_destination(self, context,
                                        instance,
                                        network_info,
                                        block_migration=False,
                                        block_device_info=None):
        pass

    def get_instance_disk_info(self, instance,
                               block_device_info=None):
        pass

    def get_available_nodes(self, refresh=False):
        pass

    def get_nodenames_by_uuid(self, refresh=False):
        pass

    def get_host_cpu_stats(self):
        pass

    def get_host_uptime(self):
        return LibvirtDriver.get_host_uptime(self)

    def manage_image_cache(self, context, all_instances):
        pass

    def cache_image(self, context, image_id):
        pass

    def finish_migration(
        self,
        context: nova_context.RequestContext,
        migration: 'objects.Migration',
        instance: 'objects.Instance',
        disk_info: str,
        network_info: network_model.NetworkInfo,
        image_meta: 'objects.ImageMeta',
        resize_instance: bool,
        allocations: ty.Dict[str, ty.Any],
        block_device_info: ty.Optional[ty.Dict[str, ty.Any]] = None,
        power_on: bool = True,
    ) -> None:
        pass

    def finish_revert_migration(
            self,
            context: nova.context.RequestContext,
            instance: 'objects.Instance',
            network_info: network_model.NetworkInfo,
            migration: 'objects.Migration',
            block_device_info: ty.Optional[ty.Dict[str, ty.Any]] = None,
            power_on: bool = True,
        ) -> None:
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
