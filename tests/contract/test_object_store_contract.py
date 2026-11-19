"""Bộ test hợp đồng của ObjectStorePort, chạy trên fake và trên S3 giả lập (moto).

Khẳng định chính theo mục 14: object **bất biến** (ghi lại cùng khóa không phá bản
cũ), `head` trả kích thước, `presign` tạo link có thời hạn, và liệt kê theo prefix
hoạt động — nền cho POC-01 và POC-15.
"""

from __future__ import annotations

from datetime import timedelta
from typing import AsyncIterator, Iterator

import pytest

from document_service.adapter.outbound.fake.in_memory import InMemoryObjectStore
from document_service.adapter.outbound.storage.s3_store import S3ObjectStoreAdapter
from document_service.config import DependencyResiliencePolicy, StorageSettings
from document_service.domain.port import ObjectStorePort
from document_service.domain.value import Checksum, DocumentId, DocumentVersionId, StorageUri
from document_service.infrastructure.resilience.executor import ResilientCallExecutor
from document_service.utils.hashing import digest_of

BUCKET = "contract-bucket"
CHECKSUM = Checksum.parse("sha256:" + "b" * 64)


def _stream(payload: bytes) -> AsyncIterator[bytes]:
    """Luồng dữ liệu một khối."""

    async def iterator() -> AsyncIterator[bytes]:
        yield payload

    return iterator()


def _uri() -> StorageUri:
    """URI theo quy ước object key."""
    return StorageUri.for_version(BUCKET, DocumentId("DOC-1"), DocumentVersionId("VER-1"))


@pytest.fixture
def moto_s3() -> Iterator[None]:
    """Bật S3 giả lập của moto và tạo bucket."""
    moto = pytest.importorskip("moto")
    import boto3

    with moto.mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=BUCKET)
        yield


@pytest.fixture(params=["in_memory", "s3_moto"])
def object_store(request: pytest.FixtureRequest) -> ObjectStorePort:
    """Hai hiện thực của object store."""
    if request.param == "in_memory":
        return InMemoryObjectStore()
    request.getfixturevalue("moto_s3")
    settings = StorageSettings(endpoint="", bucket=BUCKET, access_key="test", secret_key="test")
    executor = ResilientCallExecutor("object_store", DependencyResiliencePolicy())
    return S3ObjectStoreAdapter(settings, executor)


class TestObjectStoreContract:
    """Hợp đồng chung cho mọi hiện thực object store."""

    async def test_put_then_head(self, object_store: ObjectStorePort) -> None:
        """Ghi rồi đọc được kích thước object."""
        uri = _uri()
        result = await object_store.put_immutable(uri, _stream(b"noi dung"), CHECKSUM)
        assert result.checksum == Checksum("sha256", digest_of(b"noi dung"))
        assert result.size_bytes == len(b"noi dung")
        info = await object_store.head(uri)
        assert info.checksum == result.checksum
        assert info.size_bytes == len(b"noi dung")

    async def test_head_missing_object(self, object_store: ObjectStorePort) -> None:
        """Object chưa tồn tại thì trả size 0, không phát lỗi."""
        missing = StorageUri(bucket=BUCKET, key="objects/DOC-X/VER-X/source")
        info = await object_store.head(missing)
        assert info.size_bytes == 0

    async def test_put_is_idempotent(self, object_store: ObjectStorePort) -> None:
        """I3, I13: ghi lại cùng khóa giữ nguyên nội dung cũ."""
        uri = _uri()
        await object_store.put_immutable(uri, _stream(b"ban dau"), CHECKSUM)
        again = await object_store.put_immutable(uri, _stream(b"ghi de"), CHECKSUM)
        assert again.checksum == Checksum("sha256", digest_of(b"ban dau"))
        assert again.already_existed is True
        chunks = [chunk async for chunk in object_store.open_stream(uri)]
        assert b"".join(chunks) == b"ban dau"

    async def test_head_rehashes_legacy_object(self, moto_s3: None) -> None:
        """Metadata checksum của bản cũ chỉ là giá trị client khai."""
        import boto3

        uri = _uri()
        boto3.client("s3", region_name="us-east-1").put_object(
            Bucket=uri.bucket, Key=uri.key, Body=b"legacy", Metadata={"checksum": str(CHECKSUM)}
        )
        settings = StorageSettings(endpoint="", bucket=BUCKET, access_key="test", secret_key="test")
        store = S3ObjectStoreAdapter(
            settings, ResilientCallExecutor("object_store", DependencyResiliencePolicy())
        )
        assert (await store.head(uri)).checksum == Checksum("sha256", digest_of(b"legacy"))

    async def test_presign_returns_url(self, object_store: ObjectStorePort) -> None:
        """Link tải có thời hạn được cấp."""
        uri = _uri()
        await object_store.put_immutable(uri, _stream(b"x"), CHECKSUM)
        url = await object_store.presign(uri, timedelta(seconds=120))
        assert uri.key in url

    async def test_list_under_prefix(self, object_store: ObjectStorePort) -> None:
        """Liệt kê theo prefix phục vụ job đối soát."""
        uri = _uri()
        await object_store.put_immutable(uri, _stream(b"x"), CHECKSUM)
        items = await object_store.list_under_prefix("objects/")
        assert any(uri.key in item.key for item in items)

    async def test_health_probe_is_read_only(self, object_store: ObjectStorePort) -> None:
        """Health check không tạo object nào."""
        from document_service.infrastructure.health import HealthProbe

        assert isinstance(object_store, HealthProbe)
        before = await object_store.list_under_prefix("objects/")
        result = await object_store.check_health()
        after = await object_store.list_under_prefix("objects/")
        assert result.healthy is True
        assert len(before) == len(after)
