"""Exercise the real S3ObjectStore + S3Storage against an S3-compatible server (MinIO/S3).

This validates the aioboto3 code path that unit tests can't (they use InMemoryObjectStore).
Requires, in the environment:
  AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_DEFAULT_REGION,
  GRIDIX_S3_BUCKET, GRIDIX_S3_ENDPOINT_URL (blank for real AWS).

Run with the app importable, e.g.:  PYTHONPATH=api python smoke/s3_integration.py
"""

import asyncio
import sys

from app.config import Settings
from app.storage import IntegrityError, S3ObjectStore, S3Storage


async def _ensure_bucket(bucket: str, endpoint: str | None) -> None:
    import aioboto3
    from botocore.exceptions import ClientError

    session = aioboto3.Session()
    async with session.client("s3", endpoint_url=endpoint) as s3:
        try:
            await s3.head_bucket(Bucket=bucket)
        except ClientError:
            await s3.create_bucket(Bucket=bucket)


async def main() -> int:
    settings = Settings()  # reads GRIDIX_S3_BUCKET / GRIDIX_S3_ENDPOINT_URL from env
    endpoint = settings.s3_endpoint_url or None
    await _ensure_bucket(settings.s3_bucket, endpoint)

    store = S3Storage(S3ObjectStore(settings))
    data = b"hello-gridix-s3-integration"

    ref = await store.put(data)
    print(f"put -> ref {ref}")
    assert await store.exists(ref), "exists() should be True after put"
    assert await store.get(ref) == data, "get() roundtrip mismatch"

    ref2 = await store.put(data)  # content-addressed dedup: identical content, identical ref
    assert ref2 == ref, "dedup: same content must yield the same ref"

    # Integrity: tamper the underlying object and confirm get() rejects it.
    await store._store.put_object(store._key(ref), b"tampered-bytes")
    try:
        await store.get(ref)
    except IntegrityError:
        print("integrity: tamper detected OK")
    else:
        print("FAIL: tampered blob was not rejected")
        return 1

    print("S3 INTEGRATION: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
