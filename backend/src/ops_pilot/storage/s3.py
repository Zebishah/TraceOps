from typing import BinaryIO

import boto3
from anyio import to_thread
from mypy_boto3_s3.client import S3Client

from ops_pilot.core.config import get_settings


class S3Storage:
    def __init__(self) -> None:
        settings = get_settings()

        self.bucket_name = settings.s3_bucket_name

        self.client: S3Client = boto3.client(
            "s3",
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
            region_name=settings.aws_region,
        )

    async def upload_file(
        self,
        *,
        file: BinaryIO,
        key: str,
        content_type: str,
    ) -> None:
        await to_thread.run_sync(
            lambda: self.client.upload_fileobj(
                file,
                self.bucket_name,
                key,
                ExtraArgs={
                    "ContentType": content_type,
                },
            )
        )

    async def delete_file(
        self,
        *,
        key: str,
    ) -> None:
        await to_thread.run_sync(
            lambda: self.client.delete_object(
                Bucket=self.bucket_name,
                Key=key,
            )
        )

    async def download_file(
        self,
        *,
        key: str,
    ) -> bytes:
        def download() -> bytes:
            response = self.client.get_object(
                Bucket=self.bucket_name,
                Key=key,
            )

            body = response["Body"]

            return bytes(body.read())

        return await to_thread.run_sync(download)

    async def upload_bytes(
        self,
        *,
        data: bytes,
        key: str,
        content_type: str,
    ) -> None:
        await to_thread.run_sync(
            lambda: self.client.put_object(
                Bucket=self.bucket_name,
                Key=key,
                Body=data,
                ContentType=content_type,
            )
        )
