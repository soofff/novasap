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


from oslo_log import log as logging

import nova.conf
from nova.virt import driver


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

    def spawn(self, context, instance, image_meta, injected_files,
              admin_password, allocations, network_info=None,
              block_device_info=None, power_on=True, accel_info=None):
        """Create a new instance/VM/domain on the virtualization platform.

        Once this successfully completes, the instance should be
        running (power_state.RUNNING) if ``power_on`` is True, else the
        instance should be stopped (power_state.SHUTDOWN).

        If this fails, any partial instance should be completely
        cleaned up, and the virtualization platform should be in the state
        that it was before this call began.

        :param context: security context
        :param instance: nova.objects.instance.Instance
                         This function should use the data there to guide
                         the creation of the new instance.
        :param nova.objects.ImageMeta image_meta:
            The metadata of the image of the instance.
        :param injected_files: User files to inject into instance.
        :param admin_password: Administrator password to set in instance.
        :param allocations: Information about resources allocated to the
                            instance via placement, of the form returned by
                            SchedulerReportClient.get_allocations_for_consumer.
        :param network_info: instance network information
        :param block_device_info: Information about block devices to be
                                  attached to the instance.
        :param power_on: True if the instance should be powered on, False
                         otherwise
        :param arqs: List of bound accelerator requests for this instance.
            [
             {'uuid': $arq_uuid,
              'device_profile_name': $dp_name,
              'device_profile_group_id': $dp_request_group_index,
              'state': 'Bound',
              'device_rp_uuid': $resource_provider_uuid,
              'hostname': $host_nodename,
              'instance_uuid': $instance_uuid,
              'attach_handle_info': {  # PCI bdf
                'bus': '0c', 'device': '0', 'domain': '0000', 'function': '0'},
              'attach_handle_type': 'PCI'
                   # or 'TEST_PCI' for Cyborg fake driver
             }
            ]
            Also doc'd in nova/accelerator/cyborg.py::get_arqs_for_instance()
        """
        raise NotImplementedError()

    def destroy(self, context, instance, network_info, block_device_info=None,
                destroy_disks=True, destroy_secrets=True):
        """Destroy the specified instance from the Hypervisor.

        If the instance is not found (for example if networking failed), this
        function should still succeed.  It's probably a good idea to log a
        warning in that case.

        :param context: security context
        :param instance: Instance object as returned by DB layer.
        :param network_info: instance network information
        :param block_device_info: Information about block devices that should
                                  be detached from the instance.
        :param destroy_disks: Indicates if disks should be destroyed
        :param destroy_secrets: Indicates if secrets should be destroyed
        """
        raise NotImplementedError()
