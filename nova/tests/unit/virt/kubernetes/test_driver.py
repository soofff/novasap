from nova import test
from unittest import mock
from kubernetes import client
from nova.tests.unit.objects import test_diagnostics
from nova.virt.hardware import InstanceInfo
from nova.virt.kubernetes import driver as kubernetes_driver
from nova import objects


def _create_test_instance():
    flavor = objects.Flavor(memory_mb=2048,
                            swap=0,
                            vcpu_weight=None,
                            root_gb=10,
                            id=2,
                            name=u'm1.small',
                            ephemeral_gb=20,
                            rxtx_factor=1.0,
                            flavorid=u'1',
                            vcpus=2,
                            extra_specs={})
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
        'vm_state': None,
        'kernel_id': None,
        'ramdisk_id': None,
        'os_type': 'linux',
        'user_id': '838a72b0-0d54-4827-8fd6-fb1227633ceb',
        'ephemeral_key_uuid': None,
        'vcpu_model': None,
        'host': 'fake-host',
        'node': 'fake-node',
        'task_state': None,
        'vm_state': None,
        'trusted_certs': None,
        'resources': None,
        'migration_context': None,
        'info_cache': None,
        'vm_state': 'active',
        'power_state': 1,
    }


def _create_driver():
    driver = kubernetes_driver.KubernetesDriver(None)
    driver._hostname = 'test-host'
    return driver


class KubernetesTestCase(test.NoDBTestCase, test_diagnostics.DiagnosticsComparisonMixin):
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
            "spec": {"uuid": "123", "display_name": "test"},
            "status": {"vm_state": "active", "power_state": 1},
            "action": None,
            "metadata": {"name": "test-instance"}
        }
        self.addCleanup(self.kube_custom_obj_api_patcher.stop)

        self.mock_custom_obj_api.return_value.list_namespaced_custom_object.return_value = {
            "items": [{
            "spec": {"uuid": "1", "display_name": "test1"},
            "status": {"vm_state": "active"},
            "action": None,
            "metadata": {"name": "1"}
        }, {
            "spec": {"uuid": "2", "display_name": "test2"},
            "status": {"vm_state": "paused"},
            "action": None,
            "metadata": {"name": "2"}
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
        driver = kubernetes_driver.KubernetesDriver(None)
        driver.init_host("test-host")
        self.assertEqual("test-host", driver._hostname)
        self.assertEqual("ff0183d3-fb29-485c-ac6c-2616c2ccb258",
                         driver._k8s_node.metadata.uid)

    def test_get_host_uptime(self):
        driver = kubernetes_driver.KubernetesDriver(None)
        result = driver.get_host_uptime()
        self.assertIn("up", result)
        self.assertIn("load average", result)

    def test_get_info(self):
        test_instance = _create_test_instance()
        driver = kubernetes_driver.KubernetesDriver(None)
        result = driver.get_info(test_instance)
        self.assertEqual(vars(result), vars(InstanceInfo(
            state=1, internal_id='123')))

    def test_spawn(self):
        driver = _create_driver()
        test_instance = _create_test_instance()
        driver.spawn(None, test_instance, None, None, None, None)
        self.mock_custom_obj_api.return_value.create_namespaced_custom_object.assert_called()

    def test_instance_exist(self):
        driver = _create_driver()
        test_instance = _create_test_instance()
        result = driver.instance_exists(test_instance)
        self.assertTrue(result)

    def test_list_instances(self):
        driver = _create_driver()
        result = driver.list_instances()
        self.assertListEqual(result, ['test1', 'test2'])

    def test_list_instance_uuids(self):
        driver = _create_driver()
        result = driver.list_instance_uuids()
        self.assertListEqual(result, ['1', '2'])

    def test_destroy_instance(self):
        driver = _create_driver()
        test_instance = _create_test_instance()
        driver.destroy(None, test_instance, None)
        self.mock_custom_obj_api.return_value.patch_namespaced_custom_object.assert_called()

    def test_reboot(self):
        driver = _create_driver()
        test_instance = _create_test_instance()
        driver.reboot(None, test_instance, None, None)
        self.mock_custom_obj_api.return_value.patch_namespaced_custom_object.assert_called()

    def test_pause(self):
        driver = _create_driver()
        test_instance = _create_test_instance()
        driver.pause(test_instance)
        self.mock_custom_obj_api.return_value.patch_namespaced_custom_object.assert_called()

    def test_unpause(self):
        driver = _create_driver()
        test_instance = _create_test_instance()
        driver.unpause(test_instance)
        self.mock_custom_obj_api.return_value.patch_namespaced_custom_object.assert_called()

    def test_power_off(self):
        driver = _create_driver()
        test_instance = _create_test_instance()
        driver.power_off(test_instance)
        self.mock_custom_obj_api.return_value.patch_namespaced_custom_object.assert_called()

    def test_power_on(self):
        driver = _create_driver()
        test_instance = _create_test_instance()
        driver.power_on(None, test_instance, None)
        self.mock_custom_obj_api.return_value.patch_namespaced_custom_object.assert_called()

    def test_suspend(self):
        driver = _create_driver()
        test_instance = _create_test_instance()
        driver.suspend(None, test_instance)
        self.mock_custom_obj_api.return_value.patch_namespaced_custom_object.assert_called()

    def test_resume(self):
        driver = _create_driver()
        test_instance = _create_test_instance()
        driver.resume(None, test_instance, None)
        self.mock_custom_obj_api.return_value.patch_namespaced_custom_object.assert_called()

    def test_get_nodenames_by_uuid(self):
        driver = _create_driver()
        driver._get_node_from_k8s()
        result = driver.get_nodenames_by_uuid()
        self.assertEqual(
            result, {driver._k8s_node.metadata.uid: driver._hostname})

    def test_get_available_nodes(self):
        driver = _create_driver()
        driver._hostname = 'test-node'
        result = driver.get_available_nodes()
        self.assertEqual(result, ['test-node'])

    def test_get_available_resources(self):
        driver = _create_driver()
        driver._get_node_from_k8s()
        driver._hostname = 'test-node'
        result = driver.get_available_resource("test-node")
        self.assertEqual(result, {
            'host_hostname': 'test-node',
            'host_name_label': 'test-node',
            'hypervisor_hostname': 'test-node',
            'hypervisor_type': 'CHV',
            'local_gb': 100.0,
            'local_gb_used': 50.0,
            'memory_mb': 8192,
            'memory_mb_used': 4096,
            'supported_instances': [('x86_64', 'kvm', 'hvm')],
            'vcpus': 4,
            'vcpus_used': 0,
            'numa_topology': None
            }
        )

    def test_update_provider_tree(self):
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

        update_inventory_args = provider_tree_mock.update_inventory.call_args.args
        self.assertEqual(update_inventory_args, (
            'test-host',
            {
                'DISK_GB': {
                'allocation_ratio': 1,
                    'max_unit': 100,
                    'min_unit': 1,
                    'reserved': 0,
                    'step_size': 1,
                    'total': 100 
                }, 'MEMORY_MB': {
                    'allocation_ratio': 1,
                    'max_unit': 0,
                    'min_unit': 1,
                    'reserved': 512,
                    'step_size': 1,
                    'total': 0
                }, 'VCPU': {
                    'allocation_ratio': 1,
                    'max_unit': 4,
                    'min_unit': 1,
                    'reserved': 0,
                    'step_size': 1,
                    'total': 4
                }
            }
        ))
