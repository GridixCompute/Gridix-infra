"""The safety gate for public image generation.

⚠️ THERE IS NO MODERATOR CONFIGURED, AND SO THERE IS NO PUBLIC IMAGE GENERATION. That is not
a temporary oversight to be patched around — it is the design. The default implementation
refuses everything, and the route asks this module whether it may run at all. Turning image
generation on requires supplying a real moderator; there is no flag that opens the route
without one.

WHY IT IS NOT IMPLEMENTED HERE. Two categories have to be refused, and neither is a thing a
keyword list can do:

  * CSAM. Real detection is perceptual-hash matching against the known-material corpora held
    by NCMEC, Thorn (Safer) and Microsoft (PhotoDNA). Access is legally controlled and
    contractual; there is no open model that does this, and an open "NSFW detector" answers
    a completely different question — it scores nudity, which is neither necessary nor
    sufficient for the thing that must be refused. Shipping one under this name would be
    worse than shipping nothing, because it would read as a control that exists.
  * NCII — sexual content depicting a real, identifiable person. Needs sexual-content
    detection AND person-identification, and the second half is what makes it hard.

A prompt-side text filter catches some of the first category and some of the second, but it
cannot be the control: this is text-to-image, so the prompt is attacker-supplied and
paraphrase is free. Anything real has to inspect the OUTPUT too.

So this module defines the interface, names exactly the two categories that must be refused
— no others, by instruction — and ships a default that says "not configured" to every
question. `is_configured()` is what the route gates on, so the failure mode of an unwired
safety system is a closed door rather than an open one.
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Verdict:
    """A moderation decision. ``allowed`` is the only field a caller may act on."""

    allowed: bool
    #: Machine-readable reason, for logs and metrics. Never returned to the caller verbatim.
    category: str | None = None

    @staticmethod
    def refuse(category: str) -> "Verdict":
        return Verdict(allowed=False, category=category)

    @staticmethod
    def allow() -> "Verdict":
        return Verdict(allowed=True)


class Moderator(Protocol):
    """What a real implementation has to provide before public images can be enabled.

    Both halves are required. A prompt-only moderator is not sufficient for text-to-image:
    the prompt is chosen by the caller, and the model's output is what actually gets served.
    """

    def is_configured(self) -> bool:
        """Whether this moderator can actually make decisions."""
        ...

    async def check_prompt(self, prompt: str) -> Verdict:
        """Screen a generation request before any GPU time is spent on it."""
        ...

    async def check_image(self, image_bytes: bytes) -> Verdict:
        """Screen generated output before it is returned to anyone."""
        ...


class UnconfiguredModerator:
    """The default: answers "no" to everything, and says so.

    Refusing rather than allowing is the entire point. A safety component that fails open is
    not a safety component — and the common shape of that bug is exactly this one, where the
    real implementation is "coming later" and the placeholder passes everything through so
    development is not blocked.
    """

    def is_configured(self) -> bool:
        return False

    async def check_prompt(self, prompt: str) -> Verdict:  # noqa: ARG002 - refuses regardless
        return Verdict.refuse("moderation_unconfigured")

    async def check_image(self, image_bytes: bytes) -> Verdict:  # noqa: ARG002 - as above
        return Verdict.refuse("moderation_unconfigured")


_moderator: Moderator = UnconfiguredModerator()


def get_moderator() -> Moderator:
    """The active moderator. Unconfigured unless something has deliberately replaced it."""
    return _moderator


def set_moderator(moderator: Moderator) -> None:
    """Install a real moderator. The only way public image generation ever opens."""
    global _moderator
    _moderator = moderator


def image_generation_available() -> bool:
    """Whether the public image route may serve anything at all.

    The route calls this first. With no moderator configured it is False, so the endpoint
    reports itself unavailable instead of generating something nobody is screening.
    """
    return get_moderator().is_configured()
