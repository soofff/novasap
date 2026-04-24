"""Tests for the Port CRD module."""

from unittest import mock

from nova import test
from nova.tests.unit.objects import test_diagnostics
from nova.virt.kubernetes.crd_port import (
    PortCrd, PortObject, PortSpec, PortStatus, PortPhase
)


def _create_test_vif():
    """Create a test VIF dictionary."""
    return {
        'id': 'port-uuid-123',
        'address': 'fa:16:3e:aa:bb:cc',
        'type': 'bridge',
        'network': {
            'id': 'network-uuid-456',
            'label': 'private-net',
        },
        'details': {
            'port_filter': True,
            'ovs_hybrid_plug': False,
        },
        'tag': 'nic0',
    }


class PortCrdTestCase(test.NoDBTestCase, test_diagnostics.DiagnosticsComparisonMixin):
    """Test cases for Port CRD operations."""

    def setUp(self):
        super().setUp()
        self.kube_config_patcher = mock.patch(
            'kubernetes.config.load_kube_config', autospec=True)
        self.mock_load_kube_config = self.kube_config_patcher.start()
        self.mock_load_kube_config.return_value = None
        self.addCleanup(self.kube_config_patcher.stop)

    @mock.patch('kubernetes.client.ApiextensionsV1Api')
    def test_port_crd_manifest(self, mock_apiext_api):
        """Test that the Port CRD manifest has correct structure."""
        mock_api_instance = mock.MagicMock()
        mock_apiext_api.return_value = mock_api_instance

        crd = PortCrd(None, "default")
        crd.create_manifest()
        mock_api_instance.create_custom_resource_definition.assert_called_once()

        manifest = mock_api_instance.create_custom_resource_definition.call_args.args[0]

        # Check basic CRD structure
        self.assertEqual(manifest['apiVersion'], 'apiextensions.k8s.io/v1')
        self.assertEqual(manifest['kind'], 'CustomResourceDefinition')
        self.assertEqual(manifest['metadata']['name'], 'ports.nova.openstack.org')

        # Check spec
        spec = manifest['spec']
        self.assertEqual(spec['group'], 'nova.openstack.org')
        self.assertEqual(spec['scope'], 'Namespaced')
        self.assertEqual(spec['names']['kind'], 'Port')
        self.assertEqual(spec['names']['plural'], 'ports')
        self.assertEqual(spec['names']['singular'], 'port')

        # Check version has status subresource
        version = spec['versions'][0]
        self.assertIn('subresources', version)
        self.assertIn('status', version['subresources'])

        # Check schema has spec and status
        schema = version['schema']['openAPIV3Schema']
        self.assertIn('spec', schema['properties'])
        self.assertIn('status', schema['properties'])

        # Check spec properties
        spec_props = schema['properties']['spec']['properties']
        self.assertIn('instanceRef', spec_props)
        self.assertIn('networkId', spec_props)
        self.assertIn('portId', spec_props)
        self.assertIn('bindingHostId', spec_props)
        self.assertIn('macAddress', spec_props)

        # Check status properties
        status_props = schema['properties']['status']['properties']
        self.assertIn('phase', status_props)
        self.assertIn('vifType', status_props)
        self.assertIn('vifDetails', status_props)
        self.assertIn('conditions', status_props)

    @mock.patch('kubernetes.client.CustomObjectsApi')
    def test_port_create_from_vif(self, mock_custom_api):
        """Test creating a Port CRD from a VIF."""
        mock_api_instance = mock.MagicMock()
        mock_custom_api.return_value = mock_api_instance

        vif = _create_test_vif()
        crd = PortCrd(None, "default")
        crd.create_from_vif(vif, 'instance-uuid-789', 'test-host')

        mock_api_instance.create_namespaced_custom_object.assert_called_once()

        call_kwargs = mock_api_instance.create_namespaced_custom_object.call_args.kwargs
        self.assertEqual(call_kwargs['group'], 'nova.openstack.org')
        self.assertEqual(call_kwargs['version'], 'v1')
        self.assertEqual(call_kwargs['namespace'], 'default')
        self.assertEqual(call_kwargs['plural'], 'ports')

        body = call_kwargs['body']
        self.assertEqual(body['kind'], 'Port')
        self.assertEqual(body['apiVersion'], 'nova.openstack.org/v1')
        self.assertEqual(body['metadata']['name'], 'port-uuid-123')
        self.assertEqual(body['metadata']['labels']['host'], 'test-host')
        self.assertEqual(body['spec']['instanceRef'], 'instance-uuid-789')
        self.assertEqual(body['spec']['networkId'], 'network-uuid-456')
        self.assertEqual(body['spec']['portId'], 'port-uuid-123')
        self.assertEqual(body['spec']['bindingHostId'], 'test-host')
        self.assertEqual(body['spec']['macAddress'], 'fa:16:3e:aa:bb:cc')
        self.assertEqual(body['spec']['tag'], 'nic0')

    @mock.patch('kubernetes.client.CustomObjectsApi')
    def test_port_get(self, mock_custom_api):
        """Test getting a Port CRD."""
        mock_api_instance = mock.MagicMock()
        mock_custom_api.return_value = mock_api_instance
        mock_api_instance.get_namespaced_custom_object.return_value = {
            'metadata': {'name': 'port-123'},
            'spec': {'instanceRef': 'instance-456', 'networkId': 'net-789'},
            'status': {'phase': 'Bound'}
        }

        crd = PortCrd(None, "default")
        result = crd.get_port('port-123')

        mock_api_instance.get_namespaced_custom_object.assert_called_once_with(
            group='nova.openstack.org',
            version='v1',
            namespace='default',
            plural='ports',
            name='port-123'
        )
        self.assertIsNotNone(result)
        self.assertEqual(result['status']['phase'], 'Bound')

    @mock.patch('kubernetes.client.CustomObjectsApi')
    def test_port_list(self, mock_custom_api):
        """Test listing Port CRDs."""
        mock_api_instance = mock.MagicMock()
        mock_custom_api.return_value = mock_api_instance
        mock_api_instance.list_namespaced_custom_object.return_value = {
            'items': [
                {'metadata': {'name': 'port1'}, 'spec': {'instanceRef': 'inst1'}},
                {'metadata': {'name': 'port2'}, 'spec': {'instanceRef': 'inst1'}},
                {'metadata': {'name': 'port3'}, 'spec': {'instanceRef': 'inst2'}},
            ]
        }

        crd = PortCrd(None, "default")

        # List all ports for host
        results = crd.list_ports(host='test-host')
        self.assertEqual(len(results), 3)

        # List ports filtered by instance
        results = crd.list_ports(instance_uuid='inst1')
        self.assertEqual(len(results), 2)

    @mock.patch('kubernetes.client.CustomObjectsApi')
    def test_update_binding(self, mock_custom_api):
        """Test updating port binding host."""
        mock_api_instance = mock.MagicMock()
        mock_custom_api.return_value = mock_api_instance

        crd = PortCrd(None, "default")
        crd.update_binding('port-123', 'new-host')

        mock_api_instance.patch_namespaced_custom_object.assert_called_once()
        call_kwargs = mock_api_instance.patch_namespaced_custom_object.call_args.kwargs
        self.assertEqual(call_kwargs['name'], 'port-123')
        self.assertEqual(call_kwargs['body']['spec']['bindingHostId'], 'new-host')

    @mock.patch('kubernetes.client.CustomObjectsApi')
    def test_update_phase(self, mock_custom_api):
        """Test updating port phase."""
        mock_api_instance = mock.MagicMock()
        mock_custom_api.return_value = mock_api_instance

        crd = PortCrd(None, "default")
        crd.update_phase('port-123', PortPhase.BINDING)

        mock_api_instance.patch_namespaced_custom_object_status.assert_called_once()
        call_kwargs = mock_api_instance.patch_namespaced_custom_object_status.call_args.kwargs
        self.assertEqual(call_kwargs['body']['status']['phase'], 'Binding')

    @mock.patch('kubernetes.client.CustomObjectsApi')
    def test_mark_bound(self, mock_custom_api):
        """Test marking port as bound with details."""
        mock_api_instance = mock.MagicMock()
        mock_custom_api.return_value = mock_api_instance

        crd = PortCrd(None, "default")
        crd.mark_bound('port-123', vif_type='ovs', vif_details={'port_filter': True})

        mock_api_instance.patch_namespaced_custom_object_status.assert_called_once()
        call_kwargs = mock_api_instance.patch_namespaced_custom_object_status.call_args.kwargs
        status = call_kwargs['body']['status']
        self.assertEqual(status['phase'], 'Bound')
        self.assertEqual(status['vifType'], 'ovs')
        self.assertEqual(status['vifDetails'], {'port_filter': True})
        self.assertIn('boundAt', status)

    @mock.patch('kubernetes.client.CustomObjectsApi')
    def test_mark_failed(self, mock_custom_api):
        """Test marking port as failed."""
        mock_api_instance = mock.MagicMock()
        mock_custom_api.return_value = mock_api_instance

        crd = PortCrd(None, "default")
        crd.mark_failed('port-123', reason='Network not found')

        mock_api_instance.patch_namespaced_custom_object_status.assert_called_once()
        call_kwargs = mock_api_instance.patch_namespaced_custom_object_status.call_args.kwargs
        status = call_kwargs['body']['status']
        self.assertEqual(status['phase'], 'Failed')
        self.assertEqual(len(status['conditions']), 1)
        self.assertEqual(status['conditions'][0]['type'], 'Ready')
        self.assertEqual(status['conditions'][0]['status'], 'False')
        self.assertEqual(status['conditions'][0]['message'], 'Network not found')

    @mock.patch('kubernetes.client.CustomObjectsApi')
    def test_port_delete(self, mock_custom_api):
        """Test deleting a Port CRD."""
        mock_api_instance = mock.MagicMock()
        mock_custom_api.return_value = mock_api_instance

        crd = PortCrd(None, "default")
        result = crd.delete('port-123')

        mock_api_instance.delete_namespaced_custom_object.assert_called_once_with(
            group='nova.openstack.org',
            version='v1',
            namespace='default',
            plural='ports',
            name='port-123'
        )
        self.assertTrue(result)


class PortObjectTestCase(test.NoDBTestCase):
    """Test cases for PortObject conversion."""

    def test_from_vif(self):
        """Test creating PortObject from VIF."""
        vif = _create_test_vif()
        obj = PortObject.from_vif(vif, 'instance-123', 'test-host')

        self.assertEqual(obj.metadata.name, 'port-uuid-123')
        self.assertEqual(obj.metadata.labels.host, 'test-host')
        self.assertEqual(obj.spec.instanceRef, 'instance-123')
        self.assertEqual(obj.spec.networkId, 'network-uuid-456')
        self.assertEqual(obj.spec.portId, 'port-uuid-123')
        self.assertEqual(obj.spec.bindingHostId, 'test-host')
        self.assertEqual(obj.spec.macAddress, 'fa:16:3e:aa:bb:cc')
        self.assertEqual(obj.spec.tag, 'nic0')
        self.assertEqual(obj.status.phase, PortPhase.PENDING)
        self.assertEqual(obj.status.vifType, 'bridge')
