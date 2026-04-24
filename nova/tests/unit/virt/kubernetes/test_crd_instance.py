"""Tests for the Instance CRD module."""

from unittest import mock

from nova import test
from nova.tests.unit.objects import test_diagnostics
from nova.tests.unit.virt.kubernetes.test_driver import _create_test_instance
from nova.virt.kubernetes.crd_instance import (
    InstanceCrd, InstanceObject, InstanceSpec, InstanceStatus,
    PowerState, RebootType, VmState, ObservedPowerState
)


class InstanceCrdTestCase(test.NoDBTestCase, test_diagnostics.DiagnosticsComparisonMixin):
    """Test cases for Instance CRD operations."""

    def setUp(self):
        super().setUp()
        self.kube_config_patcher = mock.patch(
            'kubernetes.config.load_kube_config', autospec=True)
        self.mock_load_kube_config = self.kube_config_patcher.start()
        self.mock_load_kube_config.return_value = None
        self.addCleanup(self.kube_config_patcher.stop)

    @mock.patch('kubernetes.client.ApiextensionsV1Api')
    def test_instance_crd_manifest(self, mock_apiext_api):
        """Test that the Instance CRD manifest has correct structure."""
        mock_api_instance = mock.MagicMock()
        mock_apiext_api.return_value = mock_api_instance

        crd = InstanceCrd(None, "default")
        crd.create_manifest()
        mock_api_instance.create_custom_resource_definition.assert_called_once()

        manifest = mock_api_instance.create_custom_resource_definition.call_args.args[0]

        # Check basic CRD structure
        self.assertEqual(manifest['apiVersion'], 'apiextensions.k8s.io/v1')
        self.assertEqual(manifest['kind'], 'CustomResourceDefinition')
        self.assertEqual(manifest['metadata']['name'], 'instances.nova.openstack.org')

        # Check spec
        spec = manifest['spec']
        self.assertEqual(spec['group'], 'nova.openstack.org')
        self.assertEqual(spec['scope'], 'Namespaced')
        self.assertEqual(spec['names']['kind'], 'Instance')
        self.assertEqual(spec['names']['plural'], 'instances')
        self.assertEqual(spec['names']['singular'], 'instance')

        # Check version has status subresource
        version = spec['versions'][0]
        self.assertEqual(version['name'], 'v1')
        self.assertTrue(version['served'])
        self.assertTrue(version['storage'])
        self.assertIn('subresources', version)
        self.assertIn('status', version['subresources'])

        # Check schema has spec and status
        schema = version['schema']['openAPIV3Schema']
        self.assertIn('spec', schema['properties'])
        self.assertIn('status', schema['properties'])

        # Check spec properties include key fields
        spec_props = schema['properties']['spec']['properties']
        self.assertIn('name', spec_props)
        self.assertIn('flavorRef', spec_props)
        self.assertIn('powerState', spec_props)
        self.assertIn('rebootType', spec_props)
        self.assertIn('networks', spec_props)
        self.assertIn('blockDeviceMappingV2', spec_props)

        # Check status properties
        status_props = schema['properties']['status']['properties']
        self.assertIn('vmState', status_props)
        self.assertIn('powerState', status_props)
        self.assertIn('taskState', status_props)
        self.assertIn('hypervisor', status_props)
        self.assertIn('interfaces', status_props)
        self.assertIn('volumeAttachments', status_props)
        self.assertIn('conditions', status_props)

    @mock.patch('kubernetes.client.CustomObjectsApi')
    def test_instance_create(self, mock_custom_api):
        """Test creating an Instance CRD."""
        mock_api_instance = mock.MagicMock()
        mock_custom_api.return_value = mock_api_instance

        instance = _create_test_instance()
        crd = InstanceCrd(None, "default")
        crd.create(instance, "test-host")

        mock_api_instance.create_namespaced_custom_object.assert_called_once()

        call_kwargs = mock_api_instance.create_namespaced_custom_object.call_args.kwargs
        self.assertEqual(call_kwargs['group'], 'nova.openstack.org')
        self.assertEqual(call_kwargs['version'], 'v1')
        self.assertEqual(call_kwargs['namespace'], 'default')
        self.assertEqual(call_kwargs['plural'], 'instances')

        body = call_kwargs['body']
        self.assertEqual(body['kind'], 'Instance')
        self.assertEqual(body['apiVersion'], 'nova.openstack.org/v1')
        self.assertEqual(body['metadata']['name'], '860f5462-f16e-4836-a6aa-2935fc7fccc0')
        self.assertEqual(body['metadata']['labels']['host'], 'test-host')
        self.assertEqual(body['spec']['name'], 'test_instance')
        self.assertEqual(body['spec']['powerState'], 'RUNNING')
        self.assertEqual(body['spec']['rebootType'], 'none')

    @mock.patch('kubernetes.client.CustomObjectsApi')
    def test_instance_get(self, mock_custom_api):
        """Test getting an Instance CRD."""
        mock_api_instance = mock.MagicMock()
        mock_custom_api.return_value = mock_api_instance
        mock_api_instance.get_namespaced_custom_object.return_value = {
            'metadata': {'name': 'test-uuid'},
            'spec': {'name': 'test', 'powerState': 'RUNNING'},
            'status': {'vmState': 'ACTIVE'}
        }

        crd = InstanceCrd(None, "default")
        result = crd.get('test-uuid')

        mock_api_instance.get_namespaced_custom_object.assert_called_once_with(
            group='nova.openstack.org',
            version='v1',
            namespace='default',
            plural='instances',
            name='test-uuid'
        )
        self.assertIsNotNone(result)
        self.assertEqual(result['spec']['powerState'], 'RUNNING')

    @mock.patch('kubernetes.client.CustomObjectsApi')
    def test_instance_list(self, mock_custom_api):
        """Test listing Instance CRDs."""
        mock_api_instance = mock.MagicMock()
        mock_custom_api.return_value = mock_api_instance
        mock_api_instance.list_namespaced_custom_object.return_value = {
            'items': [
                {'metadata': {'name': 'uuid1'}, 'spec': {'name': 'instance1'}},
                {'metadata': {'name': 'uuid2'}, 'spec': {'name': 'instance2'}},
            ]
        }

        crd = InstanceCrd(None, "default")
        results = crd.list_instances("test-host")

        mock_api_instance.list_namespaced_custom_object.assert_called_once()
        call_kwargs = mock_api_instance.list_namespaced_custom_object.call_args.kwargs
        self.assertEqual(call_kwargs['label_selector'], 'host=test-host')
        self.assertEqual(len(results), 2)

    @mock.patch('kubernetes.client.CustomObjectsApi')
    def test_update_power_state(self, mock_custom_api):
        """Test updating power state via spec patch."""
        mock_api_instance = mock.MagicMock()
        mock_custom_api.return_value = mock_api_instance

        crd = InstanceCrd(None, "default")
        crd.update_power_state('test-uuid', PowerState.STOPPED)

        mock_api_instance.patch_namespaced_custom_object.assert_called_once()
        call_kwargs = mock_api_instance.patch_namespaced_custom_object.call_args.kwargs
        self.assertEqual(call_kwargs['name'], 'test-uuid')
        self.assertEqual(call_kwargs['body']['spec']['powerState'], 'STOPPED')

    @mock.patch('kubernetes.client.CustomObjectsApi')
    def test_request_reboot(self, mock_custom_api):
        """Test requesting a reboot via spec patch."""
        mock_api_instance = mock.MagicMock()
        mock_custom_api.return_value = mock_api_instance

        crd = InstanceCrd(None, "default")
        crd.request_reboot('test-uuid', RebootType.SOFT)

        mock_api_instance.patch_namespaced_custom_object.assert_called_once()
        call_kwargs = mock_api_instance.patch_namespaced_custom_object.call_args.kwargs
        self.assertEqual(call_kwargs['body']['spec']['rebootType'], 'soft')

    @mock.patch('kubernetes.client.CustomObjectsApi')
    def test_update_status(self, mock_custom_api):
        """Test updating instance status."""
        mock_api_instance = mock.MagicMock()
        mock_custom_api.return_value = mock_api_instance

        crd = InstanceCrd(None, "default")
        crd.update_status('test-uuid', vmState=VmState.ACTIVE, taskState='running')

        mock_api_instance.patch_namespaced_custom_object_status.assert_called_once()
        call_kwargs = mock_api_instance.patch_namespaced_custom_object_status.call_args.kwargs
        self.assertEqual(call_kwargs['body']['status']['vmState'], 'ACTIVE')
        self.assertEqual(call_kwargs['body']['status']['taskState'], 'running')

    @mock.patch('kubernetes.client.CustomObjectsApi')
    def test_instance_delete(self, mock_custom_api):
        """Test deleting an Instance CRD."""
        mock_api_instance = mock.MagicMock()
        mock_custom_api.return_value = mock_api_instance

        crd = InstanceCrd(None, "default")
        result = crd.delete('test-uuid')

        mock_api_instance.delete_namespaced_custom_object.assert_called_once_with(
            group='nova.openstack.org',
            version='v1',
            namespace='default',
            plural='instances',
            name='test-uuid'
        )
        self.assertTrue(result)


class InstanceObjectTestCase(test.NoDBTestCase):
    """Test cases for InstanceObject conversion."""

    def test_from_nova_instance(self):
        """Test converting a Nova instance to InstanceObject."""
        instance = _create_test_instance()
        obj = InstanceObject.from_nova_instance(instance, 'test-host')

        self.assertEqual(obj.metadata.name, '860f5462-f16e-4836-a6aa-2935fc7fccc0')
        self.assertEqual(obj.metadata.labels.host, 'test-host')
        self.assertEqual(obj.spec.name, 'test_instance')
        self.assertEqual(obj.spec.powerState, PowerState.RUNNING)
        self.assertEqual(obj.spec.rebootType, RebootType.NONE)
        self.assertEqual(obj.status.vmState, VmState.ACTIVE)
        self.assertEqual(obj.status.hypervisor, 'test-host')

    def test_power_state_mapping(self):
        """Test Nova power state to CRD power state mapping."""
        instance = _create_test_instance()

        # Test RUNNING (power_state=1)
        instance['power_state'] = 1
        obj = InstanceObject.from_nova_instance(instance, 'host')
        self.assertEqual(obj.status.powerState, ObservedPowerState.RUNNING)

        # Test PAUSED (power_state=3)
        instance['power_state'] = 3
        obj = InstanceObject.from_nova_instance(instance, 'host')
        self.assertEqual(obj.status.powerState, ObservedPowerState.PAUSED)

        # Test SHUTDOWN (power_state=4)
        instance['power_state'] = 4
        obj = InstanceObject.from_nova_instance(instance, 'host')
        self.assertEqual(obj.status.powerState, ObservedPowerState.SHUTDOWN)

    def test_vm_state_mapping(self):
        """Test Nova VM state to CRD VM state mapping."""
        instance = _create_test_instance()

        for nova_state, expected in [
            ('active', VmState.ACTIVE),
            ('building', VmState.BUILDING),
            ('paused', VmState.PAUSED),
            ('stopped', VmState.STOPPED),
            ('error', VmState.ERROR),
        ]:
            instance['vm_state'] = nova_state
            obj = InstanceObject.from_nova_instance(instance, 'host')
            self.assertEqual(obj.status.vmState, expected)
