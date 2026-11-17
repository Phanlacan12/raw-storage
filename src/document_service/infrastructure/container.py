"""ServiceContainer: điểm wiring duy nhất của service (quy tắc R2).

Container là singleton, giữ đúng một instance cho mỗi thành phần hạ tầng: executor
theo từng phụ thuộc, adapter, use case, registry health. Mọi lớp khác nhận phụ thuộc
qua constructor và không tự khởi tạo adapter.
"""

from __future__ import annotations

from document_service.adapter.inbound.health.indicators import (
    AdapterHealthIndicator,
    IdpHealthIndicator,
    ReconcileBacklogIndicator,
)
from document_service.adapter.inbound.health.registry import (
    DegradedModeGate,
    HealthCheckRegistry,
)
from document_service.adapter.outbound.fake.in_memory import (
    AllowAllPolicyDecision,
    InMemoryAuditLog,
    InMemoryCatalog,
    InMemoryDocumentLock,
    InMemoryEventPublisher,
    InMemoryIntentStore,
    InMemoryObjectStore,
    InMemoryRelationshipStore,
)
from document_service.adapter.outbound.intent.s3_manifest_store import S3ManifestIntentStore
from document_service.adapter.outbound.intent.sqlite_store import SqliteRegistryIntentStore
from document_service.adapter.outbound.observability.audit_log import (
    OutboxEventPublisher,
    StructuredAuditLogger,
)
from document_service.adapter.outbound.observability.metrics import MetricsRecorder
from document_service.adapter.outbound.policy.policy_decision import CachingPolicyDecision
from document_service.adapter.outbound.relationship.sqlite_registry import (
    SqliteRelationshipRegistry,
)
from document_service.adapter.outbound.openmetadata.catalog_adapter import (
    OpenMetadataCatalogAdapter,
)
from document_service.adapter.outbound.openmetadata.client import OmHttpClient
from document_service.adapter.outbound.openmetadata.lineage import (
    OmLineageRelationshipStore,
)
from document_service.adapter.outbound.sqlite_support import SqliteDatabase
from document_service.adapter.outbound.storage.download import (
    PresignedUrlIssuer,
    ProxyStreamer,
)
from document_service.adapter.outbound.storage.s3_store import S3ObjectStoreAdapter
from document_service.application.context import PolicySet, PortBundle
from document_service.application.metadata_builder import CatalogMetadataBuilder
from document_service.application.usecase.approve_version import ApproveVersionUseCase
from document_service.application.usecase.create_version import CreateVersionUseCase
from document_service.application.usecase.issue_download import IssueDownloadUseCase
from document_service.application.usecase.register_document import RegisterDocumentUseCase
from document_service.application.usecase.relationships import (
    DeclareRelationshipUseCase,
    QueryRelationshipsUseCase,
)
from document_service.application.usecase.search_documents import (
    ListAuditUseCase,
    SearchDocumentsUseCase,
    UpdateAccessPolicyUseCase,
)
from document_service.adapter.inbound.sync.source_sync import (
    SourceSyncJob,
    SourceSyncScheduler,
)
from document_service.config import (
    AdapterProfile,
    IntentStoreKind,
    RelationshipStoreKind,
    Settings,
    get_settings,
)
from document_service.domain.policy import (
    DedupPolicy,
    LifecyclePolicy,
    RelationshipPolicy,
    VersionPolicy,
)
from document_service.infrastructure.health import HealthProbe
from document_service.infrastructure.resilience.executor import (
    ExecutorRegistry,
    ResilientCallExecutor,
)
from document_service.utils.logging_setup import LoggingConfigurator
from document_service.utils.singleton import SingletonMeta


class ServiceContainer(metaclass=SingletonMeta):
    """Khởi tạo và giữ toàn bộ phụ thuộc của service."""

    def __init__(self, settings: Settings | None = None) -> None:
        """Dựng container theo profile adapter trong cấu hình."""
        self._settings = settings or get_settings()
        LoggingConfigurator().configure(
            self._settings.logging.level, self._settings.logging.json_format
        )
        self._executors = ExecutorRegistry()
        self._register_executors()
        self._ports = self._build_ports()
        self._policies = self._build_policies()
        self._builder = CatalogMetadataBuilder()
        self._health = HealthCheckRegistry()
        self._gate = DegradedModeGate()
        self._metrics = MetricsRecorder()
        self._register_health()

    @property
    def settings(self) -> Settings:
        """Cấu hình đang dùng."""
        return self._settings

    @property
    def ports(self) -> PortBundle:
        """Bundle port đã wiring."""
        return self._ports

    @property
    def policies(self) -> PolicySet:
        """Tập domain policy."""
        return self._policies

    @property
    def health(self) -> HealthCheckRegistry:
        """Registry health."""
        return self._health

    @property
    def metrics(self) -> MetricsRecorder:
        """Bộ chỉ số dùng chung (mục 11.7)."""
        return self._metrics

    def source_sync_job(self) -> SourceSyncJob:
        """Job đồng bộ từ nguồn hiện có (D17)."""
        return SourceSyncJob(
            self.register_document(), self.create_version(), self._settings.sync
        )

    def source_sync_scheduler(self) -> SourceSyncScheduler:
        """Bộ lập lịch cho job đồng bộ."""
        return SourceSyncScheduler(self.source_sync_job(), self._settings.sync)

    # pylint: disable-next=too-many-public-methods
    def proxy_streamer(self) -> ProxyStreamer:
        """Đường tải qua dịch vụ, dùng cho tài liệu cần thu hồi ngay (POC-23)."""
        return ProxyStreamer(self._ports.objects)

    def presigned_issuer(self) -> PresignedUrlIssuer:
        """Bộ cấp link tải có thời hạn cho tài liệu thông thường."""
        return PresignedUrlIssuer(
            self._ports.objects, self._settings.storage.presign_ttl_seconds
        )

    def executor(self, name: str) -> ResilientCallExecutor:
        """Executor của một phụ thuộc, dùng khi cần tạo client ngoài container."""
        return self._executors.get(name)

    @property
    def gate(self) -> DegradedModeGate:
        """Cổng chặn hành động theo chế độ suy giảm."""
        return self._gate

    def register_document(self) -> RegisterDocumentUseCase:
        """Use case đăng ký tài liệu."""
        return RegisterDocumentUseCase(self._ports, self._builder)

    def create_version(self) -> CreateVersionUseCase:
        """Use case tạo phiên bản."""
        return CreateVersionUseCase(self._ports, self._policies, self._builder)

    def approve_version(self) -> ApproveVersionUseCase:
        """Use case chuyển trạng thái phiên bản."""
        return ApproveVersionUseCase(self._ports, self._policies, self._builder)

    def declare_relationship(self) -> DeclareRelationshipUseCase:
        """Use case khai báo quan hệ."""
        return DeclareRelationshipUseCase(self._ports, self._policies)

    def query_relationships(self) -> QueryRelationshipsUseCase:
        """Use case truy vấn quan hệ."""
        return QueryRelationshipsUseCase(self._ports)

    def issue_download(self) -> IssueDownloadUseCase:
        """Use case cấp file."""
        return IssueDownloadUseCase(self._ports, self._settings.storage.presign_ttl_seconds)

    def search_documents(self) -> SearchDocumentsUseCase:
        """Use case tìm kiếm."""
        return SearchDocumentsUseCase(self._ports)

    def update_access_policy(self) -> UpdateAccessPolicyUseCase:
        """Use case cập nhật chính sách truy cập."""
        return UpdateAccessPolicyUseCase(self._ports, self._builder)

    def list_audit(self) -> ListAuditUseCase:
        """Use case đọc audit."""
        return ListAuditUseCase(self._ports)

    def reset(self) -> None:
        """Xoá registry phụ thuộc, dùng trong test."""
        self._executors.reset()
        self._health.reset()
        self._gate.reset()
        self._metrics.reset()

    def _register_executors(self) -> None:
        """Một executor cho mỗi phụ thuộc, theo configs/resilience.yml."""
        resilience = self._settings.resilience
        self._executors.register("catalog", resilience.catalog)
        self._executors.register("object_store", resilience.storage)
        self._executors.register("intent_store", resilience.intent)
        self._executors.register("relationship_store", resilience.relationship)
        self._executors.register("idp", resilience.idp)

    def _build_ports(self) -> PortBundle:
        """Chọn bộ adapter theo profile."""
        if self._settings.app.profile is AdapterProfile.FAKE:
            return self._build_fake_ports()
        return self._build_real_ports()

    def _build_fake_ports(self) -> PortBundle:
        """Bộ adapter in-memory, chạy không cần hạ tầng."""
        catalog = InMemoryCatalog()
        return PortBundle(
            catalog=catalog,
            relationships=InMemoryRelationshipStore(),
            objects=InMemoryObjectStore(),
            intents=InMemoryIntentStore(),
            policies=AllowAllPolicyDecision(),
            events=InMemoryEventPublisher(),
            audit=InMemoryAuditLog(),
            locks=InMemoryDocumentLock(),
        )

    def _build_real_ports(self) -> PortBundle:
        """Bộ adapter dùng OpenMetadata, Object Storage và registry sqlite."""
        database = SqliteDatabase(self._settings.intent.sqlite_path)
        client = OmHttpClient(self._settings.catalog, self._executors.get("catalog"))
        catalog = OpenMetadataCatalogAdapter(
            client, self._settings.catalog, self._executors.get("catalog")
        )
        objects = S3ObjectStoreAdapter(
            self._settings.storage, self._executors.get("object_store")
        )
        relationships = (
            OmLineageRelationshipStore(client, self._executors.get("relationship_store"))
            if self._settings.relationship.kind is RelationshipStoreKind.LINEAGE
            else SqliteRelationshipRegistry(
                database, self._executors.get("relationship_store")
            )
        )
        intents = (
            S3ManifestIntentStore(
                objects,
                self._settings.storage.bucket,
                self._executors.get("intent_store"),
                self._settings.intent.manifest_prefix,
            )
            if self._settings.intent.kind is IntentStoreKind.S3_MANIFEST
            else SqliteRegistryIntentStore(database, self._executors.get("intent_store"))
        )
        return PortBundle(
            catalog=catalog,
            relationships=relationships,
            objects=objects,
            intents=intents,
            policies=CachingPolicyDecision(catalog, self._settings.security),
            events=OutboxEventPublisher(database, self._executors.get("intent_store")),
            audit=StructuredAuditLogger(database, self._executors.get("intent_store")),
            locks=InMemoryDocumentLock(),
        )

    def _build_policies(self) -> PolicySet:
        """Tập domain policy, dùng bucket trong cấu hình storage."""
        dedup = DedupPolicy()
        return PolicySet(
            version=VersionPolicy(self._settings.storage.bucket, dedup=dedup),
            lifecycle=LifecyclePolicy(),
            relationship=RelationshipPolicy(),
            dedup=dedup,
        )

    def _register_health(self) -> None:
        """Đăng ký indicator: mỗi adapter tự khai báo health của phụ thuộc."""
        for candidate in (
            self._ports.catalog,
            self._ports.objects,
            self._ports.intents,
            self._ports.relationships,
            self._ports.locks,
        ):
            if isinstance(candidate, HealthProbe):
                self._health.register(AdapterHealthIndicator(candidate))
        self._health.register(IdpHealthIndicator(jwks_available=True))
        self._health.register(
            ReconcileBacklogIndicator(
                self._ports.intents,
                self._settings.intent.stale_after_seconds,
                self._settings.health.backlog_threshold,
            )
        )
