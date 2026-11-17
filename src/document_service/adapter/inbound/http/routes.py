"""Router nghiệp vụ, đúng hợp đồng API ở mục 12 của docs/c4-04b-code-structure.md.

Payload không chứa khái niệm của OpenMetadata (`fqn`, `extension`, `entityType`): đổi
phiên bản hay sản phẩm catalog không được làm vỡ hợp đồng này. Dependency được gom
thành context object ở `context.py` để mỗi endpoint giữ ít tham số.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import StreamingResponse

from document_service.adapter.inbound.http.context import (
    RequestContext,
    SearchParams,
    UploadContext,
    WriteContext,
    get_request_context,
    get_search_params,
    get_upload_context,
    get_write_context,
)
from document_service.adapter.inbound.http.dependencies import (
    require_download_mode,
    require_write_mode,
)
from document_service.adapter.inbound.http.schemas import (
    AccessPolicyPayload,
    AuditEventResponse,
    CreateDocumentRequest,
    DeclareRelationshipRequest,
    DocumentResponse,
    DownloadResponse,
    RelationshipResponse,
    SearchResponse,
    TransitionStatusRequest,
    VersionResponse,
)
from document_service.application.usecase.approve_version import TransitionStatusCommand
from document_service.application.usecase.create_version import (
    CreateVersionCommand,
    CreateVersionResult,
)
from document_service.application.usecase.issue_download import IssueDownloadCommand
from document_service.application.usecase.register_document import RegisterDocumentCommand
from document_service.application.usecase.relationships import (
    DeclareRelationshipCommand,
    QueryRelationshipsCommand,
)
from document_service.application.usecase.search_documents import (
    ListAuditCommand,
    SearchCommand,
    UpdateAccessPolicyCommand,
)
from document_service.domain.errors import PolicyDeniedError
from document_service.domain.model import DocumentMetadata
from document_service.domain.value import (
    Action,
    Direction,
    DocumentId,
    DocumentStatus,
    DocumentVersionId,
    RelationType,
)

router = APIRouter()

ReadCtx = Annotated[RequestContext, Depends(get_request_context)]
WriteCtx = Annotated[WriteContext, Depends(get_write_context)]
UploadCtx = Annotated[UploadContext, Depends(get_upload_context)]
SearchCtx = Annotated[SearchParams, Depends(get_search_params)]
WRITE_GATE = Depends(require_write_mode)
DOWNLOAD_GATE = Depends(require_download_mode)


@router.post("/documents", response_model=DocumentResponse, status_code=201)
async def create_document(
    payload: CreateDocumentRequest,
    ctx: WriteCtx,
    _: None = WRITE_GATE,
) -> DocumentResponse:
    """Đăng ký một tài liệu logic mới."""
    command = RegisterDocumentCommand(
        principal=ctx.principal,
        metadata=DocumentMetadata(
            title=payload.title,
            description=payload.description,
            document_type=payload.document_type,
            tags=tuple(payload.tags),
            language=payload.language,
            owner=payload.owner or ctx.principal.principal_id,
            department=payload.department,
            collection_id=payload.collection_id,
        ),
        access_policy=payload.access_policy.to_domain(),
        document_id=DocumentId(payload.document_id) if payload.document_id else None,
        retention_policy=payload.retention_policy,
    )
    document = await ctx.container.register_document().execute(command)
    return DocumentResponse.from_domain(document)


@router.get("/documents/{document_id}", response_model=DocumentResponse)
async def read_document(document_id: str, ctx: ReadCtx) -> DocumentResponse:
    """Đọc thông tin tài liệu và số phiên bản."""
    identifier = DocumentId(document_id)
    decision = await ctx.container.ports.policies.decide(
        ctx.principal, Action.VIEW_METADATA, str(identifier)
    )
    if not decision.allowed:
        raise PolicyDeniedError(decision.reason or "không có quyền xem tài liệu")
    document = await ctx.container.ports.catalog.read_document(identifier)
    return DocumentResponse.from_domain(document)


@router.post(
    "/documents/{document_id}/versions", response_model=VersionResponse, status_code=201
)
async def create_version(
    document_id: str,
    ctx: UploadCtx,
    file: UploadFile = File(...),
    version_label: str | None = Form(default=None),
    _: None = WRITE_GATE,
) -> VersionResponse:
    """Nhận file gốc và tạo một phiên bản nội dung mới."""
    prepared = await ctx.handler.prepare(
        DocumentId(document_id),
        file,
        ctx.principal,
        ctx.idempotency_key,
        version_label,
    )
    result: CreateVersionResult = await ctx.container.create_version().execute(
        CreateVersionCommand(
            request=prepared.request,
            principal=ctx.principal,
            stream_factory=prepared.stream_factory,
        )
    )
    return VersionResponse.from_domain(
        result.version, created=result.created, duplicate=result.duplicate
    )


@router.post("/versions/{version_id}/status", response_model=VersionResponse)
async def transition_status(
    version_id: str,
    payload: TransitionStatusRequest,
    ctx: ReadCtx,
    document_id: str = Query(...),
    _: None = WRITE_GATE,
) -> VersionResponse:
    """Chuyển trạng thái một phiên bản (Draft → Approved → Obsolete)."""
    command = TransitionStatusCommand(
        document_id=DocumentId(document_id),
        version_id=DocumentVersionId(version_id),
        target_status=DocumentStatus(payload.status),
        principal=ctx.principal,
    )
    result = await ctx.container.approve_version().execute(command)
    return VersionResponse.from_domain(result.approved)


@router.post("/relationships", response_model=RelationshipResponse, status_code=201)
async def declare_relationship(
    payload: DeclareRelationshipRequest,
    ctx: WriteCtx,
    _: None = WRITE_GATE,
) -> RelationshipResponse:
    """Khai báo quan hệ giữa hai phiên bản."""
    command = DeclareRelationshipCommand(
        relation_type=RelationType(payload.relation_type),
        source_version_id=DocumentVersionId(payload.source_version_id),
        target_version_id=DocumentVersionId(payload.target_version_id),
        principal=ctx.principal,
    )
    relationship = await ctx.container.declare_relationship().execute(command)
    return RelationshipResponse.from_domain(relationship)


@router.get(
    "/versions/{version_id}/relationships", response_model=list[RelationshipResponse]
)
async def query_relationships(
    version_id: str,
    ctx: ReadCtx,
    direction: Direction = Query(default=Direction.BOTH),
    relation_type: RelationType | None = Query(default=None),
) -> list[RelationshipResponse]:
    """Truy vấn quan hệ hai chiều theo loại quan hệ."""
    command = QueryRelationshipsCommand(
        version_id=DocumentVersionId(version_id),
        principal=ctx.principal,
        direction=direction,
        relation_type=relation_type,
    )
    items = await ctx.container.query_relationships().execute(command)
    return [RelationshipResponse.from_domain(item) for item in items]


@router.get("/versions/{version_id}/download", response_model=DownloadResponse)
async def download_version(
    version_id: str,
    ctx: ReadCtx,
    document_id: str = Query(...),
    _: None = DOWNLOAD_GATE,
) -> Any:
    """Cấp link tải có thời hạn, hoặc proxy stream khi policy yêu cầu."""
    command = IssueDownloadCommand(
        document_id=DocumentId(document_id),
        version_id=DocumentVersionId(version_id),
        principal=ctx.principal,
    )
    grant = await ctx.container.issue_download().execute(command)
    if not grant.proxied:
        return DownloadResponse.from_domain(grant)
    document = await ctx.container.ports.catalog.read_document(command.document_id)
    version = document.find_version(command.version_id)
    return StreamingResponse(
        ctx.container.proxy_streamer().stream(version.storage_uri),
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{version.original_file_name}"'
        },
    )


@router.get("/search", response_model=SearchResponse)
async def search_documents(ctx: ReadCtx, params: SearchCtx) -> SearchResponse:
    """Tìm kiếm theo metadata với lọc tổ hợp và phân trang."""
    page = await ctx.container.search_documents().execute(
        SearchCommand(query=params.to_query(), principal=ctx.principal)
    )
    return SearchResponse.from_domain(page)


@router.patch("/documents/{document_id}/access-policy", response_model=AccessPolicyPayload)
async def update_access_policy(
    document_id: str,
    payload: AccessPolicyPayload,
    ctx: WriteCtx,
    _: None = WRITE_GATE,
) -> AccessPolicyPayload:
    """Cập nhật chính sách truy cập của tài liệu."""
    command = UpdateAccessPolicyCommand(
        document_id=DocumentId(document_id),
        principal=ctx.principal,
        access_policy=payload.to_domain(),
    )
    policy = await ctx.container.update_access_policy().execute(command)
    return AccessPolicyPayload.from_domain(policy)


@router.get("/documents/{document_id}/audit", response_model=list[AuditEventResponse])
async def list_audit(document_id: str, ctx: ReadCtx) -> list[AuditEventResponse]:
    """Đọc lịch sử audit của một tài liệu."""
    command = ListAuditCommand(document_id=DocumentId(document_id), principal=ctx.principal)
    events = await ctx.container.list_audit().execute(command)
    return [AuditEventResponse.from_domain(event) for event in events]
