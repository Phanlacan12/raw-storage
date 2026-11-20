"""Tạo bucket trên Object Storage của môi trường dev, không cần AWS CLI.

README cũ dùng `aws s3 mb`, nhưng AWS CLI là một thứ phải cài riêng. Script này dùng
boto3 đã có sẵn trong .venv và đọc đúng cấu hình mà service đọc, nên không có chuyện
bucket được tạo ở một endpoint khác với endpoint service sẽ gọi.

Chạy:

    set -a && source deploy/.env && set +a
    uv run python deploy/create_bucket.py

Chạy lại nhiều lần an toàn: bucket đã tồn tại thì script báo và thoát 0.
"""

from __future__ import annotations

import sys

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from document_service.config import SettingsProvider


def main() -> int:
    """Tạo bucket theo configs/storage.yml và biến môi trường DS_STORAGE__*."""
    storage = SettingsProvider().reload().storage
    print(f"endpoint = {storage.endpoint}")
    print(f"bucket   = {storage.bucket}")

    client = boto3.client(
        "s3",
        endpoint_url=storage.endpoint,
        aws_access_key_id=storage.access_key,
        aws_secret_access_key=storage.secret_key,
        region_name=storage.region,
    )
    try:
        existing = {item["Name"] for item in client.list_buckets().get("Buckets", [])}
    except (BotoCoreError, ClientError) as error:
        print(f"[FAIL] cannot reach the object store: {error}")
        print("       Is the stack up? docker compose -f deploy/docker-compose.yml ps")
        return 1

    if storage.bucket in existing:
        print(f"[OK  ] bucket already exists: {storage.bucket}")
        return 0
    try:
        client.create_bucket(Bucket=storage.bucket)
    except (BotoCoreError, ClientError) as error:
        print(f"[FAIL] cannot create the bucket: {error}")
        return 1
    print(f"[OK  ] bucket created: {storage.bucket}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
