from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from nova.objects.instance import Instance
from nova.virt.kubernetes.os_crd import OsCrd, OsCrdObj, OsCrdObjBody, \
    OsCrdObjMetadata, OsCrdObjMetadataLabels, \
    OsCrdObjSpec, OsCrdObjStatus, OsCrdObjAction \



@dataclass
class OsCrdObjInstanceSpec(OsCrdObjSpec):
    uuid: str
    display_name: str


@dataclass
class OsCrdObjInstanceStatus(OsCrdObjStatus):
    vm_state: str = field(metadata={"print": True})


class OsCrdObjInstanceActionState(str, Enum):
    REBOOT_SOFT = "reboot_soft"
    REBOOT_HARD = "reboot_hard"
    SUSPEND = "suspend"
    RESUME = "resume"
    PAUSE = "pause"
    UNPAUSE = "unpause"
    POWER_OFF = "power_off"
    POWER_ON = "power_on"

    @classmethod
    def list(cls):
        return [cls.REBOOT_SOFT, cls.REBOOT_HARD, cls.SUSPEND, cls.RESUME,
                cls.PAUSE, cls.UNPAUSE, cls.POWER_OFF, cls.POWER_ON]

    def __str__(self):
        return self.value


@dataclass
class OsCrdObjInstanceAction(OsCrdObjAction):
    destroy: bool = None
    state: Optional[OsCrdObjInstanceActionState] = None


@dataclass
class OsCrdObjBodyInstanceBody(OsCrdObjBody):
    spec: OsCrdObjInstanceSpec = None
    status: OsCrdObjInstanceStatus = None
    action: OsCrdObjInstanceAction = None


@dataclass
class OsCrdObjInstance(OsCrdObj, OsCrdObjBodyInstanceBody):
    pass

    @staticmethod
    def from_instance(instance: Instance) -> 'OsCrdObjInstance':
        return OsCrdObjInstance(
            metadata=OsCrdObjMetadata(
                name=instance['uuid'],
                labels=OsCrdObjMetadataLabels(
                    host=instance['host']
                )
            ),
            spec=OsCrdObjInstanceSpec(
                uuid=instance['uuid'],
                display_name=instance['display_name']
            ),
            status=OsCrdObjInstanceStatus(
                vm_state=instance['vm_state']
            ),
            action=OsCrdObjInstanceAction()
        )


class OsCrdInstance(OsCrd):
    CRD_KIND = 'OsInstance'
    CRD_PLURAL = 'osinstances'
    CRD_SINGULAR = 'osinstance'
    CRD_NAME = 'osinstances.sap.com'
    CRD_SHORT_NAMES = ['osinst']
    CRD_ACTION = OsCrdObjInstanceAction
    CRD_SPEC = OsCrdObjInstanceSpec
    CRD_STATUS = OsCrdObjInstanceStatus

    def __init__(self, api_client, namespace):
        super().__init__(api_client, namespace)

    def create(self, instance: Instance):
        self.create_object(
            OsCrdObjInstance.from_instance(instance)
        )

    def get(self, instance: Instance) -> Optional[OsCrdObjInstance]:
        name = instance['uuid']
        return super().get(name, OsCrdObjInstance)

    def patch(self, instance: Instance, patch: OsCrdObjBodyInstanceBody):
        super().patch(instance['uuid'], patch)

    def list(self, host: str = None) -> list[OsCrdObjInstance]:
        label_selector = f"host={host}" if host else None
        return super().list(label_selector, OsCrdObjInstance)
