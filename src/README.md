# src/ — Document Service

Hiện thực Python của kho raw data dùng chung, theo thiết kế ở [../docs/](../docs/). Catalog đã chốt là **OpenMetadata** (quyết định Q1).

## Chạy

```bash
conda activate rawstorage          # conda chỉ cấp interpreter 3.12
uv sync --all-extras --dev         # uv quản lý toàn bộ dependency
uv run uvicorn document_service.main:app --port 8080    # profile fake, không cần hạ tầng
curl -s localhost:8080/readyz
```

Dùng hạ tầng thật: xem [../deploy/README.md](../deploy/README.md). Cấu hình: [../configs/README.md](../configs/README.md). Môi trường project dùng `.venv` riêng (seed từ interpreter của conda env `rawstorage`), không cài vào conda env.

```bash
make test        # mypy -> pytest -> pylint, đúng thứ tự CI
make reconcile   # chạy một lượt đối soát intent/object/entity
make docs-check  # parse mọi sơ đồ mermaid trong docs/
```

## Ánh xạ module ↔ thành phần thiết kế

Thành phần D1–D27 theo [c4-03](../docs/c4-03-component-document-service.md) mục 3.2 và [c4-04b](../docs/c4-04b-code-structure.md) mục 4.

| ID | Thành phần | File hiện thực |
|---|---|---|
| D1 | API Layer | `adapter/inbound/http/routes.py`, `schemas.py`, `errors.py`, `dependencies.py`, `context.py` |
| D2 | Authentication | `adapter/inbound/security/auth.py` (`OidcTokenVerifier`, `PrincipalResolver`) |
| D3 | Authorization / PDP | `adapter/outbound/policy/policy_decision.py` (`CachingPolicyDecision`) |
| D4 | Upload Handler | `adapter/inbound/http/upload_handler.py` (`UploadHandler`, `IdempotencyKeyFilter`) |
| D5 | Checksum & Dedup | `domain/policy.py` (`DedupPolicy`) + `utils/hashing.py` (`StreamingHasher`) |
| D6 | Version Manager | `domain/policy.py` (`VersionPolicy`) |
| D7 | Lifecycle Manager | `domain/policy.py` (`LifecyclePolicy`) + `application/usecase/approve_version.py` |
| D8 | Relationship Manager | `domain/policy.py` (`RelationshipPolicy`) + `application/usecase/relationships.py` |
| D9 | Access Policy Manager | `application/usecase/access_policy.py` (`UpdateAccessPolicyUseCase`) + D3 |
| D10 | Download Issuer | `adapter/outbound/storage/download.py` (`PresignedUrlIssuer`, `ProxyStreamer`) + `application/usecase/issue_download.py` |
| D11 | Intent & Idempotency | `application/orchestration/idempotency.py`, `upload_saga.py`, `snapshot.py`, `lock_manager.py` |
| D12 | Catalog Adapter | `adapter/outbound/openmetadata/` (`client`, `entity`, `search`, `lineage`, `bootstrap`, `catalog_adapter`) |
| D13 | Storage Adapter | `adapter/outbound/storage/s3_store.py` |
| D14 | Outbox Writer | `adapter/outbound/observability/outbox_publisher.py` (`OutboxEventPublisher`) + `outbox_store.py` (`SqliteOutbox`, `OutboxRecord`); phát đi ở `outbox_dispatcher.py` (`OutboxDispatcher`, `WebhookEventSender`) |
| D15 | Reconciliation Worker | `worker/reconcile.py` |
| D16 | Audit Logger | `adapter/outbound/observability/audit_log.py` (`StructuredAuditLogger`) + `application/usecase/audit.py` (`ListAuditUseCase`) |
| D17 | Sync Orchestrator | `adapter/inbound/sync/source_sync.py` (`SourceSyncJob`, `FileSystemSourceConnector`, `SourcePermissionMapper`, `SourceSyncScheduler`) |
| D18 | Search Query Service | `application/usecase/search_documents.py` (`SearchDocumentsUseCase`) + `adapter/outbound/openmetadata/search.py` |
| D19 | Relationship Store Adapter | `adapter/outbound/relationship/sqlite_registry.py` (`SqliteRelationshipRegistry`) + `adapter/outbound/openmetadata/lineage.py` (`OmLineageRelationshipStore`) |
| D20 | State Store Adapter | `adapter/outbound/sqlite_support.py` + `adapter/outbound/intent/` + `adapter/outbound/observability/` |
| D21 | Policy Decision Adapter | `adapter/outbound/policy/policy_decision.py` (`CachingPolicyDecision`) |
| D22 | Document Lock Adapter | `adapter/outbound/fake/in_memory.py` (`InMemoryDocumentLock`) + `adapter/outbound/lock/redis_lock.py` (`RedisDocumentLock`) + `application/orchestration/lock_manager.py` |
| D23 | Metadata Schema & Validation | Ngoài phạm vi; chỗ cắm ở `domain/metadata_fields.py` |
| D24 | Collection Manager | Ngoài phạm vi; chỗ cắm ở `MetadataCatalogPort.ensure_collection`/`find_collection` |
| D25 | Retention & Deletion | Ngoài phạm vi; chỗ cắm ở `Document.retention_policy` |
| D26 | Outbox Dispatcher | `adapter/outbound/observability/outbox_dispatcher.py` + `worker/dispatch.py` (`OutboxDispatchRunner`) |
| D27 | Hạ tầng xuyên suốt | `infrastructure/container.py`, `infrastructure/health.py`, `infrastructure/resilience/`, `adapter/inbound/health/` |

Bảng đầy đủ D1–D27, kèm cột lớp và cột bất biến, nằm ở [docs/c4-09-lld.md](../docs/c4-09-lld.md) mục 2.2; bảng trên đây chỉ là bản rút gọn.

Dựng use case: `application/factory.py` (`UseCaseFactory`), lấy qua `container.use_cases`.

Thành phần hạ tầng kèm theo: health check [c4-04b mục 10](../docs/c4-04b-code-structure.md#10-health-check) ở `infrastructure/health.py` + `adapter/inbound/health/`; resilience [mục 11](../docs/c4-04b-code-structure.md#11-retry-timeout-và-chịu-lỗi-kết-nối) ở `infrastructure/resilience/`; chỉ số [mục 11.7](../docs/c4-04b-code-structure.md#117-chỉ-số-và-cảnh-báo-bắt-buộc) ở `adapter/outbound/observability/metrics.py`; wiring ở `infrastructure/container.py`.

## Quy tắc phải giữ khi sửa code

1. **Base class cho mọi hợp đồng.** 8 port ở `domain/port.py` là `ABC`; use case kế thừa `UseCase` → `ReadUseCase`/`WriteUseCase`; adapter outbound kế thừa `OutboundAdapter`; policy kế thừa `DomainPolicy`.
2. **Mỗi phụ thuộc ngoài tự khai báo health.** Adapter hiện thực `_probe_dependency()`; lớp inbound chỉ ủy quyền qua `AdapterHealthIndicator`.
3. **`utils/` chỉ dùng stdlib** và không import ngược vào service. Màu/format log terminal ở `utils/logging_setup.py`; audit nghiệp vụ ở `observability`.
4. **Singleton có `reset()`** và được `tests/conftest.py` dọn giữa các test. Không singleton cho dữ liệu nghiệp vụ.
5. **Cấu hình ở `configs/*.yml`**, bí mật chỉ qua biến môi trường.
6. **Xong một module thì đối soát** với docs và ghi vào [c4-08](../docs/c4-08-tra-soat-code-vs-thiet-ke.md).

## Phân lớp

```
adapter/inbound  →  application  →  domain  ←  adapter/outbound (implements port)
                         ↓              ↓
                  infrastructure  ←  utils
```

`domain/` và `domain/port.py` không import `httpx`, `boto3`, `fastapi`, `sqlite3` hay `config` — được kiểm tra bằng AST trong `tests/unit/test_architecture_rules.py`, không phải bằng quy ước.
