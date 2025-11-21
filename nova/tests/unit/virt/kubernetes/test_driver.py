from nova import test
from unittest import mock
from kubernetes import client
from nova.tests.unit.objects import test_diagnostics
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
        'vm_state': 'active'
    }


def _create_driver():
    driver = kubernetes_driver.KubernetesDriver(None)
    driver._hostname = 'test-host'
    return driver


class KubernetesTestCase(test.NoDBTestCase, test_diagnostics.DiagnosticsComparisonMixin):
    def setUp(self):
        super().setUp()
        self.kube_config_patcher = mock.patch(
            'kubernetes.config.load_kube_config', autospec=True)
        self.mock_load_kube_config = self.kube_config_patcher.start()
        self.mock_load_kube_config.return_value = None
        self.addCleanup(self.kube_config_patcher.stop)

        self.kube_custom_obj_api_patcher = mock.patch(
            'kubernetes.client.CustomObjectsApi', autospec=True)
        self.mock_custom_obj_api = self.kube_custom_obj_api_patcher.start()
        self.mock_custom_obj_api.return_value.get_namespaced_custom_object.return_value = {
            "spec": {"uuid": "123", "display_name": "test"},
            "status": {"vm_state": "active"},
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

    def test_init_host(self):
        driver = kubernetes_driver.KubernetesDriver(None)
        driver.init_host("test-host")
        self.assertEqual("test-host", driver._hostname)
        self.assertIsNotNone(driver._local_node_uuid)

    def test_get_host_uptime(self):
        driver = kubernetes_driver.KubernetesDriver(None)
        result = driver.get_host_uptime()
        self.assertIn("up", result)
        self.assertIn("load average", result)

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
        result = driver.get_nodenames_by_uuid()
        self.assertEqual(result, {driver._local_node_uuid: driver._hostname})

    def test_get_available_nodes(self):
        driver = _create_driver()
        driver._hostname = 'test-node'
        result = driver.get_available_nodes()
        self.assertEqual(result, ['test-node'])
