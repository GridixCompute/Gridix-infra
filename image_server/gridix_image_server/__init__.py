"""GRIDIX image server — a text-to-image backend a node bridges images.generations to.

Kept out of the node package on purpose: image generation needs the heavy ML stack
(torch/diffusers) and its own GPU, where the node needs only websockets + httpx. A node
reaches this server over HTTP (``IMAGE_SERVER_URL``), the same way it reaches Ollama for chat.
"""

from gridix_image_server.server import IMAGE_SIZE, create_app

__all__ = ["IMAGE_SIZE", "create_app"]
