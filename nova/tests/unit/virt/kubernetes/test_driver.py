"""Tests for the Kubernetes compute driver."""

from unittest import mock

from nova import test
from nova.tests.unit.objects import test_diagnostics
from nova.virt.hardware import InstanceInfo
from nova.virt.kubernetes import driver as kubernetes_driver
from nova.virt.kubernetes.crd_instance import PowerState, RebootType, VmState
from nova.virt.kubernetes.crd_port import PortPhase
from nova import objects


def _create_test_instance():
    """Create a test instance dictionary."""
    flavor = objects.Flavor(
        memory_mb=2048,
        swap=0,
        vcpu_weight=None,
        root_gb=10,
        id=2,
        name=u'm1.small',
        ephemeral_gb=20,
        rxtx_factor=1.0,
        flavorid=u'1',
        vcpus=2,
        extra_specs={}
    )
    return {
        'id': 1,
        'uuid': '860f5462-f16e-4836-a6aa-2935fc7fccc0',
        'memory_kb': '1024000',
        'basepath': '/some/path',
        'bridge_name': 'bridge1',
        'display_name': "test_instance",
        'vcpus': 2,
        'project_id': 'proj1',
        'bridge': 'br1',
        'image_ref': '155d900f-4e14-4e4c-a73d-069cbf4541e6',
        'root_gb': 10,
        'ephemeral_gb': 20,
        'system_metadata': {
            'image_disk_format': 'raw'
        },
        'instance_type_id': flavor.id,
        'flavor': flavor,
        'new_flavor': None,
        'old_flavor': None,
        'pci_devices': objects.PciDeviceList(),
        'numa_topology': None,
        'config_drive': None,
        'vm_mode': None,
        'vm_state': 'active',
        'kernel_id': None,
        'ramdisk_id': None,
        'os_type': 'linux',
        'user_id': '838a72b0-0d54-4827-8fd6-fb1227633ceb',
        'ephemeral_key_uuid': None,
        'vcpu_model': None,
        'host': 'fake-host',
        'node': 'fake-node',
        'task_state': None,
        'trusted_certs': None,
        'resources': None,
        'migration_context': None,
        'info_cache': None,
        'power_state': 1,
        'locked': False,
    }


def _create_test_vif():
    """Create a test VIF dictionary."""
    return {
        'id': 'vif-uuid-123',
        'address': 'fa:16:3e:aa:bb:cc',
        'type': 'bridge',
        'network': {
            'id': 'network-uuid-456',
            'label': 'private-net',
        },
        'details': {},
    }


def _create_driver():
    """Create a KubernetesDriver instance with mocked hostname."""
    driver = kubernetes_driver.KubernetesDriver(None)
    driver._hostname = 'test-host'
    return driver


class KubernetesDriverTestCase(test.NoDBTestCase, test_diagnostics.DiagnosticsComparisonMixin):
    """Test cases for the Kubernetes compute driver."""

    def setUp(self):
        super().setUp()

        # Patch load_kube_config
        self.kube_config_patcher = mock.patch(
            'kubernetes.config.load_kube_config', autospec=True)
        self.mock_load_kube_config = self.kube_config_patcher.start()
        self.mock_load_kube_config.return_value = None
        self.addCleanup(self.kube_config_patcher.stop)

        # Patch CustomObjectsApi
        self.kube_custom_obj_api_patcher = mock.patch(
            'kubernetes.client.CustomObjectsApi', autospec=True)
        self.mock_custom_obj_api = self.kube_custom_obj_api_patcher.start()
        self.mock_custom_obj_api.return_value.get_namespaced_custom_object.return_value = {
            "spec": {"name": "test", "powerState": "RUNNING"},
            "status": {"vmState": "ACTIVE", "powerState": "RUNNING"},
            "metadata": {"name": "test-instance"}
        }
        self.addCleanup(self.kube_custom_obj_api_patcher.stop)

        self.mock_custom_obj_api.return_value.list_namespaced_custom_object.return_value = {
            "items": [{
                "spec": {"name": "test1"},
                "status": {"vmState": "ACTIVE"},
                "metadata": {"name": "uuid1"}
            }, {
                "spec": {"name": "test2"},
                "status": {"vmState": "PAUSED"},
                "metadata": {"name": "uuid2"}
            }]
        }

        # Patch CoreV1Api
        self.kube_v1_api_patcher = mock.patch(
            'kubernetes.client.CoreV1Api.read_node', autospec=True)
        self.mock_v1_api = self.kube_v1_api_patcher.start()
        self.mock_v1_api.return_value = mock.MagicMock()
        self.mock_v1_api.return_value.metadata.uid = 'ff0183d3-fb29-485c-ac6c-2616c2ccb258'
        self.mock_v1_api.return_value.status.capacity = {
            'cpu': '4',
        }
        self.addCleanup(self.kube_v1_api_patcher.stop)

        # Patch get_fs_info
        self.get_fs_info_patcher = mock.patch(
            "nova.virt.libvirt.utils.get_fs_info", autospec=True)
        self.mock_get_fs_info = self.get_fs_info_patcher.start()
        self.mock_get_fs_info.return_value = {
            'total': 100 * 1024 * 1024 * 1024,
            'used': 50 * 1024 * 1024 * 1024,
            'free': 50 * 1024 * 1024 * 1024,
        }
        self.addCleanup(self.get_fs_info_patcher.stop)

        # Patch psutil.virtual_memory
        self.psutil_virtual_memory_patcher = mock.patch(
            "psutil.virtual_memory", autospec=True)
        self.mock_psutil_virtual_memory = self.psutil_virtual_memory_patcher.start()
        mock_memory = mock.MagicMock()
        mock_memory.total = 8 * 1024 * 1024 * 1024
        mock_memory.used = 4 * 1024 * 1024 * 1024
        self.mock_psutil_virtual_memory.return_value = mock_memory
        self.addCleanup(self.psutil_virtual_memory_patcher.stop)

    def test_init_host(self):
        """Test driver initialization."""
        driver = kubernetes_driver.KubernetesDriver(None)
        driver.init_host("test-host")
        self.assertEqual("test-host", driver._hostname)
        self.assertEqual("ff0183d3-fb29-485c-ac6c-2616c2ccb258",
                         driver._k8s_node.metadata.uid)

    def test_get_host_uptime(self):
        """Test getting host uptime."""
        driver = kubernetes_driver.KubernetesDriver(None)
        result = driver.get_host_uptime()
        self.assertIn("up", result)
        self.assertIn("load average", result)

    def test_spawn(self):
        """Test spawning an instance creates CRD."""
        driver = _create_driver()
        test_instance = _create_test_instance()
        driver.spawn(None, test_instance, None, None, None, None)
        self.mock_custom_obj_api.return_value.create_namespaced_custom_object.assert_called()

    def test_spawn_with_network_info(self):
        """Test spawning creates Port CRDs for network interfaces."""
        driver = _create_driver()
        test_instance = _create_test_instance()
        network_info = [_create_test_vif()]

        driver.spawn(None, test_instance, None, None, None, None,
                     network_info=network_info)

        # Should create Instance CRD and Port CRD
        create_calls = self.mock_custom_obj_api.return_value.create_namespaced_custom_object.call_args_list
        self.assertGreaterEqual(len(create_calls), 1)

    def test_instance_exists(self):
        """Test checking instance existence."""
        driver = _create_driver()
        test_instance = _create_test_instance()
        result = driver.instance_exists(test_instance)
        self.assertTrue(result)

    def test_list_instances(self):
        """Test listing instance names."""
        driver = _create_driver()
        result = driver.list_instances()
        self.assertListEqual(result, ['test1', 'test2'])

    def test_list_instance_uuids(self):
        """Test listing instance UUIDs."""
        driver = _create_driver()
        result = driver.list_instance_uuids()
        self.assertListEqual(result, ['uuid1', 'uuid2'])

    def test_destroy_instance(self):
        """Test destroying an instance deletes CRD."""
        driver = _create_driver()
        test_instance = _create_test_instance()
        driver.destroy(None, test_instance, None)
        self.mock_custom_obj_api.return_value.delete_namespaced_custom_object.assert_called()

    def test_reboot_soft(self):
        """Test soft reboot patches rebootType."""
        driver = _create_driver()
        test_instance = _create_test_instance()
        driver.reboot(None, test_instance, None, 'SOFT')
        self.mock_custom_obj_api.return_value.patch_namespaced_custom_object.assert_called()

        call_kwargs = self.mock_custom_obj_api.return_value.patch_namespaced_custom_object.call_args.kwargs
        self.assertEqual(call_kwargs['body']['spec']['rebootType'], 'soft')

    def test_reboot_hard(self):
        """Test hard reboot patches rebootType."""
        driver = _create_driver()
        test_instance = _create_test_instance()
        driver.reboot(None, test_instance, None, 'HARD')

        call_kwargs = self.mock_custom_obj_api.return_value.patch_namespaced_custom_object.call_args.kwargs
        self.assertEqual(call_kwargs['body']['spec']['rebootType'], 'hard')

    def test_pause(self):
        """Test pausing sets powerState to PAUSED."""
        driver = _create_driver()
        test_instance = _create_test_instance()
        driver.pause(test_instance)

        call_kwargs = self.mock_custom_obj_api.return_value.patch_namespaced_custom_object.call_args.kwargs
        self.assertEqual(call_kwargs['body']['spec']['powerState'], 'PAUSED')

    def test_unpause(self):
        """Test unpausing sets powerState to RUNNING."""
        driver = _create_driver()
        test_instance = _create_test_instance()
        driver.unpause(test_instance)

        call_kwargs = self.mock_custom_obj_api.return_value.patch_namespaced_custom_object.call_args.kwargs
        self.assertEqual(call_kwargs['body']['spec']['powerState'], 'RUNNING')

    def test_power_off(self):
        """Test power off sets powerState to STOPPED."""
        driver = _create_driver()
        test_instance = _create_test_instance()
        driver.power_off(test_instance)

        call_kwargs = self.mock_custom_obj_api.return_value.patch_namespaced_custom_object.call_args.kwargs
        self.assertEqual(call_kwargs['body']['spec']['powerState'], 'STOPPED')

    def test_power_on(self):
        """Test power on sets powerState to RUNNING."""
        driver = _create_driver()
        test_instance = _create_test_instance()
        driver.power_on(None, test_instance, None)

        call_kwargs = self.mock_custom_obj_api.return_value.patch_namespaced_custom_object.call_args.kwargs
        self.assertEqual(call_kwargs['body']['spec']['powerState'], 'RUNNING')

    def test_suspend(self):
        """Test suspend sets powerState to STOPPED."""
        driver = _create_driver()
        test_instance = _create_test_instance()
        driver.suspend(None, test_instance)

        call_kwargs = self.mock_custom_obj_api.return_value.patch_namespaced_custom_object.call_args.kwargs
        self.assertEqual(call_kwargs['body']['spec']['powerState'], 'STOPPED')

    def test_resume(self):
        """Test resume sets powerState to RUNNING."""
        driver = _create_driver()
        test_instance = _create_test_instance()
        driver.resume(None, test_instance, None)

        call_kwargs = self.mock_custom_obj_api.return_value.patch_namespaced_custom_object.call_args.kwargs
        self.assertEqual(call_kwargs['body']['spec']['powerState'], 'RUNNING')

    def test_plug_vifs(self):
        """Test plugging VIFs creates/updates Port CRDs."""
        from kubernetes.client.rest import ApiException

        driver = _create_driver()
        test_instance = _create_test_instance()
        network_info = [_create_test_vif()]

        # Mock get to raise 404 (port doesn't exist)
        self.mock_custom_obj_api.return_value.get_namespaced_custom_object.side_effect = \
            ApiException(status=404)

        driver.plug_vifs(test_instance, network_info)
        # Should attempt to create Port CRD
        self.mock_custom_obj_api.return_value.create_namespaced_custom_object.assert_called()

    def test_attach_interface(self):
        """Test attaching interface creates Port CRD."""
        driver = _create_driver()
        test_instance = _create_test_instance()
        vif = _create_test_vif()

        driver.attach_interface(None, test_instance, None, vif)
        self.mock_custom_obj_api.return_value.create_namespaced_custom_object.assert_called()

    def test_detach_interface(self):
        """Test detaching interface deletes Port CRD."""
        driver = _create_driver()
        test_instance = _create_test_instance()
        vif = _create_test_vif()

        driver.detach_interface(None, test_instance, vif)
        self.mock_custom_obj_api.return_value.delete_namespaced_custom_object.assert_called()

    def test_attach_volume(self):
        """Test attaching volume updates instance status."""
        driver = _create_driver()
        test_instance = _create_test_instance()

        # Mock existing instance with no volumes
        self.mock_custom_obj_api.return_value.get_namespaced_custom_object.return_value = {
            "spec": {"name": "test"},
            "status": {"volumeAttachments": []},
            "metadata": {"name": "test-instance"}
        }

        connection_info = {
            'data': {'volume_id': 'vol-123', 'attachment_id': 'attach-456'},
            'serial': 'vol-123'
        }

        driver.attach_volume(None, connection_info, test_instance, '/dev/vdb')
        self.mock_custom_obj_api.return_value.patch_namespaced_custom_object_status.assert_called()

        call_kwargs = self.mock_custom_obj_api.return_value.patch_namespaced_custom_object_status.call_args.kwargs
        attachments = call_kwargs['body']['status']['volumeAttachments']
        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0]['volumeId'], 'vol-123')
        self.assertEqual(attachments[0]['device'], '/dev/vdb')

    def test_detach_volume(self):
        """Test detaching volume updates instance status."""
        driver = _create_driver()
        test_instance = _create_test_instance()

        # Mock existing instance with one volume
        self.mock_custom_obj_api.return_value.get_namespaced_custom_object.return_value = {
            "spec": {"name": "test"},
            "status": {"volumeAttachments": [
                {'id': 'attach-456', 'volumeId': 'vol-123', 'device': '/dev/vdb'}
            ]},
            "metadata": {"name": "test-instance"}
        }

        connection_info = {
            'data': {'volume_id': 'vol-123'},
            'serial': 'vol-123'
        }

        driver.detach_volume(None, connection_info, test_instance, '/dev/vdb')
        self.mock_custom_obj_api.return_value.patch_namespaced_custom_object_status.assert_called()

        call_kwargs = self.mock_custom_obj_api.return_value.patch_namespaced_custom_object_status.call_args.kwargs
        attachments = call_kwargs['body']['status']['volumeAttachments']
        self.assertEqual(len(attachments), 0)

    def test_get_nodenames_by_uuid(self):
        """Test getting node names by UUID."""
        driver = _create_driver()
        driver._get_node_from_k8s()
        result = driver.get_nodenames_by_uuid()
        self.assertEqual(
            result, {driver._k8s_node.metadata.uid: driver._hostname})

    def test_get_available_nodes(self):
        """Test getting available nodes."""
        driver = _create_driver()
        driver._hostname = 'test-node'
        result = driver.get_available_nodes()
        self.assertEqual(result, ['test-node'])

    def test_get_available_resources(self):
        """Test getting available resources."""
        driver = _create_driver()
        driver._get_node_from_k8s()
        driver._hostname = 'test-node'
        result = driver.get_available_resource("test-node")

        self.assertEqual(result['hypervisor_type'], 'CHV')
        self.assertEqual(result['hypervisor_hostname'], 'test-node')
        self.assertEqual(result['local_gb'], 100.0)
        self.assertEqual(result['local_gb_used'], 50.0)
        self.assertEqual(result['memory_mb'], 8192)
        self.assertEqual(result['vcpus'], 4)

    def test_update_provider_tree(self):
        """Test updating provider tree."""
        provider_tree_mock = mock.MagicMock()
        provider_tree_mock.exists.return_value = False

        driver = _create_driver()
        driver._hostname = 'test-host'
        driver._get_node_from_k8s()
        driver.update_provider_tree(provider_tree_mock, "test-host")

        new_root_args = provider_tree_mock.new_root.call_args.args
        self.assertEqual(new_root_args, (
            'test-host',
            'ff0183d3-fb29-485c-ac6c-2616c2ccb258'
        ))

        provider_tree_mock.update_inventory.assert_called_once()
