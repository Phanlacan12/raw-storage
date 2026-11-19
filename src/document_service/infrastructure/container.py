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
from document_service.adapter.inbound.health.registry import DegradedModeGate, HealthCheckRegistry
from document_service.adapter.inbound.security.auth import PrincipalResolver
from document_service.adapter.inbound.sync.source_sync import SourceSyncJob, SourceSyncScheduler
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
from document_service.adapter.outbound.observability.audit_log import StructuredAuditLogger
from document_service.adapter.outbound.observability.metrics import MetricsRecorder
from document_service.adapter.outbound.observability.outbox_dispatcher import (
    OutboxDispatcher,
    WebhookEventSender,
)
from document_service.adapter.outbound.observability.outbox_publisher import OutboxEventPublisher
from document_service.adapter.outbound.observability.outbox_store import SqliteOutbox
from document_service.adapter.outbound.openmetadata.catalog_adapter import (
    OpenMetadataCatalogAdapter,
)
from document_service.adapter.outbound.openmetadata.client import OmHttpClient
from document_service.adapter.outbound.openmetadata.lineage import OmLineageRelationshipStore
from document_service.adapter.outbound.policy.policy_decision import CachingPolicyDecision
from document_service.adapter.outbound.relationship.sqlite_registry import (
    SqliteRelationshipRegistry,
)
from document_service.adapter.outbound.sqlite_support import SqliteDatabase
from document_service.adapter.outbound.storage.download import PresignedUrlIssuer, ProxyStreamer
from document_service.adapter.outbound.storage.s3_store import S3ObjectStoreAdapter
from document_service.application.context import PolicySet, PortBundle
from document_service.application.factory import UseCaseFactory
from document_service.config import (
    AdapterProfile,
    IntentStoreKind,
    RelationshipStoreKind,
    Settings,
    get_settings,
)
from document_service.domain.metadata_builder import CatalogMetadataBuilder
from document_service.domain.policy import (
    DedupPolicy,
    LifecyclePolicy,
    RelationshipPolicy,
    VersionPolicy,
)
from document_service.infrastructure.health import HealthProbeMixin
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
        self._use_cases = UseCaseFactory(
            self._ports,
            self._policies,
            self._settings.storage.presign_ttl_seconds,
            self._builder,
            self._settings.catalog.require_existing_collection,
        )
        self._resolver = PrincipalResolver(self._settings.security)
        self._health = HealthCheckRegistry(self._ports.policies.has_cached_download)
        self._gate = DegradedModeGate()
        self._metrics = MetricsRecorder()
        self._register_health()

    @property
    def settings(self) -> Settings:
        """Cấu hình đang dùng."""
        return self._settings

    @property
    def resolver(self) -> PrincipalResolver:
        """Bộ xác thực dùng chung cho request và health IdP."""
        return self._resolver

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
            self._use_cases.register_document(),
            self._use_cases.create_version(),
            self._settings.sync,
        )

    def source_sync_scheduler(self) -> SourceSyncScheduler:
        """Bộ lập lịch cho job đồng bộ."""
        return SourceSyncScheduler(self.source_sync_job(), self._settings.sync)

    def outbox_dispatcher(self) -> OutboxDispatcher | None:
        """Worker phát sự kiện cho downstream, None nếu dùng profile fake.

        `WebhookEventSender` dùng executor **riêng** (`events`): downstream và outbox
        store là hai phụ thuộc khác nhau, nên circuit breaker của bên này không được
        làm health của bên kia báo DOWN.
        """
        publisher = self._ports.events
        if isinstance(publisher, OutboxEventPublisher):
            sender = WebhookEventSender(self._settings.events, self._executors.get("events"))
            return OutboxDispatcher(publisher.outbox, sender, self._settings.events)
        return None

    def proxy_streamer(self) -> ProxyStreamer:
        """Đường tải qua dịch vụ, dùng cho tài liệu cần thu hồi ngay (POC-23)."""
        return ProxyStreamer(self._ports.objects)

    def presigned_issuer(self) -> PresignedUrlIssuer:
        """Bộ cấp link tải có thời hạn cho tài liệu thông thường."""
        return PresignedUrlIssuer(self._ports.objects, self._settings.storage.presign_ttl_seconds)

    def executor(self, name: str) -> ResilientCallExecutor:
        """Executor của một phụ thuộc, dùng khi cần tạo client ngoài container."""
        return self._executors.get(name)

    @property
    def gate(self) -> DegradedModeGate:
        """Cổng chặn hành động theo chế độ suy giảm."""
        return self._gate

    @property
    def use_cases(self) -> UseCaseFactory:
        """Factory dựng use case (xem application/factory.py)."""
        return self._use_cases

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
        # Executor `idp` đã bị loại (X50, c4-09 mục 5.3): OidcTokenVerifier không
        # nhận executor nào, nên khối `resilience.idp` cũ hoàn toàn vô tác dụng.
        self._executors.register("events", resilience.events)
        self._executors.register("outbox", resilience.intent)
        self._executors.register("audit", resilience.intent)

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
            policies=AllowAllPolicyDecision(catalog),
            events=InMemoryEventPublisher(),
            audit=InMemoryAuditLog(),
            locks=InMemoryDocumentLock(),
        )

    def _build_real_ports(self) -> PortBundle:
        """Bộ adapter dùng OpenMetadata, Object Storage và registry sqlite."""
        database = SqliteDatabase(self._settings.intent.sqlite_path)
        catalog_client = OmHttpClient(self._settings.catalog, self._executors.get("catalog"))
        catalog = OpenMetadataCatalogAdapter(
            catalog_client, self._settings.catalog, self._executors.get("catalog")
        )
        objects = S3ObjectStoreAdapter(self._settings.storage, self._executors.get("object_store"))
        # Lineage store có client HTTP **riêng** dựng trên executor của chính nó
        # (X22, c4-09 mục 5.3, luật L-EX1): mọi lời gọi của nó phải đi qua executor
        # `relationship_store` để breaker và health indicator nói đúng về traffic
        # thật, không trộn với executor `catalog`.
        lineage_client = OmHttpClient(
            self._settings.catalog, self._executors.get("relationship_store")
        )
        relationships = (
            OmLineageRelationshipStore(lineage_client, self._executors.get("relationship_store"))
            if self._settings.relationship.kind is RelationshipStoreKind.LINEAGE
            else SqliteRelationshipRegistry(database, self._executors.get("relationship_store"))
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
            events=OutboxEventPublisher(SqliteOutbox(database), self._executors.get("outbox")),
            audit=StructuredAuditLogger(database, self._executors.get("audit")),
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
            self._ports.audit,
            self._ports.events,
            self._ports.policies,
        ):
            if isinstance(candidate, HealthProbeMixin):
                candidate.set_health_cache_ttl(self._settings.health.cache_ttl_seconds)
                self._health.register(AdapterHealthIndicator(candidate))
        self._health.register(IdpHealthIndicator(self._resolver.verifier.probe_jwks))
        self._health.register(
            ReconcileBacklogIndicator(
                self._ports.intents,
                self._settings.intent.stale_after_seconds,
                self._settings.health.backlog_threshold,
            )
        )
