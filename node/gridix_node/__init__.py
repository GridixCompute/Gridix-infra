"""GRIDIX thin inference node — relay WebSocket client backed by local Ollama."""

from gridix_node.client import (
    MODEL_MAP,
    Config,
    NodeAuthError,
    handle_request,
    load_config,
    run,
)

__all__ = ["MODEL_MAP", "Config", "NodeAuthError", "handle_request", "load_config", "run"]
