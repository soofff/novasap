from dataclasses import asdict, dataclass, fields, field
from datetime import datetime
from enum import Enum
from kubernetes import client
from kubernetes.client.rest import ApiException
from typing import ClassVar, Optional, Type, TypeVar, Generic, List, get_origin, get_args
import typing


@dataclass
class CrdProperties:
    """Base class for CRD spec/status sections with schema generation support."""
    NAME: ClassVar[str] = None

    @staticmethod
    def python_type_to_json_schema(py_type) -> dict:
        """Convert Python type hints to OpenAPI v3 schema definitions."""
        # Handle Optional types
        origin = get_origin(py_type)
        is_optional = origin is typing.Union and type(None) in get_args(py_type)

        if is_optional:
            # Get the non-None type from Optional
            args = [a for a in get_args(py_type) if a is not type(None)]
            if args:
                py_type = args[0]
                origin = get_origin(py_type)

        schema = {}

        # Handle List types
        if origin is list:
            schema["type"] = "array"
            args = get_args(py_type)
            if args:
                item_schema = CrdProperties.python_type_to_json_schema(args[0])
                schema["items"] = item_schema
        # Handle dict types
        elif py_type is dict or origin is dict:
            schema["type"] = "object"
            schema["additionalProperties"] = True
        # Handle Enum types
        elif isinstance(py_type, type) and issubclass(py_type, Enum):
            schema["type"] = "string"
            schema["enum"] = [e.value for e in py_type]
        # Handle datetime
        elif py_type is datetime:
            schema["type"] = "string"
            schema["format"] = "date-time"
        # Handle nested dataclasses
        elif hasattr(py_type, '__dataclass_fields__'):
            schema["type"] = "object"
            schema["properties"] = {}
            for f in fields(py_type):
                schema["properties"][f.name] = CrdProperties.python_type_to_json_schema(f.type)
        # Handle primitives
        elif py_type in [str, typing.Optional[str]]:
            schema["type"] = "string"
        elif py_type in [int, typing.Optional[int]]:
            schema["type"] = "integer"
        elif py_type in [float, typing.Optional[float]]:
            schema["type"] = "number"
        elif py_type in [bool, typing.Optional[bool]]:
            schema["type"] = "boolean"
        else:
            schema["type"] = "string"  # fallback

        if is_optional:
            schema["nullable"] = True

        return schema

    @classmethod
    def to_properties(cls) -> dict:
        """Generate OpenAPI v3 properties schema from dataclass fields."""
        props = {}
        for f in fields(cls):
            if f.name == 'NAME':  # Skip ClassVar
                continue
            props[f.name] = cls.python_type_to_json_schema(f.type)
            # Add description from metadata if present
            if f.metadata.get("description"):
                props[f.name]["description"] = f.metadata["description"]
        return props

    @classmethod
    def to_printer_columns(cls) -> list:
        """Generate additionalPrinterColumns from fields marked with print=True."""
        columns = []
        for f in fields(cls):
            if f.name == 'NAME':
                continue
            if f.metadata.get("print", False):
                col = {
                    "name": f.metadata.get("print_name", f.name.replace("_", " ").title()),
                    "type": cls._get_printer_type(f.type),
                    "jsonPath": f".{cls.NAME}.{f.name}"
                }
                columns.append(col)
        return columns

    @staticmethod
    def _get_printer_type(py_type) -> str:
        """Get the printer column type for a Python type."""
        origin = get_origin(py_type)
        if origin is typing.Union:
            args = [a for a in get_args(py_type) if a is not type(None)]
            if args:
                py_type = args[0]

        if py_type in [int, typing.Optional[int]]:
            return "integer"
        elif py_type in [bool, typing.Optional[bool]]:
            return "boolean"
        elif py_type is datetime:
            return "date"
        else:
            return "string"


@dataclass
class Condition:
    """Kubernetes-style condition for status tracking."""
    type: str
    status: str  # "True", "False", "Unknown"
    lastTransitionTime: datetime
    reason: Optional[str] = None
    message: Optional[str] = None


@dataclass
class CrdMetadataLabels:
    """Labels for CRD metadata."""
    host: Optional[str] = None


@dataclass
class CrdMetadata:
    """Kubernetes metadata for CRD objects."""
    name: str
    labels: Optional[CrdMetadataLabels] = None
    namespace: Optional[str] = None


@dataclass
class CrdSpec(CrdProperties):
    """Base class for CRD spec sections."""
    NAME: ClassVar[str] = "spec"


@dataclass
class CrdStatus(CrdProperties):
    """Base class for CRD status sections."""
    NAME: ClassVar[str] = "status"


@dataclass
class CrdBody:
    """Base class for CRD body (spec + status)."""
    spec: CrdSpec = None
    status: CrdStatus = None


@dataclass
class CrdObject(CrdBody):
    """Base class for full CRD objects with metadata."""
    metadata: CrdMetadata = None
    apiVersion: str = None
    kind: str = None


T = TypeVar("T", bound=CrdObject)


class Crd(Generic[T]):
    """Base class for Kubernetes Custom Resource Definitions."""

    CRD_VERSION = 'v1'
    CRD_GROUP = 'nova.openstack.org'
    CRD_NAME = None
    CRD_KIND = None
    CRD_SINGULAR = None
    CRD_PLURAL = None
    CRD_SHORT_NAMES = []
    CRD_SPEC = CrdSpec
    CRD_STATUS = CrdStatus
    CRD_USE_STATUS_SUBRESOURCE = True

    def __init__(self, api_client, namespace: str):
        self.api_client = api_client
        self.custom_api = client.CustomObjectsApi(api_client)
        self.api_ext = client.ApiextensionsV1Api(api_client)
        self.namespace = namespace

    def _manifest(self) -> dict:
        """Generate the CRD manifest for Kubernetes."""
        version_spec = {
            "name": self.CRD_VERSION,
            "served": True,
            "storage": True,
            "schema": {
                "openAPIV3Schema": {
                    "type": "object",
                    "required": ["spec"],
                    "properties": {
                        "spec": {
                            "type": "object",
                            "properties": self.CRD_SPEC.to_properties()
                        },
                        "status": {
                            "type": "object",
                            "nullable": True,
                            "properties": self.CRD_STATUS.to_properties()
                        }
                    }
                }
            },
            "additionalPrinterColumns": (
                self.CRD_SPEC.to_printer_columns() +
                self.CRD_STATUS.to_printer_columns() +
                [{"name": "Age", "type": "date", "jsonPath": ".metadata.creationTimestamp"}]
            )
        }

        # Add status subresource if enabled
        if self.CRD_USE_STATUS_SUBRESOURCE:
            version_spec["subresources"] = {"status": {}}

        return {
            "apiVersion": "apiextensions.k8s.io/v1",
            "kind": "CustomResourceDefinition",
            "metadata": {
                "name": self.CRD_NAME,
            },
            "spec": {
                "group": self.CRD_GROUP,
                "versions": [version_spec],
                "scope": "Namespaced",
                "names": {
                    "plural": self.CRD_PLURAL,
                    "singular": self.CRD_SINGULAR,
                    "kind": self.CRD_KIND,
                    "shortNames": self.CRD_SHORT_NAMES
                }
            }
        }

    def create_manifest(self) -> bool:
        """Create the CRD manifest in Kubernetes."""
        try:
            self.api_ext.create_custom_resource_definition(self._manifest())
        except ApiException as e:
            if e.status == 409:  # Conflict - already exists
                return False
            raise e
        return True

    def create_object(self, obj: CrdObject) -> dict:
        """Create a new CRD object."""
        obj.kind = self.CRD_KIND
        obj.apiVersion = f'{self.CRD_GROUP}/{self.CRD_VERSION}'

        body = self._serialize(obj)

        return self.custom_api.create_namespaced_custom_object(
            group=self.CRD_GROUP,
            version=self.CRD_VERSION,
            namespace=self.namespace,
            plural=self.CRD_PLURAL,
            body=body
        )

    def get(self, name: str, obj_type: Type[T] = None) -> Optional[T]:
        """Get a CRD object by name."""
        try:
            result = self.custom_api.get_namespaced_custom_object(
                group=self.CRD_GROUP,
                version=self.CRD_VERSION,
                namespace=self.namespace,
                plural=self.CRD_PLURAL,
                name=name
            )
            if obj_type:
                return self._deserialize(result, obj_type)
            return result
        except ApiException as e:
            if e.status == 404:
                return None
            raise

    def list(self, label_selector: str = None, obj_type: Type[T] = None) -> list:
        """List CRD objects with optional label selector."""
        result = self.custom_api.list_namespaced_custom_object(
            group=self.CRD_GROUP,
            version=self.CRD_VERSION,
            namespace=self.namespace,
            plural=self.CRD_PLURAL,
            label_selector=label_selector
        )
        items = result.get("items", [])
        if obj_type:
            return [self._deserialize(item, obj_type) for item in items]
        return items

    def patch(self, name: str, patch: dict) -> dict:
        """Patch a CRD object."""
        # Remove None values recursively
        patch = self._remove_none_fields(patch)

        return self.custom_api.patch_namespaced_custom_object(
            group=self.CRD_GROUP,
            version=self.CRD_VERSION,
            namespace=self.namespace,
            plural=self.CRD_PLURAL,
            name=name,
            body=patch
        )

    def patch_status(self, name: str, status: dict) -> dict:
        """Patch just the status subresource."""
        body = {"status": self._remove_none_fields(status)}

        return self.custom_api.patch_namespaced_custom_object_status(
            group=self.CRD_GROUP,
            version=self.CRD_VERSION,
            namespace=self.namespace,
            plural=self.CRD_PLURAL,
            name=name,
            body=body
        )

    def delete(self, name: str) -> bool:
        """Delete a CRD object."""
        try:
            self.custom_api.delete_namespaced_custom_object(
                group=self.CRD_GROUP,
                version=self.CRD_VERSION,
                namespace=self.namespace,
                plural=self.CRD_PLURAL,
                name=name
            )
            return True
        except ApiException as e:
            if e.status == 404:
                return False
            raise

    def _serialize(self, obj) -> dict:
        """Serialize a dataclass to dict, handling enums and removing None."""
        if hasattr(obj, '__dataclass_fields__'):
            result = {}
            for f in fields(obj):
                value = getattr(obj, f.name)
                if value is not None:
                    result[f.name] = self._serialize(value)
            return result
        elif isinstance(obj, Enum):
            return obj.value
        elif isinstance(obj, datetime):
            return obj.isoformat() + "Z"
        elif isinstance(obj, list):
            return [self._serialize(item) for item in obj]
        elif isinstance(obj, dict):
            return {k: self._serialize(v) for k, v in obj.items() if v is not None}
        else:
            return obj

    def _deserialize(self, data: dict, obj_type: Type[T]) -> T:
        """Deserialize a dict to a dataclass object."""
        # Simple pass-through for now - full deserialization is complex
        # and we primarily need serialization for CRD creation
        return data

    @staticmethod
    def _remove_none_fields(obj):
        """Recursively remove None fields from dicts."""
        if isinstance(obj, dict):
            return {k: Crd._remove_none_fields(v) for k, v in obj.items() if v is not None}
        elif isinstance(obj, list):
            return [Crd._remove_none_fields(v) for v in obj if v is not None]
        else:
            return obj


# Legacy aliases for backwards compatibility during migration
OsCrdProperties = CrdProperties
OsCrdObjMetadataLabels = CrdMetadataLabels
OsCrdObjMetadata = CrdMetadata
OsCrdObjSpec = CrdSpec
OsCrdObjStatus = CrdStatus
OsCrdObjBody = CrdBody
OsCrdObj = CrdObject
OsCrd = Crd

# Legacy action class (deprecated - use declarative spec.powerState instead)
@dataclass
class OsCrdObjAction(CrdProperties):
    NAME: ClassVar[str] = "action"
