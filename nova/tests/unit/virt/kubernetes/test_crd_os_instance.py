from nova import test
from unittest import mock
from kubernetes import client
from nova.tests.unit.objects import test_diagnostics
from nova.tests.unit.virt.kubernetes.test_driver import _create_test_instance
from nova.virt.kubernetes import driver as kubernetes_driver
from nova import objects
from nova.virt.kubernetes.os_crd_instance import OsCrdInstance, OsCrdObjBodyInstanceBody, OsCrdObjInstanceAction


class KubernetesCrdTestCase(test.NoDBTestCase, test_diagnostics.DiagnosticsComparisonMixin):
    def setUp(self):
        super().setUp()
        self.kube_config_patcher = mock.patch(
            'kubernetes.config.load_kube_config', autospec=True)
        self.mock_load_kube_config = self.kube_config_patcher.start()
        self.mock_load_kube_config.return_value = None
        self.addCleanup(self.kube_config_patcher.stop)

    @mock.patch('kubernetes.client.ApiextensionsV1Api')
    def test_crd_os_instance_manifest(self, mock_apiext_api):
        mock_api_instance = mock.MagicMock()
        mock_apiext_api.return_value = mock_api_instance

        i = OsCrdInstance(None, "default")
        i.create_manifest()
        mock_api_instance.create_custom_resource_definition.assert_called_once()

        arg = mock_api_instance.create_custom_resource_definition.call_args.args[0]
        self.assertEqual(
            arg,
            {
            'apiVersion': 'apiextensions.k8s.io/v1',
            'kind': 'CustomResourceDefinition',
            'metadata': {
                'name': 'osinstances.sap.com'
            },
            'spec': {
                'group': 'sap.com',
                'versions': [{
                    'name': 'v1',
                    'served': True,
                    'storage': True,
                    'schema': {
                    'openAPIV3Schema': {
                        'type': 'object',
                        'properties': {
                        'spec': {
                            'type': 'object',
                            'properties': {
                                'uuid': {'type': 'string'},
                                'display_name': {'type': 'string'}
                            }
                        },
                        'status': {
                            'type': 'object',
                            'properties': {
                                'vm_state': {'type': 'string'}
                            }
                        },
                        'action': {
                            'type': 'object',
                            'properties': {
                                'destroy': {'type': 'boolean'},
                                'state': {'type': 'string'}
                            }
                        }
                        }
                    }
                    },
                    'additionalPrinterColumns': [{
                        'name': 'Vm State',
                        'type': 'string',
                        'jsonPath': '.status.vm_state'
                    }]
                }],
                'scope': 'Namespaced',
                'names': {
                'plural': 'osinstances',
                'singular': 'osinstance',
                'kind': 'OsInstance',
                'shortNames': ['osinst']
                }
            }
            }
        )

    @mock.patch('kubernetes.client.CustomObjectsApi')
    def test_crd_instance_create(self, mock_custom_api):
        mock_api_instance = mock.MagicMock()
        mock_custom_api.return_value = mock_api_instance

        instance = _create_test_instance()
        i = OsCrdInstance(None, "default")
        i.create(instance)

        mock_api_instance.create_namespaced_custom_object.assert_called_once()

        arg = mock_api_instance.create_namespaced_custom_object.call_args.kwargs['body']

        self.assertEqual(
            arg, {
                'spec': {
                    'uuid': '860f5462-f16e-4836-a6aa-2935fc7fccc0',
                    'display_name': 'test_instance'
                           },
                  'status': {
                      'vm_state': 'active'
                      },
                  'action': {
                      'destroy': None,
                      'state': None
                      },
                  'metadata': {
                      'name': '860f5462-f16e-4836-a6aa-2935fc7fccc0',
                      'labels': {
                          'host': 'fake-host'
                          }
                      },
                  'apiVersion': 'sap.com/v1',
                  'kind': 'OsInstance'
                  }
            )

    @mock.patch('kubernetes.client.CustomObjectsApi')
    def test_crd_instance_get(self, mock_custom_api):
        mock_api_instance = mock.MagicMock()
        mock_custom_api.return_value = mock_api_instance

        instance = _create_test_instance()
        i = OsCrdInstance(None, "default")
        i.get(instance)

        mock_api_instance.get_namespaced_custom_object.assert_called_once()

        arg = mock_api_instance.get_namespaced_custom_object.call_args.kwargs

        self.assertEqual(arg, {
            'group': 'sap.com', 'version': 'v1',
            'namespace': 'default',
            'plural': 'osinstances',
            'name': '860f5462-f16e-4836-a6aa-2935fc7fccc0'
        })

    @mock.patch('kubernetes.client.CustomObjectsApi')
    def test_crd_instance_list(self, mock_custom_api):
        mock_api_instance = mock.MagicMock()
        mock_custom_api.return_value = mock_api_instance

        i = OsCrdInstance(None, "default")
        i.list("fake-host")

        mock_api_instance.list_namespaced_custom_object.assert_called_once()

        arg = mock_api_instance.list_namespaced_custom_object.call_args.kwargs

        self.assertEqual(arg, {
            'group': 'sap.com', 'version': 'v1',
            'namespace': 'default',
            'plural': 'osinstances',
            'label_selector': 'host=fake-host',
        })

    @mock.patch('kubernetes.client.CustomObjectsApi')
    def test_crd_instance_patch(self, mock_custom_api):
        mock_api_instance = mock.MagicMock()
        mock_custom_api.return_value = mock_api_instance

        instance = _create_test_instance()
        i = OsCrdInstance(None, "default")
        i.patch(instance, OsCrdObjBodyInstanceBody(
            action=OsCrdObjInstanceAction(
                destroy=True
            )
        ))
        mock_api_instance.patch_namespaced_custom_object.assert_called_once()

        arg = mock_api_instance.patch_namespaced_custom_object.call_args.kwargs

        self.assertEqual(arg, {
            'group': 'sap.com',
            'version': 'v1',
            'namespace': 'default',
            'plural': 'osinstances',
            'name': '860f5462-f16e-4836-a6aa-2935fc7fccc0',
            'body': {
                'spec': None,
                'status': None,
                'action': {
                    'destroy': True,
                    'state': None
                }}
            })
