"""Session 8.4 — chunked/resumable uploads: offset append, resume, digest-verified assembly."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from app.chunked import ChunkedUploadStaging, OffsetMismatchError
from app.storage import content_digest
from conftest import auth, register
from httpx import AsyncClient

pytestmark = pytest.mark.usefixtures("_no_redis")


@pytest.fixture
def _no_redis():
    with patch("app.routes.jobs.enqueue_job", new=AsyncMock()):
        yield


# ── staging unit ────────────────────────────────────────────────────────────────
def test_staging_appends_by_offset_and_rejects_mismatch(tmp_path) -> None:
    st = ChunkedUploadStaging(str(tmp_path))
    uid = uuid.uuid4()
    st.create(uid)
    assert st.append(uid, 0, b"abc") == 3
    assert st.append(uid, 3, b"def") == 6
    assert st.assemble(uid) == b"abcdef"
    # A duplicated / wrong-offset chunk is rejected, not silently corrupting the stream.
    with pytest.raises(OffsetMismatchError):
        st.append(uid, 0, b"zzz")


# ── endpoint resume flow ────────────────────────────────────────────────────────
async def test_resumable_upload_end_to_end(client: AsyncClient) -> None:
    _dev, key = await register(client, "developer", "acme")
    full = b"chunk-one|" + b"chunk-two|" + b"chunk-three"
    c1, c2 = full[:10], full[10:]
    digest = content_digest(full)

    created = await client.post("/uploads", headers=auth(key), json={"digest": digest})
    uid = created.json()["upload_id"]
    assert created.json()["received"] == 0

    # First chunk, then a simulated interruption.
    r1 = await client.patch(
        f"/uploads/{uid}", headers={**auth(key), "Upload-Offset": "0"}, content=c1
    )
    assert r1.json()["received"] == len(c1)

    # Resume: ask how much was received, continue from there.
    offset = (await client.get(f"/uploads/{uid}", headers=auth(key))).json()["received"]
    assert offset == len(c1)
    r2 = await client.patch(
        f"/uploads/{uid}", headers={**auth(key), "Upload-Offset": str(offset)}, content=c2
    )
    assert r2.json()["received"] == len(full)

    done = await client.post(f"/uploads/{uid}/complete", headers=auth(key))
    assert done.status_code == 200
    assert done.json()["ref"] == digest  # assembled bytes match the content-address


async def test_offset_mismatch_is_409(client: AsyncClient) -> None:
    _dev, key = await register(client, "developer", "acme")
    uid = (await client.post("/uploads", headers=auth(key), json={})).json()["upload_id"]
    await client.patch(
        f"/uploads/{uid}", headers={**auth(key), "Upload-Offset": "0"}, content=b"aaaa"
    )
    # Wrong offset (should be 4) → 409 so the client re-syncs via GET.
    bad = await client.patch(
        f"/uploads/{uid}", headers={**auth(key), "Upload-Offset": "0"}, content=b"bbbb"
    )
    assert bad.status_code == 409


async def test_complete_rejects_digest_mismatch(client: AsyncClient) -> None:
    _dev, key = await register(client, "developer", "acme")
    wrong_digest = content_digest(b"something else")
    uid = (await client.post("/uploads", headers=auth(key), json={"digest": wrong_digest})).json()[
        "upload_id"
    ]
    await client.patch(
        f"/uploads/{uid}", headers={**auth(key), "Upload-Offset": "0"}, content=b"actual bytes"
    )
    resp = await client.post(f"/uploads/{uid}/complete", headers=auth(key))
    assert resp.status_code == 400
