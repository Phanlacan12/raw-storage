"""S3ObjectStoreAdapter: ghi và đọc object bất biến trên Object Storage.

Chỉ dùng **API S3 chuẩn** (mục 3.8 báo cáo), nên thay sản phẩm lưu trữ không làm đổi
phần còn lại. boto3 là thư viện đồng bộ, nên mọi lời gọi đi qua `ThreadOffloader` để
không chặn event loop (quyết định trong plan: không thêm aioboto3).

Ghi object là **idempotent**: khóa cố định theo `document_version_id`, và adapter kiểm
tra object đã tồn tại trước khi ghi, nên retry của saga không tạo bản trùng (I3, I13).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any, AsyncIterator, Callable

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import BotoCoreError, ClientError

from document_service.adapter.outbound.base import OutboundAdapter
from document_service.config import StorageSettings
from document_service.domain.dto import ObjectInfo, PutResult
from document_service.domain.errors import DependencyUnavailableError
from document_service.domain.port import ObjectStorePort
from document_service.domain.value import Checksum, StorageUri
from document_service.infrastructure.health import DependencyKind, HealthResult
from document_service.infrastructure.resilience.executor import ResilientCallExecutor
from document_service.infrastructure.resilience.retry import ClassifiedError, ErrorClass
from document_service.utils.asyncx import ThreadOffloader
from document_service.utils.hashing import StreamingHasher, digest_of

_RETRYABLE_CODES = frozenset({"SlowDown", "RequestTimeout", "InternalError", "ServiceUnavailable"})
_CHUNK_SIZE = 1024 * 1024
# Giới hạn phần nhỏ nhất của một multipart part do S3 quy định.
_MIN_MULTIPART_PART_BYTES = 5 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class _MultipartContext:
    """Tham số của một lượt multipart upload, gom lại để giữ dưới `max-args`."""

    uri: StorageUri
    upload_id: str
    hasher: StreamingHasher
    part_size: int


class S3ObjectStoreAdapter(ObjectStorePort, OutboundAdapter):
    """Adapter Object Storage tương thích S3."""

    extra_kinds = frozenset({DependencyKind.REQUIRED_FOR_WRITE})

    def __init__(self, settings: StorageSettings, executor: ResilientCallExecutor) -> None:
        """Dựng client boto3 theo cấu hình và executor của phụ thuộc storage."""
        OutboundAdapter.__init__(self, executor, DependencyKind.REQUIRED_FOR_DOWNLOAD)
        self._settings = settings
        self._offloader = ThreadOffloader()
        timeouts = executor.timeouts
        self._client = self._build_client(settings, timeouts, retries_max=1)
        # Client dành riêng cho multipart (B16, c4-09 mục 5.3 phần ngoại lệ): nhường
        # boto3 retry từng part thay vì gửi lại toàn file, nhưng mỗi lời gọi vẫn
        # đi qua `_call` nên breaker vẫn thấy lỗi.
        self._transfer_client = self._build_client(settings, timeouts, retries_max=3)

    @staticmethod
    def _build_client(
        settings: StorageSettings,
        timeouts: Any,
        retries_max: int,
    ) -> Any:
        """Dựng client boto3 với số lần retry định trước."""
        return boto3.client(
            "s3",
            endpoint_url=settings.endpoint or None,
            region_name=settings.region,
            aws_access_key_id=settings.access_key or None,
            aws_secret_access_key=settings.secret_key or None,
            config=BotoConfig(
                connect_timeout=timeouts.connect_seconds,
                read_timeout=timeouts.read_seconds,
                retries={"max_attempts": retries_max, "mode": "standard"},
                signature_version="s3v4",
            ),
        )

    async def put_immutable(
        self, uri: StorageUri, stream: AsyncIterator[bytes], checksum: Checksum
    ) -> PutResult:
        """Ghi object nếu chưa tồn tại; nếu đã có thì giữ nguyên bản cũ.

        Không gom toàn bộ nội dung vào RAM: chia luồng theo ngưỡng cấu hình, nhánh
        nhỏ dùng một `put_object`, nhánh lớn dùng multipart upload với mỗi part là
        một `_call` riêng để retry áp ở mức part (c4-09 mục 6.2).
        """
        existing = await self.head(uri)
        if existing.etag:
            if existing.checksum is None:
                raise DependencyUnavailableError("object_store", "concurrent object disappeared")
            return PutResult(
                existing.etag, existing.size_bytes, existing.checksum, already_existed=True
            )
        threshold = max(self._settings.multipart_threshold_bytes, _MIN_MULTIPART_PART_BYTES)
        buffer, _size, hasher, iterator = await self._buffer_up_to(stream, threshold)
        if iterator is None:
            return await self._put_small(uri, buffer, hasher, checksum)
        return await self._put_multipart(uri, buffer, iterator, hasher, checksum)

    async def _buffer_up_to(
        self, stream: AsyncIterator[bytes], threshold: int
    ) -> tuple[bytes, int, StreamingHasher, AsyncIterator[bytes] | None]:
        """Đệm tối đa `threshold` byte để quyết định nhánh nhỏ hay multipart."""
        hasher = StreamingHasher()
        parts: list[bytes] = []
        total = 0
        async for chunk in stream:
            if not chunk:
                continue
            hasher.update(chunk)
            parts.append(chunk)
            total += len(chunk)
            if total > threshold:
                return b"".join(parts), total, hasher, stream
        return b"".join(parts), total, hasher, None

    async def _put_small(
        self,
        uri: StorageUri,
        body: bytes,
        hasher: StreamingHasher,
        checksum: Checksum,
    ) -> PutResult:
        """Nhánh nhỏ: một `put_object` duy nhất, retry ở mức `_call`."""
        actual = Checksum(checksum.algorithm, hasher.hex_digest())
        response = await self._call(
            lambda: self._offloader.call(self._put_object, uri, body, actual)
        )
        if response:
            return PutResult(str(response["ETag"]).strip('"'), hasher.size_bytes, actual)
        # Một lượt ghi khác đã thắng If-None-Match trong lúc chuẩn bị body.
        existing = await self.head(uri)
        if existing.checksum is None:
            raise DependencyUnavailableError("object_store", "concurrent object disappeared")
        return PutResult(
            existing.etag, existing.size_bytes, existing.checksum, already_existed=True
        )

    async def _put_multipart(
        self,
        uri: StorageUri,
        head_buffer: bytes,
        rest: AsyncIterator[bytes],
        hasher: StreamingHasher,
        checksum: Checksum,
    ) -> PutResult:
        """Nhánh multipart: tự dispatch từng `upload_part` qua `_call`."""
        part_size = max(self._settings.multipart_part_bytes, _MIN_MULTIPART_PART_BYTES)
        upload_id = await self._call(lambda: self._offloader.call(self._create_multipart, uri))
        try:
            parts, total_bytes = await self._stream_parts(
                _MultipartContext(uri, upload_id, hasher, part_size),
                head_buffer,
                rest,
            )
            response = await self._call(
                lambda: self._offloader.call(self._complete_multipart, uri, upload_id, parts)
            )
        except Exception:
            await self._safe_abort_multipart(uri, upload_id)
            raise
        actual = Checksum(checksum.algorithm, hasher.hex_digest())
        etag = str(response.get("ETag", "")).strip('"')
        return PutResult(etag, total_bytes, actual)

    async def _stream_parts(
        self,
        ctx: "_MultipartContext",
        head_buffer: bytes,
        rest: AsyncIterator[bytes],
    ) -> tuple[list[dict[str, Any]], int]:
        """Đọc luồng còn lại, cắt thành part và upload từng cái một."""
        parts: list[dict[str, Any]] = []
        buffer = bytearray(head_buffer)
        total_bytes = len(head_buffer)
        async for chunk in rest:
            if not chunk:
                continue
            buffer.extend(chunk)
            ctx.hasher.update(chunk)
            total_bytes += len(chunk)
            while len(buffer) >= ctx.part_size:
                part_bytes = bytes(buffer[: ctx.part_size])
                del buffer[: ctx.part_size]
                parts.append(
                    await self._upload_part(ctx.uri, ctx.upload_id, len(parts) + 1, part_bytes)
                )
        if buffer:
            parts.append(
                await self._upload_part(ctx.uri, ctx.upload_id, len(parts) + 1, bytes(buffer))
            )
        return parts, total_bytes

    async def _upload_part(
        self, uri: StorageUri, upload_id: str, number: int, body: bytes
    ) -> dict[str, Any]:
        """Một `upload_part`, mỗi lời gọi là một `_call` để breaker thấy lỗi."""
        response = await self._call(
            lambda: self._offloader.call(self._do_upload_part, uri, upload_id, number, body)
        )
        return {"ETag": response["ETag"], "PartNumber": number}

    async def _safe_abort_multipart(self, uri: StorageUri, upload_id: str) -> None:
        """Huỷ multipart trong finally, nuốt lỗi vì đã có lỗi cần raise."""
        try:
            await self._offloader.call(self._abort_multipart, uri, upload_id)
        except Exception:  # pylint: disable=broad-exception-caught
            self._logger.warning(
                "abort_multipart_upload failed", extra={"key": uri.key, "upload_id": upload_id}
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
        response = await self._call(lambda: self._offloader.call(self._head_object, uri))
        if not response:
            return ObjectInfo(key=uri.key, size_bytes=0)
        metadata = response.get("Metadata") or {}
        if "content-digest" in metadata:
            checksum = Checksum.parse(metadata["content-digest"])
        else:
            # Phiên bản cũ lưu checksum khai báo. Băm lại bytes trước khi phục hồi.
            algorithm = metadata.get("checksum", "sha256:").partition(":")[0]
            digest = await StreamingHasher(algorithm).consume_async(self.open_stream(uri))
            checksum = Checksum(algorithm, digest.hex_digest())
        return ObjectInfo(
            key=uri.key,
            checksum=checksum,
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
            try:
                while chunk := await self._offloader.call(body.read, _CHUNK_SIZE):
                    yield chunk
            finally:
                await self._offloader.call(body.close)

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
                Metadata={"content-digest": str(checksum)},
                IfNoneMatch="*",
            ),
            empty_on_status=412,
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
        return self._guard(
            lambda: self._client.head_object(Bucket=uri.bucket, Key=uri.key), empty_on_status=404
        )

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

    def _create_multipart(self, uri: StorageUri) -> str:
        """Khởi tạo multipart upload, trả `UploadId`."""
        response = self._guard(
            lambda: self._transfer_client.create_multipart_upload(Bucket=uri.bucket, Key=uri.key)
        )
        return str(response["UploadId"])

    def _do_upload_part(
        self, uri: StorageUri, upload_id: str, number: int, body: bytes
    ) -> dict[str, Any]:
        """Một `upload_part`, chạy đồng bộ trong offloader."""
        return self._guard(
            lambda: self._transfer_client.upload_part(
                Bucket=uri.bucket,
                Key=uri.key,
                UploadId=upload_id,
                PartNumber=number,
                Body=body,
            )
        )

    def _complete_multipart(
        self, uri: StorageUri, upload_id: str, parts: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Hoàn tất multipart upload với danh sách part đã ghi."""
        return self._guard(
            lambda: self._transfer_client.complete_multipart_upload(
                Bucket=uri.bucket,
                Key=uri.key,
                UploadId=upload_id,
                MultipartUpload={"Parts": parts},
            )
        )

    def _abort_multipart(self, uri: StorageUri, upload_id: str) -> dict[str, Any]:
        """Huỷ multipart upload để không rò part đã ghi dở."""
        return self._guard(
            lambda: self._transfer_client.abort_multipart_upload(
                Bucket=uri.bucket, Key=uri.key, UploadId=upload_id
            )
        )

    def _guard(self, operation: Callable[[], Any], empty_on_status: int | None = None) -> Any:
        """Chuyển lỗi boto3 thành ClassifiedError để executor phân loại."""
        try:
            return operation()
        except ClientError as error:
            code = str(error.response.get("Error", {}).get("Code", ""))
            status = int(
                error.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 500) or 500
            )
            if status == empty_on_status:
                return {}
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
                ErrorClass.RETRYABLE_TRANSIENT, f"S3 connection error: {error}"
            ) from error
