from dataclasses import asdict, dataclass, fields
from kubernetes import client
from kubernetes.client.rest import ApiException
from typing import ClassVar, Optional, Type, TypeVar, Generic


@dataclass
class OsCrdProperties(object):
    NAME: ClassVar[str] = None

    @staticmethod
    def python_type_to_json_type(py_type):
        if py_type in [str, Optional[str]]:
            return "string"
        if py_type in [int, Optional[int]]:
            return "integer"
        if py_type in [float, Optional[float]]:
            return "number"
        if py_type in [bool, Optional[bool]]:
            return "boolean"
        if py_type in [dict, Optional[dict]]:
            return "object"
        if py_type in [list, Optional[list]]:
            return "array"
        return "string"  # fallback

    @classmethod
    def to_properties(cls):
        props = {}
        for f in fields(cls):
            json_type = cls.python_type_to_json_type(f.type)
            props[f.name] = {"type": json_type}
        return props

    @classmethod
    def to_print(cls):
        print_fields = []
        for f in fields(cls):
            if f.metadata.get("print", False):
                print_fields.append({
                        "name": f.name.replace("_", " ").title(),
                        "type": cls.python_type_to_json_type(f.type),
                        "jsonPath": f".{cls.NAME}.{f.name}"
                })
        return print_fields


@dataclass
class OsCrdObjMetadataLabels(object):
    host: str


@dataclass
class OsCrdObjMetadata(object):
    name: str
    labels: OsCrdObjMetadataLabels


@dataclass
class OsCrdObjSpec(OsCrdProperties):
    NAME: ClassVar[str] = "spec"


@dataclass
class OsCrdObjStatus(OsCrdProperties):
    NAME: ClassVar[str] = "status"


@dataclass
class OsCrdObjAction(OsCrdProperties):
    NAME: ClassVar[str] = "action"


@dataclass
class OsCrdObjBody(object):
    spec: OsCrdObjSpec = None
    status: OsCrdObjStatus = None
    action: OsCrdObjAction = None


@dataclass
class OsCrdObj(OsCrdObjBody):
    metadata: OsCrdObjMetadata = None

    # overridden on creation call
    apiVersion: str = None
    kind: str = None


T = TypeVar("T", bound=OsCrdObj)


class OsCrd(Generic[T]):
    CRD_VERSION = 'v1'
    CRD_GROUP = 'sap.com'
    CRD_NAME = None
    CRD_KIND = None
    CRD_SINGULAR = None
    CRD_PLURAL = None
    CRD_SHORT_NAMES = []
    CRD_SPEC = OsCrdObjSpec
    CRD_STATUS = OsCrdObjStatus
    CRD_ACTION = OsCrdObjAction

    def __init__(self, api_client, namespace: str):
        self.api_client = api_client
        self.custom_api = client.CustomObjectsApi(api_client)
        self.api_ext = client.ApiextensionsV1Api(api_client)
        self.namespace = namespace

    def create_manifest(self):
        crd_manifest = {
            "apiVersion": "apiextensions.k8s.io/v1",
            "kind": "CustomResourceDefinition",
            "metadata": {
                "name": self.CRD_NAME,
            },
            "spec": {
                "group": self.CRD_GROUP,
                "versions": [{
                    "name": self.CRD_VERSION,
                    "served": True,
                    "storage": True,
                    "schema": {
                        "openAPIV3Schema": {
                            "type": "object",
                            "properties": {
                                "spec": {
                                    "type": "object",
                                    "properties": self.CRD_SPEC.to_properties()
                                },
                                "status": {
                                    "type": "object",
                                    "properties": self.CRD_STATUS.to_properties()
                                },
                                "action": {
                                    "type": "object",
                                    "properties": self.CRD_ACTION.to_properties()
                                }
                            }
                        }
                    },
                "additionalPrinterColumns":
                    self.CRD_STATUS.to_print() + self.CRD_SPEC.to_print() +
                                             self.CRD_ACTION.to_print()
                }],
                "scope": "Namespaced",
                "names": {
                    "plural": self.CRD_PLURAL,
                    "singular": self.CRD_SINGULAR,
                    "kind": self.CRD_KIND,
                    "shortNames": self.CRD_SHORT_NAMES
                }
            }
        }

        try:
            self.api_ext.create_custom_resource_definition(crd_manifest)
        except ApiException as e:
            if e.status == 409:  # Conflict - already exists
                pass
            else:
                raise e

    def create_object(self, obj: OsCrdObj):
        obj.kind = self.CRD_KIND
        obj.apiVersion = f'{self.CRD_GROUP}/{self.CRD_VERSION}'

        return self.custom_api.create_namespaced_custom_object(
            group=self.CRD_GROUP,
            version=self.CRD_VERSION,
            namespace=self.namespace,
            plural=self.CRD_PLURAL,
            body=asdict(obj)
        )

    def get(self, name: str, obj_type: Type[T] = OsCrdObj) -> Optional[T]:
        try:
            result = self.custom_api.get_namespaced_custom_object(
                group=self.CRD_GROUP,
                version=self.CRD_VERSION,
                namespace=self.namespace,
                plural=self.CRD_PLURAL,
                name=name
            )
            return obj_type(**result)
        except ApiException as e:
            if e.status == 404:
                return None
            raise

    def list(self, label_selector: str = None, obj_type: Type[T] = OsCrdObj) -> list[T]:
        result = self.custom_api.list_namespaced_custom_object(
            group=self.CRD_GROUP,
            version=self.CRD_VERSION,
            namespace=self.namespace,
            plural=self.CRD_PLURAL,
            label_selector=label_selector
        )

        return [obj_type(**item) for item in result.get("items", [])]

    def patch(self, name: str, patch: OsCrdObjBody):
        d = asdict(patch)

        def remove_none_fields(obj):
            if isinstance(obj, dict):
                return {k: remove_none_fields(v) for k, v in obj.items() if v is not None}
            elif isinstance(obj, list):
                return [remove_none_fields(v) for v in obj if v is not None]
            else:
                return obj

        d = remove_none_fields(d)

        return self.custom_api.patch_namespaced_custom_object(
            group=self.CRD_GROUP,
            version=self.CRD_VERSION,
            namespace=self.namespace,
            plural=self.CRD_PLURAL,
            name=name,
            body=d
        )

    def wait_status(self, key: str, name: str, desired_state: str, timeout: int = 60):
        import time

        start = time.time()
        while time.time() - start < timeout:
            obj = self.get(name)
            if obj and obj.status[key] == desired_state:
                return
            time.sleep(1)

        raise TimeoutError(
            f"Timeout waiting for {name} to reach state {desired_state}")
