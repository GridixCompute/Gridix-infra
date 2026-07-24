"""Turn a node's by-value image reply into stored, browser-reachable URLs.

Nodes return generated images INLINE as base64 (by-value transport: the bytes cross the relay
frame, bounded to 512x512 so they stay under the 1 MiB cap). A node cannot upload to the blob
store — ``POST /blobs`` is developer-gated — and a node-hosted URL would be unreachable by a
browser and would die with the node. So the coordinator, which does hold the store, decodes
each image, persists it content-addressed, and hands back a URL a browser can load and that
outlives the node that made it.

Used by BOTH image paths — the paid ``/v1/images/generations`` and the free ``/public/images``
— so one node's reply shape serves both.
"""

from __future__ import annotations

import base64
import binascii

from loguru import logger

from app.config import Settings
from app.storage import get_storage


def image_url(ref: str, settings: Settings) -> str:
    """The public, browser-reachable URL for a stored image ref."""
    return f"{settings.public_base_url.rstrip('/')}/public/image/{ref}"


async def store_node_images(images: object, *, settings: Settings) -> list[str]:
    """Decode base64 PNGs from a node reply and store each; return public URLs.

    Defensive by design — a node is untrusted input:
      * a non-list ``images`` is treated as no images (strings are iterable; a bare string
        would otherwise be stored character by character),
      * an element that is not a valid base64 string is skipped, not stored,
    so a malformed reply yields fewer URLs rather than garbage or a 500.
    """
    if not isinstance(images, list):
        return []

    urls: list[str] = []
    for item in images:
        if not isinstance(item, str):
            logger.warning("node image element is {}, not a base64 string; skipping", type(item))
            continue
        try:
            data = base64.b64decode(item, validate=True)
        except (binascii.Error, ValueError):
            logger.warning("node image element was not valid base64; skipping")
            continue
        if not data:
            continue
        ref = await get_storage().put(data, suffix=".png")
        urls.append(image_url(ref, settings))
    return urls
