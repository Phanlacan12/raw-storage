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
    get_upload_context,
    get_write_context,
)
from document_service.adapter.inbound.http.dependencies import (
    require_download_mode,
    require_read_mode,
    require_write_mode,
)
from document_service.adapter.inbound.http.schemas import (
    AccessPolicyPayload,
    AuditEventResponse,
    CreateDocumentRequest,
    DeclareRelationshipRequest,
    DocumentResponse,
    DownloadResponse,
    PageResponse,
    RelationshipResponse,
    SearchResponse,
    TransitionStatusRequest,
    VersionResponse,
)
from document_service.application.usecase.access_policy import UpdateAccessPolicyCommand
from document_service.application.usecase.approve_version import TransitionStatusCommand
from document_service.application.usecase.audit import ListAuditCommand
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
from document_service.application.usecase.search_documents import SearchCommand
from document_service.domain.dto import PageRequest
from document_service.domain.errors import PolicyDeniedError
from document_service.domain.model import Document, DocumentMetadata
from document_service.domain.value import (
    Action,
    Direction,
    DocumentId,
    DocumentStatus,
    DocumentVersionId,
    RelationType,
)
from document_service.infrastructure.health import ServiceMode

router = APIRouter()

ReadCtx = Annotated[RequestContext, Depends(get_request_context)]
WriteCtx = Annotated[WriteContext, Depends(get_write_context)]
UploadCtx = Annotated[UploadContext, Depends(get_upload_context)]
SearchCtx = Annotated[SearchParams, Query()]
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
        idempotency_key=ctx.idempotency_key,
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
    document = await ctx.container.use_cases.register_document().execute(command)
    return DocumentResponse.from_domain(document)


def get_page(
    page_size: int = Query(50, ge=1, le=200), cursor: str | None = Query(None)
) -> PageRequest:
    """Đọc và giới hạn kích thước trang."""
    return PageRequest(page_size, cursor)


PageCtx = Annotated[PageRequest, Depends(get_page)]


@router.get(
    "/documents/{document_id}/versions",
    dependencies=[Depends(require_read_mode)],
    response_model=PageResponse[VersionResponse],
)
async def list_versions(
    document_id: str, ctx: ReadCtx, page: PageCtx
) -> PageResponse[VersionResponse]:
    """Liệt kê phiên bản kể cả Obsolete sau khi kiểm tra quyền metadata."""
    document = await _visible_document(document_id, ctx)
    versions = page.slice(sorted(document.versions, key=lambda version: str(version.version_id)))
    return PageResponse(
        items=[VersionResponse.from_domain(v) for v in versions.items],
        next_cursor=versions.next_cursor,
    )


@router.get(
    "/documents/{document_id}",
    dependencies=[Depends(require_read_mode)],
    response_model=DocumentResponse,
)
async def read_document(document_id: str, ctx: ReadCtx) -> DocumentResponse:
    """Đọc thông tin tài liệu và số phiên bản."""
    return DocumentResponse.from_domain(await _visible_document(document_id, ctx))


async def _visible_document(document_id: str, ctx: ReadCtx) -> Document:
    identifier = DocumentId(document_id)
    decision = await ctx.container.ports.policies.decide(
        ctx.principal, Action.VIEW_METADATA, str(identifier)
    )
    if not decision.allowed:
        raise PolicyDeniedError(decision.reason or "not allowed to view the document")
    return await ctx.container.ports.catalog.read_document(identifier)


@router.post("/documents/{document_id}/versions", response_model=VersionResponse, status_code=201)
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
    result: CreateVersionResult = await ctx.container.use_cases.create_version().execute(
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
    ctx: WriteCtx,
    document_id: str = Query(...),
    _: None = WRITE_GATE,
) -> VersionResponse:
    """Chuyển trạng thái một phiên bản (Draft → Approved → Obsolete)."""
    command = TransitionStatusCommand(
        document_id=DocumentId(document_id),
        version_id=DocumentVersionId(version_id),
        target_status=DocumentStatus(payload.status),
        idempotency_key=ctx.idempotency_key,
        principal=ctx.principal,
    )
    result = await ctx.container.use_cases.approve_version().execute(command)
    return VersionResponse.from_domain(result.changed)


@router.post("/relationships", response_model=RelationshipResponse, status_code=201)
async def declare_relationship(
    payload: DeclareRelationshipRequest,
    ctx: WriteCtx,
    _: None = WRITE_GATE,
) -> RelationshipResponse:
    """Khai báo quan hệ giữa hai phiên bản."""
    command = DeclareRelationshipCommand(
        idempotency_key=ctx.idempotency_key,
        relation_type=RelationType(payload.relation_type),
        source_version_id=DocumentVersionId(payload.source_version_id),
        target_version_id=DocumentVersionId(payload.target_version_id),
        principal=ctx.principal,
    )
    relationship = await ctx.container.use_cases.declare_relationship().execute(command)
    return RelationshipResponse.from_domain(relationship, Direction.OUTGOING)


@router.get(
    "/versions/{version_id}/relationships",
    dependencies=[Depends(require_read_mode)],
    response_model=PageResponse[RelationshipResponse],
)
async def query_relationships(
    version_id: str,
    ctx: ReadCtx,
    page: PageCtx,
    direction: Direction = Query(default=Direction.BOTH),
    relation_type: RelationType | None = Query(default=None),
) -> PageResponse[RelationshipResponse]:
    """Truy vấn quan hệ hai chiều theo loại quan hệ."""
    command = QueryRelationshipsCommand(
        version_id=DocumentVersionId(version_id),
        principal=ctx.principal,
        direction=direction,
        relation_type=relation_type,
    )
    edges = await ctx.container.use_cases.query_relationships().page(command, page)
    return PageResponse(
        items=[
            RelationshipResponse.from_domain(edge.relationship, edge.direction)
            for edge in edges.items
        ],
        next_cursor=edges.next_cursor,
    )


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
        cached_only=ctx.container.gate.mode is ServiceMode.DOWNLOAD_ONLY,
    )
    grant = await ctx.container.use_cases.issue_download().execute(command)
    if not grant.proxied:
        return DownloadResponse.from_domain(grant)
    document = await ctx.container.ports.catalog.read_document(command.document_id)
    version = document.find_version(command.version_id)
    return StreamingResponse(
        ctx.container.proxy_streamer().stream(version.storage_uri),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{version.original_file_name}"'},
    )


@router.get("/search", dependencies=[Depends(require_read_mode)], response_model=SearchResponse)
async def search_documents(ctx: ReadCtx, params: SearchCtx) -> SearchResponse:
    """Tìm kiếm theo metadata với lọc tổ hợp và phân trang."""
    page = await ctx.container.use_cases.search_documents().execute(
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
        idempotency_key=ctx.idempotency_key,
        document_id=DocumentId(document_id),
        principal=ctx.principal,
        access_policy=payload.to_domain(),
    )
    policy = await ctx.container.use_cases.update_access_policy().execute(command)
    return AccessPolicyPayload.from_domain(policy)


@router.get(
    "/documents/{document_id}/audit",
    dependencies=[Depends(require_read_mode)],
    response_model=PageResponse[AuditEventResponse],
)
async def list_audit(
    document_id: str, ctx: ReadCtx, page: PageCtx
) -> PageResponse[AuditEventResponse]:
    """Đọc lịch sử audit của một tài liệu."""
    command = ListAuditCommand(
        document_id=DocumentId(document_id), principal=ctx.principal, page=page
    )
    events = await ctx.container.use_cases.list_audit().execute(command)
    return PageResponse(
        items=[AuditEventResponse.from_domain(event) for event in events.items],
        next_cursor=events.next_cursor,
    )
