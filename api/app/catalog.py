"""The model catalogue: what GRIDIX serves, and what it costs.

Nodes declare which models they run; this says what those names mean and what they bill.
A model a node offers but the catalogue doesn't know is not servable — otherwise a node
could invent a name and there would be no price to charge for it.

Prices are USDC. Chat bills per 1M tokens, split in/out because generation costs far more
than reading; images bill per image.
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class Modality(StrEnum):
    """What kind of request a model answers."""

    chat = "chat"
    image = "image"


@dataclass(frozen=True)
class ModelSpec:
    """A servable model and its price."""

    id: str
    modality: Modality
    # Chat pricing (per 1,000,000 tokens). Zero for image models.
    input_usdc_per_mtok: Decimal = Decimal(0)
    output_usdc_per_mtok: Decimal = Decimal(0)
    # Image pricing (per image). Zero for chat models.
    usdc_per_image: Decimal = Decimal(0)
    # Ceiling used for the pre-dispatch balance gate.
    max_output_tokens: int = 4096
    context_window: int = 8192


CATALOG: dict[str, ModelSpec] = {
    m.id: m
    for m in (
        ModelSpec(
            id="llama-3.1-8b",
            modality=Modality.chat,
            input_usdc_per_mtok=Decimal("0.05"),
            output_usdc_per_mtok=Decimal("0.08"),
            context_window=128_000,
        ),
        ModelSpec(
            id="llama-3.1-70b",
            modality=Modality.chat,
            input_usdc_per_mtok=Decimal("0.40"),
            output_usdc_per_mtok=Decimal("0.80"),
            context_window=128_000,
        ),
        ModelSpec(
            id="qwen-2.5-coder-32b",
            modality=Modality.chat,
            input_usdc_per_mtok=Decimal("0.18"),
            output_usdc_per_mtok=Decimal("0.30"),
            context_window=32_768,
        ),
        ModelSpec(
            id="sdxl-turbo",
            modality=Modality.image,
            usdc_per_image=Decimal("0.01"),
        ),
        ModelSpec(
            id="flux-schnell",
            modality=Modality.image,
            usdc_per_image=Decimal("0.03"),
        ),
    )
}


def get_model(model_id: str) -> ModelSpec | None:
    """The spec for ``model_id``, or None if GRIDIX does not serve it."""
    return CATALOG.get(model_id)


def chat_cost(spec: ModelSpec, *, input_tokens: int, output_tokens: int) -> Decimal:
    """What a completed chat request costs, from the tokens it actually used."""
    per_token_in = spec.input_usdc_per_mtok / Decimal(1_000_000)
    per_token_out = spec.output_usdc_per_mtok / Decimal(1_000_000)
    return per_token_in * Decimal(max(input_tokens, 0)) + per_token_out * Decimal(
        max(output_tokens, 0)
    )


def image_cost(spec: ModelSpec, *, images: int) -> Decimal:
    """What a completed image request costs."""
    return spec.usdc_per_image * Decimal(max(images, 0))


def chat_worst_case(spec: ModelSpec, *, input_tokens: int, max_output_tokens: int) -> Decimal:
    """The most a chat request could cost, for the pre-dispatch balance gate.

    Deliberately the ceiling, not an estimate: the gate exists so a request that cannot be
    paid for never reaches a node's GPU. Guessing low would let it through.
    """
    return chat_cost(spec, input_tokens=input_tokens, output_tokens=max_output_tokens)
