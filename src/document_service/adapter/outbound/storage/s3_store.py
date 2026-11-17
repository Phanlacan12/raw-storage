"""S3ObjectStoreAdapter: ghi và đọc object bất biến trên Object Storage.

Chỉ dùng **API S3 chuẩn** (mục 3.8 báo cáo), nên thay sản phẩm lưu trữ không làm đổi
phần còn lại. boto3 là thư viện đồng bộ, nên mọi lời gọi đi qua `ThreadOffloader` để
không chặn event loop (quyết định trong plan: không thêm aioboto3).

Ghi object là **idempotent**: khóa cố định theo `document_version_id`, và adapter kiểm
tra object đã tồn tại trước khi ghi, nên retry của saga không tạo bản trùng (I3, I13).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, AsyncIterator, Callable

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import BotoCoreError, ClientError

from document_service.adapter.outbound.base import OutboundAdapter
from document_service.config import StorageSettings
from document_service.domain.dto import ObjectInfo, PutResult
from document_service.domain.port import ObjectStorePort
from document_service.domain.value import Checksum, StorageUri
from document_service.infrastructure.health import DependencyKind, HealthResult
from document_service.infrastructure.resilience.executor import ResilientCallExecutor
from document_service.infrastructure.resilience.retry import ClassifiedError, ErrorClass
from document_service.utils.asyncx import ThreadOffloader
from document_service.utils.hashing import digest_of

_RETRYABLE_CODES = frozenset({"SlowDown", "RequestTimeout", "InternalError", "ServiceUnavailable"})
_CHUNK_SIZE = 1024 * 1024


class S3ObjectStoreAdapter(ObjectStorePort, OutboundAdapter):
    """Adapter Object Storage tương thích S3."""

    def __init__(self, settings: StorageSettings, executor: ResilientCallExecutor) -> None:
        """Dựng client boto3 theo cấu hình và executor của phụ thuộc storage."""
        OutboundAdapter.__init__(self, executor, DependencyKind.REQUIRED_FOR_DOWNLOAD)
        self._settings = settings
        self._offloader = ThreadOffloader()
        timeouts = executor.timeouts
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.endpoint or None,
            region_name=settings.region,
            aws_access_key_id=settings.access_key or None,
            aws_secret_access_key=settings.secret_key or None,
            config=BotoConfig(
                connect_timeout=timeouts.connect_seconds,
                read_timeout=timeouts.read_seconds,
                retries={"max_attempts": 1},
                signature_version="s3v4",
            ),
        )

    async def put_immutable(
        self, uri: StorageUri, stream: AsyncIterator[bytes], checksum: Checksum
    ) -> PutResult:
        """Ghi object nếu chưa tồn tại; nếu đã có thì giữ nguyên bản cũ."""
        existing = await self.head(uri)
        if existing.etag:
            return PutResult(
                etag=existing.etag,
                size_bytes=existing.size_bytes,
                checksum=checksum,
                already_existed=True,
            )
        body = b"".join([chunk async for chunk in stream])
        response = await self._call(
            lambda: self._offloader.call(self._put_object, uri, body, checksum)
        )
        return PutResult(
            etag=str(response.get("ETag", "")).strip('"'),
            size_bytes=len(body),
            checksum=checksum,
        )

    async def put_overwrite(
        self, uri: StorageUri, payload: bytes, content_type: str = "application/json"
    ) -> PutResult:
        """Ghi object cho phép ghi đè, dùng cho manifest điều phối."""
        response = await self._call(
            lambda: self._offloader.call(self._put_raw, uri, payload, content_type)
        )
        return PutResult(
            etag=str(response.get("ETag", "")).strip('"'),
            size_bytes=len(payload),
            checksum=Checksum(algorithm="sha256", hex_digest=digest_of(payload)),
        )

    async def head(self, uri: StorageUri) -> ObjectInfo:
        """Thông tin object, trả size 0 nếu chưa tồn tại."""
        try:
            response = await self._call(lambda: self._offloader.call(self._head_object, uri))
        except ClassifiedError as error:
            if error.error_class is ErrorClass.NON_RETRYABLE_CLIENT:
                return ObjectInfo(key=uri.key, size_bytes=0)
            raise
        return ObjectInfo(
            key=uri.key,
            size_bytes=int(response.get("ContentLength", 0) or 0),
            etag=str(response.get("ETag", "")).strip('"'),
        )

    async def presign(self, uri: StorageUri, ttl: timedelta) -> str:
        """Cấp link tải có thời hạn.

        Link đã cấp **không** tự mất hiệu lực khi quyền đổi; tài liệu cần thu hồi ngay
        phải dùng `open_stream` qua dịch vụ (POC-23).
        """
        seconds = int(ttl.total_seconds()) or self._settings.presign_ttl_seconds
        return await self._offloader.call(self._presign_url, uri, seconds)

    def open_stream(self, uri: StorageUri) -> AsyncIterator[bytes]:
        """Mở luồng đọc object để proxy qua dịch vụ."""

        async def _iterator() -> AsyncIterator[bytes]:
            response = await self._call(lambda: self._offloader.call(self._get_object, uri))
            body = response["Body"]
            while True:
                chunk = await self._offloader.call(body.read, _CHUNK_SIZE)
                if not chunk:
                    break
                yield chunk

        return _iterator()

    async def list_under_prefix(self, prefix: str) -> list[ObjectInfo]:
        """Liệt kê object theo prefix, dùng cho job đối soát."""
        response = await self._call(lambda: self._offloader.call(self._list_objects, prefix))
        contents = response.get("Contents", []) or []
        return [
            ObjectInfo(
                key=str(item.get("Key", "")),
                size_bytes=int(item.get("Size", 0) or 0),
                etag=str(item.get("ETag", "")).strip('"'),
            )
            for item in contents
        ]

    async def _probe_dependency(self) -> HealthResult:
        """HEAD bucket: thao tác chỉ đọc, không tạo object."""
        await self._offloader.call(self._head_bucket)
        return self.health_up(f"bucket={self._settings.bucket}")

    def _put_object(self, uri: StorageUri, body: bytes, checksum: Checksum) -> dict[str, Any]:
        """Ghi object kèm metadata checksum."""
        return self._guard(
            lambda: self._client.put_object(
                Bucket=uri.bucket,
                Key=uri.key,
                Body=body,
                Metadata={"checksum": str(checksum)},
            )
        )

    def _put_raw(self, uri: StorageUri, payload: bytes, content_type: str) -> dict[str, Any]:
        """Ghi object với kiểu nội dung cho trước."""
        return self._guard(
            lambda: self._client.put_object(
                Bucket=uri.bucket, Key=uri.key, Body=payload, ContentType=content_type
            )
        )

    def _head_object(self, uri: StorageUri) -> dict[str, Any]:
        """HEAD một object."""
        return self._guard(lambda: self._client.head_object(Bucket=uri.bucket, Key=uri.key))

    def _get_object(self, uri: StorageUri) -> dict[str, Any]:
        """GET một object."""
        return self._guard(lambda: self._client.get_object(Bucket=uri.bucket, Key=uri.key))

    def _list_objects(self, prefix: str) -> dict[str, Any]:
        """Liệt kê object theo prefix."""
        return self._guard(
            lambda: self._client.list_objects_v2(Bucket=self._settings.bucket, Prefix=prefix)
        )

    def _head_bucket(self) -> dict[str, Any]:
        """HEAD bucket."""
        return self._guard(lambda: self._client.head_bucket(Bucket=self._settings.bucket))

    def _presign_url(self, uri: StorageUri, seconds: int) -> str:
        """Dựng presigned URL."""
        return str(
            self._client.generate_presigned_url(
                "get_object",
                Params={"Bucket": uri.bucket, "Key": uri.key},
                ExpiresIn=seconds,
            )
        )

    def _guard(self, operation: Callable[[], Any]) -> Any:
        """Chuyển lỗi boto3 thành ClassifiedError để executor phân loại."""
        try:
            return operation()
        except ClientError as error:
            code = str(error.response.get("Error", {}).get("Code", ""))
            status = int(
                error.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 500) or 500
            )
            error_class = (
                ErrorClass.RETRYABLE_THROTTLED
                if code in _RETRYABLE_CODES
                else (
                    ErrorClass.NON_RETRYABLE_CLIENT
                    if 400 <= status < 500
                    else ErrorClass.RETRYABLE_TRANSIENT
                )
            )
            raise ClassifiedError(error_class, f"S3 {code}: {error}") from error
        except BotoCoreError as error:
            raise ClassifiedError(
                ErrorClass.RETRYABLE_TRANSIENT, f"lỗi kết nối S3: {error}"
            ) from error
