"""Bundle các port và policy để tiêm vào use case.

Lý do gom lại: pylint giới hạn `max-args=5`, trong khi mỗi use case cần nhiều port.
Từng port vẫn truy cập qua thuộc tính cùng tên như sơ đồ lớp ở
docs/c4-04b-code-structure.md mục 3, nên hợp đồng thiết kế không đổi.
"""

from __future__ import annotations

from dataclasses import dataclass

from document_service.domain.policy import (
    DedupPolicy,
    LifecyclePolicy,
    RelationshipPolicy,
    VersionPolicy,
)
from document_service.domain.port import (
    AuditPort,
    DocumentLockPort,
    EventPublisherPort,
    IntentStorePort,
    MetadataCatalogPort,
    ObjectStorePort,
    PolicyDecisionPort,
    RelationshipStorePort,
)


@dataclass(frozen=True, slots=True)
class PortBundle:
    """Tập hợp tám port mà lớp application được phép dùng."""

    catalog: MetadataCatalogPort
    relationships: RelationshipStorePort
    objects: ObjectStorePort
    intents: IntentStorePort
    policies: PolicyDecisionPort
    events: EventPublisherPort
    audit: AuditPort
    locks: DocumentLockPort


@dataclass(frozen=True, slots=True)
class PolicySet:
    """Tập hợp domain service giữ bất biến."""

    version: VersionPolicy
    lifecycle: LifecyclePolicy
    relationship: RelationshipPolicy
    dedup: DedupPolicy
