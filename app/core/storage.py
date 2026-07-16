"""
Object storage client — wraps boto3's S3 client.

Points at MinIO locally (S3_ENDPOINT_URL set) and would point at real AWS S3
in production by simply omitting/changing that one setting — boto3's S3
client works identically against any S3-API-compatible store, so no code
here changes between environments, only configuration.
"""

import boto3

from app.core.config import settings

_s3_client = boto3.client(
    "s3",
    endpoint_url=settings.s3_endpoint_url,
    aws_access_key_id=settings.s3_access_key,
    aws_secret_access_key=settings.s3_secret_key,
    region_name=settings.s3_region,
)


def upload_file(file_obj, object_key: str, content_type: str) -> None:
    """Upload a file-like object to the configured bucket under the given key."""
    _s3_client.upload_fileobj(
        file_obj,
        settings.s3_bucket_name,
        object_key,
        ExtraArgs={"ContentType": content_type},
    )


def generate_presigned_download_url(object_key: str, expires_in_seconds: int = 600) -> str:
    """
    Generate a time-limited, signed URL for downloading a private object.

    This is the standard pattern for private file access: the bucket itself
    stays locked down (never public), and access is granted per-request,
    per-file, and expires — here, in 10 minutes by default.
    """
    return _s3_client.generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.s3_bucket_name, "Key": object_key},
        ExpiresIn=expires_in_seconds,
    )
